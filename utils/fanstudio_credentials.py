#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fan Studio /all 鉴权凭证辅助。

应用 AppID 以异或混淆后的密文形式写入二进制，运行时再还原，降低明文被直接搜出的风险。
用户 API Key（sk-…）由设置页填写并保存在本地配置中。
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Dict, Optional, Tuple

# 盐值与密文分离存放，避免整段明文 AppID 出现在源码中
_APP_ID_SALT = b"RollingSubtitle.FanStudio.v1"
_APP_ID_CIPHER_B64 = "Zy9M0QfuENEJ6PN4NCIQr2mNZ2f1x5NWKtUkZZ1elHk2dE3Z"


def _xor_unmask(data: bytes, key: bytes) -> bytes:
    """按字节异或还原/混淆。"""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def get_fanstudio_app_id() -> str:
    """解密并返回本软件定制的 Fan Studio AppID。"""
    key = hashlib.sha256(_APP_ID_SALT + b"#appId").digest()
    raw = base64.b64decode(_APP_ID_CIPHER_B64)
    return _xor_unmask(raw, key).decode("utf-8")


def build_fanstudio_auth_payload(api_key: str) -> Dict[str, str]:
    """
    构造 Fan Studio WebSocket 鉴权消息体。

    发送格式：{"type":"auth","appId":"...","key":"sk-..."}
    """
    key = (api_key or "").strip()
    return {
        "type": "auth",
        "appId": get_fanstudio_app_id(),
        "key": key,
    }


def build_fanstudio_auth_message(api_key: str) -> str:
    """构造可直接通过 WebSocket 发送的鉴权 JSON 字符串。"""
    return json.dumps(build_fanstudio_auth_payload(api_key), ensure_ascii=False, separators=(",", ":"))


def parse_fanstudio_auth_response(data: Any) -> Tuple[Optional[bool], str]:
    """
    解析鉴权响应。

    Returns:
        (True, message) 鉴权成功；
        (False, message) 鉴权失败（type=error）；
        (None, "") 非鉴权相关消息。
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None, ""
    if not isinstance(data, dict):
        return None, ""
    msg_type = str(data.get("type") or "").strip().lower()
    message = str(data.get("message") or "").strip()
    if msg_type == "auth_success":
        return True, message or "鉴权成功，已接入数据流。"
    if msg_type == "error":
        return False, message or "鉴权失败"
    return None, ""


def test_fanstudio_auth(api_key: str, timeout_seconds: float = 15.0) -> Tuple[bool, str]:
    """
    临时连接 Fan Studio /all，发送鉴权并等待 auth_success / error。

    Returns:
        (成功与否, 提示文案)
    """
    import asyncio
    import time

    import websockets

    from config import FANSTUDIO_ALL_URL

    key = (api_key or "").strip()
    if not key:
        return False, "请先填写 Fan Studio API Key"

    async def _run() -> Tuple[bool, str]:
        auth_msg = build_fanstudio_auth_message(key)
        async with websockets.connect(
            FANSTUDIO_ALL_URL,
            open_timeout=10,
            ping_interval=None,
            close_timeout=3,
        ) as websocket:
            await websocket.send(auth_msg)
            deadline = time.monotonic() + max(3.0, float(timeout_seconds))
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=min(5.0, remaining))
                except asyncio.TimeoutError:
                    continue
                if isinstance(raw, bytes):
                    try:
                        raw = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        raw = raw.decode("utf-8", errors="replace")
                ok, message = parse_fanstudio_auth_response(raw)
                if ok is True:
                    return True, message
                if ok is False:
                    return False, message
            return False, "等待鉴权响应超时，请检查网络或稍后重试"

    try:
        return asyncio.run(_run())
    except Exception as e:
        return False, f"连接失败: {e}"
