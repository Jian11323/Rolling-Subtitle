#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中国经验烈度估算 provider。

仅用于「有感 / 强有感」触发判断，不追求精确工程烈度。

公式：
    I = 0.92 + 1.63 * M - 3.49 * log10(R_eff)
    R_eff = sqrt(epi_dist_km^2 + (depth_km + 10)^2)

并将结果裁剪到 [0, 12] 区间。后续如需引入省/市经验修正，可在 ``REGION_ADJUST`` 增加条目。
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from utils.logger import get_logger

from .base import IntensityProvider, IntensityResult

logger = get_logger()


REGION_ADJUST: Dict[str, float] = {
    # "四川省": 0.5,
    # "云南省": 0.3,
}


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """计算两点之间的大圆距离（千米）。"""
    try:
        if not all(map(math.isfinite, (lat1, lon1, lat2, lon2))):
            return 0.0
        if abs(lat1 - lat2) < 1e-6 and abs(lon1 - lon2) < 1e-6:
            return 0.0
        r = 6371.0
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
        logger.debug(f"计算震中距失败: {e}")
        return 0.0


def estimate_intensity(
    magnitude: float,
    depth_km: float,
    epi_lat: float,
    epi_lon: float,
    site_lat: float,
    site_lon: float,
    region_name: Optional[str] = None,
) -> IntensityResult:
    """估算指定站点的中国经验烈度，并返回 ``IntensityResult``。"""
    try:
        try:
            m = float(magnitude)
        except (TypeError, ValueError):
            m = 0.0

        epi_dist_km = haversine_distance_km(epi_lat, epi_lon, site_lat, site_lon)

        if m <= 0:
            return IntensityResult(
                intensity=0.0,
                intensity_level=0,
                distance_km=epi_dist_km,
                magnitude=max(m, 0.0),
                provider_name="china_empirical",
                epi_lat=epi_lat,
                epi_lon=epi_lon,
            )

        if epi_dist_km <= 0:
            epi_dist_km_eff = 1.0
        else:
            epi_dist_km_eff = epi_dist_km

        try:
            d = float(depth_km)
        except (TypeError, ValueError):
            d = 10.0

        r_eff = math.sqrt(epi_dist_km_eff ** 2 + (d + 10.0) ** 2)
        intensity = 0.92 + 1.63 * m - 3.49 * math.log10(max(r_eff, 1.0))

        if region_name:
            adj = REGION_ADJUST.get(region_name.strip(), 0.0)
            intensity += adj

        if not math.isfinite(intensity):
            intensity = 0.0
        intensity = max(0.0, min(12.0, intensity))
        intensity_level = int(round(intensity))
        return IntensityResult(
            intensity=intensity,
            intensity_level=intensity_level,
            distance_km=epi_dist_km,
            magnitude=m,
            provider_name="china_empirical",
            epi_lat=epi_lat,
            epi_lon=epi_lon,
        )
    except Exception as e:
        logger.debug(f"估算中国烈度失败: {e}")
        return IntensityResult(
            intensity=0.0,
            intensity_level=0,
            distance_km=0.0,
            magnitude=0.0,
            provider_name="china_empirical",
            epi_lat=epi_lat,
            epi_lon=epi_lon,
        )


class ChinaEmpiricalProvider(IntensityProvider):
    """基于中国经验公式的烈度 provider。"""

    name = "china_empirical"

    def compute(
        self,
        parsed_data: Dict[str, Any],
        site_lat: float,
        site_lon: float,
        site_region_name: Optional[str] = None,
    ) -> Optional[IntensityResult]:
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

            try:
                depth_km = float(parsed_data.get("depth") or 10.0)
            except (TypeError, ValueError):
                depth_km = 10.0

            return estimate_intensity(
                magnitude=magnitude,
                depth_km=depth_km,
                epi_lat=epi_lat,
                epi_lon=epi_lon,
                site_lat=site_lat,
                site_lon=site_lon,
                region_name=site_region_name,
            )
        except Exception as e:
            logger.debug(f"ChinaEmpiricalProvider.compute 失败: {e}")
            return None


__all__ = [
    "ChinaEmpiricalProvider",
    "REGION_ADJUST",
    "estimate_intensity",
    "haversine_distance_km",
]
