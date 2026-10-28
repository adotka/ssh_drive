"""Генерирует иконки для exe: build/sshdrive.ico и build/sshshare.ico."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sshdrive.tray import make_icon_image  # noqa: E402
from ssh_share.app import make_icon as make_share_icon  # noqa: E402

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> int:
    build = ROOT / "build"
    build.mkdir(parents=True, exist_ok=True)

    for name, factory in (
        ("sshdrive.ico", make_icon_image),
        ("sshshare.ico", make_share_icon),
    ):
        target = build / name
        image = factory(256)
        image.save(target, format="ICO", sizes=SIZES)
        print(f"иконка: {target} ({target.stat().st_size} байт)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
