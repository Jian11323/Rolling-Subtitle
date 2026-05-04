#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SCEEW 式本地烈度（与四川地震预警 SCEEW 程序一致）。

对照上游仓库 ``SCEEW-main/SCEEW.py``：
- 震中距：`distance(lat1, lon1, lat2, lon2)`（约 548–558 行），球半径 6378.137 km，haversine 大圆弧；
- 本地烈度：`max(1.92 + 1.63 * M - 3.49 * log10(eqdistance), 0.0)`（约 635–638 行，原代码为 ``math.log(eqdistance, 10)``）。

本模块中震中距为 ``sceew_surface_distance_km``；烈度为 ``estimate_sceew_cnshindo``。
距离 ≤0 km 时按 1 km 参与 log10，避免与震中重合时 ``log10(0)`` 无定义（上游若 eqdistance 为 0 会异常）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from utils.logger import get_logger

from .base import IntensityProvider, IntensityResult

logger = get_logger()

# WGS84 赤道半径（km），与 SCEEW-main/SCEEW.py 中 distance() 一致
_SCEEW_EARTH_RADIUS_KM = 6378.137


def sceew_surface_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """SCEEW 使用的震中—站点大圆距离（千米）。"""
    try:
        if not all(map(math.isfinite, (lat1, lon1, lat2, lon2))):
            return 0.0
        if abs(lat1 - lat2) < 1e-6 and abs(lon1 - lon2) < 1e-6:
            return 0.0
        r = _SCEEW_EARTH_RADIUS_KM
        rad = math.radians
        dlat = rad(lat2 - lat1)
        dlon = rad(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(rad(lat1)) * math.cos(rad(lat2)) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return max(0.0, r * c)
    except Exception as e:
        logger.debug(f"SCEEW 距离计算失败: {e}")
        return 0.0


def estimate_sceew_cnshindo(magnitude: float, epicenter_distance_km: float) -> float:
    """
    SCEEW 本地烈度（浮点「度」），与 SCEEW.py 中 cnshindo 计算一致。
    ``epicenter_distance_km`` 为地表震中距；≤0 时按 1 km 处理。
    """
    try:
        m = float(magnitude)
    except (TypeError, ValueError):
        m = 0.0
    try:
        d = float(epicenter_distance_km)
    except (TypeError, ValueError):
        d = 0.0
    if m <= 0:
        return 0.0
    d_use = max(d, 1.0)
    raw = 1.92 + 1.63 * m - 3.49 * math.log10(d_use)
    v = max(0.0, raw)
    if not math.isfinite(v):
        return 0.0
    return min(12.0, v)


class SceewLocalProvider(IntensityProvider):
    """基于 SCEEW 经验式的站点烈度，用于中国大陆相关预警源。"""

    name = "sceew_local"

    def compute(
        self,
        parsed_data: Dict[str, Any],
        site_lat: float,
        site_lon: float,
        site_region_name: Optional[str] = None,
    ) -> Optional[IntensityResult]:
        _ = site_region_name
        try:
            mag_raw = parsed_data.get("magnitude")
            try:
                magnitude = float(mag_raw) if mag_raw is not None else 0.0
            except (TypeError, ValueError):
                magnitude = 0.0
            if magnitude <= 0:
                return None

            try:
                epi_lat = float(parsed_data.get("latitude") or 0.0)
                epi_lon = float(parsed_data.get("longitude") or 0.0)
            except (TypeError, ValueError):
                return None
            if abs(epi_lat) < 1e-6 and abs(epi_lon) < 1e-6:
                return None

            dist_km = sceew_surface_distance_km(epi_lat, epi_lon, site_lat, site_lon)
            cn = estimate_sceew_cnshindo(magnitude, dist_km)
            level = int(round(min(12.0, max(0.0, cn))))

            return IntensityResult(
                intensity=float(cn),
                intensity_level=level,
                distance_km=dist_km,
                magnitude=magnitude,
                provider_name=self.name,
                epi_lat=epi_lat,
                epi_lon=epi_lon,
            )
        except Exception as e:
            logger.debug(f"SceewLocalProvider.compute 失败: {e}")
            return None


__all__ = [
    "SceewLocalProvider",
    "estimate_sceew_cnshindo",
    "sceew_surface_distance_km",
]
