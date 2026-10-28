# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-спецификация SSH Drive (onefile, без консоли).

Обычная сборка:      pyinstaller sshdrive.spec
Offline-сборка:      set SSHDRIVE_BUNDLE_TOOLS=1
                     (дополнительно кладёт в exe rclone.exe и MSI WinFsp)
Имя файла:           set SSHDRIVE_EXE_NAME=SSHDrive-offline
"""

import os
from pathlib import Path

ROOT = Path(SPECPATH)
BUILD = ROOT / "build"
ICON = BUILD / "sshdrive.ico"
NAME = os.environ.get("SSHDRIVE_EXE_NAME", "SSHDrive")
BUNDLE_TOOLS = os.environ.get("SSHDRIVE_BUNDLE_TOOLS") == "1"

if not ICON.is_file():
    raise SystemExit("Нет build/sshdrive.ico — сначала запустите tools/make_icon.py")

binaries = []
datas = [(str(ROOT / "README.md"), ".")]

if BUNDLE_TOOLS:
    rclone_exe = BUILD / "rclone.exe"
    if not rclone_exe.is_file():
        raise SystemExit("Нет build/rclone.exe — сначала запустите tools/fetch_tools.py")
    binaries.append((str(rclone_exe), "."))
    for msi in sorted(BUILD.glob("winfsp-*.msi")):
        datas.append((str(msi), "."))

a = Analysis(
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "pystray._win32",
        "pystray._util.win32",
        "PIL._tkinter_finder",
        "paramiko",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter.test",
        "PIL.ImageQt",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
)
