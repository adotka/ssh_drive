# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-спецификация SSH Share (onefile, без консоли)."""

from pathlib import Path

ROOT = Path(SPECPATH)
ICON = ROOT / "build" / "sshshare.ico"

if not ICON.is_file():
    raise SystemExit("Нет build/sshshare.ico — сначала запустите tools/make_icon.py")

a = Analysis(
    [str(ROOT / "run_share.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "README.md"), ".")],
    hiddenimports=[
        "asyncssh",
        "pystray._win32",
        "PIL._tkinter_finder",
        "paramiko",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "PIL.ImageQt", "PyQt5", "PyQt6", "PySide2", "PySide6"],
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
    name="SSHShare",
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
