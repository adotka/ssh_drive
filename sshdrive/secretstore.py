"""Шифрование паролей через DPAPI (текущий пользователь Windows).

Пароли никогда не пишутся в открытом виде: в profiles.json лежит только
base64-строка, зашифрованная CryptProtectData. Расшифровать её может только
тот же пользователь на той же машине.
"""

from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes

CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


if os.name == "nt":
    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    _crypt32.CryptProtectData.restype = wintypes.BOOL

    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL

    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
else:  # pragma: no cover - приложение всё же под Windows
    _crypt32 = None
    _kernel32 = None


def _make_blob(data: bytes) -> tuple[_DataBlob, object]:
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    return blob, buf


def _take_blob(blob: _DataBlob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if blob.pbData:
            _kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def protect(text: str) -> str:
    """Шифрует строку и возвращает base64."""
    if not text:
        return ""
    if _crypt32 is None:
        raise RuntimeError("DPAPI доступен только на Windows")
    data = text.encode("utf-8")
    in_blob, _keep = _make_blob(data)
    out_blob = _DataBlob()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    return base64.b64encode(_take_blob(out_blob)).decode("ascii")


def unprotect(token: str) -> str:
    """Расшифровывает base64-строку, созданную protect()."""
    if not token:
        return ""
    if _crypt32 is None:
        raise RuntimeError("DPAPI доступен только на Windows")
    raw = base64.b64decode(token)
    in_blob, _keep = _make_blob(raw)
    out_blob = _DataBlob()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    return _take_blob(out_blob).decode("utf-8")


def try_unprotect(token: str) -> str | None:
    """Как unprotect(), но возвращает None вместо исключения."""
    try:
        return unprotect(token)
    except Exception:
        return None
