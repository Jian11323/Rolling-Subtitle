#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向下兼容 shim。

历史路径 ``utils.intensity_china`` 已迁移到 ``utils.intensity`` 包：
- ``estimate_intensity_china`` → ``utils.intensity.china_empirical.estimate_intensity``（返回值由浮点改为
  ``IntensityResult``，本 shim 仍返回浮点保持旧调用方兼容）
- ``classify_perceived`` 仅供旧代码使用，新代码请改用 ``AlertConfig.min_intensity_to_alert /
  min_intensity_to_flash`` 阈值化判定。

下个版本可移除本文件。
"""

from __future__ import annotations

import math
from typing import Tuple

from .intensity.china_empirical import (
    REGION_ADJUST,
    estimate_intensity as _estimate_intensity_full,
)


def estimate_intensity_china(
    magnitude: float,
    depth_km: float,
    epi_lat: float,
    epi_lon: float,
    site_lat: float,
    site_lon: float,
    region_name: str | None = None,
) -> float:
    result = _estimate_intensity_full(
        magnitude=magnitude,
        depth_km=depth_km,
        epi_lat=epi_lat,
        epi_lon=epi_lon,
        site_lat=site_lat,
        site_lon=site_lon,
        region_name=region_name,
    )
    return float(result.intensity)


def classify_perceived(intensity: float) -> Tuple[str, int]:
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
