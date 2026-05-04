#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按 ``source_type`` 选择 ``IntensityProvider`` 的注册表。

设计目标：
- 解除 adapter 中的 ``china_related_sources`` 硬编码 set；
- 后续若引入 JMA 震度模型 / USGS 简化模型，只需在此注册 provider 并扩展 ``_DEFAULT_BINDINGS``。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from utils.logger import get_logger

from .base import IntensityProvider, IntensityResult
from .china_empirical import ChinaEmpiricalProvider
from .sceew_local import SceewLocalProvider

logger = get_logger()


_DEFAULT_BINDINGS: Dict[str, str] = {
    # 本地预估烈度统一为 SCEEW 同款：地表大圆距离 + 1.92 + 1.63*M - 3.49*log10(距离)
    "cea": "sceew_local",
    "cea-pr": "sceew_local",
    "cenc": "sceew_local",
    "ningxia": "sceew_local",
    "guangxi": "sceew_local",
    "shanxi": "sceew_local",
    "beijing": "sceew_local",
    "yunnan": "sceew_local",
    "cwa-eew": "sceew_local",
    "jma": "sceew_local",
    "sa": "sceew_local",
    "kma-eew": "sceew_local",
    "wolfx_jma_eew": "sceew_local",
    "wolfx_sc_eew": "sceew_local",
    "wolfx_fj_eew": "sceew_local",
    "wolfx_cenc_eew": "sceew_local",
    "wolfx_cq_eew": "sceew_local",
    "wolfx_cwa_eew": "sceew_local",
}


class IntensityProviderRegistry:
    """单例注册表：按 source_type 路由到具体 provider。"""

    _providers: Dict[str, IntensityProvider] = {}
    _bindings: Dict[str, str] = dict(_DEFAULT_BINDINGS)
    _initialized: bool = False

    @classmethod
    def _ensure_initialized(cls) -> None:
        if cls._initialized:
            return
        cls._providers["china_empirical"] = ChinaEmpiricalProvider()
        cls._providers["sceew_local"] = SceewLocalProvider()
        cls._initialized = True

    @classmethod
    def register(cls, name: str, provider: IntensityProvider) -> None:
        cls._ensure_initialized()
        cls._providers[name] = provider

    @classmethod
    def bind(cls, source_type: str, provider_name: str) -> None:
        cls._ensure_initialized()
        cls._bindings[source_type] = provider_name

    @classmethod
    def provider_for(cls, source_type: Optional[str]) -> Optional[IntensityProvider]:
        cls._ensure_initialized()
        if not source_type:
            return None
        name = cls._bindings.get(source_type)
        if not name:
            return None
        return cls._providers.get(name)

    @classmethod
    def compute(
        cls,
        parsed_data: Dict[str, Any],
        site_lat: float,
        site_lon: float,
        site_region_name: Optional[str] = None,
    ) -> Optional[IntensityResult]:
        cls._ensure_initialized()
        try:
            source_type = (parsed_data.get("source_type") or "").strip()
            provider = cls.provider_for(source_type)
            if provider is None:
                return None
            return provider.compute(
                parsed_data=parsed_data,
                site_lat=site_lat,
                site_lon=site_lon,
                site_region_name=site_region_name,
            )
        except Exception as e:
            logger.debug(f"IntensityProviderRegistry.compute 失败: {e}")
            return None


def compute_for_parsed(
    parsed_data: Dict[str, Any],
    alert_config: Any,
) -> Optional[IntensityResult]:
    """
    便捷函数：基于 ``AlertConfig`` 上的站点经纬度调用注册表。

    站点经纬度近似 0 时直接返回 None（避免在赤道附近的极少数用户被波及）。
    """
    try:
        if alert_config is None:
            return None
        if not getattr(alert_config, "enabled", False):
            return None
        site_lat = float(getattr(alert_config, "site_lat", 0.0) or 0.0)
        site_lon = float(getattr(alert_config, "site_lon", 0.0) or 0.0)
        if abs(site_lat) < 1e-3 and abs(site_lon) < 1e-3:
            return None
        site_region_name = getattr(alert_config, "site_region_name", "") or None
        return IntensityProviderRegistry.compute(
            parsed_data=parsed_data,
            site_lat=site_lat,
            site_lon=site_lon,
            site_region_name=site_region_name,
        )
    except Exception as e:
        logger.debug(f"compute_for_parsed 失败: {e}")
        return None


__all__ = [
    "IntensityProviderRegistry",
    "compute_for_parsed",
]
