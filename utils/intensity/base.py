#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
烈度 provider 的抽象接口与结果数据类。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class IntensityResult:
    """
    烈度计算结果。

    Attributes:
        intensity: 估算烈度（0-12 度，可能为小数）
        intensity_level: 取整后的烈度（0-12）
        distance_km: 站点到震中距离（km）
        magnitude: 入参震级（用于过滤）
        provider_name: 计算 provider 名称（用于日志）
        epi_lat: 震中纬度
        epi_lon: 震中经度
    """
    intensity: float
    intensity_level: int
    distance_km: float
    magnitude: float
    provider_name: str = ""
    epi_lat: float = 0.0
    epi_lon: float = 0.0


class IntensityProvider(ABC):
    """烈度计算 provider 抽象基类。"""

    name: str = "base"

    @abstractmethod
    def compute(
        self,
        parsed_data: Dict[str, Any],
        site_lat: float,
        site_lon: float,
        site_region_name: Optional[str] = None,
    ) -> Optional[IntensityResult]:
        """
        基于一条 parsed_data 与站点经纬度，给出烈度结果。

        实现应保证：
        - 入参不合法（缺少震中坐标/震级等）时返回 ``None``，由调用方决定是否回退；
        - 不抛异常，所有异常都内部处理并返回 ``None``。
        """
        raise NotImplementedError
