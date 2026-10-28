"""Скачивает WiX Toolset 3.14 (portable binaries) в build/wix.

Нужен только для сборки MSI; интернет требуется один раз.
"""

from __future__ import annotations

import hashlib
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
# SHA256 архива, снятый при закреплении версии (GitHub его для WiX не публикует).
# Меняете URL — обновите и хэш.
SHA256 = "6ac824e1642d6f7277d0ed7ea09411a508f6116ba6fae0aa5f2c7daa2ff43d31"


def main() -> int:
    if (TARGET / "candle.exe").is_file() and (TARGET / "light.exe").is_file():
        print(f"WiX уже распакован: {TARGET}")
        return 0

    print("Скачиваю WiX Toolset 3.14…")
    request = urllib.request.Request(URL, headers={"User-Agent": "SSHDrive-build"})
    with urllib.request.urlopen(request, timeout=180) as response:
        data = response.read()

    actual = hashlib.sha256(data).hexdigest()
    if actual != SHA256:
        print(
            "Контрольная сумма WiX не совпала — архив повреждён или подменён.\n"
            f"  ожидалась {SHA256}\n  получена  {actual}",
            file=sys.stderr,
        )
        return 1

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
