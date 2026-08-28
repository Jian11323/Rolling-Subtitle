#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
震中烈度相关工具：仅使用报文自带烈度/震度，不做经验式估算（降低误导风险）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# 日台相关源：展示侧走震度文案，不按中国烈度口径处理
SOURCE_NO_CHINA_EPI_ESTIMATE = frozenset(
    {
        "jma",
        "jma_eq",
        "cwa-eew",
        "cwa",
        "wolfx_jma_eew",
        "wolfx_cwa_eew",
        "wolfx_jma_eqlist",
        "eqsc_jma_eew",
        "eqsc_cwa",
        "p2pquake",
        "p2pquake_eew",
    }
)

# 情报/观测最大震度（非 EEW 预估）：文案用「最大震度」
SOURCE_JP_TW_REPORT_MAX_SHINDO = frozenset(
    {
        "jma_eq",
        "cwa",
        "wolfx_jma_eqlist",
        "p2pquake",
    }
)

# 不进入「有感/强有感」告警序列、不拼接安全提示的 source_type（台湾、日本相关源）
SOURCE_TW_JP_ALERT_EXCLUDE = frozenset(
    {
        "jma",
        "jma_eq",
        "cwa-eew",
        "cwa",
        "wolfx_jma_eew",
        "wolfx_cwa_eew",
        "wolfx_jma_eqlist",
        "eqsc_jma_eew",
        "eqsc_cwa",
        "p2pquake",
        "p2pquake_eew",
    }
)

_EPI_KEYS = (
    "intensity",
    "max_intensity",
    "epiIntensity",
    "epi_intensity",
    "maxIntensity",
    "MaxIntensity",
)  # 报文震中烈度/震度字段名候选


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


def effective_epi_for_alert(parsed_data: Dict[str, Any]) -> Optional[float]:
    """
    用于有感/强有感门槛与告警触发的烈度标量（非日台序列）。
    仅采用报文已有数值；官方未提供则返回 None。
    """
    pd = parsed_data or {}
    st = (pd.get("source_type") or "").strip().lower()
    if st in SOURCE_TW_JP_ALERT_EXCLUDE:  # 日台源不进入本烈度告警序列
        return None
    return _to_positive_float(_first_epi_raw(pd))
