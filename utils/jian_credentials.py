#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jian Project（auth.sismotide.top）鉴权凭证辅助。

流程：邮件登录密钥 lk_（约 5 分钟、用后作废）
  → 长期 Token rt_（约 180 天，应本地持久化）
  → 访问令牌 at_（约 1 小时，握手用）。

文档：https://api.sismotide.top/api/#auth
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple

import requests

from utils.logger import get_logger

logger = get_logger()

JIAN_AUTH_BASE = "https://auth.sismotide.top"
JIAN_REFRESH_URL = f"{JIAN_AUTH_BASE}/api/refresh"
JIAN_ACCESS_URL = f"{JIAN_AUTH_BASE}/api/access"
JIAN_AUTH_PAGE = "https://auth.sismotide.top/"

# 访问令牌约 3600s；提前刷新避免边界失效
_ACCESS_REFRESH_SKEW_SEC = 120
# 长期 Token 约 259200 分钟（180 天）→ 秒
_REFRESH_FALLBACK_TTL_SEC = 259200 * 60

_lock = threading.RLock()
# cache_key -> 缓存（优先用 rt_ 前缀作键，避免依赖已作废的 lk_）
_cache: Dict[str, Dict[str, Any]] = {}


class _TokenFlight:
    """单次换票飞行：多路建连共用同一 HTTP 结果，避免 stampede。"""

    __slots__ = ("event", "result")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Optional[Tuple[bool, str, str]] = None


_flights: Dict[str, _TokenFlight] = {}


def classify_jian_credential(value: str) -> str:
    """识别凭证前缀：login / refresh / access / unknown。"""
    v = (value or "").strip()
    if v.startswith("lk_"):
        return "login"
    if v.startswith("rt_"):
        return "refresh"
    if v.startswith("at_"):
        return "access"
    return "unknown"


