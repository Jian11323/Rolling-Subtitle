#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地理距离计算与区域过滤。"""

import math
from typing import Any, Dict, Optional


# 地球平均半径（公里），用于 haversine 距离计算
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """计算两点间大圆距离（公里）。"""
    r = 6371.0  # 地球平均半径（公里）
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))  # haversine 大圆距离


def event_coordinates(parsed_data: Dict[str, Any]) -> Optional[tuple]:
    """从解析结果提取 (lat, lon)。"""
    if not isinstance(parsed_data, dict):
        return None
    try:
        lat = float(parsed_data.get("latitude") or 0)
        lon = float(parsed_data.get("longitude") or 0)
    except (TypeError, ValueError):
        return None
    if lat == 0 and lon == 0:
        return None  # 0,0 视为无效坐标
    return lat, lon


def passes_magnitude_filter(parsed_data: Dict[str, Any], config: Any, message_type: str) -> bool:
    """震级过滤：0 表示不启用。"""
    mc = getattr(config, "message_config", None)
    if mc is None:
        return True
    if message_type == "warning":
        return True  # 预警不受震级过滤限制
    try:
        min_mag = float(getattr(mc, "min_report_magnitude", 0) or 0)
    except (TypeError, ValueError):
        min_mag = 0.0
    if min_mag <= 0:
        return True  # 0 表示不限制震级
    try:
        mag = float(parsed_data.get("magnitude") or 0)
    except (TypeError, ValueError):
        return True
    return mag >= min_mag


def passes_geo_filter(parsed_data: Dict[str, Any], config: Any) -> bool:
    """距离过滤：未启用或缺少坐标时放行。"""
    mc = getattr(config, "message_config", None)
    if mc is None or not getattr(mc, "geo_filter_enabled", False):
        return True
    coords = event_coordinates(parsed_data)
    if coords is None:
        return True
    try:
        center_lat = float(getattr(mc, "geo_filter_latitude", 0))
        center_lon = float(getattr(mc, "geo_filter_longitude", 0))
        radius = float(getattr(mc, "geo_filter_radius_km", 1000) or 1000)
    except (TypeError, ValueError):
        return True
    if radius <= 0:
        return True
    dist = haversine_km(center_lat, center_lon, coords[0], coords[1])
    return dist <= radius  # 在半径内则通过


def should_accept_message(
    parsed_data: Dict[str, Any],
    config: Any,
    message_type: str,
) -> bool:
    """综合震级与区域过滤。"""
    if not passes_magnitude_filter(parsed_data, config, message_type):
        return False
    if not passes_geo_filter(parsed_data, config):
        return False
    return True
