"""Конфигурация SSH Share: папка, порт и пользователи."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from sshdrive.secretstore import protect, try_unprotect

from . import paths

USER_NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,32}")


@dataclass
class ShareUser:
    """Пользователь, которому разрешён доступ к папке."""

    name: str = ""
    password_enc: str = ""
    keys: list[str] = field(default_factory=list)  # публичные ключи (OpenSSH, одна строка)
    read_only: bool = True

    @property
    def has_password(self) -> bool:
        return bool(self.password_enc)

    def password(self) -> str:
        """Расшифрованный пароль (или пустая строка)."""
        return try_unprotect(self.password_enc) or ""

    def set_password(self, plain: str) -> None:
        self.password_enc = protect(plain) if plain else ""

    def auth_label(self) -> str:
        if self.has_password and self.keys:
            return "пароль+ключ"
        if self.has_password:
            return "пароль"
        if self.keys:
            return "ключ"
        return "нет входа"

    def access_label(self) -> str:
        return "чтение" if self.read_only else "чтение/запись"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ShareUser":
        known = {item.name for item in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        keys = values.get("keys") or []
        values["keys"] = [str(key) for key in keys if str(key).strip()]
        return cls(**values)


@dataclass
class ShareConfig:
    folder: str = ""
    port: int = 2222
    bind: str = "0.0.0.0"
    users: list[ShareUser] = field(default_factory=list)

    def user(self, name: str) -> ShareUser | None:
        return next((user for user in self.users if user.name == name), None)

    def to_dict(self) -> dict:
        return {
            "folder": self.folder,
            "port": self.port,
            "bind": self.bind,
            "users": [user.to_dict() for user in self.users],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ShareConfig":
        try:
            port = int(data.get("port", 2222))
        except (TypeError, ValueError):
            port = 2222
        bind = str(data.get("bind") or "0.0.0.0")
        if bind not in ("0.0.0.0", "127.0.0.1"):
            bind = "0.0.0.0"
        users: list[ShareUser] = []
        for item in data.get("users") or []:
            if not isinstance(item, dict):
                continue
            try:
                user = ShareUser.from_dict(item)
            except Exception:
                continue
            if USER_NAME_RE.fullmatch(user.name):
                users.append(user)
        return cls(
            folder=str(data.get("folder") or ""),
            port=port,
            bind=bind,
            users=users,
        )


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else paths.config_file()
        self.config = ShareConfig()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.config = ShareConfig()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            self.config = ShareConfig.from_dict(raw)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.config.to_dict(), ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)


def validate_share(config: ShareConfig) -> None:
    """Проверка настроек перед запуском сервера."""
    from .server import ShareError

    if not config.folder or not Path(config.folder).is_dir():
        raise ShareError("Укажите существующую папку для общего доступа.")
    if not (0 <= int(config.port) <= 65535):
        raise ShareError("Порт должен быть от 0 до 65535 (0 — выбрать свободный автоматически).")
    if not config.users:
        raise ShareError("Добавьте хотя бы одного пользователя.")
    names = set()
    for user in config.users:
        if not USER_NAME_RE.fullmatch(user.name):
            raise ShareError(
                f"Недопустимое имя пользователя «{user.name}»: разрешены латиница, "
                "цифры и символы . _ - (до 32 символов)."
            )
        if user.name.lower() in names:
            raise ShareError(f"Пользователь «{user.name}» указан дважды.")
        names.add(user.name.lower())
        if not user.has_password and not user.keys:
            raise ShareError(f"У пользователя «{user.name}» нет пароля или ключа.")
