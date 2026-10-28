"""Генерирует build/sshdrive.ico для exe и ярлыков."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sshdrive.tray import make_icon_image  # noqa: E402

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> int:
    target = ROOT / "build" / "sshdrive.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    image = make_icon_image(256)
    image.save(target, format="ICO", sizes=SIZES)
    print(f"иконка: {target} ({target.stat().st_size} байт)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
