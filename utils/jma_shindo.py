#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日本气象厅震度（情报震度）解析与比较。"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

# 震度等级序：0 … 4 < 5弱 < 5強 < 6弱 < 6強 < 7
_SHINDO_RANK: Dict[str, int] = {
    "0": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5弱": 5,
    "5強": 6,
    "5-": 5,
    "5+": 6,
    "6弱": 7,
    "6強": 8,
    "6-": 7,
    "6+": 8,
    "7": 9,
    "over": 10,
    "7超": 10,
}

_NHK_BELL_THRESHOLD_RANK = _SHINDO_RANK["6弱"]

# NHK 一级新闻铃仅适用于 P2PQuake 地震情报（code 551），不含地震预警
NHK_BELL_SOURCE_TYPES = frozenset({"p2pquake"})
JMA_EEW_SOURCE_TYPES = frozenset({"jma", "wolfx_jma_eew"})

_JMA_EEW_ALERT_TOKENS = frozenset({"警報", "警报"})
_JMA_EEW_FORECAST_TOKENS = frozenset({"予報", "预报"})
_JMA_EEW_TITLE_TYPE_RE = re.compile(r"[（(](警報|警报|予報|预报)[）)]")

# P2PQuake scale 合法取值；-1 表示无震度
_P2P_VALID_SCALE_CODES = frozenset({-1, 0, 10, 20, 30, 40, 45, 46, 50, 55, 60, 70})

_SHINDO_TEXT_RE = re.compile(
    r"^(?P<num>[0-7])\s*(?P<qual>弱|強|[-+]|超)?$",
    re.IGNORECASE,
)


def p2pquake_scale_to_decimal(value: Any) -> Optional[float]:
    """
    P2PQuake maxScale / points.scale → 计测震度小数。

    整数震度 1–4：scale = 震度 × 10（10→1.0, 40→4.0）。
    半级震度：scale = 计测值 × 10
      4.5–4.9 → 45, 5.0–5.4 → 50, 5.5–5.9 → 55, 6.0–6.4 → 60, 7.0 → 70。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        code = int(float(value))
    except (TypeError, ValueError):
        return None
    if code == -1:
        return None
    if code not in _P2P_VALID_SCALE_CODES:
        return None
    return code / 10.0


def instrumental_shindo_to_rank(decimal: float) -> Optional[int]:
    """
    计测震度小数 → 可比较等级。

    区间：4.5–4.9→5弱, 5.0–5.4→5強, 5.5–5.9→6弱, 6.0–6.4→6強, ≥6.5→7。
    """
    try:
        d = float(decimal)
    except (TypeError, ValueError):
        return None
    if d < 0:
        return None
    if d < 4.5:
        if d == int(d) and 0 <= d <= 4:
            return int(d)
        return None
    if d < 5.0:
        return 5
    if d < 5.5:
        return 6
    if d < 6.0:
        return 7
    if d < 6.5:
        return 8
    return 9


def p2pquake_scale_rank(value: Any) -> Optional[int]:
    """P2PQuake scale 编码 → 震度等级。"""
    dec = p2pquake_scale_to_decimal(value)
    if dec is None:
        return None
    return instrumental_shindo_to_rank(dec)


def shindo_rank(value: Any) -> Optional[int]:
    """将震度原始值转为可比较的整数等级；无法识别时返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        if f == int(f):
            p2p = p2pquake_scale_rank(int(f))
            if p2p is not None:
                return p2p
        if 0 <= f <= 4 and f == int(f):
            return int(f)
        if f >= 4.5:
            return instrumental_shindo_to_rank(f)
        return None

    text = str(value).strip()
    if not text:
        return None
    text = text.replace("震度", "").replace("度", "").strip()
    text = text.replace("－", "-").replace("−", "-").replace("＋", "+")
    text = text.replace("OVER", "over").replace("Over", "over")

    if text in _SHINDO_RANK:
        return _SHINDO_RANK[text]

    m = _SHINDO_TEXT_RE.match(text)
    if not m:
        return None
    num = m.group("num")
    qual = (m.group("qual") or "").strip()
    if not qual:
        return _SHINDO_RANK.get(num)
    if qual in ("弱", "-"):
        key = f"{num}弱" if qual == "弱" else f"{num}-"
        return _SHINDO_RANK.get(key)
    if qual in ("強", "+", "超"):
        if qual == "超":
            return _SHINDO_RANK.get("7超")
        key = f"{num}強" if qual == "強" else f"{num}+"
        return _SHINDO_RANK.get(key)
    return None


