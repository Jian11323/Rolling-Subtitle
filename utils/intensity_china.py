#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中国经验烈度估算工具

仅用于公开版中「有感 / 强有感」触发判断，不追求精确工程烈度。
公式参考常见经验关系：

    I = 0.92 + 1.63 * M - 3.49 * log10(R)

其中：
- I 为烈度（度）
- M 为震级
- R 为震中距（km）

这里增加简单的等效距离修正，将震源深度叠加到 R 中：

    R_eff = sqrt(R^2 + (depth_km + 10)^2)

并将结果裁剪到 [0, 12] 区间。

后续若需要引入更复杂的省/市经验修正表，可在 REGION_ADJUST 中增加条目，
并在 estimate_intensity_china 中按 region_name 调整结果。
"""

from __future__ import annotations

import math
from typing import Tuple

from .logger import get_logger

logger = get_logger()


# 预留按地区修正烈度的结构（目前默认全 0，不做修正）
REGION_ADJUST = {
    # "四川省": 0.5,
    # "云南省": 0.3,
}


def _haversine_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """
    计算两点之间的大圆距离（千米）。

    使用简单 Haversine 公式，精度对于烈度粗略估算已足够。
    """
    try:
        # 无效坐标直接返回 0
        if not all(map(math.isfinite, (lat1, lon1, lat2, lon2))):
            return 0.0

        # 相同点
        if abs(lat1 - lat2) < 1e-6 and abs(lon1 - lon2) < 1e-6:
            return 0.0

        r = 6371.0  # 地球半径，km
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


def estimate_intensity_china(
    magnitude: float,
    depth_km: float,
    epi_lat: float,
    epi_lon: float,
    site_lat: float,
    site_lon: float,
    region_name: str | None = None,
) -> float:
    """
    估算指定站点的中国经验烈度（度）。

    返回值可能为小数，调用方可再取整或四舍五入。
    """
    try:
        try:
            m = float(magnitude)
        except (TypeError, ValueError):
            m = 0.0

        # 无震级直接返回 0
        if m <= 0:
            return 0.0

        # 距离（平面） + 深度修正
        epi_dist_km = _haversine_distance_km(epi_lat, epi_lon, site_lat, site_lon)

        # 若距离为 0，给一个很小的值避免 log(0)
        if epi_dist_km <= 0:
            epi_dist_km = 1.0

        try:
            d = float(depth_km)
        except (TypeError, ValueError):
            d = 10.0

        # 等效距离：叠加震源深度，避免近场烈度过高
        r_eff = math.sqrt(epi_dist_km**2 + (d + 10.0) ** 2)

        # 使用经验公式 I = 0.92 + 1.63M - 3.49log10(R_eff)
        intensity = 0.92 + 1.63 * m - 3.49 * math.log10(max(r_eff, 1.0))

        # 地区修正（目前默认 0）
        if region_name:
            adj = REGION_ADJUST.get(region_name.strip(), 0.0)
            intensity += adj

        # 将结果限制在 [0, 12] 区间
        if not math.isfinite(intensity):
            intensity = 0.0
        intensity = max(0.0, min(12.0, intensity))
        return intensity
    except Exception as e:
        logger.debug(f"估算中国烈度失败: {e}")
        return 0.0


def classify_perceived(intensity: float) -> Tuple[str, int]:
    """
    根据烈度数值划分是否「有感 / 强有感」。

    返回:
        (level, int_level)
        level: 'none' | 'felt' | 'strong_felt'
        int_level: 0–12 之间的整数烈度
    """
    try:
        if not math.isfinite(intensity):
            intensity = 0.0
    except Exception:
        intensity = 0.0

    int_level = int(round(max(0.0, min(12.0, float(intensity)))))

    if int_level <= 0:
        return "none", int_level
    if int_level <= 5:
        return "felt", int_level
    return "strong_felt", int_level


__all__ = [
    "estimate_intensity_china",
    "classify_perceived",
    "REGION_ADJUST",
]

