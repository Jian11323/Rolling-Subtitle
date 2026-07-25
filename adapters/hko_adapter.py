#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""香港天文台（HKO）地震速报适配器。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils


class HkoAdapter(BaseAdapter):
    """解析 HKO qem JSON 地震信息。"""

    response_format = "json"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 HKO 地震 JSON（对象或列表取最新）。"""
        item = None
        if isinstance(raw_data, list):
            for row in raw_data:
                if isinstance(row, dict):
                    item = row
                    break
        elif isinstance(raw_data, dict):
            # 部分接口包在 data / earthquakes 下
            if any(k in raw_data for k in ("mag", "magnitude", "lat", "latitude", "ptime", "time")):
                item = raw_data
            else:
                for key in ("data", "earthquakes", "eq", "qem"):
                    nested = raw_data.get(key)
                    if isinstance(nested, list) and nested and isinstance(nested[0], dict):
                        item = nested[0]
                        break
                    if isinstance(nested, dict):
                        item = nested
                        break
        if not isinstance(item, dict):
            return None
        return self._parse_item(item)

    def _parse_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将单条 HKO 记录转为标准速报。"""
        place_name = str(
            item.get("region")
            or item.get("place")
            or item.get("placeName")
            or item.get("location")
            or ""
        ).strip()
        mag = self._safe_float(item.get("mag", item.get("magnitude")), 0.0)
        lat = self._safe_float(item.get("lat", item.get("latitude")), 0.0)
        lon = self._safe_float(item.get("lon", item.get("longitude")), 0.0)
        depth = self._safe_float(item.get("depth"), 10.0)
        if depth <= 0:
            depth = 10.0
        shock_raw = str(
            item.get("ptime")
            or item.get("otime")
            or item.get("time")
            or item.get("eventTime")
            or ""
        ).strip()
        shock_time = ""
        if shock_raw:
            # HKO 常见为香港时间（UTC+8）
            shock_time = timezone_utils.cst_to_display(shock_raw)
        if not place_name and not shock_time:
            return None
        event_id = str(item.get("eventId") or item.get("id") or "").strip()
        if not event_id:
            event_id = f"hko_{shock_time}_{lat}_{lon}"
        result: Dict[str, Any] = {
            "type": "report",
            "source_type": "hko",
            "place_name": place_name or "未知地区",
            "shock_time": shock_time,
            "magnitude": mag,
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "organization": self.get_organization_name(),
            "event_id": event_id,
            "raw_data": item,
        }
        region = str(item.get("region") or "").strip()
        if region:
            result["region"] = region
        return result

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """安全转换为浮点数。"""
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（HKO 为速报）。"""
        return data.get("type", "report")
