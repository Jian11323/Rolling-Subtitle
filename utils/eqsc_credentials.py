#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EQSC（equake.top）鉴权凭证辅助。

用户仅需填写 https://equake.top/auth 申请到的登录密钥；
软件内自动完成：登录密钥 → RefreshToken → AccessToken。
文档：https://equake.top/apidocs
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple

import requests

from utils.logger import get_logger

logger = get_logger()

EQSC_BASE_URL = "https://equake.top"
EQSC_WS_URL = "wss://equake.top:50023/"
EQSC_CREATE_REFRESH_TOKEN_URL = f"{EQSC_BASE_URL}/createRefreshToken/v1"
EQSC_CREATE_ACCESS_TOKEN_URL = f"{EQSC_BASE_URL}/createAccessToken/v1"

# AccessToken 默认约 3600s；提前刷新避免边界失效
_ACCESS_REFRESH_SKEW_SEC = 120
# RefreshToken 默认约 259200 分钟；本地缓存失败时再重新换取
_REFRESH_FALLBACK_TTL_SEC = 259200 * 60

_lock = threading.RLock()
# login_key -> 缓存
_cache: Dict[str, Dict[str, Any]] = {}


class _TokenFlight:
    """单次换票飞行：多路轮询共用同一 HTTP 结果，避免 stampede。"""

    __slots__ = ("event", "result")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Optional[Tuple[bool, str, str]] = None


# login_key -> 进行中的换票
_flights: Dict[str, _TokenFlight] = {}


def _bearer_headers(token: str) -> Dict[str, str]:
    """构造 Bearer 鉴权头。"""
    return {
        "Authorization": f"Bearer {(token or '').strip()}",
        "Accept": "application/json",
        "User-Agent": "RollingSubtitle-EQSC/1.0",
    }


def _parse_token_response(body: Any) -> Tuple[bool, str, str, int]:
    """
    解析 createRefreshToken / createAccessToken 响应。

    Returns:
        (ok, token, message, expires_hint)
        expires_hint：秒（Access）或分钟（Refresh，调用方自行换算）
    """
    if not isinstance(body, dict):
        return False, "", "响应格式无效", 0
    code = body.get("code")
    try:
        code_i = int(code)
    except (TypeError, ValueError):
        code_i = -1
    desc = str(body.get("description") or "").strip()
    token = str(body.get("token") or "").strip()
    if code_i != 0 or not token:
        return False, "", desc or f"鉴权失败(code={code})", 0
    expires = 0
    for key in ("expiresAfterSec", "expiresAfterMin"):
        if key in body:
            try:
                expires = int(body.get(key) or 0)
            except (TypeError, ValueError):
                expires = 0
            break
    return True, token, desc or "OK", expires


def create_refresh_token(login_key: str, timeout: float = 15.0) -> Tuple[bool, str, str, int]:
    """
    使用登录密钥换取 RefreshToken。

    Returns:
        (ok, refresh_token, message, expires_after_min)
    """
    key = (login_key or "").strip()
    if not key:
        return False, "", "请先填写 EQSC 登录密钥", 0
    try:
        resp = requests.get(
            EQSC_CREATE_REFRESH_TOKEN_URL,
            headers=_bearer_headers(key),
            timeout=timeout,
        )
        body = resp.json() if resp.content else {}
        ok, token, msg, expires = _parse_token_response(body)
        if not ok:
            return False, "", msg or f"HTTP {resp.status_code}", 0
        return True, token, msg, expires
    except Exception as e:
        logger.warning(f"[EQSC] 获取 RefreshToken 失败: {e}")
        return False, "", f"获取 RefreshToken 失败: {e}", 0


def create_access_token(refresh_token: str, timeout: float = 15.0) -> Tuple[bool, str, str, int]:
    """
    使用 RefreshToken 换取 AccessToken。

    Returns:
        (ok, access_token, message, expires_after_sec)
    """
    token = (refresh_token or "").strip()
    if not token:
        return False, "", "RefreshToken 为空", 0
    try:
        resp = requests.get(
            EQSC_CREATE_ACCESS_TOKEN_URL,
            headers=_bearer_headers(token),
            timeout=timeout,
        )
        body = resp.json() if resp.content else {}
        ok, access, msg, expires = _parse_token_response(body)
        if not ok:
            return False, "", msg or f"HTTP {resp.status_code}", 0
        return True, access, msg, expires
    except Exception as e:
        logger.warning(f"[EQSC] 获取 AccessToken 失败: {e}")
        return False, "", f"获取 AccessToken 失败: {e}", 0


