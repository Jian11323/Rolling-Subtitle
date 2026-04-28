#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义数据源适配器
支持两种约定 JSON 格式：平铺格式与 Data 嵌套格式
"""

from typing import Dict, Any, Optional, Union

from .base_adapter import BaseAdapter


class CustomAdapter(BaseAdapter):
    """自定义数据源适配器，解析约定格式的预警 JSON"""

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """
        解析原始数据。支持格式 A（平铺）或格式 B（Data 嵌套）。
        若为数组则取第一条解析。
        """
        if raw_data is None:
            return None
        data = raw_data
        if isinstance(data, list):
            if not data:
                return None
            data = data[0]
        if not isinstance(data, dict):
            return None
        # 格式 B：根节点有 Data
        if "Data" in data and isinstance(data["Data"], dict):
            return self._parse_nested(data)
        # 格式 A：平铺
        return self._parse_flat(data)

    def _parse_flat(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """格式 A：平铺字段"""
        place_name = data.get("placeName", "")
        if not place_name:
            return None
        shock_time = data.get("shockTime", "")
        magnitude = self._safe_float(data.get("magnitude", 0))
        latitude = self._safe_float(data.get("latitude", 0))
        longitude = self._safe_float(data.get("longitude", 0))
        depth = self._safe_float(data.get("depth", 0))
        report_num = data.get("reportNum")
        if report_num is not None:
            try:
                updates = int(report_num)
            except (TypeError, ValueError):
                updates = None
        else:
            updates = None
        source_name = (data.get("sourceName") or "自定义").strip() or "自定义"
        return {
            "type": "warning",
            "place_name": place_name,
            "magnitude": magnitude,
            "latitude": latitude,
            "longitude": longitude,
            "depth": depth,
            "shock_time": shock_time,
            "organization": source_name,
            "source_type": "custom",
            "updates": updates,
            "raw_data": data,
        }

    def _parse_nested(self, root: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """格式 B：Data 嵌套"""
        data = root["Data"]
        if not isinstance(data, dict):
            return None
        place_name = data.get("placeName", "")
        if not place_name:
            return None
        shock_time = data.get("shockTime", "")
        magnitude = self._safe_float(data.get("magnitude", 0))
        latitude = self._safe_float(data.get("latitude", 0))
        longitude = self._safe_float(data.get("longitude", 0))
        depth = self._safe_float(data.get("depth", 0))
        updates = data.get("updates")
        if updates is not None:
            try:
                updates = int(updates)
            except (TypeError, ValueError):
                updates = None
        return {
            "type": "warning",
            "place_name": place_name,
            "magnitude": magnitude,
            "latitude": latitude,
            "longitude": longitude,
            "depth": depth,
            "shock_time": shock_time,
            "organization": "自定义",
            "source_type": "custom",
            "updates": updates,
            "raw_data": root,
        }

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "warning")
