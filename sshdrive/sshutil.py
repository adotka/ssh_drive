"""SSH-операции: проверка ключа хоста, вход, установка публичного ключа."""

from __future__ import annotations

import base64
import hashlib
import shlex
from pathlib import Path
from typing import Callable

import paramiko

ConfirmHostKey = Callable[[str, str, str, tuple[str, ...]], bool]


class SSHError(Exception):
    """Понятная пользователю ошибка SSH."""


class HostKeyMismatch(SSHError):
    """Ключ хоста не совпадает с сохранённым (возможна MITM-атака)."""


class AuthCancelled(SSHError):
    """Пользователь отказался доверять новому ключу хоста."""


def fingerprint(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def _hostkey_name(host: str, port: int) -> str:
    """Имя хоста в формате known_hosts (как в OpenSSH)."""
    return host if int(port) == 22 else f"[{host}]:{int(port)}"


def _save_verified_key(path: Path, hostname: str, key: paramiko.PKey) -> None:
    """Оставляет для хоста ровно один ключ — проверенный.

    Go-клиент внутри rclone строго сверяет ключ с known_hosts: если для хоста
    лежат ещё и записи других типов (например, старый RSA рядом с новым
    ed25519), он падает с «knownhosts: key mismatch». Поэтому чистим лишнее.
    """
    hosts = paramiko.HostKeys()
    if path.exists():
        hosts.load(str(path))
    hosts.pop(hostname, None)
    hosts.add(hostname, key.get_name(), key)
    path.parent.mkdir(parents=True, exist_ok=True)
    hosts.save(str(path))


class _TOFUPolicy(paramiko.MissingHostKeyPolicy):
    """Спрашивает подтверждение у пользователя и запоминает ключ хоста."""

    def __init__(self, known_hosts: Path | None, confirm: ConfirmHostKey | None) -> None:
        self._path = Path(known_hosts) if known_hosts else None
        self._confirm = confirm

    def missing_host_key(self, client, hostname, key):  # noqa: ARG002 - API paramiko
        fp = fingerprint(key)
        if self._path is None or self._confirm is None:
            raise HostKeyMismatch(f"Неизвестный ключ хоста {hostname} ({fp})")

        existing: tuple[str, ...] = ()
        hosts = paramiko.HostKeys()
        if self._path.exists():
            try:
                hosts.load(str(self._path))
                entry = hosts.lookup(hostname)
                if entry is not None:
                    existing = tuple(sorted(entry.keys()))
            except Exception:
                pass

        if not self._confirm(hostname, key.get_name(), fp, existing):
            raise AuthCancelled(f"Ключ хоста {hostname} отклонён пользователем")
        hosts.pop(hostname, None)
        hosts.add(hostname, key.get_name(), key)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        hosts.save(str(self._path))


def connect(
    host: str,
    port: int,
    user: str,
    *,
    password: str | None = None,
    pkey: paramiko.PKey | None = None,
    known_hosts: Path | str | None = None,
    confirm: ConfirmHostKey | None = None,
    timeout: float = 20.0,
) -> paramiko.SSHClient:
    """Подключается по SSH, проверяя ключ хоста через known_hosts."""
    client = paramiko.SSHClient()
    known_path = Path(known_hosts) if known_hosts else None
    try:
        if known_path and known_path.exists():
            client.load_host_keys(str(known_path))
    except Exception as exc:  # noqa: BLE001 - файл мог быть повреждён
        client.close()
        raise SSHError(f"Не удалось прочитать {known_path}: {exc}") from exc
    client.set_missing_host_key_policy(_TOFUPolicy(known_path, confirm))

    try:
        client.connect(
            hostname=host,
            port=int(port),
            username=user,
            password=password or None,
            pkey=pkey,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )
    except paramiko.BadHostKeyException as exc:
        client.close()
        raise HostKeyMismatch(
            f"Ключ хоста {host}:{port} изменился!\n"
            f"  сохранённый: {fingerprint(exc.expected_key)}\n"
            f"  полученный:  {fingerprint(exc.key)}\n"
            "Если это ожидаемо — удалите запись через «Сервис → Известные хосты»."
        ) from exc
    except paramiko.AuthenticationException as exc:
        client.close()
        raise SSHError(
            "Сервер отклонил вход. Проверьте логин, пароль/ключ и что вход по SSH разрешён."
        ) from exc
    except (OSError, paramiko.SSHException) as exc:
        client.close()
        raise SSHError(f"Не удалось подключиться к {host}:{port}: {exc}") from exc
    except AuthCancelled:
        client.close()
        raise
    except Exception:
        client.close()
        raise

    # Запоминаем именно тот ключ, который реально использовался, и убираем
    # устаревшие записи других типов — иначе rclone (Go known_hosts) ругается
    # «key mismatch».
    if known_path is not None:
        try:
            transport = client.get_transport()
            server_key = transport.get_remote_server_key() if transport else None
            if server_key is not None:
                _save_verified_key(
                    known_path, _hostkey_name(host, int(port)), server_key
                )
        except Exception:  # noqa: BLE001 - не критично для подключения
            pass
    return client


def run(client: paramiko.SSHClient, command: str, timeout: float = 30.0) -> tuple[int, str, str]:
    """Выполняет команду и возвращает (код, stdout, stderr)."""
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def home_dir(client: paramiko.SSHClient) -> str:
    sftp = client.open_sftp()
    try:
        return sftp.normalize(".")
    finally:
        sftp.close()


def _posix_install_command(pubkey: str) -> str:
    q = shlex.quote(pubkey.strip())
    auth = '"$HOME/.ssh/authorized_keys"'
    return (
        'umask 077; '
        'mkdir -p "$HOME/.ssh"; '
        f'touch {auth}; '
        f'if ! grep -qxF -- {q} {auth}; then printf "%s\\n" {q} >> {auth}; fi; '
        'chmod 700 "$HOME/.ssh"; '
        f'chmod 600 {auth}; '
        f'grep -qxF -- {q} {auth} && echo SSHDRIVE_OK'
    )


def _windows_install_script(pubkey: str) -> str:
    key = pubkey.strip()
    if "'" in key:
        raise SSHError("Публичный ключ содержит одинарную кавычку — установите его вручную")
    return f"""
$ErrorActionPreference = 'Stop'
$key = '{key}'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$targets = @(Join-Path $env:USERPROFILE '.ssh\\authorized_keys')
if ($isAdmin) {{ $targets += (Join-Path $env:ProgramData 'ssh\\administrators_authorized_keys') }}
foreach ($file in $targets) {{
    $dir = Split-Path -Parent $file
    if (-not (Test-Path $dir)) {{ New-Item -ItemType Directory -Force -Path $dir | Out-Null }}
    if (-not (Test-Path $file)) {{ New-Item -ItemType File -Force -Path $file | Out-Null }}
    if (-not (Select-String -Path $file -SimpleMatch -Quiet -Pattern $key)) {{
        Add-Content -Path $file -Value $key -Encoding ascii
    }}
    if $isAdmin -and ($file -like '*administrators_authorized_keys')) {{
        icacls $file /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null
    }}
    Write-Output ("updated: " + $file)
}}
Write-Output 'SSHDRIVE_OK'
"""


def install_public_key(client: paramiko.SSHClient, pubkey: str) -> str:
    """Добавляет публичный ключ в authorized_keys на сервере (идемпотентно).

    Пробует POSIX-команду, затем PowerShell (сервер Windows с OpenSSH).
    """
    code, out, err = run(client, _posix_install_command(pubkey))
    if code == 0 and "SSHDRIVE_OK" in out:
        return "ключ добавлен в ~/.ssh/authorized_keys"

    script = _windows_install_script(pubkey)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    command = (
        "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass "
        f"-EncodedCommand {encoded}"
    )
    code2, out2, err2 = run(client, command, timeout=60.0)
    if "SSHDRIVE_OK" in out2:
        return out2.strip() or "ключ добавлен"

    raise SSHError(
        "Не удалось добавить ключ в authorized_keys.\n"
        f"POSIX-попытка: код {code}, {err.strip()[:300]}\n"
        f"PowerShell-попытка: код {code2}, {(err2 or out2).strip()[:300]}"
    )


def test_login(
    host: str,
    port: int,
    user: str,
    *,
    password: str | None = None,
    pkey: paramiko.PKey | None = None,
    known_hosts: Path | str | None = None,
    confirm: ConfirmHostKey | None = None,
) -> dict[str, object]:
    """Проверяет вход и возвращает сведения о сервере и ключе хоста."""
    client = connect(
        host, port, user, password=password, pkey=pkey, known_hosts=known_hosts, confirm=confirm
    )
    try:
        transport = client.get_transport()
        home = home_dir(client)
        version = transport.remote_version if transport else ""
        server_key = transport.get_remote_server_key() if transport else None
        key_type = server_key.get_name() if server_key else ""
        return {
            "home": home,
            "version": version,
            "key_type": key_type,
            "host_key": (
                f"{key_type} {server_key.get_base64()}" if server_key else ""
            ),
            "fingerprint": fingerprint(server_key) if server_key else "",
        }
    finally:
        client.close()