def invalidate_eqsc_token_cache(login_key: Optional[str] = None) -> None:
    """清除指定登录密钥（或全部）的本地 Token 缓存。"""
    with _lock:
        if login_key is None:
            _cache.clear()
            return
        _cache.pop((login_key or "").strip(), None)


def _cached_access_if_valid(key: str, *, force_refresh: bool) -> Optional[Tuple[bool, str, str]]:
    """锁内：若缓存 AccessToken 仍可用则返回结果，否则 None。"""
    if force_refresh:
        return None
    now = time.time()
    entry = _cache.get(key)
    if (
        entry
        and entry.get("access_token")
        and float(entry.get("access_expire_at") or 0) > now + 5
    ):
        return True, str(entry["access_token"]), "OK(cached)"
    return None


def _fetch_and_cache_access_token(
    key: str,
    *,
    force_refresh: bool,
    timeout: float,
) -> Tuple[bool, str, str]:
    """执行密钥→Refresh→Access（调用方负责 single-flight）。"""
    now = time.time()
    with _lock:
        entry = _cache.get(key)
        refresh = ""
        refresh_expire_at = 0.0
        if entry and entry.get("refresh_token"):
            refresh = str(entry["refresh_token"])
            refresh_expire_at = float(entry.get("refresh_expire_at") or 0)
        need_new_refresh = (
            force_refresh
            or not refresh
            or (refresh_expire_at and refresh_expire_at <= now + 60)
        )

    if need_new_refresh:
        ok, refresh, msg, expires_min = create_refresh_token(key, timeout=timeout)
        if not ok:
            return False, "", msg
        refresh_ttl = max(3600, int(expires_min or 0) * 60 or _REFRESH_FALLBACK_TTL_SEC)
        refresh_expire_at = now + refresh_ttl
        with _lock:
            _cache[key] = {
                "refresh_token": refresh,
                "refresh_expire_at": refresh_expire_at,
                "access_token": "",
                "access_expire_at": 0.0,
            }

    ok, access, msg, expires_sec = create_access_token(refresh, timeout=timeout)
    if not ok:
        # Refresh 可能已失效：强制再换一次
        ok2, refresh2, msg2, expires_min2 = create_refresh_token(key, timeout=timeout)
        if not ok2:
            return False, "", msg or msg2
        ok3, access, msg3, expires_sec = create_access_token(refresh2, timeout=timeout)
        if not ok3:
            return False, "", msg3
        refresh = refresh2
        refresh_ttl = max(3600, int(expires_min2 or 0) * 60 or _REFRESH_FALLBACK_TTL_SEC)
        refresh_expire_at = time.time() + refresh_ttl
        msg = msg3

    access_ttl = max(60, int(expires_sec or 3600) - _ACCESS_REFRESH_SKEW_SEC)
    with _lock:
        _cache[key] = {
            "refresh_token": refresh,
            "refresh_expire_at": refresh_expire_at or (time.time() + _REFRESH_FALLBACK_TTL_SEC),
            "access_token": access,
            "access_expire_at": time.time() + access_ttl,
        }
    return True, access, msg or "OK"


def get_eqsc_access_token(
    login_key: str,
    *,
    force_refresh: bool = False,
    timeout: float = 15.0,
) -> Tuple[bool, str, str]:
    """
    获取可用 AccessToken（自动完成密钥→Refresh→Access 转换并缓存）。

    同一 login_key 并发请求会 single-flight：仅一路发起 HTTP，其余等待结果。

    Returns:
        (ok, access_token, message)
    """
    key = (login_key or "").strip()
    if not key:
        return False, "", "请先填写 EQSC 登录密钥"

    wait_timeout = max(5.0, float(timeout) + 10.0)
    while True:
        with _lock:
            cached = _cached_access_if_valid(key, force_refresh=force_refresh)
            if cached is not None:
                return cached
            flight = _flights.get(key)
            if flight is None:
                flight = _TokenFlight()
                _flights[key] = flight
                leader = True
            else:
                leader = False

        if not leader:
            if not flight.event.wait(timeout=wait_timeout):
                return False, "", "等待鉴权超时"
            if flight.result is not None:
                return flight.result
            # 领航失败且未写入结果：再试（可能已有新缓存）
            force_refresh = False
            continue

        try:
            result = _fetch_and_cache_access_token(
                key, force_refresh=force_refresh, timeout=timeout
            )
            flight.result = result
            return result
        except Exception as e:
            result = (False, "", f"鉴权异常: {e}")
            flight.result = result
            logger.warning(f"[EQSC] AccessToken single-flight 异常: {e}")
            return result
        finally:
            with _lock:
                if _flights.get(key) is flight:
                    _flights.pop(key, None)
            flight.event.set()


