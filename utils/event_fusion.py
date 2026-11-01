#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨源同事件融合：同一机构/产品通道族内，主源与 EQSC/Wolfx/P2P 等视为同一事件槽。

不做解析开关互斥覆盖；仅在字幕缓冲层合并，避免双报。
CENC 自动测定与正式测定视为不同条目，禁止互吞。
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 通道族：同组内可跨 source 判定为同一事件
EQSC_FUSION_CHANNEL_GROUPS: Tuple[frozenset, ...] = (
    frozenset({"jma", "eqsc_jma_eew", "wolfx_jma_eew"}),
    frozenset({"cea", "eqsc_cea"}),
    frozenset({"cea-pr", "cea_pr", "eqsc_cea_pr"}),
    frozenset({"cwa-eew", "cwa_eew", "eqsc_cwa_eew", "wolfx_cwa_eew"}),
    frozenset({"jma_eq", "eqsc_jma_report", "p2pquake", "wolfx_jma_eqlist"}),
    frozenset({"jma_tsunami", "eqsc_jma_tsunami", "p2pquake_tsunami"}),
    frozenset({"cenc", "eqsc_cenc", "wolfx_cenc"}),
    frozenset({"cenc-ir", "cenc_ir", "eqsc_cenc_ir"}),
    frozenset({"cwa", "eqsc_cwa"}),
    frozenset({"hko", "eqsc_hko"}),
    frozenset({"usgs", "eqsc_usgs"}),
    frozenset({"emsc", "eqsc_emsc"}),
    frozenset({"jian_typhoon", "eqsc_typhoon", "whews_typhoon"}),
    frozenset({"jma_volcano", "eqsc_volcano"}),
)

# 别名归一（WS path / 历史键）
_SOURCE_ALIASES: Dict[str, str] = {
    "cea_pr": "cea-pr",
    "cwa_eew": "cwa-eew",
    "cenc_ir": "cenc-ir",
}

_SOURCE_TO_GROUP: Dict[str, frozenset] = {}
for _g in EQSC_FUSION_CHANNEL_GROUPS:
    for _s in _g:
        _SOURCE_TO_GROUP[_s] = _g
        canon = _SOURCE_ALIASES.get(_s, _s)
        _SOURCE_TO_GROUP[canon] = _g

# 发震时间接近阈值（秒）
_SHOCK_TIME_TOLERANCE_SEC = 120.0
# 震中距离接近阈值（公里）
_EPICENTER_TOLERANCE_KM = 80.0
# 震级差上限
_MAG_TOLERANCE = 1.0

# CENC 通道族（自动/正式测定隔离）
_CENC_REPORT_SOURCES = frozenset({"cenc", "eqsc_cenc", "wolfx_cenc"})


def normalize_source_key(source: str) -> str:
    """统一 source 键（小写 + 别名）。"""
    key = str(source or "").strip().lower()
    return _SOURCE_ALIASES.get(key, key)


def fusion_group_for_source(source: str) -> Optional[frozenset]:
    """返回 source 所属融合通道族；无则 None。"""
    key = normalize_source_key(source)
    return _SOURCE_TO_GROUP.get(key)


def sources_in_same_fusion_group(a: str, b: str) -> bool:
    """两数据源是否属于同一融合通道族。"""
    if not a or not b:
        return False
    na, nb = normalize_source_key(a), normalize_source_key(b)
    if na == nb:
        return True
    ga = fusion_group_for_source(na)
    gb = fusion_group_for_source(nb)
    return ga is not None and ga is gb


def _cenc_measure_kind(info_type: Any, event_id: str = "") -> str:
    """
    CENC 测定类型：official / auto / unknown。
    优先 info_type 文案；其次 event_id 后缀 _A / _M。
    """
    s = str(info_type or "").strip()
    if "正式" in s:
        return "official"
    if "自动" in s:
        return "auto"
    eid = str(event_id or "").strip().upper()
    if eid.endswith("_M") or eid.endswith("-M") or ".M" in eid[-4:]:
        return "official"
    if eid.endswith("_A") or eid.endswith("-A") or ".A" in eid[-4:]:
        return "auto"
    # 常见基座后接 A/M
    m = re.search(r"([_\-.])([AM])$", eid)
    if m:
        return "official" if m.group(2) == "M" else "auto"
    return "unknown"


