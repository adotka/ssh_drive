"""Расположение файлов приложения.

Все пользовательские данные лежат в %APPDATA%\\SSHDrive (профили, ключи,
known_hosts), а бинарники и кэш — в %LOCALAPPDATA%\\SSHDrive.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "SSHDrive"
APP_TITLE = "SSH Drive"


def _roaming_root() -> Path:
    base = os.environ.get("APPDATA")
    return Path(base) if base else Path.home() / "AppData" / "Roaming"


def _local_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) if base else Path.home() / "AppData" / "Local"


def appdata_dir() -> Path:
    return _roaming_root() / APP_NAME


def localappdata_dir() -> Path:
    return _local_root() / APP_NAME


def bin_dir() -> Path:
    return localappdata_dir() / "bin"


def logs_dir() -> Path:
    return localappdata_dir() / "logs"


def tmp_dir() -> Path:
    return localappdata_dir() / "tmp"


def keys_dir() -> Path:
    return appdata_dir() / "keys"


def profiles_file() -> Path:
    return appdata_dir() / "profiles.json"


def known_hosts_file() -> Path:
    return appdata_dir() / "known_hosts"


def rclone_config_file() -> Path:
    return appdata_dir() / "rclone.conf"


def rclone_exe() -> Path:
    return bin_dir() / "rclone.exe"


def app_log_file() -> Path:
    return logs_dir() / "app.log"


def ensure_dirs() -> None:
    """Создаёт каталоги и пустой конфиг rclone (он нужен, чтобы rclone не читал чужой)."""
    for path in (appdata_dir(), bin_dir(), logs_dir(), tmp_dir(), keys_dir()):
        path.mkdir(parents=True, exist_ok=True)
    config = rclone_config_file()
    if not config.exists():
        config.write_text("", encoding="utf-8")
    log = app_log_file()
    if log.exists() and log.stat().st_size > 2 * 1024 * 1024:
        try:
            log.replace(log.with_suffix(".log.old"))
        except OSError:
            pass


def forward_slashes(path: str | os.PathLike[str]) -> str:
    """rclone на Windows надёжнее понимает пути с прямыми слэшами."""
    return str(path).replace("\\", "/")