def warm_eqsc_access_token(login_key: str, timeout: float = 15.0) -> Tuple[bool, str]:
    """启用 EQSC 时预热 AccessToken，降低首轮多路轮询并发换票。"""
    ok, _token, msg = get_eqsc_access_token(login_key, timeout=timeout)
    return ok, msg or ("OK" if ok else "鉴权失败")


def eqsc_auth_headers(login_key: str) -> Tuple[bool, Dict[str, str], str]:
    """构造带 AccessToken 的 HTTP 请求头。"""
    ok, token, msg = get_eqsc_access_token(login_key)
    if not ok:
        return False, {}, msg
    return True, _bearer_headers(token), msg


def test_eqsc_auth(login_key: str, timeout: float = 15.0) -> Tuple[bool, str]:
    """设置页「连接」测试：验证登录密钥可换取 AccessToken。"""
    key = (login_key or "").strip()
    if not key:
        return False, "请先填写 EQSC 登录密钥"
    invalidate_eqsc_token_cache(key)
    ok, token, msg = get_eqsc_access_token(key, force_refresh=True, timeout=timeout)
    if not ok:
        return False, msg or "鉴权失败"
    if not token:
        return False, "未返回 AccessToken"
    return True, "鉴权成功，已换取 AccessToken"


# WebSocket/HTTP scope 名（与 API URL 主干一致）
EQSC_ALL_SCOPES: Tuple[str, ...] = (
    "jma_eew",
    "jma_report",
    "jma_tsunami",
    "eqlistCENC",
    "listIntensityReportCENC",
    "intensityReportCENC",
    "eqlistCWA",
    "eqlistHKO",
    "eqlistUSGS",
    "eqlistEMSC",
    "typhoonNMC",
    "volcanoJMA",
)

# scope -> MessageConfig 解析开关字段
EQSC_SCOPE_FLAG_FIELD: Dict[str, str] = {
    "jma_eew": "eqsc_parse_jma_eew",
    "jma_report": "eqsc_parse_jma_report",
    "jma_tsunami": "eqsc_parse_jma_tsunami",
    "eqlistCENC": "eqsc_parse_cenc",
    "listIntensityReportCENC": "eqsc_parse_cenc_ir",
    "intensityReportCENC": "eqsc_parse_cenc_ir",
    "eqlistCWA": "eqsc_parse_cwa",
    "eqlistHKO": "eqsc_parse_hko",
    "eqlistUSGS": "eqsc_parse_usgs",
    "eqlistEMSC": "eqsc_parse_emsc",
    "typhoonNMC": "eqsc_parse_typhoon",
    "volcanoJMA": "eqsc_parse_volcano",
}


def build_eqsc_scopes(enabled_parse_flags: Dict[str, bool]) -> str:
    """
    根据解析开关构造 WebSocket scopes 字符串。

    enabled_parse_flags 键为 eqsc_parse_* 字段名。
    全部开启时返回 ALL。
    """
    selected = []
    # 订阅用 scope：烈度详情由列表触发 HTTP 拉取，不必单独订阅
    subscribe_scopes = [s for s in EQSC_ALL_SCOPES if s != "intensityReportCENC"]
    for scope in subscribe_scopes:
        flag = EQSC_SCOPE_FLAG_FIELD.get(scope)
        if flag and bool(enabled_parse_flags.get(flag, True)):
            selected.append(scope)
    if not selected:
        return ""
    if len(selected) >= len(subscribe_scopes):
        return "ALL"
    return ",".join(selected)


def build_respond_authentication_message(
    access_token: str,
    scopes: str,
    *,
    include_training: bool = False,
) -> str:
    """构造 EQSC WebSocket respond_authentication JSON。"""
    import json

    payload = {
        "type": "respond_authentication",
        "data": {
            "accessToken": (access_token or "").strip(),
            "scopes": (scopes or "ALL").strip() or "ALL",
            "isTrainingIncluded": "true" if include_training else "false",
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
