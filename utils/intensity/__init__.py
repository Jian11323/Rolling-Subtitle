#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
站点烈度估算包：提供可插拔的烈度计算与按数据源路由。

外部入口：
- ``IntensityResult``：烈度计算结果 dataclass
- ``IntensityProvider``：抽象 provider 接口
- ``IntensityProviderRegistry``：按 ``source_type`` 路由 provider
- ``compute_for_parsed``：便捷函数，直接基于 parsed_data + AlertConfig 计算
"""

from .base import IntensityResult, IntensityProvider
from .registry import IntensityProviderRegistry, compute_for_parsed
from .china_empirical import ChinaEmpiricalProvider
from .sceew_local import SceewLocalProvider

__all__ = [
    "IntensityResult",
    "IntensityProvider",
    "IntensityProviderRegistry",
    "ChinaEmpiricalProvider",
    "SceewLocalProvider",
    "compute_for_parsed",
]
