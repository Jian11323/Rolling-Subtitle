#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
敏感配置落盘保护。

Windows：使用当前用户 DPAPI 加密（仅本机本用户可解密）。
其它平台：无法 DPAPI 时保持明文，并带前缀兼容读取。

内存中 Config 始终持有明文；仅 settings.json 写入加密串。
"""

from __future__ import annotations

import base64
import sys
from typing import Any, Dict, Iterable, Optional, Tuple

from utils.logger import get_logger

logger = get_logger()

# 落盘前缀：enc:v1:<base64>
_ENC_PREFIX = "enc:v1:"

# (section, field) — 需保护的敏感键
SECRET_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("WS_CONFIG", "fanstudio_api_key"),
    ("WS_CONFIG", "whews_token"),
    ("WS_CONFIG", "eqsc_login_token"),
    ("TRANSLATION_CONFIG", "baidu_secret"),
)


def is_encrypted_value(value: Any) -> bool:
    """是否为本模块写出的加密串。"""
    return isinstance(value, str) and value.startswith(_ENC_PREFIX)


def _dpapi_protect(raw: bytes) -> Optional[bytes]:
    """Windows DPAPI Encrypt；失败返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        blob_in = DATA_BLOB(
            len(raw),
            ctypes.cast(ctypes.create_string_buffer(raw, len(raw)), ctypes.POINTER(ctypes.c_char)),
        )
        blob_out = DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception as e:
        logger.debug(f"DPAPI 加密失败: {e}")
        return None


def _dpapi_unprotect(blob: bytes) -> Optional[bytes]:
    """Windows DPAPI Decrypt；失败返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        blob_in = DATA_BLOB(
            len(blob),
            ctypes.cast(ctypes.create_string_buffer(blob, len(blob)), ctypes.POINTER(ctypes.c_char)),
        )
        blob_out = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(blob_out),
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception as e:
        logger.debug(f"DPAPI 解密失败: {e}")
        return None


def encrypt_secret(plaintext: str) -> str:
    """
    加密敏感字符串以便写入配置文件。

    空串原样返回；非 Windows 或 DPAPI 失败时回退明文（行为与历史一致）。
    """
    text = "" if plaintext is None else str(plaintext)
    if not text:
        return ""
    if is_encrypted_value(text):
        return text
    protected = _dpapi_protect(text.encode("utf-8"))
    if not protected:
        if sys.platform == "win32":
            logger.warning("敏感字段 DPAPI 加密失败，将以明文写入配置（可忽略于受限环境）")
        return text
    return _ENC_PREFIX + base64.b64encode(protected).decode("ascii")


def decrypt_secret(value: Any) -> str:
    """
    读取配置时还原敏感字段。

    已是明文、空值或解密失败时尽量安全回退（解密失败返回空并打日志）。
    """
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if not is_encrypted_value(text):
        return text
    try:
        blob = base64.b64decode(text[len(_ENC_PREFIX) :], validate=True)
    except Exception:
        logger.warning("敏感字段密文损坏，已忽略该值")
        return ""
    raw = _dpapi_unprotect(blob)
    if raw is None:
        logger.warning("敏感字段 DPAPI 解密失败（可能换用户/机器），已清空该密钥")
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("敏感字段解密结果非 UTF-8，已清空")
        return ""


def protect_secrets_in_config_dict(config_data: Dict[str, Any]) -> Dict[str, Any]:
    """深拷贝式就地加密：返回新 dict（顶层与敏感 section 复制）。"""
    if not isinstance(config_data, dict):
        return config_data
    out = dict(config_data)
    for section, field in SECRET_FIELDS:
        sec = out.get(section)
        if not isinstance(sec, dict) or field not in sec:
            continue
        sec_copy = dict(sec)
        sec_copy[field] = encrypt_secret(sec_copy.get(field) or "")
        out[section] = sec_copy
    return out


def reveal_secrets_in_config_dict(config_data: Dict[str, Any]) -> None:
    """就地解密配置 dict 中的敏感字段（加载阶段用）。"""
    if not isinstance(config_data, dict):
        return
    for section, field in SECRET_FIELDS:
        sec = config_data.get(section)
        if not isinstance(sec, dict) or field not in sec:
            continue
        sec[field] = decrypt_secret(sec.get(field))


def secret_fields_for_section(section: str) -> Iterable[str]:
    """某配置段下的敏感字段名。"""
    return tuple(f for s, f in SECRET_FIELDS if s == section)
