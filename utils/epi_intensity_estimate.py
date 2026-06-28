#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
震中烈度估算（浅源经验式）：有报文震中烈度字段时不估算；台湾、日本相关源不估算。

公式（深度 h 已知，单位 km）：I0 = 1.5M - 3.5*log10(h) + 3.0
无有效深度时采用国内常用近似：I0 ≈ 1.5M - 1.5
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

# 不使用中国浅源经验式估算震中烈度的 source_type（台湾、日本相关源）
SOURCE_NO_CHINA_EPI_ESTIMATE = frozenset(
    {"jma", "cwa-eew", "cwa", "wolfx_jma_eew", "wolfx_cwa_eew"}
)

# 不进入「有感/强有感」告警序列、不拼接安全提示的 source_type（台湾、日本相关源）
SOURCE_TW_JP_ALERT_EXCLUDE = frozenset(
    {"jma", "cwa-eew", "cwa", "wolfx_jma_eew", "wolfx_cwa_eew"}
)

_EPI_KEYS = (
    "intensity",
    "max_intensity",
    "epiIntensity",
    "epi_intensity",
    "maxIntensity",
    "MaxIntensity",
)  # 报文震中烈度/震度字段名候选


def parsed_declares_epi_intensity(data: Dict[str, Any]) -> bool:
    """解析结果或 raw 中是否已声明震中/最大烈度类字段（有字段即视为「带来源值」，不覆盖估算）。"""
    for k in _EPI_KEYS:
        if k in data:  # 报文已含烈度字段，不再估算
            return True
    raw = data.get("raw_data")
    if isinstance(raw, dict):
        for k in _EPI_KEYS + ("Intensity",):
            if k in raw:
                return True
    return False


def _first_epi_raw(parsed: Dict[str, Any]) -> Any:
    """从解析结果或 raw_data 中取第一个非空的震中烈度原始值。"""
    for k in _EPI_KEYS:
        v = parsed.get(k)
        if v is not None and str(v).strip():
            return v
    raw = parsed.get("raw_data")
    if isinstance(raw, dict):
        for k in _EPI_KEYS + ("Intensity",):
            v = raw.get(k)
            if v is not None and str(v).strip():
                return v
    return None


def _to_positive_float(value: Any) -> Optional[float]:
    """将烈度值转为正浮点数；无法解析时返回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            x = float(value)
        except (TypeError, ValueError):
            return None
        return x if x > 0 else None
    try:
        x = float(str(value).strip().replace("度", ""))
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def estimate_epi_intensity(M: float, depth_km: Optional[float]) -> Optional[float]:
    """
    由震级 M 与震源深度（km）估算震中烈度标量；深度无效时用 1.5M-1.5。
    返回值保留为浮点，由调用方决定展示小数位。
    """
    try:
        m = float(M)
    except (TypeError, ValueError):
        return None
    if m <= 0:
        return None
    h: Optional[float] = None
    if depth_km is not None:
        try:
            hf = float(depth_km)
            if hf > 0:
                h = hf
        except (TypeError, ValueError):
            h = None
    if h is not None:  # 浅源经验式（含深度项）
        i0 = 1.5 * m - 3.5 * math.log10(h) + 3.0
    else:
        i0 = 1.5 * m - 1.5  # 无深度时用国内常用近似
    return float(i0)


def effective_epi_for_alert(parsed_data: Dict[str, Any]) -> Optional[float]:
    """
    用于有感/强有感门槛与告警触发的烈度标量（非日台序列）。
    优先报文已有数值；未声明字段时对非日台源做浅源经验估算。
    """
    pd = parsed_data or {}
    st = (pd.get("source_type") or "").strip().lower()
    if st in SOURCE_TW_JP_ALERT_EXCLUDE:  # 日台源不参与中国经验式告警
        return None
    v = _to_positive_float(_first_epi_raw(pd))
    if v is not None:
        return v
    if parsed_declares_epi_intensity(pd):  # 有字段但无有效数值，不强行估算
        return None
    try:
        mag = float(pd.get("magnitude") or 0.0)
    except (TypeError, ValueError):
        return None
    if mag <= 0:
        return None
    depth_raw = pd.get("depth")
    depth_f: Optional[float] = None
    if depth_raw is not None:
        try:
            d = float(depth_raw)
            depth_f = d if d > 0 else None
        except (TypeError, ValueError):
            depth_f = None
    est = estimate_epi_intensity(mag, depth_f)
    if est is None or est <= 0:
        return None
    return float(est)
