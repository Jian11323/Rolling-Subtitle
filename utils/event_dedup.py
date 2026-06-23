#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨数据源事件去重（仅程序内部合并展示，不对外转发）。"""

import time
from typing import Any, Dict, List, Optional

from utils.geo_utils import haversine_km, event_coordinates

_DEDUP_TIME_SEC = 120.0
_DEDUP_DISTANCE_KM = 50.0
_MAG_TOLERANCE = 0.5


def _parse_shock_ts(shock_time: str) -> Optional[float]:
    if not shock_time:
        return None
    try:
        from utils import timezone_utils
        dt = timezone_utils.parse_display_time(str(shock_time).strip())
        if dt is not None:
            return dt.timestamp()
    except Exception:
        pass
    return None


def find_duplicate_index(
    parsed_data: Dict[str, Any],
    recent_events: List[Dict[str, Any]],
) -> Optional[int]:
    """在 recent_events 中查找与 parsed_data 匹配的跨源重复项。"""
    coords = event_coordinates(parsed_data)
    if coords is None:
        return None

    shock_ts = _parse_shock_ts(str(parsed_data.get("shock_time") or ""))
    try:
        mag = float(parsed_data.get("magnitude") or 0)
    except (TypeError, ValueError):
        mag = 0.0

    now = time.time()
    for idx in range(len(recent_events) - 1, -1, -1):
        item = recent_events[idx]
        other = item.get("parsed_data") or {}
        if not isinstance(other, dict):
            continue
        ocoords = event_coordinates(other)
        if ocoords is None:
            continue
        if haversine_km(coords[0], coords[1], ocoords[0], ocoords[1]) > _DEDUP_DISTANCE_KM:
            continue
        try:
            omag = float(other.get("magnitude") or 0)
        except (TypeError, ValueError):
            omag = 0.0
        if mag > 0 and omag > 0 and abs(mag - omag) > _MAG_TOLERANCE:
            continue
        if shock_ts is not None:
            ots = _parse_shock_ts(str(other.get("shock_time") or ""))
            if ots is not None and abs(shock_ts - ots) > _DEDUP_TIME_SEC:
                continue
        else:
            recv = float(item.get("received_at_ts") or 0)
            if recv and (now - recv) > _DEDUP_TIME_SEC:
                continue
        return idx
    return None


def merge_sources(existing: Dict[str, Any], source_name: str) -> None:
    """将新数据源名称合并到已有记录的 merged_sources 列表。"""
    merged = existing.setdefault("merged_sources", [])
    if not isinstance(merged, list):
        existing["merged_sources"] = merged = []
    display = source_name
    if display and display not in merged:
        merged.append(display)
