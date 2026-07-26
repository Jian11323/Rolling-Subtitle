#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MMD 马来西亚气象局 HTTP 地震速报适配器。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils


class MmdAdapter(BaseAdapter):
    """解析 MMD shake admis JSON，取最新一条。"""

    response_format = "json"
    fetch_timeout = 45

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw_data, dict):
            return None
        rows = raw_data.get("data")
        if not isinstance(rows, list) or not rows:
            return None
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 14:
                continue
            try:
                mag = float(row[13] or 0)
                if mag <= 0:
                    continue
                utc_s = str(row[2] or "").strip()
                if not utc_s:
                    continue
                shock_time = timezone_utils.utc_to_display(utc_s)
                if "T" not in utc_s and "+" not in utc_s and "Z" not in utc_s.upper():
                    # 无时区按 UTC 朴素串
                    shock_time = timezone_utils.local_tz_to_display(utc_s, "UTC")
                return {
                    "type": "report",
                    "source_type": "mmd",
                    "place_name": str(row[9] or "未知地区").strip() or "未知地区",
                    "shock_time": shock_time,
                    "magnitude": mag,
                    "latitude": float(row[4]),
                    "longitude": float(row[5]),
                    "depth": float(row[8] or 0),
                    "organization": self.get_organization_name(),
                    "event_id": str(row[1] or row[0] or ""),
                    "raw_data": list(row),
                    "fanstudio": False,
                    "whews": False,
                }
            except (ValueError, TypeError, IndexError):
                continue
        return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "report")