def format_jian_refresh_expire(expire_at: float) -> str:
    """把 refresh 过期时间格式化为本地日期文案。"""
    try:
        ts = float(expire_at or 0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return ""


def _bearer_headers(token: str) -> Dict[str, str]:
    """构造 Bearer 鉴权头。"""
    return {
        "Authorization": f"Bearer {(token or '').strip()}",
        "Accept": "application/json",
        "User-Agent": "RollingSubtitle-Jian/1.0",
    }


def _parse_token_response(body: Any) -> Tuple[bool, str, str, int, str]:
    """
    解析 /api/refresh、/api/access 响应。

    Returns:
        (ok, token, message, expires_hint, expire_unit)
        expire_unit: ``sec`` | ``min`` | ``""``
    """
    if not isinstance(body, dict):
        return False, "", "响应格式无效", 0, ""
    if body.get("ok") is False:
        err = str(body.get("error") or body.get("message") or "鉴权失败").strip()
        code = body.get("code")
        if code is not None:
            err = f"{err} (code={code})"
        return False, "", err, 0, ""
    token = str(body.get("token") or "").strip()
    if not token:
        err = str(body.get("error") or body.get("message") or "未返回令牌").strip()
        return False, "", err, 0, ""
    expires = 0
    unit = ""
    if "expires_after_sec" in body:
        try:
            expires = int(body.get("expires_after_sec") or 0)
        except (TypeError, ValueError):
            expires = 0
        unit = "sec"
    elif "expires_after_min" in body:
        try:
            expires = int(body.get("expires_after_min") or 0)
        except (TypeError, ValueError):
            expires = 0
        unit = "min"
    return True, token, "OK", expires, unit


def create_refresh_token(login_key: str, timeout: float = 15.0) -> Tuple[bool, str, str, int]:
    """
    使用登录密钥换取长期 Token（rt_…）。

    Returns:
        (ok, refresh_token, message, expires_after_min)
    """
    key = (login_key or "").strip()
    if not key:
        return False, "", "请先填写 Jian 登录密钥（邮件内 lk_…）", 0
    if classify_jian_credential(key) != "login":
        return False, "", "请填写邮件内 lk_ 开头的登录密钥（约 5 分钟有效、用后作废）", 0
    try:
        resp = requests.post(
            JIAN_REFRESH_URL,
            headers=_bearer_headers(key),
            timeout=timeout,
        )
        body = resp.json() if resp.content else {}
        ok, token, msg, expires, unit = _parse_token_response(body)
        if not ok:
            return False, "", msg or f"HTTP {resp.status_code}", 0
        if unit == "sec":
            expires = max(1, expires // 60)
        return True, token, msg, expires
    except Exception as e:
        logger.warning(f"[Jian] 获取长期 Token 失败: {e}")
        return False, "", f"获取长期 Token 失败: {e}", 0


def create_access_token(refresh_token: str, timeout: float = 15.0) -> Tuple[bool, str, str, int]:
    """
    使用长期 Token 换取访问令牌（at_…）。

    Returns:
        (ok, access_token, message, expires_after_sec)
    """
    token = (refresh_token or "").strip()
    if not token:
        return False, "", "长期 Token 为空", 0
    try:
        resp = requests.post(
            JIAN_ACCESS_URL,
            headers=_bearer_headers(token),
            timeout=timeout,
        )
        body = resp.json() if resp.content else {}
        ok, access, msg, expires, unit = _parse_token_response(body)
        if not ok:
            return False, "", msg or f"HTTP {resp.status_code}", 0
        if unit == "min":
            expires = max(60, expires * 60)
        return True, access, msg, expires
    except Exception as e:
        logger.warning(f"[Jian] 获取访问令牌失败: {e}")
        return False, "", f"获取访问令牌失败: {e}", 0


def invalidate_jian_token_cache(cache_key: Optional[str] = None) -> None:
    """清除指定键（或全部）的本地 Token 内存缓存。"""
    with _lock:
        if cache_key is None:
            _cache.clear()
            return
        _cache.pop((cache_key or "").strip(), None)


def peek_jian_refresh_bundle(cache_key: str = "") -> Tuple[str, float]:
    """
    读取内存缓存中的长期 Token。

    Returns:
        (refresh_token, refresh_expire_at)
    """
    with _lock:
        if cache_key:
            entry = _cache.get((cache_key or "").strip())
            if entry and entry.get("refresh_token"):
                return (
                    str(entry.get("refresh_token") or ""),
                    float(entry.get("refresh_expire_at") or 0),
                )
        # 回退：任意一条仍有效的 rt_
        now = time.time()
        for entry in _cache.values():
            rt = str(entry.get("refresh_token") or "").strip()
            exp = float(entry.get("refresh_expire_at") or 0)
            if rt.startswith("rt_") and (not exp or exp > now + 60):
                return rt, exp
        return "", 0.0


def seed_jian_refresh_cache(
    refresh_token: str,
    refresh_expire_at: float = 0.0,
    *,
    cache_key: str = "",
) -> str:
    """
    用已持久化的 rt_ 预热内存缓存。

    Returns:
        实际使用的 cache_key
    """
    rt = (refresh_token or "").strip()
    if not rt:
        return ""
    key = (cache_key or rt).strip()
    exp = float(refresh_expire_at or 0)
    if exp <= 0:
        exp = time.time() + _REFRESH_FALLBACK_TTL_SEC
    with _lock:
        prev = _cache.get(key) or {}
        _cache[key] = {
            "refresh_token": rt,
            "refresh_expire_at": exp,
            "access_token": str(prev.get("access_token") or ""),
            "access_expire_at": float(prev.get("access_expire_at") or 0),
        }
    return key


def _cached_access_if_valid(key: str, *, force_refresh: bool) -> Optional[Tuple[bool, str, str]]:
    """锁内：若缓存访问令牌仍可用则返回结果，否则 None。"""
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


def _store_bundle(
    key: str,
    *,
    refresh: str,
    refresh_expire_at: float,
    access: str,
    access_ttl: float,
) -> None:
    """写入内存缓存。"""
    with _lock:
        _cache[key] = {
            "refresh_token": refresh,
            "refresh_expire_at": refresh_expire_at,
            "access_token": access,
            "access_expire_at": time.time() + max(60.0, access_ttl),
        }


def _fetch_and_cache_access_token(
    cache_key: str,
    *,
    login_key: str,
    seed_refresh: str,
    seed_expire_at: float,
    force_new_refresh: bool,
    timeout: float,
) -> Tuple[bool, str, str]:
    """
    执行换票并缓存。

    - 有有效 seed_refresh（rt_）且未强制换新：直接 rt→at
    - 否则若有 lk_：lk→rt→at
    """
    now = time.time()
    refresh = (seed_refresh or "").strip()
    refresh_expire_at = float(seed_expire_at or 0)

    with _lock:
        entry = _cache.get(cache_key)
        if entry and entry.get("refresh_token"):
            cached_rt = str(entry.get("refresh_token") or "").strip()
            cached_exp = float(entry.get("refresh_expire_at") or 0)
            if cached_rt and (not refresh or cached_rt == refresh):
                refresh = cached_rt
                if cached_exp:
                    refresh_expire_at = cached_exp

    refresh_still_valid = bool(
        refresh
        and classify_jian_credential(refresh) == "refresh"
        and (not refresh_expire_at or refresh_expire_at > now + 60)
    )
    need_new_refresh = force_new_refresh or not refresh_still_valid

    if need_new_refresh:
        lk = (login_key or "").strip()
        if classify_jian_credential(lk) != "login":
            if refresh_still_valid and not force_new_refresh:
                need_new_refresh = False
            else:
                return (
                    False,
                    "",
                    "请粘贴邮件内新的 lk_ 登录密钥（约 5 分钟有效）；"
                    "换票成功后会本地保存 180 天长期 Token",
                )

    if need_new_refresh:
        ok, refresh, msg, expires_min = create_refresh_token(login_key, timeout=timeout)
        if not ok:
            hint = msg or "换取长期 Token 失败"
            if "4101" in hint or "invalid_login_key" in hint:
                hint += "。lk_ 约 5 分钟有效且用后作废，请到 auth.sismotide.top 重新申请邮件密钥"
            return False, "", hint
        refresh_ttl = max(3600, int(expires_min or 0) * 60 or _REFRESH_FALLBACK_TTL_SEC)
        refresh_expire_at = now + refresh_ttl
        with _lock:
            _cache[cache_key] = {
                "refresh_token": refresh,
                "refresh_expire_at": refresh_expire_at,
                "access_token": "",
                "access_expire_at": 0.0,
            }

    ok, access, msg, expires_sec = create_access_token(refresh, timeout=timeout)
    if not ok:
        # 长期 Token 可能已失效：若仍有 lk_ 再换一次；否则提示重新申请
        lk = (login_key or "").strip()
        if classify_jian_credential(lk) == "login":
            ok2, refresh2, msg2, expires_min2 = create_refresh_token(lk, timeout=timeout)
            if not ok2:
                return False, "", msg or msg2
            ok3, access, msg3, expires_sec = create_access_token(refresh2, timeout=timeout)
            if not ok3:
                return False, "", msg3
            refresh = refresh2
            refresh_ttl = max(3600, int(expires_min2 or 0) * 60 or _REFRESH_FALLBACK_TTL_SEC)
            refresh_expire_at = time.time() + refresh_ttl
            msg = msg3
        else:
            hint = msg or "长期 Token 换取访问令牌失败"
            if "4201" in hint or "4202" in hint or "invalid" in hint.lower():
                hint += "。请重新申请邮件 lk_ 并点「连接」换取新的长期 Token"
            return False, "", hint

    access_ttl = max(60, int(expires_sec or 3600) - _ACCESS_REFRESH_SKEW_SEC)
    _store_bundle(
        cache_key,
        refresh=refresh,
        refresh_expire_at=refresh_expire_at or (time.time() + _REFRESH_FALLBACK_TTL_SEC),
        access=access,
        access_ttl=float(access_ttl),
    )
    # 同时用 rt_ 自身作键，便于仅凭持久化 rt_ 命中缓存
    if refresh.startswith("rt_") and cache_key != refresh:
        _store_bundle(
            refresh,
            refresh=refresh,
            refresh_expire_at=refresh_expire_at or (time.time() + _REFRESH_FALLBACK_TTL_SEC),
            access=access,
            access_ttl=float(access_ttl),
        )
    return True, access, msg or "OK"


def get_jian_access_token(
    login_key: str = "",
    *,
    persisted_refresh: str = "",
    persisted_refresh_expire_at: float = 0.0,
    force_refresh: bool = False,
    timeout: float = 15.0,
) -> Tuple[bool, str, str]:
    """
    获取可用访问令牌。

    优先使用已持久化的 rt_；仅在强制换新或 rt_ 缺失/过期时用 lk_。

    Returns:
        (ok, access_token, message)
    """
    lk = (login_key or "").strip()
    rt = (persisted_refresh or "").strip()
    # 输入框误贴了 rt_：当作持久化长期 Token
    if not rt and classify_jian_credential(lk) == "refresh":
        rt = lk
        lk = ""
    if classify_jian_credential(lk) == "access":
        return False, "", "请勿填写 at_ 访问令牌；请填邮件 lk_，由软件换取并保存 rt_"

    if rt:
        cache_key = seed_jian_refresh_cache(
            rt, persisted_refresh_expire_at, cache_key=rt
        )
    elif lk:
        cache_key = lk
    else:
        return False, "", "请先填写邮件内 lk_ 登录密钥，或确认已保存长期 Token"

    force_new = bool(force_refresh and classify_jian_credential(lk) == "login")

    wait_timeout = max(5.0, float(timeout) + 10.0)
    while True:
        with _lock:
            cached = _cached_access_if_valid(cache_key, force_refresh=force_new)
            if cached is not None:
                return cached
            flight = _flights.get(cache_key)
            if flight is None:
                flight = _TokenFlight()
                _flights[cache_key] = flight
                leader = True
            else:
                leader = False

        if not leader:
            if not flight.event.wait(timeout=wait_timeout):
                return False, "", "等待鉴权超时"
            if flight.result is not None:
                return flight.result
            force_new = False
            continue

        try:
            result = _fetch_and_cache_access_token(
                cache_key,
                login_key=lk,
                seed_refresh=rt,
                seed_expire_at=float(persisted_refresh_expire_at or 0),
                force_new_refresh=force_new,
                timeout=timeout,
            )
            flight.result = result
            return result
        except Exception as e:
            result = (False, "", f"鉴权异常: {e}")
            flight.result = result
            logger.warning(f"[Jian] AccessToken single-flight 异常: {e}")
            return result
        finally:
            with _lock:
                if _flights.get(cache_key) is flight:
                    _flights.pop(cache_key, None)
            flight.event.set()


def warm_jian_access_token(
    login_key: str = "",
    *,
    persisted_refresh: str = "",
    persisted_refresh_expire_at: float = 0.0,
    timeout: float = 15.0,
) -> Tuple[bool, str]:
    """启用 Jian 时预热访问令牌。"""
    ok, _token, msg = get_jian_access_token(
        login_key,
        persisted_refresh=persisted_refresh,
        persisted_refresh_expire_at=persisted_refresh_expire_at,
        timeout=timeout,
    )
    return ok, msg or ("OK" if ok else "鉴权失败")


def test_jian_auth(
    login_key: str = "",
    *,
    persisted_refresh: str = "",
    persisted_refresh_expire_at: float = 0.0,
    timeout: float = 15.0,
) -> Tuple[bool, str, str, float]:
    """
    设置页「连接」：用 lk_ 换 rt_（并验证可换 at_），或用已保存 rt_ 验证。

    Returns:
        (ok, message, refresh_token, refresh_expire_at)
    """
    lk = (login_key or "").strip()
    rt = (persisted_refresh or "").strip()
    kind = classify_jian_credential(lk)

    if kind == "login":
        # 新邮件密钥：强制 lk→rt，覆盖旧长期 Token
        invalidate_jian_token_cache(lk)
        if rt:
            invalidate_jian_token_cache(rt)
        ok, _access, msg = get_jian_access_token(
            lk,
            force_refresh=True,
            timeout=timeout,
        )
        if not ok:
            return False, msg or "鉴权失败", "", 0.0
        refresh, exp = peek_jian_refresh_bundle(lk)
        if not refresh:
            refresh, exp = peek_jian_refresh_bundle()
        if not refresh:
            return False, "未返回长期 Token", "", 0.0
        date_s = format_jian_refresh_expire(exp)
        suffix = f"，约有效至 {date_s}" if date_s else "（约 180 天）"
        return True, f"鉴权成功，已换取并保存长期 Token{suffix}", refresh, exp

    if kind == "refresh":
        rt = lk
        lk = ""

    if not rt and not lk:
        return False, "请先粘贴邮件内 lk_ 登录密钥", "", 0.0

    if rt:
        invalidate_jian_token_cache(rt)
        seed_jian_refresh_cache(rt, persisted_refresh_expire_at, cache_key=rt)

    ok, _access, msg = get_jian_access_token(
        lk,
        persisted_refresh=rt,
        persisted_refresh_expire_at=persisted_refresh_expire_at,
        force_refresh=False,
        timeout=timeout,
    )
    if not ok:
        return False, msg or "鉴权失败", "", 0.0
    refresh, exp = peek_jian_refresh_bundle(rt or lk)
    if not refresh:
        refresh, exp = rt, float(persisted_refresh_expire_at or 0)
    date_s = format_jian_refresh_expire(exp)
    suffix = f"，约有效至 {date_s}" if date_s else ""
    return True, f"长期 Token 有效，已换取访问令牌{suffix}", refresh, exp


def append_jian_ws_key(url: str, access_token: str) -> str:
    """将 at_… 以 ?key= 追加到 WebSocket URL（已有 query 则用 &）。"""
    base = (url or "").strip()
    token = (access_token or "").strip()
    if not base or not token:
        return base
    from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

    parts = urlsplit(base)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q["key"] = token
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))
