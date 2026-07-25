#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨数据源事件去重（告警反馈等内部比对）。"""

import time
from typing import Any, Dict, List, Optional

from utils.geo_utils import haversine_km, event_coordinates

_DEDUP_TIME_SEC = 120.0  # 跨源去重：发震时间差上限（秒）
_DEDUP_DISTANCE_KM = 50.0  # 跨源去重：震中距离上限（公里）
_MAG_TOLERANCE = 0.5  # 跨源去重：震级容差


def _parse_shock_ts(shock_time: str) -> Optional[float]:
    """将发震时间字符串解析为 Unix 时间戳（秒）。"""
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
    if coords is None:  # 无坐标无法做空间去重
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
        if haversine_km(coords[0], coords[1], ocoords[0], ocoords[1]) > _DEDUP_DISTANCE_KM:  # 震中距离超限视为不同事件
            continue
        try:
            omag = float(other.get("magnitude") or 0)
        except (TypeError, ValueError):
            omag = 0.0
        if mag > 0 and omag > 0 and abs(mag - omag) > _MAG_TOLERANCE:
            continue
        if shock_ts is not None:
            ots = _parse_shock_ts(str(other.get("shock_time") or ""))
            if ots is not None and abs(shock_ts - ots) > _DEDUP_TIME_SEC:  # 发震时间差超限
                continue
        else:
            recv = float(item.get("received_at_ts") or 0)
            if recv and (now - recv) > _DEDUP_TIME_SEC:
                continue
        return idx
    return None
