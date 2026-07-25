#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""USGS FDSN GeoJSON 地震速报适配器。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils


class UsgsAdapter(BaseAdapter):
    """解析 USGS GeoJSON，取 features 中最新一条地震。"""

    response_format = "json"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 USGS FeatureCollection，返回最新事件速报。"""
        if not isinstance(raw_data, dict):
            return None
        features = raw_data.get("features")
        if not isinstance(features, list) or not features:
            return None
        best = None
        best_t = -1
        for feature in features:
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties") or {}
            if str(props.get("type") or "").lower() not in ("", "earthquake"):
                # 仅地震事件；缺省 type 也视为地震
                if props.get("type") and str(props.get("type")).lower() != "earthquake":
                    continue
            t = props.get("time")
            try:
                t_i = int(t) if t is not None else -1
            except (TypeError, ValueError):
                t_i = -1
            if best is None or t_i > best_t:
                best = feature
                best_t = t_i
        if best is None:
            best = features[0] if isinstance(features[0], dict) else None
        if not best:
            return None
        return self._parse_feature(best)

    def _parse_feature(self, feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将单条 GeoJSON Feature 转为标准速报。"""
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        place_name = str(props.get("place") or props.get("title") or "").strip()
        if not place_name:
            return None
        lon = lat = 0.0
        depth = 10.0
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                lon = float(coords[0])
                lat = float(coords[1])
                if len(coords) >= 3 and coords[2] is not None:
                    depth = float(coords[2])
            except (TypeError, ValueError):
                pass
        if depth <= 0:
            depth = 10.0
        mag = 0.0
        try:
            mag = float(props.get("mag") or 0)
        except (TypeError, ValueError):
            mag = 0.0
        shock_time = ""
        t_ms = props.get("time")
        if t_ms is not None:
            try:
                dt = datetime.fromtimestamp(int(t_ms) / 1000.0, tz=timezone.utc)
                shock_time = timezone_utils.utc_to_display(dt.strftime("%Y-%m-%d %H:%M:%S"))
            except (TypeError, ValueError, OSError, OverflowError):
                shock_time = ""
        event_id = str(feature.get("id") or props.get("code") or "").strip()
        result: Dict[str, Any] = {
            "type": "report",
            "source_type": "usgs",
            "place_name": place_name,
            "shock_time": shock_time,
            "magnitude": mag,
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "organization": self.get_organization_name(),
            "event_id": event_id or f"usgs_{shock_time}",
            "raw_data": feature,
        }
        url = str(props.get("url") or "").strip()
        if url:
            result["url"] = url
        return result

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（USGS 为速报）。"""
        return data.get("type", "report")
