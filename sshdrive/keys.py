"""Генерация, чтение и экспорт SSH-ключей (ed25519, формат OpenSSH)."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from . import paths


class KeyError_(Exception):
    """Ошибка работы с ключом."""


def default_key_path() -> Path:
    return paths.keys_dir() / "id_ed25519"


def unique_path(base: Path) -> Path:
    if not base.exists() and not base.with_suffix(base.suffix + ".pub").exists():
        return base
    for index in range(2, 1000):
        candidate = base.with_name(f"{base.name}_{index}")
        if not candidate.exists() and not candidate.with_suffix(candidate.suffix + ".pub").exists():
            return candidate
    raise KeyError_(f"Не удалось подобрать имя файла рядом с {base}")


def generate(path: Path, comment: str, passphrase: str = "") -> str:
    """Создаёт пару ключей и возвращает строку публичного ключа."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    private = ed25519.Ed25519PrivateKey.generate()
    encryption = (
        serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
        if passphrase
        else serialization.NoEncryption()
    )
    blob = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        encryption,
    )
    # На Windows chmod не работает, но файл всё равно лежит в профиле пользователя.
    path.write_bytes(blob)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    public = private.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    line = f"{public} {comment}".strip()
    path.with_suffix(path.suffix + ".pub").write_text(line + "\n", encoding="utf-8")
    return line


def load(path: str | Path, passphrase: str = "") -> paramiko.PKey:
    path = Path(path)
    if not path.exists():
        raise KeyError_(f"Файл ключа не найден: {path}")
    try:
        # paramiko 5.x передаёт пароль в cryptography без кодирования,
        # поэтому передаём bytes напрямую (str там падает с TypeError).
        return paramiko.PKey.from_path(str(path), password=passphrase.encode("utf-8") or None)
    except paramiko.PasswordRequiredException as exc:
        raise KeyError_("Ключ зашифрован парольной фразой") from exc
    except paramiko.SSHException as exc:
        raise KeyError_(f"Не удалось прочитать ключ: {exc}") from exc
    except (ValueError, TypeError) as exc:
        text = str(exc).lower()
        if "not provided" in text or "password-protected" in text:
            raise KeyError_("Ключ зашифрован парольной фразой") from exc
        if passphrase:
            raise KeyError_("Неверная парольная фраза или неизвестный формат ключа") from exc
        raise KeyError_(f"Не удалось прочитать ключ: {exc}") from exc


def needs_passphrase(path: str | Path) -> bool:
    """Зашифрован ли приватный ключ парольной фразой."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    loaders = (serialization.load_ssh_private_key, serialization.load_pem_private_key)
    for loader in loaders:
        try:
            loader(data, password=None)
            return False
        except TypeError:
            return True
        except Exception:  # формат не подошёл — пробуем другой загрузчик
            continue
    return False


def public_line(path: str | Path, passphrase: str = "") -> str:
    """Публичный ключ: сначала пробуем .pub, иначе вычисляем из приватного."""
    path = Path(path)
    pub_file = path.with_suffix(path.suffix + ".pub")
    if pub_file.exists():
        text = pub_file.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith(("ssh-", "ecdsa-")):
            return text
    key = load(path, passphrase)
    return f"{key.get_name()} {key.get_base64()}".strip()


def export_unencrypted(path: str | Path, passphrase: str, destination: Path) -> Path:
    """Пишет незашифрованную копию ключа — её понимает rclone.

    Копия создаётся только на время подключения и удаляется при отключении.
    """
    source = Path(path)
    data = source.read_bytes()
    password = passphrase.encode("utf-8") if passphrase else None
    try:
        private = serialization.load_ssh_private_key(data, password=password)
    except ValueError:
        private = serialization.load_pem_private_key(data, password=password)
    blob = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(blob)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return destination


def fingerprint(path: str | Path, passphrase: str = "") -> str:
    key = load(path, passphrase)
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")