def cenc_measure_kind_from_parsed(
    source: str,
    event_id: str,
    parsed: Optional[Dict[str, Any]],
) -> str:
    """从 source + parsed 推断 CENC 测定类型。"""
    src = normalize_source_key(source)
    if src not in _CENC_REPORT_SOURCES:
        return ""
    info = None
    if isinstance(parsed, dict):
        info = parsed.get("info_type") or parsed.get("infoTypeName") or parsed.get("type")
        # EQSC reviewed/automatic
        t = str(parsed.get("type") or "").strip().lower()
        if t == "reviewed":
            return "official"
        if t == "automatic":
            return "auto"
    return _cenc_measure_kind(info, event_id)


def cenc_measures_conflict(
    source_a: str,
    event_id_a: str,
    parsed_a: Optional[Dict[str, Any]],
    source_b: str,
    event_id_b: str,
    parsed_b: Optional[Dict[str, Any]],
) -> bool:
    """两端均为 CENC 族且一端正式一端自动时，禁止融合。"""
    ka = cenc_measure_kind_from_parsed(source_a, event_id_a, parsed_a)
    kb = cenc_measure_kind_from_parsed(source_b, event_id_b, parsed_b)
    if not ka or not kb:
        return False
    if ka == "unknown" or kb == "unknown":
        return False
    return ka != kb


def normalize_fusion_event_id(event_id: str) -> str:
    """规范化 event_id 便于跨源比较（保留测定后缀语义由上层隔离）。"""
    s = str(event_id or "").strip()
    if not s:
        return ""
    s = re.sub(r"^(eqsc_|wolfx_|jian_)+", "", s, flags=re.I)
    return s.strip()


