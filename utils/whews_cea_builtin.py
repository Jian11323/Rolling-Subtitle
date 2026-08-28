# -*- coding: utf-8 -*-
"""
WeJet CEA App 内置凭证（仅本软件使用，不对外暴露设置项）。

通过 /ws/cea_all 一次鉴权同时覆盖 CEA 与 CEA-PR。
"""

from __future__ import annotations

import base64
from typing import Tuple

# 轻量混淆，避免源码字符串表直接出现完整明文（非强加密）
_XOR_KEY = b"subtitl-whews-cea-v1"
_APP_ID_BLOB = "EgUSKwxDXhVEWVRDQxUAXQUVFAI="
_APP_SECRET_BLOB = (
    "FhRRTVEVVRpADFVHEk5bVFNOQgVDRQMSDxcOFBFdVUdAH1ZdUkhGBRJDBE1eTAgb"
)


def _deobfuscate(blob_b64: str) -> str:
    raw = base64.b64decode(blob_b64.encode("ascii"))
    key = _XOR_KEY
    plain = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw))
    return plain.decode("utf-8")


def get_builtin_whews_cea_credentials() -> Tuple[str, str]:
    """返回内置 (appId, appSecret)。"""
    return _deobfuscate(_APP_ID_BLOB), _deobfuscate(_APP_SECRET_BLOB)


def apply_builtin_whews_cea_credentials(ws_config: object) -> None:
    """将内置凭证写入 ws_config（覆盖外部篡改，保证软件内一致）。"""
    if ws_config is None:
        return
    app_id, app_secret = get_builtin_whews_cea_credentials()
    setattr(ws_config, "whews_cea_app_id", app_id)
    setattr(ws_config, "whews_cea_app_secret", app_secret)
