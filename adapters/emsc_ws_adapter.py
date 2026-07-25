#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EMSC SeismicPortal standing_order WebSocket 适配器。"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils


class EmscWsAdapter(BaseAdapter):
    """解析 EMSC standing_order 推送（action + GeoJSON Feature）。"""

    def __init__(self, source_name: str, source_url: str):
        """初始化并准备事件去重状态。"""
        super().__init__(source_name, source_url)
        self._last_event_key = ""

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 EMSC WebSocket JSON 消息。"""
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError, ValueError):
                return None
        if not isinstance(raw_data, dict):
            return None

        action = str(raw_data.get("action") or "").strip().lower()
        # 仅处理新建/更新事件；忽略心跳等
        if action and action not in ("create", "created", "update", "updated"):
            return None

        data = raw_data.get("data")
        if not isinstance(data, dict):
            # 兼容直接推送 properties 的精简帧
            if "mag" in raw_data or "flynn_region" in raw_data:
                props = raw_data
                geom = {}
            else:
                return None
        else:
            props = data.get("properties") if isinstance(data.get("properties"), dict) else data
            geom = data.get("geometry") if isinstance(data.get("geometry"), dict) else {}

        if not isinstance(props, dict):
            return None

        place_name = str(
            props.get("flynn_region") or props.get("region") or props.get("place") or ""
        ).strip()
        mag = self._safe_float(props.get("mag"), 0.0)
        lat = self._safe_float(props.get("lat"), 0.0)
        lon = self._safe_float(props.get("lon"), 0.0)
        depth = self._safe_float(props.get("depth"), 10.0)
        if depth <= 0:
            depth = 10.0

        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            try:
                if not lon:
                    lon = float(coords[0])
                if not lat:
                    lat = float(coords[1])
                if len(coords) >= 3 and coords[2] is not None and depth == 10.0:
                    # EMSC 坐标第三维常为负深度
                    d = abs(float(coords[2]))
                    if d > 0:
                        depth = d
            except (TypeError, ValueError):
                pass

        shock_raw = str(props.get("time") or "").strip()
        shock_time = timezone_utils.utc_to_display(shock_raw) if shock_raw else ""
        if not place_name and not shock_time:
            return None

        event_id = str(
            props.get("unid")
            or props.get("source_id")
            or (data.get("id") if isinstance(data, dict) else "")
            or ""
        ).strip()
        if not event_id:
            event_id = f"emsc_{shock_time}_{lat}_{lon}"

        # 同事件更新：用 unid+mag+time 去重，避免无变化刷屏；幅度/时间变化仍放行
        dedup_key = f"{event_id}|{mag}|{shock_raw}"
        if self._last_event_key == dedup_key:
            return None
        self._last_event_key = dedup_key

        return {
            "type": "report",
            "source_type": "emsc",
            "place_name": place_name or "未知地区",
            "shock_time": shock_time,
            "magnitude": mag,
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "organization": self.get_organization_name(),
            "event_id": event_id,
            "raw_data": raw_data,
        }

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """安全转换为浮点数。"""
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（EMSC 为速报）。"""
        return data.get("type", "report")
