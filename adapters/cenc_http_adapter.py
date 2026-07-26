#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CENC 个推 igexin HTTP 地震速报适配器（POST getDataAction）。"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from .base_adapter import BaseAdapter
from utils import timezone_utils
from utils.logger import get_logger

logger = get_logger()

# 拉取近 N 天事件（对齐 fused_list EVENT_RETENTION 用途，取较近窗口）
CENC_HTTP_LOOKBACK_DAYS = 7


class CencHttpAdapter(BaseAdapter):
    """解析个推 CENC JSON，取最新一条正式/自动测定。"""

    response_format = "json"
    fetch_timeout = 25

    def fetch_raw(self, session: requests.Session, url: str) -> Any:
        """POST getDataAction 拉取 CEIC 目录。"""
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - CENC_HTTP_LOOKBACK_DAYS * 24 * 3600 * 1000
        payload = {
            "action": "getDataAction",
            "startTime": str(start_ms),
            "endTime": str(end_ms),
            "dataSource": "CEIC",
        }
        r = session.post(
            url,
            json=payload,
            timeout=self.fetch_timeout,
            proxies={"http": None, "https": None},
            verify=True,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _normalize_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            t_ms = item.get("time")
            if t_ms is None:
                return None
            mag = float(item.get("mag") or 0)
            if mag <= 0:
                return None
            depth_raw = float(item.get("depth") or 0)
            depth_km = depth_raw / 1000.0 if depth_raw >= 1000 else depth_raw
            eqid = str(item.get("eqid") or "")
            eq_type = str(item.get("eq_type") or "").strip()
            is_auto = eq_type == "A"
            shock = timezone_utils.timestamp_to_display(int(t_ms))
            return {
                "shock_time": shock,
                "place_name": item.get("loc_name") or item.get("loc_province") or "未知地区",
                "magnitude": mag,
                "depth": depth_km,
                "latitude": float(item.get("latitude") or 0),
                "longitude": float(item.get("longitude") or 0),
                "event_id": eqid,
                "info_type": "[自动测定]" if is_auto else "[正式测定]",
                "raw": item,
            }
        except (ValueError, TypeError):
            return None

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw_data, dict):
            return None
        if raw_data.get("result") != "OK":
            logger.debug(f"[CENC HTTP] 响应 result={raw_data.get('result')}")
            return None
        values = raw_data.get("values") or []
        if not isinstance(values, list) or not values:
            return None
        # values 通常新→旧；取第一条有效
        for item in values:
            if not isinstance(item, dict):
                continue
            norm = self._normalize_item(item)
            if not norm:
                continue
            result = {
                "type": "report",
                "source_type": "cenc",
                "place_name": norm["place_name"],
                "shock_time": norm["shock_time"],
                "magnitude": norm["magnitude"],
                "latitude": norm["latitude"],
                "longitude": norm["longitude"],
                "depth": norm["depth"],
                "organization": self.get_organization_name(),
                "event_id": norm["event_id"] or f"cenc_{norm['shock_time']}",
                "info_type": norm["info_type"],
                "raw_data": norm["raw"],
                "fanstudio": False,
                "whews": False,
            }
            return result
        return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "report")