def _iter_shindo_candidates(parsed_data: Dict[str, Any]) -> Iterable[Any]:
    """从解析结果及 raw 中收集可能含震度的字段值。"""
    pd = parsed_data or {}
    st = (pd.get("source_type") or "").strip().lower()

    if st == "p2pquake":
        if "max_scale" in pd:
            yield pd.get("max_scale")
        for pt in pd.get("points") or []:
            if isinstance(pt, dict) and "scale" in pt:
                yield pt.get("scale")
        raw = pd.get("raw_data")
        if isinstance(raw, dict):
            eq = raw.get("earthquake")
            if isinstance(eq, dict) and "maxScale" in eq:
                yield eq.get("maxScale")
            for pt in raw.get("points") or []:
                if isinstance(pt, dict) and "scale" in pt:
                    yield pt.get("scale")
        return

    for key in ("epiIntensity", "epi_intensity", "intensity", "maxIntensity", "MaxIntensity"):
        if key in pd:
            yield pd.get(key)

    raw = pd.get("raw_data")
    if isinstance(raw, dict):
        for key in ("epiIntensity", "epi_intensity", "intensity", "maxIntensity", "MaxIntensity"):
            if key in raw:
                yield raw.get(key)
        wa = raw.get("WarnArea")
        items = wa if isinstance(wa, list) else ([wa] if isinstance(wa, dict) else [])
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("Shindo1", "Shindo2", "shindo1", "shindo2"):
                if key in item:
                    yield item.get(key)

    for row in pd.get("wolfx_warn_areas") or []:
        if not isinstance(row, dict):
            continue
        for key in ("shindo1", "shindo2"):
            if key in row:
                yield row.get(key)


def max_jma_shindo_rank(parsed_data: Dict[str, Any]) -> Optional[int]:
    """取报文中出现的最高震度等级。"""
    best: Optional[int] = None
    for value in _iter_shindo_candidates(parsed_data):
        rank = shindo_rank(value)
        if rank is None:
            continue
        if best is None or rank > best:
            best = rank
    return best


def jma_shindo_meets_nhk_bell_threshold(parsed_data: Dict[str, Any]) -> bool:
    """情报震度是否达到 6弱 及以上（含 6強、7）。"""
    rank = max_jma_shindo_rank(parsed_data)
    return rank is not None and rank >= _NHK_BELL_THRESHOLD_RANK


def _normalize_jma_eew_warn_token(value: Any) -> str:
    """将发报类型规范为「予報」或「警報」；无法识别时返回空串。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if text in _JMA_EEW_ALERT_TOKENS or "警報" in text or "警报" in text:
        return "警報"
    if text in _JMA_EEW_FORECAST_TOKENS or "予報" in text or "预报" in text:
        return "予報"
    return ""


def jma_eew_warn_type(parsed_data: Dict[str, Any]) -> str:
    """JMA 緊急地震速報 当前发报类型：予報 / 警報 / 空。"""
    pd = parsed_data or {}
    st = (pd.get("source_type") or "").strip().lower()
    if st not in JMA_EEW_SOURCE_TYPES:
        return ""

    for key in ("warn_area_type", "info_type"):
        normalized = _normalize_jma_eew_warn_token(pd.get(key))
        if normalized:
            return normalized

    raw = pd.get("raw_data")
    if isinstance(raw, dict):
        if raw.get("isWarn") is True:
            return "警報"
        if raw.get("isWarn") is False:
            return "予報"
        for title_key in ("Title", "title"):
            m = _JMA_EEW_TITLE_TYPE_RE.search(str(raw.get(title_key) or ""))
            if m:
                return _normalize_jma_eew_warn_token(m.group(1))
        normalized = _normalize_jma_eew_warn_token(raw.get("infoTypeName"))
        if normalized:
            return normalized
        warn_area = raw.get("WarnArea")
        items = warn_area if isinstance(warn_area, list) else ([warn_area] if isinstance(warn_area, dict) else [])
        saw_forecast = False
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_jma_eew_warn_token(item.get("Type") or item.get("type"))
            if normalized == "警報":
                return "警報"
            if normalized == "予報":
                saw_forecast = True
        if saw_forecast:
            return "予報"
    return ""


def jma_eew_upgraded_to_alert(parsed_data: Dict[str, Any], previous_type: str) -> bool:
    """当前报文为警報，且此前同事件未处于警報状态（含由予報升级或首报即为警報）。"""
    current = jma_eew_warn_type(parsed_data)
    if current != "警報":
        return False
    prev = _normalize_jma_eew_warn_token(previous_type)
    return prev != "警報"
