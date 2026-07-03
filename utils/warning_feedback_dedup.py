#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预警音 / TTS 播放去重（多数据源同 event_id 或同一物理事件重复报文）。"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from utils.event_dedup import find_duplicate_index

# 全局去重状态锁，保护 _last_by_event 与 _recent_physical
_state_lock = threading.Lock()
# 按 event_key 记录最近一次播放状态（震级、档位、报数等）
_last_by_event: Dict[str, Dict[str, Any]] = {}
# 已播放反馈的物理事件快照（跨数据源：时间+位置+震级）
_recent_physical: List[Dict[str, Any]] = []
_MAX_RECENT_PHYSICAL = 64  # 物理事件快照环形缓冲上限
_PHYSICAL_DEDUP_SEC = 120.0  # 跨源物理去重时间窗口（秒）
# 多源同时首报（event_id/文案不同）的短时合并窗口
_BURST_WINDOW_SEC = 3.0
_MAG_TOLERANCE = 0.5  # 突发合并时震级容差

POLICY_SMART = "smart"
POLICY_FIRST_RECEIVED = "first_received"


def normalize_warning_feedback_policy(policy: Optional[str]) -> str:
    """归一化预警反馈策略名。"""
    p = (policy or POLICY_FIRST_RECEIVED).strip().lower()
    if p in ("first_report_only", "first_only", "first_received"):
        return POLICY_FIRST_RECEIVED
    if p == POLICY_SMART:
        return POLICY_SMART
    return POLICY_FIRST_RECEIVED


def normalize_event_id(event_id: str) -> str:
    """
    归一化 event_id，合并多源同一震次的不同写法。
    例：Wolfx 四川 ``202606290012.0001_1`` 与 CEA ``202606290012.0001`` 视为同一键。
    """
    eid = str(event_id or "").strip()
    if not eid or "_" not in eid:
        return eid
    base, suffix = eid.rsplit("_", 1)
    if suffix.isdigit() and "." in base:
        return base
    return eid


def event_key(parsed_data: Dict[str, Any]) -> str:
    """生成事件去重键：优先归一化 event_id，否则用地名+发震时间（跨源一致）。"""
    raw_id = str(parsed_data.get("event_id") or parsed_data.get("id") or "").strip()
    event_id = normalize_event_id(raw_id)
    if event_id:
        return event_id
    place = str(parsed_data.get("place_name") or "").strip()
    shock = str(parsed_data.get("shock_time") or "").strip()
    if place and shock:
        return f"pt|{place}|{shock}"
    if place:
        return f"pn|{place}"
    return ""


def _warning_updates_value(data: Dict[str, Any]) -> Optional[int]:
    """提取数据源原始预警报数（updates）；仅作记录，first_received 策略不据此决定是否播放。"""
    updates = data.get("updates")
    if updates is not None:
        try:
            updates = int(updates)
            if updates <= 0:
                updates = None
        except (TypeError, ValueError):
            updates = None
    source_type = (data.get("source_type") or "").strip()
    if updates is None and source_type == "sa":
        updates = 1
    if not updates or updates <= 0:
        return None
    return updates


def _state_record(
    parsed_data: Dict[str, Any],
    mag: float,
    tier: str,
    now: float,
) -> Dict[str, Any]:
    """构建写入 _last_by_event 的状态快照。"""
    return {
        "time": now,
        "mag": mag,
        "tier": tier,
        "updates": _warning_updates_value(parsed_data),
        "source_updates": _warning_updates_value(parsed_data),
        "internal_seq": 0,
        "played_feedback": False,
        "final": bool(parsed_data.get("final", False)),
    }


def _is_duplicate_warning_snapshot(
    parsed_data: Dict[str, Any],
    prev: Dict[str, Any],
    tier: str,
    mag: float,
) -> bool:
    """同源重复报文：档位、震级、源报数、最终报标志均未变。"""
    if str(prev.get("tier") or "") != tier:
        return False
    if abs(float(prev.get("mag") or 0.0) - mag) >= 0.01:
        return False
    if _warning_updates_value(parsed_data) != prev.get("source_updates"):
        return False
    if bool(parsed_data.get("final", False)) != bool(prev.get("final", False)):
        return False
    return True


