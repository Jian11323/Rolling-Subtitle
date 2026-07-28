#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JMA EEW 特殊手法识别：PLUM / Level / IPF单点 / 深発。

与 fused_eew_api_v2 口径对齐；PLUM 以 isAssumption 为准（勿单靠电文 aa=36，
早期 IPF 单点报也可能以 36 开头）。
"""

from __future__ import annotations

import re
from typing import Any, Dict

_ACC_WS_RE = re.compile(r"\s+")


def normalize_acc_text(text: Any) -> str:
    """去掉 Accuracy 文案中的空白，便于稳定匹配。"""
    return _ACC_WS_RE.sub("", str(text or ""))


def telegram_aa(original_text: Any) -> str:
    """从 OriginalText 取电文种类代码 aa（如 35/36/37）。"""
    s = str(original_text or "").strip()
    if len(s) >= 2 and s[:2].isdigit():
        return s[:2]
    return ""


def intensity_valid(value: Any) -> bool:
    """预估震度是否有效（非空/不明/占位）。"""
    s = str(value or "").strip()
    if not s:
        return False
    return s not in ("0", "不明", "/", "//", "None", "null", "-")


def classify_jma_eew_special(data: Dict[str, Any]) -> Dict[str, Any]:
    """识别 PLUM / Level / IPF单点 / 深発。

    优先级（防误报）：PLUM > Level > IPF单点 > 深発。
    Accuracy「レベル超え／IPF 1点／仮定震源」文案在多类报中共用，
    不以 Accuracy 单独判定 Level/PLUM。
    """
    is_assumption = bool(data.get("isAssumption", False))
    original = data.get("OriginalText") or data.get("originalText") or ""
    title = str(data.get("Title") or data.get("title") or "")
    code_type = str(data.get("CodeType") or data.get("codeType") or "")
    aa = telegram_aa(original)

    acc = data.get("Accuracy") if isinstance(data.get("Accuracy"), dict) else {}
    acc_epi = normalize_acc_text(
        data.get("accuracyEpicenter")
        or (acc.get("Epicenter") if isinstance(acc, dict) else "")
        or (acc.get("epicenter") if isinstance(acc, dict) else "")
        or ""
    )

    # PLUM：推定震源（M1.0/深10km 为假设值）；电文 36 仅为辅助，须配合 isAssumption
    is_plum = is_assumption

    # Level：电文种类 35，或标题/说明标明「最大予測震度のみ」
    is_level = (not is_plum) and (
        aa == "35"
        or "最大予測震度のみ" in title
        or "最大予測震度のみ" in code_type
    )

    # IPF 单点：Accuracy 明确写 IPF 1点，且已排除 PLUM/Level
    is_ipf1 = (not is_plum) and (not is_level) and (
        "IPF法（1点）" in acc_epi or "IPF法(1点)" in acc_epi
    )

    depth_raw = data.get("Depth")
    if depth_raw is None:
        depth_raw = data.get("depth", 0)
    try:
        depth_val = int(round(float(depth_raw or 0), 0))
    except (TypeError, ValueError):
        depth_val = 0
    # 深発：震源深度 > 150km（气象厅：150km より深く）
    is_deep = depth_val > 150

    method = ""
    if is_plum:
        method = "PLUM"
    elif is_level:
        method = "Level"
    elif is_ipf1:
        method = "IPF"
    elif is_deep:
        method = "深発"

    return {
        "method": method,
        "is_plum": is_plum,
        "is_level": is_level,
        "is_ipf1": is_ipf1,
        "is_deep": is_deep,
    }
