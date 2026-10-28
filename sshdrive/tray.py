"""Иконка в системном трее (pystray + Pillow).

Окно при закрытии не завершает программу: оно скрывается, а диски продолжают
работать. Выход — через меню иконки или «Файл → Выход».
"""

from __future__ import annotations

import threading
from typing import Callable

from PIL import Image, ImageDraw

try:
    import pystray
except Exception:  # noqa: BLE001 - без pystray программа всё равно работает
    pystray = None


def make_icon_image(size: int = 64) -> "Image.Image":
    """Простая иконка: синий квадрат, белый «диск» и зелёный индикатор."""
    scale = size / 64.0
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def px(value: float) -> float:
        return value * scale

    draw.rounded_rectangle(
        [px(2), px(2), px(62), px(62)], radius=px(14), fill=(30, 64, 175, 255)
    )
    draw.rounded_rectangle(
        [px(13), px(19), px(51), px(45)], radius=px(6), fill=(255, 255, 255, 255)
    )
    draw.rounded_rectangle(
        [px(19), px(25), px(45), px(29)], radius=px(2), fill=(30, 64, 175, 255)
    )
    draw.ellipse([px(42), px(35), px(48), px(41)], fill=(34, 197, 94, 255))
    return image


class TrayIcon:
    """Обёртка над pystray: колбэки вызываются из потока трея."""

    def __init__(
        self,
        on_open: Callable[[], None],
        on_disconnect_all: Callable[[], None],
        on_quit: Callable[[], None],
        tooltip: str = "SSH Drive",
    ) -> None:
        self._on_open = on_open
        self._on_disconnect_all = on_disconnect_all
        self._on_quit = on_quit
        self._icon = None
        self._thread: threading.Thread | None = None
        self.error: str = ""
        if pystray is None:
            self.error = "модуль pystray не установлен"
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Открыть окно", self._open, default=True),
                pystray.MenuItem("Отключить все диски", self._disconnect_all),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Выход", self._quit),
            )
            self._icon = pystray.Icon("ssh_drive", make_icon_image(), tooltip, menu)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)

    @property
    def available(self) -> bool:
        return self._icon is not None

    # --- колбэки пунктов меню (запускаются в потоке pystray) --------------
    def _open(self, *_args) -> None:
        self._on_open()

    def _disconnect_all(self, *_args) -> None:
        self._on_disconnect_all()

    def _quit(self, *_args) -> None:
        self._on_quit()

    # --- управление ------------------------------------------------------
    def start(self) -> bool:
        if self._icon is None:
            return False
        self._thread = threading.Thread(target=self._run, name="tray-icon", daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        try:
            assert self._icon is not None
            self._icon.run()
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)

    def stop(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001
            pass

    def set_tooltip(self, text: str) -> None:
        if self._icon is None:
            return
        try:
            self._icon.title = text
        except Exception:  # noqa: BLE001
            pass

    def notify(self, message: str, title: str = "SSH Drive") -> None:
        if self._icon is None:
            return
        try:
            self._icon.notify(message, title)
        except Exception:  # noqa: BLE001
            pass