def _is_warning_update_report(
    parsed_data: Dict[str, Any],
    prev: Optional[Dict[str, Any]],
    tier: str,
) -> bool:
    """同一事件的预警更新报（报数增加或出现最终报）。"""
    if tier not in ("felt", "critical", "nhk") or prev is None:
        return False
    is_final = bool(parsed_data.get("final", False))
    if is_final and not bool(prev.get("final", False)):
        return True
    current = _warning_updates_value(parsed_data)
    if current is None or current <= 1:
        return False
    prev_updates = prev.get("updates")
    if prev_updates is not None:
        try:
            prev_updates = int(prev_updates)
        except (TypeError, ValueError):
            prev_updates = None
    if prev_updates is not None:
        return current > prev_updates
    return True


def _place_time_key(parsed_data: Dict[str, Any]) -> str:
    """地名+发震时间的组合键，用于跨源物理去重。"""
    place = str(parsed_data.get("place_name") or "").strip()
    shock = str(parsed_data.get("shock_time") or "").strip()
    if not place or not shock:
        return ""
    return f"{place}|{shock}"


def _find_physical_duplicate(parsed_data: Dict[str, Any]) -> Optional[int]:
    """跨数据源：同一震次（坐标/时间/震级相近，或地名+发震时间一致）。"""
    idx = find_duplicate_index(parsed_data, _recent_physical)
    if idx is not None:
        return idx
    pt_key = _place_time_key(parsed_data)
    if not pt_key:
        return None
    now = time.time()
    for i in range(len(_recent_physical) - 1, -1, -1):
        item = _recent_physical[i]
        other = item.get("parsed_data") or {}
        if _place_time_key(other) != pt_key:
            continue
        recv = float(item.get("received_at_ts") or 0)
        if recv and (now - recv) <= _PHYSICAL_DEDUP_SEC:
            return i
    return None


def _snapshot_for_physical(parsed_data: Dict[str, Any]) -> Dict[str, Any]:
    """提取物理去重所需的核心字段子集。"""
    return {
        k: parsed_data.get(k)
        for k in (
            "latitude", "longitude", "magnitude", "shock_time",
            "place_name", "event_id", "source_type",
        )
    }


def _record_physical_play(parsed_data: Dict[str, Any], tier: str, now: float) -> None:
    """记录已播放的物理事件快照，超出上限时丢弃最旧条目。"""
    _recent_physical.append({
        "parsed_data": _snapshot_for_physical(parsed_data),
        "received_at_ts": now,
        "tier": tier,
    })
    while len(_recent_physical) > _MAX_RECENT_PHYSICAL:
        _recent_physical.pop(0)


def _find_burst_duplicate(mag: float, now: float) -> bool:
    """短时窗口内震级相近的重复首报视为同一突发，只响一次。"""
    for item in reversed(_recent_physical):
        recv = float(item.get("received_at_ts") or 0)
        if not recv or (now - recv) > _BURST_WINDOW_SEC:
            break
        other = item.get("parsed_data") or {}
        try:
            omag = float(other.get("magnitude") or 0)
        except (TypeError, ValueError):
            omag = 0.0
        if mag > 0 and omag > 0 and abs(mag - omag) > _MAG_TOLERANCE:
            continue
        return True
    return False


def _apply_physical_dedup(
    parsed_data: Dict[str, Any],
    record: Dict[str, Any],
    key: str,
    prev: Optional[Dict[str, Any]],
    mag: float,
    now: float,
) -> bool:
    """
    跨源物理 / 突发去重（仅 event_key 首条时生效）。
    同一 event_key 的更新报不再做物理拦截，避免 smart 策略下修订报被误杀。
    """
    if prev is not None:
        return True
    if _find_physical_duplicate(parsed_data) is not None:
        _last_by_event[key] = record
        return False
    if _find_burst_duplicate(mag, now):
        _last_by_event[key] = record
        return False
    return True


