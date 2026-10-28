"""Скачивает WiX Toolset 3.14 (portable binaries) в build/wix.

Нужен только для сборки MSI; интернет требуется один раз.
"""

from __future__ import annotations

import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "build" / "wix"
URL = (
    "https://github.com/wixtoolset/wix3/releases/download/"
    "wix3141rtm/wix314-binaries.zip"
)


def main() -> int:
    if (TARGET / "candle.exe").is_file() and (TARGET / "light.exe").is_file():
        print(f"WiX уже распакован: {TARGET}")
        return 0

    print("Скачиваю WiX Toolset 3.14…")
    request = urllib.request.Request(URL, headers={"User-Agent": "SSHDrive-build"})
    with urllib.request.urlopen(request, timeout=180) as response:
        data = response.read()

    TARGET.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
        handle.write(data)
        archive = Path(handle.name)
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(TARGET)
    finally:
        archive.unlink(missing_ok=True)

    if not (TARGET / "light.exe").is_file():
        print("в архиве WiX не найден light.exe", file=sys.stderr)
        return 1
    print(f"WiX готов: {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
