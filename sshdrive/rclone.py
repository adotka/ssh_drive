"""Управление rclone: скачивание, монтирование SFTP как диска, размонтирование."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

from . import keys, paths
from .profiles import Profile

Progress = Callable[[int, int], None]
Log = Callable[[str], None]
LineHandler = Callable[[str], None]

USER_AGENT = "SSHDrive/1.0"
GITHUB_LATEST = "https://api.github.com/repos/rclone/rclone/releases/latest"
PINNED_VERSION = "v1.75.2"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class RcloneError(RuntimeError):
    """rclone недоступен или не смог смонтировать диск."""


# --------------------------------------------------------------------------
# Поиск и установка rclone.exe
# --------------------------------------------------------------------------
def find_exe() -> str | None:
    override = os.environ.get("SSHDRIVE_RCLONE")
    if override and Path(override).is_file():
        return str(Path(override))
    local = paths.rclone_exe()
    if local.is_file():
        return str(local)
    # rclone, встроенный в offline-сборку exe
    bundled = paths.bundled_file("rclone.exe")
    if bundled is not None:
        return str(bundled)
    found = shutil.which("rclone")
    return found


def version(exe: str | None = None) -> str:
    exe = exe or find_exe()
    if not exe:
        return ""
    try:
        result = subprocess.run(
            [exe, "version"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        first = (result.stdout or "").strip().splitlines()
        if first and first[0].lower().startswith("rclone v"):
            return first[0].split()[1]
    except Exception:
        pass
    return ""


@lru_cache(maxsize=8)
def supports_host_key_pinning(exe: str) -> bool:
    """Пиннинг ключа хоста (host_keys) появился в rclone 1.75."""
    raw = version(exe).lstrip("vV")
    try:
        major, minor = (int(part) for part in raw.split(".")[:2])
    except (TypeError, ValueError):
        return False
    return (major, minor) >= (1, 75)


def _release() -> tuple[str, str, str | None]:
    """Возвращает (версия, url zip, url SHA256SUMS) последнего релиза."""
    try:
        request = urllib.request.Request(GITHUB_LATEST, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
        tag = data.get("tag_name", "")
        assets = {a.get("name", ""): a.get("browser_download_url", "") for a in data.get("assets", [])}
        for name, url in assets.items():
            if name.endswith("windows-amd64.zip"):
                return tag, url, assets.get("SHA256SUMS")
    except Exception:
        pass
    url = (
        f"https://github.com/rclone/rclone/releases/download/{PINNED_VERSION}/"
        f"rclone-{PINNED_VERSION}-windows-amd64.zip"
    )
    sums = f"https://github.com/rclone/rclone/releases/download/{PINNED_VERSION}/SHA256SUMS"
    return PINNED_VERSION, url, sums


def _fetch(url: str, dest: Path, progress: Progress | None = None) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)


def _expected_sha(sums_url: str, archive_name: str) -> str | None:
    try:
        request = urllib.request.Request(sums_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", "replace")
    except Exception:
        return None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == archive_name:
            return parts[0].lower()
    return None


def download_executable(progress: Progress | None = None, log: Log | None = None) -> str:
    """Скачивает rclone с GitHub, проверяет SHA256 и кладёт в %LOCALAPPDATA%."""
    tag, url, sums_url = _release()
    archive_name = url.rsplit("/", 1)[-1]
    workdir = Path(tempfile.mkdtemp(prefix="sshdrive-"))
    archive = workdir / archive_name

    if log:
        log(f"Скачиваю rclone {tag} ({archive_name})…")
    _fetch(url, archive, progress)

    expected = _expected_sha(sums_url, archive_name) if sums_url else None
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if expected and actual != expected:
        raise RcloneError(
            "Контрольная сумма rclone не совпала — скачивание повреждено или подменено."
        )
    if log:
        log("SHA256 совпала." if expected else "SHA256-файл недоступен, пропускаю проверку.")

    paths.bin_dir().mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        member = next((n for n in zf.namelist() if n.lower().endswith("rclone.exe")), None)
        if member is None:
            raise RcloneError("В архиве rclone не найден rclone.exe")
        data = zf.read(member)

    target = paths.rclone_exe()
    tmp = target.with_suffix(".exe.tmp")
    tmp.write_bytes(data)
    try:
        os.replace(tmp, target)
    except OSError as exc:
        raise RcloneError(
            f"Не удалось записать {target}: {exc}. Закройте уже запущенный rclone и повторите."
        ) from exc

    shutil.rmtree(workdir, ignore_errors=True)
    if log:
        log(f"rclone установлен: {target}")
    return str(target)


def ensure_executable(progress: Progress | None = None, log: Log | None = None) -> str:
    exe = find_exe()
    if exe:
        return exe
    return download_executable(progress, log)


def obscure(exe: str, secret: str) -> str:
    """Кодирует пароль так, как его ждёт rclone (это не шифрование!)."""
    result = subprocess.run(
        [exe, "obscure", secret],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=CREATE_NO_WINDOW,
    )
    value = (result.stdout or "").strip()
    if result.returncode != 0 or not value:
        raise RcloneError(f"rclone obscure завершился с ошибкой: {(result.stderr or '').strip()[:200]}")
    return value


# --------------------------------------------------------------------------
# Буквы дисков
# --------------------------------------------------------------------------
def used_drives() -> set[str]:
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return {chr(ord("A") + i) for i in range(26) if mask & (1 << i)}
    except Exception:
        return {d for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:\\")}


def free_letters() -> list[str]:
    used = used_drives()
    preferred = list("ZYXWVUTSRQPONMLKJ")
    return [letter for letter in preferred if letter not in used]


def drive_exists(letter: str) -> bool:
    return letter.upper() in used_drives()


# --------------------------------------------------------------------------
# Монтирование
# --------------------------------------------------------------------------
@dataclass
class MountHandle:
    profile_id: str
    drive: str
    proc: subprocess.Popen
    tmp_key: Path | None = None
    output: list[str] = field(default_factory=list)

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self, timeout: float = 12.0) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        if self.tmp_key is not None:
            try:
                self.tmp_key.unlink(missing_ok=True)
            except OSError:
                pass
            self.tmp_key = None

        # WinFsp иногда не успевает убрать букву — пробуем освободить её.
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and drive_exists(self.drive):
            time.sleep(0.25)
        if drive_exists(self.drive):
            try:
                subprocess.run(
                    ["net", "use", f"{self.drive}:", "/delete", "/y"],
                    capture_output=True,
                    timeout=15,
                    creationflags=CREATE_NO_WINDOW,
                )
            except Exception:
                pass


def _split_extra(extra: str) -> list[str]:
    if not extra.strip():
        return []
    try:
        parts = shlex.split(extra, posix=False)
    except ValueError:
        parts = extra.split()
    cleaned = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'":
            part = part[1:-1]
        cleaned.append(part)
    return cleaned


def mount(
    profile: Profile,
    *,
    password: str = "",
    passphrase: str = "",
    drive: str,
    host_key: str = "",
    on_line: LineHandler | None = None,
    timeout: float = 45.0,
) -> MountHandle:
    """Запускает `rclone mount` и ждёт появления диска.

    host_key — строка вида «ssh-ed25519 AAAA…», проверенная paramiko.
    rclone пинится на неё: и алгоритм согласования, и байты ключа.
    """
    exe = find_exe()
    if not exe:
        raise RcloneError("rclone.exe не найден. Меню «Сервис → Скачать rclone».")
    if drive_exists(drive):
        raise RcloneError(f"Диск {drive}: уже занят")

    tmp_key: Path | None = None
    env = {k: v for k, v in os.environ.items() if not k.startswith("RCLONE_")}
    env["RCLONE_CONFIG_SSHDRIVE_TYPE"] = "sftp"
    env["RCLONE_CONFIG_SSHDRIVE_HOST"] = profile.host
    env["RCLONE_CONFIG_SSHDRIVE_USER"] = profile.user
    env["RCLONE_CONFIG_SSHDRIVE_PORT"] = str(profile.port)
    env["RCLONE_CONFIG_SSHDRIVE_KEY_USE_AGENT"] = "false"

    if profile.auth == "key":
        key_path = Path(profile.key_path)
        if passphrase:
            tmp_key = paths.tmp_dir() / f"key-{profile.id}.pem"
            keys.export_unencrypted(key_path, passphrase, tmp_key)
            key_path = tmp_key
        env["RCLONE_CONFIG_SSHDRIVE_KEY_FILE"] = paths.forward_slashes(key_path)
    else:
        env["RCLONE_CONFIG_SSHDRIVE_PASS"] = obscure(exe, password)

    if host_key and supports_host_key_pinning(exe):
        # rclone проверяет ключ хоста сам по пину и сам сужает список
        # алгоритмов (для RSA — до rsa-sha2-*). known_hosts_file в этом режиме
        # задавать нельзя: он имеет приоритет и отключает пин.
        env["RCLONE_CONFIG_SSHDRIVE_HOST_KEYS"] = host_key
    else:
        known_hosts = paths.known_hosts_file()
        if known_hosts.exists() and known_hosts.stat().st_size:
            env["RCLONE_CONFIG_SSHDRIVE_KNOWN_HOSTS_FILE"] = paths.forward_slashes(known_hosts)

    remote_path = profile.remote_path.strip()
    if remote_path and not remote_path.startswith("/") and ":" not in remote_path:
        remote_path = "/" + remote_path

    config_file = paths.rclone_config_file()
    if not config_file.exists():
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text("", encoding="utf-8")

    args = [
        exe,
        "mount",
        f"sshdrive:{remote_path}",
        f"{drive}:",
        "--config",
        str(config_file),
        "--network-mode",
        "--volname",
        profile.name or "SSH Drive",
        "--vfs-cache-mode",
        "writes",
        "--dir-cache-time",
        "15s",
        "--attr-timeout",
        "3s",
        "--log-level",
        "NOTICE",
        "--stats",
        "0",
    ]
    if profile.read_only:
        args.append("--read-only")
    args.extend(_split_extra(profile.extra_opts))

    try:
        proc = subprocess.Popen(
            args,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        if tmp_key is not None:
            try:
                tmp_key.unlink(missing_ok=True)
            except OSError:
                pass
        raise RcloneError(f"Не удалось запустить rclone: {exc}") from exc

    handle = MountHandle(profile.id, drive.upper(), proc, tmp_key)

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            handle.output.append(line)
            del handle.output[:-200]
            if on_line:
                on_line(line)

    threading.Thread(target=reader, name=f"rclone-log-{profile.id}", daemon=True).start()

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            time.sleep(0.3)  # дать дочитать вывод
            detail = "\n".join(handle.output[-12:]) or "rclone не вывел ничего"
            handle.stop(timeout=2)
            raise RcloneError(f"rclone завершился с кодом {proc.returncode}.\n{detail}")
        if drive_exists(drive):
            return handle
        time.sleep(0.25)

    detail = "\n".join(handle.output[-12:])
    handle.stop(timeout=3)
    raise RcloneError(
        f"Диск {drive}: не появился за {int(timeout)} с.\n{detail or 'rclone не вывел ничего'}"
    )
