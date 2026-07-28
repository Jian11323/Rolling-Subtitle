#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeJet WAuth 统一登录（OAuth2 Authorization Code + PKCE）。

流程：
1. 本机临时监听 127.0.0.1:18765/callback
2. 浏览器打开授权页
3. 用授权码换取 token；响应中的 api_token（wat_…）用于 WeJet 数据源鉴权
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, Optional, Tuple

import requests

from utils.wauth_credentials import (
    WAUTH_ISSUER,
    WAUTH_LOOPBACK_HOST,
    WAUTH_LOOPBACK_PORT,
    WAUTH_REDIRECT_URI,
    get_wauth_client_credentials,
)

_AUTHORIZE_URL = f"{WAUTH_ISSUER}/oauth2/authorize"
_TOKEN_URL = f"{WAUTH_ISSUER}/oauth2/token"
_USERINFO_URL = f"{WAUTH_ISSUER}/oauth2/userinfo"
_VERIFY_URL = f"{WAUTH_ISSUER}/api/token/verify"


@dataclass
class WAuthLoginResult:
    """统一登录结果。"""

    ok: bool
    message: str
    api_token: str = ""
    access_token: str = ""
    username: str = ""
    user_id: str = ""


def _b64url(data: bytes) -> str:
    """Base64URL（无填充）。"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_pair() -> Tuple[str, str]:
    """生成 PKCE code_verifier / S256 code_challenge。"""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _html_page(title: str, body: str) -> bytes:
    """生成回调页 HTML。"""
    html = (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'/>"
        f"<title>{title}</title>"
        "<style>body{font-family:Segoe UI,Microsoft YaHei,sans-serif;"
        "padding:40px;line-height:1.6;color:#1d2129;background:#f5f7fa}"
        ".card{max-width:480px;margin:40px auto;background:#fff;padding:28px;"
        "border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.06)}</style>"
        f"</head><body><div class='card'><h2>{title}</h2><p>{body}</p>"
        "<p style='color:#86909c;font-size:13px'>可关闭本页，返回实况栏设置窗口。</p>"
        "</div></body></html>"
    )
    return html.encode("utf-8")


class _CallbackServer(HTTPServer):
    """携带授权结果的本机回调服务。"""

    def __init__(self, server_address, RequestHandlerClass):
        super().__init__(server_address, RequestHandlerClass)
        self.auth_code: Optional[str] = None
        self.auth_error: Optional[str] = None
        self.expected_state: str = ""
        self.done_event = threading.Event()


def _make_handler() -> type:
    """构造回调 Handler 类。"""

    class Handler(BaseHTTPRequestHandler):
        """处理 OAuth redirect。"""

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.rstrip("/") != "/callback":
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_html_page("未找到", "无效的回调路径。"))
                return
            qs = urllib.parse.parse_qs(parsed.query)
            server: _CallbackServer = self.server  # type: ignore[assignment]
            state = (qs.get("state") or [""])[0]
            err = (qs.get("error") or [""])[0]
            code = (qs.get("code") or [""])[0]
            if err:
                server.auth_error = err
                desc = (qs.get("error_description") or [err])[0]
                body = _html_page("登录失败", f"授权被拒绝或失败：{desc}")
                self.send_response(400)
            elif not code:
                server.auth_error = "missing_code"
                body = _html_page("登录失败", "回调中缺少授权码。")
                self.send_response(400)
            elif state != server.expected_state:
                server.auth_error = "invalid_state"
                body = _html_page("登录失败", "state 校验失败，请重试。")
                self.send_response(400)
            else:
                server.auth_code = code
                body = _html_page("登录成功", "WeJet 统一登录已完成，请返回设置窗口。")
                self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            server.done_event.set()

    return Handler


def _exchange_code(code: str, code_verifier: str, timeout: float = 20.0) -> Dict[str, Any]:
    """用授权码换取 token（含 api_token）。"""
    client_id, client_secret = get_wauth_client_credentials()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": WAUTH_REDIRECT_URI,
        "code_verifier": code_verifier,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    resp = requests.post(
        _TOKEN_URL,
        data=data,
        auth=(client_id, client_secret),
        timeout=timeout,
        headers={"Accept": "application/json"},
    )
    try:
        payload = resp.json()
    except Exception:
        payload = {"error": "invalid_response", "error_description": resp.text[:300]}
    if resp.status_code >= 400:
        err = payload.get("error") or f"http_{resp.status_code}"
        desc = payload.get("error_description") or payload.get("message") or str(payload)
        raise RuntimeError(f"换取令牌失败：{err} — {desc}")
    if not isinstance(payload, dict):
        raise RuntimeError("换取令牌失败：响应格式无效")
    return payload


def _fetch_userinfo(access_token: str, timeout: float = 15.0) -> Dict[str, Any]:
    """拉取 UserInfo（可选）。"""
    if not access_token:
        return {}
    try:
        resp = requests.get(
            _USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )
        if resp.status_code >= 400:
            return {}
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def verify_api_token(api_token: str, timeout: float = 12.0) -> Tuple[bool, str]:
    """校验 wat_ 令牌是否有效。"""
    token = (api_token or "").strip()
    if not token:
        return False, "令牌为空"
    try:
        resp = requests.post(
            _VERIFY_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        data = resp.json() if resp.content else {}
        if isinstance(data, dict) and data.get("valid") is True:
            name = data.get("username") or data.get("user_id") or ""
            return True, f"令牌有效{f'（{name}）' if name else ''}"
        err = ""
        if isinstance(data, dict):
            err = str(data.get("error") or data.get("message") or "")
        return False, err or "令牌无效"
    except Exception as e:
        return False, f"校验失败: {e}"


def login_with_browser(
    timeout_seconds: float = 180.0,
    open_browser: bool = True,
    on_authorize_url: Optional[Callable[[str], None]] = None,
) -> WAuthLoginResult:
    """
    打开浏览器完成 WAuth 统一登录，返回 api_token（wat_…）。

    Args:
        timeout_seconds: 等待用户完成授权的最长时间
        open_browser: 是否自动打开系统浏览器
        on_authorize_url: 若提供，在打开浏览器前回调授权 URL（便于 UI 展示）
    """
    client_id, _ = get_wauth_client_credentials()
    if not client_id:
        return WAuthLoginResult(False, "未配置 WAuth AppID")

    verifier, challenge = _pkce_pair()
    state = _b64url(secrets.token_bytes(16))
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": WAUTH_REDIRECT_URI,
        "scope": "openid profile email",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{_AUTHORIZE_URL}?{urllib.parse.urlencode(query)}"

    try:
        server = _CallbackServer(
            (WAUTH_LOOPBACK_HOST, WAUTH_LOOPBACK_PORT),
            _make_handler(),
        )
    except OSError as e:
        return WAuthLoginResult(
            False,
            f"无法监听 {WAUTH_REDIRECT_URI}（端口可能被占用）：{e}",
        )

    server.expected_state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if on_authorize_url is not None:
            try:
                on_authorize_url(authorize_url)
            except Exception:
                pass
        if open_browser:
            webbrowser.open(authorize_url)

        deadline = time.monotonic() + max(30.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            if server.done_event.wait(timeout=0.4):
                break
        else:
            return WAuthLoginResult(False, "等待授权超时，请重试并在浏览器中完成登录")

        if server.auth_error:
            return WAuthLoginResult(False, f"授权失败：{server.auth_error}")
        if not server.auth_code:
            return WAuthLoginResult(False, "未收到授权码")

        token_payload = _exchange_code(server.auth_code, verifier)
        # 文档约定：OAuth 登录时 token 响应自动下发应用专用 api_token（wat_…）
        api_token = str(token_payload.get("api_token") or "").strip()
        access_token = str(token_payload.get("access_token") or "").strip()
        if not api_token:
            return WAuthLoginResult(False, "令牌响应中缺少 api_token，请检查应用权限或联系 WeJet")

        info = _fetch_userinfo(access_token)
        username = str(
            info.get("preferred_username")
            or info.get("name")
            or info.get("username")
            or ""
        ).strip()
        user_id = str(info.get("sub") or info.get("user_id") or "").strip()
        tip = "登录成功"
        if username:
            tip = f"登录成功：{username}"
        return WAuthLoginResult(
            True,
            tip,
            api_token=api_token,
            access_token=access_token,
            username=username,
            user_id=user_id,
        )
    except Exception as e:
        return WAuthLoginResult(False, f"登录失败：{e}")
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
