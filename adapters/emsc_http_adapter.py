#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EMSC FDSN GeoJSON HTTP 地震速报适配器。"""

from __future__ import annotations

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


class EmscHttpAdapter(BaseAdapter):
    """解析 EMSC FDSN JSON，取最新一条；复用过期过滤与 ID+MD5 去重。"""

    response_format = "json"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw_data, dict):
            return None
        features = raw_data.get("features") or []
        if not isinstance(features, list) or not features:
            return None

        best = None
        best_origin = None
        for f in features:
            if not isinstance(f, dict):
                continue
            props = f.get("properties") or {}
            mag = props.get("mag")
            try:
                mag_f = float(mag)
            except (TypeError, ValueError):
                continue
            if mag_f <= 0:
                continue
            t = props.get("time")
            if t is None or t == "":
                continue
            if is_emsc_event_expired(t):
                continue
            origin = parse_emsc_origin_utc(t)
            if origin is None:
                continue
            if best is None or (best_origin and origin > best_origin) or best_origin is None:
                best = f
                best_origin = origin

        if best is None:
            # 全部过期时打一条日志
            if features:
                logger.debug(
                    f"[EMSC HTTP] 无可用事件（均超过 {EMSC_WSS_MAX_AGE_HOURS}h 或无效）"
                )
            return None

        props = best.get("properties") or {}
        mag = float(props.get("mag") or 0)
        lat = float(props.get("lat") or 0)
        lon = float(props.get("lon") or 0)
        depth = float(props.get("depth") or 0)
        shock_raw = props.get("time")
        shock_time = ""
        if isinstance(shock_raw, (int, float)):
            shock_time = timezone_utils.timestamp_to_display(int(shock_raw))
        else:
            shock_time = timezone_utils.utc_to_display(str(shock_raw).strip())
        place = str(props.get("flynn_region") or "未知地区").strip() or "未知地区"
        event_id = str(best.get("id") or props.get("unid") or "").strip()
        if not event_id:
            event_id = f"emsc_{shock_time}_{lat}_{lon}"

        if EmscDedupStore.is_duplicate(event_id, shock_time, mag, lat, lon, depth):
            logger.debug(f"[EMSC HTTP] 重复数据跳过 id={event_id}")
            return None
        EmscDedupStore.remember(event_id, shock_time, mag, lat, lon, depth)

        return {
            "type": "report",
            "source_type": "emsc",
            "place_name": place,
            "shock_time": shock_time,
            "magnitude": mag,
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "organization": self.get_organization_name(),
            "event_id": event_id,
            "raw_data": best,
            "fanstudio": False,
            "whews": False,
        }

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "report")
