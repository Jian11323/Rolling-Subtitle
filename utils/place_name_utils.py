#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地名本地化辅助：区分中文数据源、判断是否需要百度翻译。"""

from __future__ import annotations

import re
from typing import Any

# 数据源本身提供中文地名，无需修正或翻译
CHINESE_SOURCE_TYPES = frozenset({
    "cea", "cea-pr", "cwa-eew", "cwa", "cenc", "cenc-ir",
    "ningxia", "guangxi", "shanxi", "beijing", "yunnan", "hko",
    "wolfx_sc", "wolfx_fj", "wolfx_cenc", "wolfx_cwa", "wolfx_cq",
    "wolfx_sc_eew", "wolfx_cenc_eew",
    "nmefc", "nmefc-tsunami",
})


def _normalize_source_type(source_type: str) -> str:
    return (source_type or "").strip().lower()


def is_chinese_source(source_type: str) -> bool:
    return _normalize_source_type(source_type) in CHINESE_SOURCE_TYPES


def place_name_has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def place_name_has_foreign(text: str) -> bool:
    """含日韩文、拉丁字母等非纯中文内容。"""
    if not text:
        return False
    return bool(
        re.search(r"[가-힣ひらがなカタカナ]", text)
        or re.search(r"[a-zA-Z]", text)
    )


def should_translate_place_name(source_type: str, place_name: str) -> bool:
    """非中文数据源且地名含外语时，启用百度翻译模式下应翻译。"""
    if not place_name or place_name == "未知地点":
        return False
    if is_chinese_source(source_type):
        return False
    if place_name_has_chinese(place_name) and not place_name_has_foreign(place_name):
        return False
    return True


def should_apply_place_name_fix(config: Any) -> bool:
    tc = getattr(config, "translation_config", config)
    enabled = bool(getattr(tc, "enabled", False))
    use_fix = bool(getattr(tc, "use_place_name_fix", True))
    return use_fix and not enabled