def event_ids_match_for_fusion(a: str, b: str) -> bool:
    """跨源 event_id 是否视为同一事件（不做自动/正式互吞）。"""
    na = normalize_fusion_event_id(a)
    nb = normalize_fusion_event_id(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # 去掉测定后缀后比较基座
    def _base(x: str) -> str:
        return re.sub(r"[_\-.][AMam]$", "", x)

    ba, bb = _base(na), _base(nb)
    if ba and bb and ba == bb and len(ba) >= 6:
        # 基座相同但后缀不同（A vs M）→ 不视为同 id 命中（由测定隔离处理）
        if _cenc_measure_kind("", na) != _cenc_measure_kind("", nb):
            if _cenc_measure_kind("", na) != "unknown" and _cenc_measure_kind("", nb) != "unknown":
                return False
        return True
    # 谨慎子串：仅当一侧为另一侧真前缀且长度足够，且测定后缀不冲突
    if len(na) >= 8 and len(nb) >= 8:
        if na.startswith(nb) or nb.startswith(na):
            if cenc_measures_conflict("cenc", na, None, "cenc", nb, None):
                return False
            return True
    return False


def _parse_shock_epoch(shock_time: Any) -> Optional[float]:
    """发震时间转 Unix 秒；失败返回 None。"""
    if shock_time is None:
        return None
    if isinstance(shock_time, (int, float)):
        v = float(shock_time)
        if v > 1e12:
            v /= 1000.0
        return v if v > 0 else None
    s = str(shock_time).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return _parse_shock_epoch(float(s))
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y年%m月%d日 %H:%M:%S",
        "%Y年%m月%d日%H时%M分%S秒",
        "%Y年%m月%d日%H时%M分",
    ):
        try:
            return datetime.strptime(s[:19] if "T" in s and len(s) >= 19 else s, fmt).timestamp()
        except Exception:
            continue
    try:
        base = s.split(".")[0].replace("T", " ")
        return datetime.strptime(base[:19], "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:
        return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点大圆距离（公里）。"""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _coords_from_parsed(parsed: Optional[Dict[str, Any]]) -> Optional[Tuple[float, float]]:
    """从 parsed_data 取经纬度。"""
    if not isinstance(parsed, dict):
        return None
    lat = parsed.get("latitude", parsed.get("lat"))
    lon = parsed.get("longitude", parsed.get("lon", parsed.get("lng")))
    try:
        if lat is None or lon is None:
            return None
        la, lo = float(lat), float(lon)
        if abs(la) > 90 or abs(lo) > 180:
            return None
        if la == 0.0 and lo == 0.0:
            return None
        return la, lo
    except (TypeError, ValueError):
        return None


def _mag_from_parsed(parsed: Optional[Dict[str, Any]]) -> Optional[float]:
    """从 parsed_data 取震级。"""
    if not isinstance(parsed, dict):
        return None
    for key in ("magnitude", "mag", "Magnitude", "Magunitude"):
        if key in parsed and parsed.get(key) not in (None, ""):
            try:
                return float(parsed.get(key))
            except (TypeError, ValueError):
                continue
    return None


def _shock_from_item(source: str, event_id: str, shock_time: Any, parsed: Optional[Dict[str, Any]]) -> Optional[float]:
    """综合 MessageItem 字段取发震时刻。"""
    ep = _parse_shock_epoch(shock_time)
    if ep is not None:
        return ep
    if isinstance(parsed, dict):
        for key in ("shock_time", "shockTime", "originTime", "origin_time", "time"):
            if key in parsed:
                ep = _parse_shock_epoch(parsed.get(key))
                if ep is not None:
                    return ep
    return None


def messages_are_same_fused_event(
    *,
    source_a: str,
    event_id_a: str,
    shock_time_a: Any,
    parsed_a: Optional[Dict[str, Any]],
    source_b: str,
    event_id_b: str,
    shock_time_b: Any,
    parsed_b: Optional[Dict[str, Any]],
) -> bool:
    """
    判断两条消息是否应融合为同一事件槽。

    同 source：仅比 event_id（由调用方处理无 id 回退）。
    跨 source：须同通道族，且 event_id 命中或（发震接近 + 震中/震级接近）。
    CENC 自动测定 vs 正式测定：永不融合。
    """
    sa = normalize_source_key(source_a)
    sb = normalize_source_key(source_b)
    if not sa or not sb:
        return False

    if cenc_measures_conflict(sa, event_id_a, parsed_a, sb, event_id_b, parsed_b):
        return False

    if sa == sb:
        if event_id_a and event_id_b:
            return event_ids_match_for_fusion(event_id_a, event_id_b)
        return False

    if not sources_in_same_fusion_group(sa, sb):
        return False

    if event_ids_match_for_fusion(event_id_a, event_id_b):
        return True

    ea = _shock_from_item(sa, event_id_a, shock_time_a, parsed_a)
    eb = _shock_from_item(sb, event_id_b, shock_time_b, parsed_b)
    if ea is None or eb is None:
        return False
    if abs(ea - eb) > _SHOCK_TIME_TOLERANCE_SEC:
        return False

    ca = _coords_from_parsed(parsed_a)
    cb = _coords_from_parsed(parsed_b)
    if ca and cb:
        if _haversine_km(ca[0], ca[1], cb[0], cb[1]) > _EPICENTER_TOLERANCE_KM:
            return False
    else:
        ma, mb = _mag_from_parsed(parsed_a), _mag_from_parsed(parsed_b)
        if ma is None or mb is None:
            return False
        if abs(ma - mb) > _MAG_TOLERANCE:
            return False
        return True

    ma, mb = _mag_from_parsed(parsed_a), _mag_from_parsed(parsed_b)
    if ma is not None and mb is not None and abs(ma - mb) > _MAG_TOLERANCE:
        return False
    return True


def prefer_message_for_fusion(a: Any, b: Any, get_rank) -> Any:
    """
    同事件两条消息择优。

    get_rank(source) -> 可比较元组，越小越优先（通常为 (priority, fixed_order_index)）。
    同级再比时间戳（更新者胜）。
    """
    ra = get_rank(getattr(a, "source", "") or "")
    rb = get_rank(getattr(b, "source", "") or "")
    if ra < rb:
        return a
    if rb < ra:
        return b
    ta = float(getattr(a, "timestamp", 0.0) or 0.0)
    tb = float(getattr(b, "timestamp", 0.0) or 0.0)
    return a if ta >= tb else b


def collapse_batch_by_fusion(messages: Sequence[Any], get_rank) -> List[Any]:
    """批量入队前：同融合事件只留排名更优（或更新）的一条。"""
    kept: List[Any] = []
    for msg in messages:
        merged = False
        for i, existing in enumerate(kept):
            same = False
            try:
                same = bool(msg.is_same_event(existing))
            except Exception:
                same = False
            if not same:
                continue
            kept[i] = prefer_message_for_fusion(existing, msg, get_rank)
            merged = True
            break
        if not merged:
            kept.append(msg)
    return kept


def all_fusion_sources() -> Tuple[str, ...]:
    """全部已登记融合源（冒烟/自检用）。"""
    out: List[str] = []
    seen = set()
    for g in EQSC_FUSION_CHANNEL_GROUPS:
        for s in sorted(g):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return tuple(out)
