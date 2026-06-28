#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GeoNet 新西兰地震速报适配器"""

from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils


class GeoNetAdapter(BaseAdapter):
    """解析 GeoNet quake API GeoJSON，取第一条非 deleted 事件。"""

    response_format = "json"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 GeoNet GeoJSON，取第一条非 deleted 事件。"""
        if not isinstance(raw_data, dict):
            return None
        features = raw_data.get("features")
        if not features or not isinstance(features, list):
            return None
        for feature in features:
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties") or {}
            if (props.get("quality") or "").strip().lower() == "deleted":
                continue  # 跳过已删除事件
            parsed = self._parse_feature(feature)
            if parsed:
                return parsed
        return None

    def _parse_feature(self, feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将 GeoJSON feature 解析为标准化速报字典。"""
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        place_name = (props.get("locality") or "").strip()
        if not place_name:
            return None
        time_str = (props.get("time") or "").strip()
        shock_time = timezone_utils.utc_to_display(time_str) if time_str else ""
        lon = lat = 0.0
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                lon = float(coords[0])  # GeoJSON 坐标顺序为 [lon, lat]
                lat = float(coords[1])
            except (TypeError, ValueError):
                pass
        depth = self._safe_float(props.get("depth", 0), 10.0)
        magnitude = self._safe_float(props.get("magnitude", 0), 0.0)
        public_id = (props.get("publicID") or "").strip()
        return {
            "type": "report",
            "source_type": "geonet",
            "place_name": place_name,
            "shock_time": shock_time,
            "magnitude": round(magnitude, 1),
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "organization": self.get_organization_name(),
            "event_id": public_id,
            "raw_data": feature,
        }

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """安全转换为浮点数。"""
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（GeoNet 默认为速报）。"""
        return data.get("type", "report")
