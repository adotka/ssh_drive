"""Пути данных SSH Share (общий доступ к папке по SSH)."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "SSHShare"
APP_TITLE = "SSH Share"


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


def config_file() -> Path:
    return appdata_dir() / "config.json"


def host_key_file() -> Path:
    return appdata_dir() / "host_ed25519"


def logs_dir() -> Path:
    return localappdata_dir() / "logs"


def log_file() -> Path:
    return logs_dir() / "app.log"


def ensure_dirs() -> None:
    for path in (appdata_dir(), logs_dir()):
        path.mkdir(parents=True, exist_ok=True)
    log = log_file()
    if log.exists() and log.stat().st_size > 2 * 1024 * 1024:
        try:
            log.replace(log.with_suffix(".log.old"))
        except OSError:
            pass
