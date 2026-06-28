#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BMKG 印尼地震速报适配器"""

import re
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils


class BMKGAdapter(BaseAdapter):
    """解析 BMKG gempaterkini.json，取最新一条 gempa。"""

    response_format = "json"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 BMKG JSON，取 gempa 列表首条有效事件。"""
        if not isinstance(raw_data, dict):
            return None
        infogempa = raw_data.get("Infogempa") or {}
        gempa_list = infogempa.get("gempa")
        if not gempa_list or not isinstance(gempa_list, list):
            return None
        first = gempa_list[0]
        if not isinstance(first, dict):
            return None
        return self._parse_item(first)

    def _parse_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将单条 gempa 记录解析为标准化速报字典。"""
        place_name = (item.get("Wilayah") or "").strip()  # 印尼语区域名
        if not place_name:
            return None
        shock_time = ""
        dt_str = (item.get("DateTime") or "").strip()
        if dt_str:
            shock_time = timezone_utils.utc_to_display(dt_str)  # UTC 转显示时区
        lat, lon = self._parse_coordinates(item)
        magnitude = self._safe_float(item.get("Magnitude", 0))
        depth = self._parse_depth(item.get("Kedalaman", ""))
        return {
            "type": "report",
            "source_type": "bmkg",
            "place_name": place_name,
            "shock_time": shock_time,
            "magnitude": magnitude,
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "organization": self.get_organization_name(),
            "event_id": f"{dt_str}_{lat}_{lon}",
            "raw_data": item,
        }

    def _parse_coordinates(self, item: Dict[str, Any]) -> tuple:
        """从 Coordinates 字段解析纬度、经度。"""
        coords = (item.get("Coordinates") or "").strip()
        if coords and "," in coords:
            parts = coords.split(",", 1)
            try:
                return float(parts[0].strip()), float(parts[1].strip())
            except (TypeError, ValueError):
                pass
        return 0.0, 0.0

    def _parse_depth(self, kedalaman: Any) -> float:
        """解析深度字符串（如 "10 km"），失败时默认 10 km。"""
        if kedalaman is None:
            return 10.0
        s = str(kedalaman).strip().lower().replace("km", "").strip()
        try:
            return float(s)
        except (TypeError, ValueError):
            return 10.0

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """安全转换为浮点数，支持带前缀数字的字符串。"""
        try:
            if value is None:
                return default
            s = str(value).strip()
            m = re.match(r"^([\d.]+)", s)
            return float(m.group(1)) if m else float(value)
        except (TypeError, ValueError):
            return default

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（BMKG 默认为速报）。"""
        return data.get("type", "report")
