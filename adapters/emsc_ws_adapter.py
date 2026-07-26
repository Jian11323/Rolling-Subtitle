#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EMSC SeismicPortal standing_order WebSocket 适配器。

过滤逻辑对齐服务器 fused_list_v2.py：
- 仅 create/update
- 震级 <= 0 丢弃
- 发震时刻超过 1 小时丢弃（防过期事件刷屏）
- ID + 内容 MD5 去重库（最新 20 条落盘）；同 ID 不同 MD5 视为修订放行
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils
from utils.emsc_dedup import (
    EMSC_WSS_MAX_AGE_HOURS,
    EmscDedupStore,
    emsc_age_hours,
    is_emsc_event_expired,
    parse_emsc_origin_utc,
)
from utils.logger import get_logger

logger = get_logger()


class EmscWsAdapter(BaseAdapter):
    """解析 EMSC standing_order 推送（action + GeoJSON Feature）。"""

    def __init__(self, source_name: str, source_url: str):
        """初始化适配器。"""
        super().__init__(source_name, source_url)

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
        if mag <= 0:
            return None

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

        shock_raw = props.get("time")
        if shock_raw is None or shock_raw == "":
            return None

        # 过期过滤：发震时刻 > 1 小时则丢弃（对齐 fused_list EMSC_WSS_MAX_AGE_HOURS）
        origin_dt = parse_emsc_origin_utc(shock_raw)
        if origin_dt is None or is_emsc_event_expired(shock_raw):
            age = emsc_age_hours(origin_dt)
            logger.info(
                f"[EMSC] 丢弃过期事件 age={age:.1f}h > {EMSC_WSS_MAX_AGE_HOURS}h "
                f"id={props.get('unid') or (data.get('id') if isinstance(data, dict) else '')} "
                f"time={shock_raw}"
            )
            return None

        shock_time = timezone_utils.utc_to_display(str(shock_raw).strip()) if shock_raw else ""
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

        # ID + MD5 去重（同 ID 不同内容视为修订，允许推送）
        if EmscDedupStore.is_duplicate(event_id, shock_time, mag, lat, lon, depth):
            logger.info(
                f"[EMSC] 重复数据不推送 action={action or '-'} id={event_id} "
                f"mag={mag} time={shock_time}"
            )
            return None

        EmscDedupStore.remember(event_id, shock_time, mag, lat, lon, depth)

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
            "fanstudio": False,
            "whews": False,
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
