"""Password protection at rest (1.3.0).

settings.json 中的连接密码使用 Windows DPAPI 加密（CryptProtectData，
当前用户 + 本机作用域，无第三方依赖）。非 Windows 平台退化为明文存储。

存储格式：``dpapi1:<base64>`` 前缀标记；无前缀的值视为明文（兼容旧文件
与 C# 版导出的设置）。导出设置文件时一律输出明文，保持与 C# 版互换。
"""
from __future__ import annotations

import base64
import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)

_PREFIX = "dpapi1:"

__all__ = ["protect", "unprotect", "is_protected", "available"]


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def available() -> bool:
    """DPAPI is only usable on Windows."""
    return ctypes.windll is not None and hasattr(ctypes, "windll")


def _crypt_protect(data: bytes, protect_: bool) -> bytes:
    func = (ctypes.windll.crypt32.CryptProtectData
            if protect_ else ctypes.windll.crypt32.CryptUnprotectData)
    blob_in = _DATA_BLOB(len(data), ctypes.cast(
        ctypes.create_string_buffer(data, len(data)),
        ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    # CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if not func(ctypes.byref(blob_in), None, None, None, None, 0x1,
                ctypes.byref(blob_out)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def protect(plaintext: str) -> str:
    """Encrypt ``plaintext`` for the current user/machine.

    Returns the ``dpapi1:``-prefixed ciphertext, or the input unchanged when
    the password is empty or DPAPI is unavailable (non-Windows)."""
    if not plaintext:
        return plaintext or ""
    if not available():
        return plaintext
    try:
        cipher = _crypt_protect(plaintext.encode("utf-8"), True)
        return _PREFIX + base64.b64encode(cipher).decode("ascii")
    except Exception as ex:  # pragma: no cover - OS specific
        log.warning("DPAPI protect failed, storing plaintext: %s", ex)
        return plaintext


def unprotect(value: str) -> str:
    """Decrypt a ``dpapi1:`` value; plaintext and empty values pass through.

    On decryption failure (e.g. settings moved to another machine) the raw
    value is returned so the user can re-enter the password."""
    if not value or not value.startswith(_PREFIX):
        return value or ""
    if not available():
        return value
    try:
        cipher = base64.b64decode(value[len(_PREFIX):])
        return _crypt_protect(cipher, False).decode("utf-8")
    except Exception as ex:  # pragma: no cover - OS specific
        log.warning("DPAPI unprotect failed: %s", ex)
        return value


def is_protected(value: str) -> bool:
    return bool(value) and value.startswith(_PREFIX)