def _should_play_first_received(
    parsed_data: Dict[str, Any],
    prev: Optional[Dict[str, Any]],
    record: Dict[str, Any],
    tier: str,
    mag: float,
) -> bool:
    """
    本程序视角的首报-only：不采用数据源原始报数。
    例：GQ 首条推送源报数 13 → 内部第 1 报，播放；源报数 14 → 内部第 2 报，不播。
    """
    source_updates = _warning_updates_value(parsed_data)
    record["source_updates"] = source_updates

    if prev is not None and _is_duplicate_warning_snapshot(parsed_data, prev, tier, mag):
        return False

    if prev is None:
        internal_seq = 1
    else:
        internal_seq = int(prev.get("internal_seq") or 0) + 1

    record["internal_seq"] = internal_seq
    record["played_feedback"] = bool(prev.get("played_feedback")) if prev else False

    if record["played_feedback"]:
        return False

    if internal_seq == 1:
        record["played_feedback"] = True
        return True

    return False


def _should_play_smart(
    parsed_data: Dict[str, Any],
    prev: Optional[Dict[str, Any]],
    tier: str,
    mag: float,
) -> bool:
    """原 smart 策略：首报、更新报、震级/档位变化可再播。"""
    if prev is None:
        return True
    if _is_warning_update_report(parsed_data, prev, tier):
        return True
    prev_tier = str(prev.get("tier") or "")
    prev_mag = float(prev.get("mag") or 0.0)
    if prev_tier and prev_tier != tier:
        return True
    if abs(prev_mag - mag) >= 0.5:
        return True
    return False


def should_play_warning_feedback(
    parsed_data: Dict[str, Any],
    tier: str,
    *,
    policy: Optional[str] = None,
) -> bool:
    """
    预警：是否播放主反馈（sound / TTS）。

    ``first_received``（默认）：本程序收到的第一条有效报文视为内部第 1 报并播放，
    后续报文（无论数据源报数为 2 还是 14）均不再播放。

    ``smart``：首报、更新报、震级/档位变化即播放；同源重复报文跳过。
    多数据源报道同一物理事件时，预设音频/TTS 只响一遍。
    """
    if tier not in ("felt", "critical", "nhk"):
        return False

    policy_key = normalize_warning_feedback_policy(policy)
    key = event_key(parsed_data)
    try:
        mag = float(parsed_data.get("magnitude") or 0.0)
    except (TypeError, ValueError):
        mag = 0.0

    now = time.time()
    with _state_lock:
        prev = _last_by_event.get(key)
        record = _state_record(parsed_data, mag, tier, now)

        if policy_key == POLICY_FIRST_RECEIVED:
            if prev is not None and _is_duplicate_warning_snapshot(
                parsed_data, prev, tier, mag
            ):
                return False
            should_play = _should_play_first_received(
                parsed_data, prev, record, tier, mag
            )
        else:
            should_play = _should_play_smart(parsed_data, prev, tier, mag)

        if should_play:
            if not _apply_physical_dedup(parsed_data, record, key, prev, mag, now):
                return False
            _last_by_event[key] = record
            _record_physical_play(parsed_data, tier, now)
            return True

        if policy_key == POLICY_FIRST_RECEIVED and prev is not None:
            if not _is_duplicate_warning_snapshot(parsed_data, prev, tier, mag):
                _last_by_event[key] = record

        return False


def is_startup_sync_message(parsed_data: Dict[str, Any]) -> bool:
    """启动批量同步历史报文：仅展示字幕，不播放告警音/TTS。"""
    return bool((parsed_data or {}).get("_suppress_tts"))


def register_warning_feedback_seen(
    parsed_data: Dict[str, Any],
    tier: str,
    *,
    policy: Optional[str] = None,
) -> None:
    """跳过播放但仍写入去重状态（启动同步等）。"""
    if tier not in ("felt", "critical", "nhk"):
        return
    policy_key = normalize_warning_feedback_policy(policy)
    try:
        mag = float(parsed_data.get("magnitude") or 0.0)
    except (TypeError, ValueError):
        mag = 0.0

    if policy_key == POLICY_FIRST_RECEIVED:
        # 启动同步不写入任何状态，避免占用内部第 1 报或物理去重槽位
        return

    key = event_key(parsed_data)
    with _state_lock:
        _last_by_event[key] = _state_record(parsed_data, mag, tier, time.time())
        _record_physical_play(parsed_data, tier, time.time())
