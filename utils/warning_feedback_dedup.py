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


def event_key(parsed_data: Dict[str, Any]) -> str:
    """生成事件去重键：优先 event_id，否则用地名+发震时间+源类型拼接。"""
    event_id = str(parsed_data.get("event_id") or parsed_data.get("id") or "").strip()
    if event_id:
        return event_id
    return "|".join(
        [
            str(parsed_data.get("source_type") or ""),
            str(parsed_data.get("place_name") or ""),
            str(parsed_data.get("shock_time") or ""),
        ]
    )


def _warning_updates_value(data: Dict[str, Any]) -> Optional[int]:
    """提取预警报数（updates）；SA 源无报数字段时视为第 1 报。"""
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
        "final": bool(parsed_data.get("final", False)),
    }


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


def should_play_warning_feedback(parsed_data: Dict[str, Any], tier: str) -> bool:
    """
    预警：首报、更新报、震级/档位变化即播放；同源重复报文跳过。
    多数据源报道同一物理事件时，预设音频/TTS 只响一遍。
    """
    if tier not in ("felt", "critical", "nhk"):
        return False

    key = event_key(parsed_data)
    try:
        mag = float(parsed_data.get("magnitude") or 0.0)
    except (TypeError, ValueError):
        mag = 0.0

    now = time.time()
    with _state_lock:
        prev = _last_by_event.get(key)
        record = _state_record(parsed_data, mag, tier, now)

        should_play = False
        if prev is None:  # 该 event_key 首次收到
            should_play = True
        elif _is_warning_update_report(parsed_data, prev, tier):  # 预警更新报或最终报
            should_play = True
        else:
            prev_tier = str(prev.get("tier") or "")
            prev_mag = float(prev.get("mag") or 0.0)
            if prev_tier and prev_tier != tier:
                should_play = True
            elif abs(prev_mag - mag) >= 0.5:
                should_play = True

        if should_play and prev is None:  # 首报时做跨源物理去重
            if _find_physical_duplicate(parsed_data) is not None:  # 其他源已响过同一震次
                _last_by_event[key] = record
                return False
            if _find_burst_duplicate(mag, now):  # 短时突发合并窗口内已响
                _last_by_event[key] = record
                return False

        if should_play:
            _last_by_event[key] = record
            _record_physical_play(parsed_data, tier, now)
            return True

        return False


def register_warning_feedback_seen(
    parsed_data: Dict[str, Any],
    tier: str,
) -> None:
    """跳过播放但仍写入去重状态（启动同步等）。"""
    if tier not in ("felt", "critical"):
        return
    try:
        mag = float(parsed_data.get("magnitude") or 0.0)
    except (TypeError, ValueError):
        mag = 0.0
    key = event_key(parsed_data)
    with _state_lock:
        _last_by_event[key] = _state_record(parsed_data, mag, tier, time.time())
        _record_physical_play(parsed_data, tier, time.time())
