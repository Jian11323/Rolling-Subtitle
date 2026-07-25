#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CWA（ExpTech）地震速报适配器。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils


class CwaReportAdapter(BaseAdapter):
    """解析 ExpTech /api/v2/eq/report 列表，取最新一条速报。"""

    response_format = "json"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 ExpTech CWA 速报数组。"""
        items = raw_data if isinstance(raw_data, list) else None
        if items is None and isinstance(raw_data, dict):
            for key in ("data", "report", "reports", "eq"):
                nested = raw_data.get(key)
                if isinstance(nested, list):
                    items = nested
                    break
        if not items:
            return None
        best = None
        best_t = -1
        for row in items:
            if not isinstance(row, dict):
                continue
            t = row.get("time")
            try:
                t_i = int(t) if t is not None else -1
            except (TypeError, ValueError):
                t_i = -1
            if best is None or t_i > best_t:
                best = row
                best_t = t_i
        if best is None:
            return None
        return self._parse_item(best)

    def _extract_location(self, data: Dict[str, Any]) -> str:
        """从 ExpTech loc 字段提取可读地名（括号内容优先）。"""
        location_raw = data.get("loc") or data.get("placeName") or data.get("location") or ""
        if not location_raw or not isinstance(location_raw, str):
            return "未知地区"
        bracket_match = re.search(r"[（(]([^）)]+)[）)]", location_raw)
        if bracket_match:
            location = bracket_match.group(1).replace("位於", "").replace("位于", "")
            location = re.sub(r"\s+", " ", location).strip()
            if location:
                return location
        return location_raw.strip() or "未知地区"

    def _parse_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将单条 ExpTech 速报转为标准字典。"""
        place_name = self._extract_location(item)
        mag = self._safe_float(item.get("mag", item.get("magnitude")), 0.0)
        lat = self._safe_float(item.get("lat", item.get("latitude")), 0.0)
        lon = self._safe_float(item.get("lon", item.get("longitude")), 0.0)
        depth = self._safe_float(item.get("depth"), 10.0)
        if depth <= 0:
            depth = 10.0
        shock_time = ""
        t_ms = item.get("time")
        if t_ms is not None:
            try:
                dt = datetime.fromtimestamp(int(t_ms) / 1000.0, tz=timezone.utc)
                shock_time = timezone_utils.utc_to_display(dt.strftime("%Y-%m-%d %H:%M:%S"))
            except (TypeError, ValueError, OSError, OverflowError):
                shock_time = ""
        event_id = str(item.get("id") or item.get("md5") or "").strip()
        if not event_id:
            event_id = f"cwa_{shock_time}_{lat}_{lon}"
        result: Dict[str, Any] = {
            "type": "report",
            "source_type": "cwa",
            "place_name": place_name,
            "shock_time": shock_time,
            "magnitude": mag,
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "organization": self.get_organization_name(),
            "event_id": event_id,
            "raw_data": item,
        }
        intensity = item.get("int")
        if intensity is not None and str(intensity).strip() != "":
            result["intensity"] = intensity
            result["epiIntensity"] = intensity
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
        """获取消息类型（CWA 速报）。"""
        return data.get("type", "report")
