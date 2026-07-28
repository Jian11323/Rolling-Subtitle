#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeJet WAuth 应用凭证辅助。

AppID / AppSecret 以异或混淆后的密文写入源码，运行时再还原，降低明文被直接搜出的风险。
"""

from __future__ import annotations

import base64
import hashlib
from typing import Tuple

# 盐值与密文分离存放，避免整段明文出现在源码中
_APP_SALT = b"RollingSubtitle.WAuth.v1"
_APP_ID_CIPHER_B64 = "PIuQU4/qflgORlU9wIBbDIj2fSmj3WRGjHwi39Cy"
_APP_SECRET_CIPHER_B64 = "RvIQywurIav5E8DEE1D6+LmL7E3V52OVCGyIB96cBQAapUWfCq97qPxAlcJDVvPz"

# 桌面端 OAuth 回调（须在 WAuth 开发者后台登记到该应用）
WAUTH_REDIRECT_URI = "http://127.0.0.1:18765/callback"
WAUTH_LOOPBACK_HOST = "127.0.0.1"
WAUTH_LOOPBACK_PORT = 18765
WAUTH_ISSUER = "https://auth.beecld.com"


def _xor_unmask(data: bytes, key: bytes) -> bytes:
    """按字节异或还原/混淆。"""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def get_wauth_app_id() -> str:
    """解密并返回本软件定制的 WAuth AppID（client_id）。"""
    key = hashlib.sha256(_APP_SALT + b"#appId").digest()
    raw = base64.b64decode(_APP_ID_CIPHER_B64)
    return _xor_unmask(raw, key).decode("utf-8")


def get_wauth_app_secret() -> str:
    """解密并返回本软件定制的 WAuth AppSecret（client_secret）。"""
    key = hashlib.sha256(_APP_SALT + b"#appSecret").digest()
    raw = base64.b64decode(_APP_SECRET_CIPHER_B64)
    return _xor_unmask(raw, key).decode("utf-8")


def get_wauth_client_credentials() -> Tuple[str, str]:
    """返回 (AppID, AppSecret)。"""
    return get_wauth_app_id(), get_wauth_app_secret()
