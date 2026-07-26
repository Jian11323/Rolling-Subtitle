#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TMD 泰国地震局 HTTP 地震速报适配器（含 IPv4 备用拉取）。"""

from __future__ import annotations

import socket
from typing import Any, Dict, Optional

import requests

from .base_adapter import BaseAdapter
from utils import timezone_utils
from utils.logger import get_logger

logger = get_logger()

TMD_IPV4_URL = "https://61.19.55.91/map-events.json"
TMD_HTTP_FALLBACK = "http://eq.tmd.go.th/map-events.json"


class TmdAdapter(BaseAdapter):
    """解析 TMD map-events.json，取最新一条。"""

    response_format = "json"
    ssl_verify = False
    fetch_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; EarthquakeScroller/1.0)",
        "Accept": "application/json,text/plain,*/*",
        "Host": "eq.tmd.go.th",
    }
    fetch_timeout = 20

    def fetch_raw(self, session: requests.Session, url: str) -> Any:
        """优先 IPv4 直连，避免部分环境 IPv6 被劫持返回 HTML。"""
        headers = dict(self.fetch_headers)
        attempts = [
            (TMD_IPV4_URL, False),
            (url, False),
            (TMD_HTTP_FALLBACK, True),
        ]
        last_err: Any = None
        try:
            import urllib3.util.connection as urllib3_cn

            orig_gai = urllib3_cn.allowed_gai_family

            def _ipv4_only():
                return socket.AF_INET

            for attempt_url, allow_redirects in attempts:
                try:
                    urllib3_cn.allowed_gai_family = _ipv4_only
                    r = session.get(
                        attempt_url,
                        timeout=self.fetch_timeout,
                        verify=False,
                        headers=headers,
                        allow_redirects=allow_redirects,
                        proxies={"http": None, "https": None},
                    )
                    body = (r.text or "").strip()
                    if r.status_code != 200:
                        last_err = f"HTTP {r.status_code} url={r.url}"
                        continue
                    if not body.startswith("{") and not body.startswith("["):
                        ctype = r.headers.get("content-type", "")
                        last_err = f"非 JSON ctype={ctype} url={r.url}"
                        continue
                    return r.json()
                except Exception as e:
                    last_err = e
                finally:
                    urllib3_cn.allowed_gai_family = orig_gai
        except Exception as e:
            last_err = e
        raise RuntimeError(f"TMD 拉取失败: {last_err}")

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        raw = raw_data.get("events") if isinstance(raw_data, dict) else raw_data
        if not isinstance(raw, list) or not raw:
            return None
        best = None
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                mag = float(item.get("mag") or 0)
            except (TypeError, ValueError):
                continue
            if mag <= 0:
                continue
            if best is None:
                best = item
                break
        if not best:
            return None
        otime = str(best.get("otime") or "").strip()
        shock_time = timezone_utils.local_tz_to_display(otime, "Asia/Bangkok") if otime else ""
        try:
            lat = float(best.get("lat") or 0)
            lon = float(best.get("lon") or 0)
            depth = float(best.get("depth") or 0)
            mag = float(best.get("mag") or 0)
        except (TypeError, ValueError):
            return None
        place = str(best.get("region") or "未知地区").strip() or "未知地区"
        event_id = str(best.get("eventID") or "").strip() or f"tmd_{shock_time}"
        return {
            "type": "report",
            "source_type": "tmd",
            "place_name": place,
            "shock_time": shock_time,
            "magnitude": mag,
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "organization": self.get_organization_name(),
            "event_id": event_id,
            "raw_data": best,
            "fanstudio": False,
            "whews": False,
        }

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "report")
