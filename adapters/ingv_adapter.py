#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""INGV Terraquake API 意大利地震速报适配器"""

from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils


class INGVAdapter(BaseAdapter):
    """解析 api.terraquakeapi.com recent 响应，取 payload 第一条。"""

    response_format = "json"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw_data, dict):
            return None
        payload = raw_data.get("payload")
        if not payload or not isinstance(payload, list):
            return None
        for item in payload:
            if not isinstance(item, dict):
                continue
            parsed = self._parse_feature(item)
            if parsed:
                return parsed
        return None

    def _parse_feature(self, feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        place_name = (props.get("place") or "").strip()
        if not place_name:
            return None
        time_str = (props.get("time") or "").strip()
        shock_time = timezone_utils.utc_to_display(time_str) if time_str else ""
        lon = lat = 0.0
        depth = 10.0
        if isinstance(coords, (list, tuple)):
            if len(coords) >= 2:
                try:
                    lon = float(coords[0])
                    lat = float(coords[1])
                except (TypeError, ValueError):
                    pass
            if len(coords) >= 3:
                try:
                    depth = float(coords[2])
                except (TypeError, ValueError):
                    pass
        magnitude = self._safe_float(props.get("mag", 0), 0.0)
        event_id = str(props.get("eventId") or props.get("originId") or "")
        return {
            "type": "report",
            "source_type": "ingv",
            "place_name": place_name,
            "shock_time": shock_time,
            "magnitude": round(magnitude, 1),
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "organization": self.get_organization_name(),
            "event_id": event_id,
            "raw_data": feature,
        }

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "report")
