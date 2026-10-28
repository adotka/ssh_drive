"""Ключ SSH-сервера (host key) для SSH Share."""

from __future__ import annotations

import os
import asyncssh

from . import paths


class HostKeyError(Exception):
    pass


def load_or_create() -> asyncssh.SSHKey:
    """Читает ключ сервера или создаёт новый ed25519."""
    path = paths.host_key_file()
    if path.exists():
        try:
            return asyncssh.import_private_key(path.read_bytes())
        except Exception as exc:  # noqa: BLE001
            raise HostKeyError(
                f"Не удалось прочитать ключ сервера {path}: {exc}. "
                "Удалите файл, чтобы программа создала новый (клиентам придётся заново "
                "подтвердить отпечаток)."
            ) from exc

    key = asyncssh.generate_private_key("ssh-ed25519", comment="ssh-share")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.export_private_key("openssh"))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def fingerprint(key: asyncssh.SSHKey) -> str:
    return key.get_fingerprint("sha256")
