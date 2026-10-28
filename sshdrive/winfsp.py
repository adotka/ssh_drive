"""Обнаружение и установка драйвера WinFsp.

WinFsp — единственная внешняя зависимость: это драйвер файловой системы
в пользовательском режиме, на нём rclone создаёт диск. Установка требует
прав администратора, поэтому запускается через UAC.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

Progress = Callable[[int, int], None]
Log = Callable[[str], None]

GITHUB_LATEST = "https://api.github.com/repos/winfsp/winfsp/releases/latest"
USER_AGENT = "SSHDrive/1.0"
DEFAULT_PATHS = (
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "WinFsp",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WinFsp",
)


def install_dir() -> Path | None:
    """Возвращает каталог установки WinFsp, если драйвер на месте."""
    candidates: list[Path] = list(DEFAULT_PATHS)

    try:
        import winreg

        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            for subkey in (r"SOFTWARE\WinFsp", r"SOFTWARE\WOW6432Node\WinFsp"):
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        subkey,
                        0,
                        winreg.KEY_READ | view,
                    ) as key:
                        value, _ = winreg.QueryValueEx(key, "InstallDir")
                        if value:
                            candidates.insert(0, Path(value))
                except OSError:
                    continue
    except ImportError:  # pragma: no cover
        pass

    for candidate in candidates:
        if (candidate / "bin" / "winfsp-x64.dll").is_file():
            return candidate
    return None


def is_installed() -> bool:
    return install_dir() is not None


def file_version(path: Path) -> str:
    """Версия exe/dll из ресурса версии (без запуска процесса)."""
    try:
        import ctypes
        from ctypes import wintypes

        version_dll = ctypes.WinDLL("version", use_last_error=True)
        version_dll.GetFileVersionInfoSizeW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        version_dll.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        version_dll.GetFileVersionInfoW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        version_dll.GetFileVersionInfoW.restype = wintypes.BOOL
        version_dll.VerQueryValueW.argtypes = [
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.UINT),
        ]
        version_dll.VerQueryValueW.restype = wintypes.BOOL

        size = version_dll.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        buffer = ctypes.create_string_buffer(size)
        if not version_dll.GetFileVersionInfoW(str(path), 0, size, buffer):
            return ""
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version_dll.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return ""
        fixed = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD * 4)).contents
        ms, ls = fixed[2], fixed[3]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return ""


def version() -> str:
    folder = install_dir()
    if folder is None:
        return ""
    return file_version(folder / "bin" / "winfsp-x64.dll")


def latest_msi() -> tuple[str, str]:
    """Возвращает (имя файла, URL) последнего MSI с GitHub."""
    request = urllib.request.Request(GITHUB_LATEST, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".msi"):
            return name, asset["browser_download_url"]
    raise RuntimeError("В последнем релизе WinFsp не найден MSI-файл")


def download(progress: Progress | None = None, log: Log | None = None) -> Path:
    name, url = latest_msi()
    if log:
        log(f"Скачиваю {name}…")
    target = Path(tempfile.gettempdir()) / name
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as handle:
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
    _check_signature(target, log)
    return target


def _check_signature(msi: Path, log: Log | None) -> None:
    """Проверяет подпись MSI (защита от подмены файла при скачивании)."""
    script = (
        "$s = Get-AuthenticodeSignature -FilePath "
        f"'{msi}'; "
        "if ($s.Status -eq 'Valid') { Write-Output ('OK ' + $s.SignerCertificate.Subject) } "
        "else { Write-Output ('BAD ' + $s.Status) }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        if log:
            log("Не удалось проверить цифровую подпись MSI — продолжаю без проверки.")
        return
    text = (result.stdout or "").strip()
    if text.startswith("OK"):
        if log:
            log(f"Подпись MSI действительна: {text[3:].strip()[:120]}")
    else:
        raise RuntimeError(f"Подпись установщика WinFsp недействительна: {text or result.stderr}")


def install(progress: Progress | None = None, log: Log | None = None) -> None:
    """Скачивает и устанавливает WinFsp (появится запрос UAC)."""
    msi = download(progress, log)
    if log:
        log("Запускаю установщик (нужно подтвердить запрос UAC)…")
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$p = Start-Process -FilePath 'msiexec.exe' "
        f"-ArgumentList '/i','\"{msi}\"','/qn','/norestart' -Verb RunAs -Wait -PassThru; "
        "exit $p.ExitCode"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=1800,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    code = result.returncode
    if code not in (0, 3010):
        raise RuntimeError(
            f"Установщик WinFsp завершился с кодом {code}. "
            f"{(result.stderr or '').strip()[:300]}"
        )
    if not is_installed():
        raise RuntimeError("WinFsp установлен, но DLL не найдена. Возможно, нужна перезагрузка.")
    if log:
        log("WinFsp установлен.")
