"""SFTP-сервер SSH Share на asyncssh.

Отдаёт выбранную папку по SSH: пароль и/или публичные ключи, chroot внутри
папки, режим «только чтение» на пользователя.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import threading
from pathlib import Path
from typing import Callable

import asyncssh

from .config import ShareConfig, ShareUser
from .hostkey import fingerprint, load_or_create

Log = Callable[[str, str], None]


class ShareError(Exception):
    """Не удалось запустить/остановить сервер."""


def _local_path(sftp_path: bytes) -> str:
    text = os.fsdecode(sftp_path)
    if text[:1] == "/" and text[2:3] == ":":
        text = text[1:]
    if os.name == "nt":
        text = text.replace("/", "\\")
    return text


def _within(root: str, path: str) -> bool:
    root_n = os.path.normcase(os.path.abspath(root))
    path_n = os.path.normcase(os.path.abspath(path))
    try:
        return os.path.commonpath([root_n, path_n]) == root_n
    except ValueError:  # разные диски
        return False


class ConfinedSFTPServer(asyncssh.SFTPServer):
    """SFTP-сервер, запертый в папке (включая симлинки/ junctions)."""

    def __init__(self, chan, root: Path) -> None:
        self._root = os.path.realpath(str(root))
        super().__init__(chan, chroot=os.fsencode(self._root))

    def map_path(self, path: bytes) -> bytes:
        mapped = super().map_path(path)
        local = os.path.realpath(_local_path(mapped))
        if not _within(self._root, local):
            raise asyncssh.SFTPPermissionDenied
        return mapped


class ReadOnlySFTPServer(ConfinedSFTPServer):
    """То же, но любые изменения запрещены."""

    _write_flags = asyncssh.FXF_WRITE | asyncssh.FXF_CREAT | asyncssh.FXF_TRUNC | asyncssh.FXF_APPEND

    def open(self, path, pflags, attrs):
        if pflags & self._write_flags:
            raise asyncssh.SFTPPermissionDenied
        return super().open(path, pflags, attrs)

    def open56(self, path, desired_access, flags, attrs):
        if desired_access & (asyncssh.ACE4_WRITE_DATA | asyncssh.ACE4_APPEND_DATA):
            raise asyncssh.SFTPPermissionDenied
        disposition = flags & asyncssh.FXF_ACCESS_DISPOSITION
        if disposition != asyncssh.FXF_OPEN_EXISTING:
            raise asyncssh.SFTPPermissionDenied
        if flags & asyncssh.FXF_APPEND_DATA:
            raise asyncssh.SFTPPermissionDenied
        return super().open56(path, desired_access, flags, attrs)

    def _deny(self, *args, **kwargs):
        raise asyncssh.SFTPPermissionDenied

    mkdir = _deny
    remove = _deny
    rmdir = _deny
    rename = _deny
    posix_rename = _deny
    symlink = _deny
    link = _deny
    setstat = _deny
    fsetstat = _deny
    lsetstat = _deny


class _AuthServer(asyncssh.SSHServer):
    """Проверка пользователей по паролю и публичным ключам."""

    def __init__(
        self,
        users: dict[str, ShareUser],
        keys: dict[str, set[bytes]],
        connections: set,
        log: Log,
    ) -> None:
        self._users = users
        self._keys = keys
        self._connections = connections
        self._log = log
        self._username = ""
        self._peer = ""
        self._conn = None

    def connection_made(self, conn) -> None:
        self._conn = conn
        self._connections.add(conn)
        try:
            self._peer = str(conn.get_extra_info("peername") or "")
        except Exception:  # noqa: BLE001
            self._peer = ""
        self._log(f"Подключение: {self._peer}", "info")

    def connection_lost(self, exc) -> None:
        self._connections.discard(self._conn)
        self._log(f"Отключение: {self._peer}", "dim")

    def begin_auth(self, username: str) -> bool:
        self._username = username
        return True

    def password_auth_supported(self) -> bool:
        return any(user.has_password for user in self._users.values())

    def validate_password(self, username: str, password: str) -> bool:
        user = self._users.get(username)
        expected = user.password() if user else ""
        ok = bool(expected) and hmac.compare_digest(expected.encode("utf-8"), password.encode("utf-8"))
        if ok:
            self._log(f"Вход по паролю: {username}@{self._peer}", "ok")
        else:
            self._log(f"Неудачный вход по паролю: {username}@{self._peer}", "warn")
        return ok

    def public_key_auth_supported(self) -> bool:
        return any(self._keys.values())

    def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
        data = key.export_public_key()
        ok = data in self._keys.get(username, set())
        if ok:
            self._log(f"Вход по ключу: {username}@{self._peer}", "ok")
        else:
            self._log(f"Неудачный вход по ключу: {username}@{self._peer}", "warn")
        return ok


class ShareServer:
    """Управляет жизненным циклом SFTP-сервера в отдельном потоке."""

    def __init__(self, config: ShareConfig, log: Log | None = None) -> None:
        self._config = config
        self._log = log or (lambda _message, _level: None)
        self._root = Path(config.folder)
        self._users = {user.name: user for user in config.users}
        self._keys = {
            user.name: {
                asyncssh.import_public_key(item).export_public_key()
                for item in user.keys
                if item.strip()
            }
            for user in config.users
        }
        self._host_key = None  # type: ignore[assignment]
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server = None
        self._ready = threading.Event()
        self._error = ""
        self.port = int(config.port)
        self._connections: set = set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and bool(self._server)

    def fingerprint(self) -> str:
        if self._host_key is None:
            return ""
        return fingerprint(self._host_key)

    def start(self) -> None:
        if self.running:
            return
        if not self._root.is_dir():
            raise ShareError(f"Папка не найдена: {self._root}")
        try:
            self._host_key = load_or_create()
        except Exception as exc:  # noqa: BLE001
            raise ShareError(str(exc)) from exc

        self._ready.clear()
        self._error = ""
        self._server = None
        self._thread = threading.Thread(target=self._run, name="share-server", daemon=True)
        self._thread.start()
        if not self._ready.wait(15):
            self.stop()
            raise ShareError("Сервер не запустился за 15 секунд.")
        if self._error:
            self.stop()
            raise ShareError(self._error)

    def stop(self) -> None:
        loop = self._loop
        server = self._server
        if loop is not None and server is not None:
            try:
                loop.call_soon_threadsafe(self._shutdown)
            except RuntimeError:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=10)
        self._thread = None
        self._server = None
        self._loop = None
        self.port = int(self._config.port)

    def _shutdown(self) -> None:
        if self._server is not None:
            try:
                self._server.close()
            except Exception:  # noqa: BLE001
                pass
        for conn in list(self._connections):
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        self._connections.clear()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            self._server = loop.run_until_complete(self._create_server())
            self.port = self._server.get_port()
            self._log(f"Сервер слушает {self._config.bind}:{self.port}", "ok")
            self._ready.set()
            loop.run_until_complete(self._server.wait_closed())
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            self._log(f"Ошибка сервера: {self._error}", "err")
            self._ready.set()
        finally:
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass

    async def _create_server(self):
        assert self._host_key is not None
        return await asyncssh.create_server(
            lambda: _AuthServer(self._users, self._keys, self._connections, self._log),
            self._config.bind or "0.0.0.0",
            int(self._config.port),
            server_host_keys=[self._host_key],
            sftp_factory=self._sftp_factory,
            server_version="SSHShare",
            login_timeout=60,
        )

    def _sftp_factory(self, chan):
        username = str(chan.get_extra_info("username") or "")
        user = self._users.get(username)
        read_only = True if user is None else user.read_only
        cls = ReadOnlySFTPServer if read_only else ConfinedSFTPServer
        return cls(chan, self._root)
