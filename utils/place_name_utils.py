#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地名本地化辅助：区分保留原文源、国外 FE 修正、百度翻译。"""

from __future__ import annotations

import re
from typing import Any

# 数据源本身提供可用原文地名（中文或官方精细地名），不做 FE / 翻译覆盖
CHINESE_SOURCE_TYPES = frozenset({
    "cea", "cea-pr", "cwa-eew", "cwa", "cenc", "cenc-ir",
    "ningxia", "guangxi", "shanxi", "beijing", "yunnan",
    "fujian", "sichuan", "shaanxi", "hubei",
    "hko",
    "wolfx_sc", "wolfx_fj", "wolfx_cenc", "wolfx_cwa", "wolfx_cq",
    "wolfx_sc_eew", "wolfx_cenc_eew", "wolfx_fj_eew", "wolfx_cq_eew", "wolfx_cwa_eew",
    "eqsc_cenc", "eqsc_cenc_ir", "eqsc_cwa", "eqsc_hko", "eqsc_typhoon",
    "nmefc", "nmefc-tsunami",
    # NMEFC 海啸正文已是中文地点+预报区，勿被 FE 粗分区覆盖
    "tsunami", "海啸信息",
})

# JMA / P2PQuake：使用官方原始地名（日文），不做 FE 粗分区覆盖
JMA_ORIGINAL_PLACE_SOURCES = frozenset({
    "jma", "jma_volcano", "jma_tsunami",
    "wolfx_jma_eew", "wolfx_jma_eqlist",
    "eqsc_jma_eew", "eqsc_jma_report", "eqsc_jma_tsunami", "eqsc_volcano",
    "p2pquake", "p2pquake_tsunami",
})

KEEP_ORIGINAL_PLACE_NAME_SOURCES = CHINESE_SOURCE_TYPES | JMA_ORIGINAL_PLACE_SOURCES

# 预警走专用区域库（SA / KMA），不走通用 FE
_FE_PLACE_FIX_EXCLUDED = frozenset({"sa", "kma-eew"})


def _normalize_source_type(source_type: str) -> str:
    """标准化数据源类型标识（小写、去空白）。"""
    return (source_type or "").strip().lower()


def is_chinese_source(source_type: str) -> bool:
    """判断数据源是否本身提供中文地名（无需翻译或修正）。"""
    return _normalize_source_type(source_type) in CHINESE_SOURCE_TYPES


def should_keep_original_place_name(source_type: str) -> bool:
    """CENC / CWA / JMA / HKO / P2PQuake 等：直接使用原始地名。"""
    return _normalize_source_type(source_type) in KEEP_ORIGINAL_PLACE_NAME_SOURCES


def should_apply_fe_place_fix(source_type: str) -> bool:
    """国外数据源优先使用 fe_fix_region_data.json 按经纬度修正地名。"""
    st = _normalize_source_type(source_type)
    if not st:
        return False
    if st in KEEP_ORIGINAL_PLACE_NAME_SOURCES or st in _FE_PLACE_FIX_EXCLUDED:
        return False
    return True


def place_name_has_chinese(text: str) -> bool:
    """判断地名是否包含汉字。"""
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def place_name_has_foreign(text: str) -> bool:
    """含日韩文、拉丁字母等非纯中文内容。"""
    if not text:
        return False
    return bool(
        re.search(r"[가-힣ぁ-ゖァ-ヺー]", text)
        or re.search(r"[a-zA-Z]", text)
    )


def should_translate_place_name(source_type: str, place_name: str) -> bool:
    """非保留原文源且地名含外语时，启用百度翻译模式下应翻译。"""
    if not place_name or place_name == "未知地点":
        return False
    if should_keep_original_place_name(source_type):
        return False
    if place_name_has_chinese(place_name) and not place_name_has_foreign(place_name):
        return False
    return True


def should_apply_place_name_fix(config: Any) -> bool:
    """是否启用地名修正（与百度翻译互斥：开启翻译时不走修正）。"""
    tc = getattr(config, "translation_config", config)
    enabled = bool(getattr(tc, "enabled", False))
    use_fix = bool(getattr(tc, "use_place_name_fix", True))
    return use_fix and not enabled  # 与百度翻译互斥
