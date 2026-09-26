# -*- coding: utf-8 -*-
"""Windows DPAPI 加密封箱（CurrentUser 作用域）。

零第三方依赖：ctypes 直调 crypt32 的 CryptProtectData / CryptUnprotectData。
- 加密绑定当前 Windows 用户 + 机器：数据拷贝到其他机器/用户无法解密（预期行为）
- 典型用途：Cookie 缓存落盘加密（见 browser.save_cookies / load_cookies）
- 注意：blob 内的描述串（"eitech-lms-cookies"）不含敏感信息
"""
import ctypes
from ctypes import wintypes

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SecretBoxError(Exception):
    """DPAPI 加解密失败。"""


class _CRYPT_INTEGER_BLOB(ctypes.Structure):
    """winbase.h 的 DATA_BLOB：DWORD cbData; BYTE *pbData;"""
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> _CRYPT_INTEGER_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _CRYPT_INTEGER_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))


def _out_blob() -> _CRYPT_INTEGER_BLOB:
    return _CRYPT_INTEGER_BLOB()


def _take(out_blob: _CRYPT_INTEGER_BLOB) -> bytes:
    """取出输出 blob 内容并释放系统分配的内存。"""
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)


_protect = ctypes.windll.crypt32.CryptProtectData
_protect.argtypes = [ctypes.POINTER(_CRYPT_INTEGER_BLOB), wintypes.LPCWSTR,
                     ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                     wintypes.DWORD, ctypes.POINTER(_CRYPT_INTEGER_BLOB)]
_protect.restype = wintypes.BOOL

_unprotect = ctypes.windll.crypt32.CryptUnprotectData
_unprotect.argtypes = [ctypes.POINTER(_CRYPT_INTEGER_BLOB), ctypes.POINTER(wintypes.LPCWSTR),
                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                       wintypes.DWORD, ctypes.POINTER(_CRYPT_INTEGER_BLOB)]
_unprotect.restype = wintypes.BOOL


def dpapi_encrypt(data: bytes) -> bytes:
    """DPAPI 加密（CurrentUser 作用域）。输入输出均为原始字节。"""
    if not isinstance(data, bytes):
        raise TypeError("dpapi_encrypt 需要 bytes")
    in_blob = _blob(data)
    out_blob = _out_blob()
    if not _protect(ctypes.byref(in_blob), "eitech-lms-cookies",
                    None, None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
        raise SecretBoxError(f"CryptProtectData 失败（GetLastError={ctypes.GetLastError()}）")
    return _take(out_blob)


def dpapi_decrypt(blob: bytes) -> bytes:
    """DPAPI 解密。损坏 / 跨机器 / 跨用户时抛 SecretBoxError。"""
    if not isinstance(blob, bytes):
        raise TypeError("dpapi_decrypt 需要 bytes")
    in_blob = _blob(blob)
    out_blob = _out_blob()
    if not _unprotect(ctypes.byref(in_blob), None,
                      None, None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob)):
        raise SecretBoxError(f"CryptUnprotectData 失败（GetLastError={ctypes.GetLastError()}）")
    return _take(out_blob)
