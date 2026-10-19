#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
告警音效：NHK 一级新闻铃、JMA 緊急地震速報「警報」提示音。
有感/强震内置 WAV（eewalert / eewcritical）已移除；通用预警反馈走 TTS。
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any, Dict, Optional

from utils.epi_intensity_estimate import effective_epi_for_alert
from utils.jma_shindo import (
    JMA_EEW_SOURCE_TYPES,
    NHK_BELL_SOURCE_TYPES,
    jma_eew_upgraded_to_alert,
    jma_eew_warn_type,
    jma_shindo_meets_nhk_bell_threshold,
)
from utils.logger import get_logger
from utils.warning_feedback_dedup import (
    event_key,
    is_startup_sync_message,
    should_play_warning_feedback,
)

logger = get_logger()

_play_lock = threading.Lock()


def _warning_feedback_policy(alert_config: Any) -> str:
    return getattr(alert_config, "warning_feedback_policy", "first_received") or "first_received"


# TTS 分级用：震级 ≥4.8 或报文烈度 ≥7 为 critical
_EEW_MAG_CRITICAL = 4.8
_EEW_INTENSITY_CRITICAL = 7.0

_DEFAULT_SOUND_FILES = {
    "nhk": "media/NHK一級ニュースベル.wav",
    "jma_eew_alert": "media/NHK緊急地震速報の音.wav",
}

_jma_eew_warn_state: Dict[str, str] = {}
_jma_eew_state_lock = threading.Lock()


def classify_eew_audio_tier(
    parsed_data: Optional[Dict[str, Any]],
    alert_config: Any,
) -> Optional[str]:
    """
    按震级与烈度判定 TTS 档位。
    返回 ``felt`` / ``critical`` / ``None``。
    """
    pd = parsed_data or {}
    try:
        magnitude = float(pd.get("magnitude") or 0.0)
    except (TypeError, ValueError):
        return None

    min_mag = float(getattr(alert_config, "min_magnitude", 3.0) or 0.0)
    if magnitude < min_mag:
        return None

    intensity = effective_epi_for_alert(pd)
    is_critical = magnitude >= _EEW_MAG_CRITICAL
    if intensity is not None and intensity >= _EEW_INTENSITY_CRITICAL:
        is_critical = True
    return "critical" if is_critical else "felt"


def resolve_sound_path(tier: str, alert_config: Any) -> Optional[str]:
    """用户自定义路径优先，否则使用内置 media 默认文件。"""
    tier = (tier or "").strip().lower()
    if tier == "nhk":
        custom = (getattr(alert_config, "nhk_news_bell_path", "") or "").strip()
        default_rel = _DEFAULT_SOUND_FILES["nhk"]
    elif tier == "jma_eew_alert":
        custom = (getattr(alert_config, "jma_eew_alert_sound_path", "") or "").strip()
        default_rel = _DEFAULT_SOUND_FILES["jma_eew_alert"]
    else:
        return None

    if custom and os.path.isfile(custom):
        return custom

    try:
        from utils.resource_path import get_resource_path

        default_path = get_resource_path(default_rel)
        if default_path.is_file():
            return str(default_path)
    except Exception:
        pass
    return None


def _sound_repeat_for_tier(tier: str, alert_config: Any) -> int:
    """读取指定档位的声音重复次数（1–10）。"""
    if tier == "nhk":
        repeat = getattr(alert_config, "nhk_news_bell_repeat", 1)
    elif tier == "jma_eew_alert":
        repeat = getattr(alert_config, "jma_eew_alert_sound_repeat", 2)
    else:
        return 1
    try:
        n = int(repeat)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(10, n))


def _tier_enabled(tier: str, alert_config: Any) -> bool:
    """检查指定档位的声音告警是否已启用。"""
    if tier == "nhk":
        return bool(getattr(alert_config, "nhk_news_bell_enabled", False))
    if tier == "jma_eew_alert":
        return bool(getattr(alert_config, "jma_eew_alert_sound_enabled", True))
    return False


def should_play_nhk_news_bell(
    parsed_data: Optional[Dict[str, Any]],
    alert_config: Any,
) -> bool:
    """P2PQuake 地震情报（非预警），且情报震度达到 6弱 及以上。"""
    if not bool(getattr(alert_config, "nhk_news_bell_enabled", False)):
        return False
    pd = parsed_data or {}
    if bool(pd.get("cancel")):
        return False
    if (pd.get("type") or "").strip().lower() not in ("", "report"):
        return False
    st = (pd.get("source_type") or "").strip().lower()
    if st not in NHK_BELL_SOURCE_TYPES:
        return False
    return jma_shindo_meets_nhk_bell_threshold(pd)


def _jma_eew_alert_upgrade_state(parsed_data: Dict[str, Any]) -> tuple[bool, str, str]:
    """读取是否应播放警報提示音，以及前后发报类型（不修改状态）。"""
    key = event_key(parsed_data)
    with _jma_eew_state_lock:
        prev = _jma_eew_warn_state.get(key, "")
    current = jma_eew_warn_type(parsed_data)
    upgraded = jma_eew_upgraded_to_alert(parsed_data, prev)
    return upgraded, prev, current


def _commit_jma_eew_warn_type(parsed_data: Dict[str, Any]) -> None:
    """播放后写入 JMA 緊急地震速報 发报类型。"""
    current = jma_eew_warn_type(parsed_data)
    if not current:
        return
    key = event_key(parsed_data)
    with _jma_eew_state_lock:
        _jma_eew_warn_state[key] = current


def should_play_jma_eew_alert_sound(
    parsed_data: Optional[Dict[str, Any]],
    alert_config: Any,
) -> bool:
    """JMA 緊急地震速報由予報升级为警報（或首报即为警報）时播放专用提示音。"""
    if not bool(getattr(alert_config, "jma_eew_alert_sound_enabled", True)):
        return False
    pd = parsed_data or {}
    if bool(pd.get("cancel")):
        return False
    msg_type = (pd.get("type") or "").strip().lower()
    if msg_type not in ("", "warning"):
        return False
    st = (pd.get("source_type") or "").strip().lower()
    if st not in JMA_EEW_SOURCE_TYPES:
        return False
    upgraded, _, _ = _jma_eew_alert_upgrade_state(pd)
    return upgraded


def _clamp_repeat(repeat: int) -> int:
    try:
        n = int(repeat)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(10, n))


def _play_mci(sound_path: str, repeat: int, mci_type: str) -> bool:
    """Windows MCI：每次 ``play from 0 wait`` 只播一遍，共 repeat 次。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        import uuid

        winmm = ctypes.windll.winmm
        alias = f"eqs_{uuid.uuid4().hex[:8]}"
        path = os.path.abspath(sound_path)
        open_cmd = f'open "{path}" type {mci_type} alias {alias}'
        if winmm.mciSendStringW(open_cmd, None, 0, 0):
            return False
        try:
            for _ in range(_clamp_repeat(repeat)):
                if winmm.mciSendStringW(f"play {alias} from 0 wait", None, 0, 0):
                    return False
            return True
        finally:
            winmm.mciSendStringW(f"close {alias}", None, 0, 0)
    except Exception:
        return False


def _play_file(sound_path: str, repeat: int) -> None:
    """按重复次数播放。禁止 Qt QSoundEffect：其 loopCount 在 Windows 上会变成无限循环。"""
    repeat = _clamp_repeat(repeat)
    if not sound_path or not os.path.isfile(sound_path):
        return

    ext = os.path.splitext(sound_path)[1].lower()
    if sys.platform == "win32" and ext == ".wav":
        played = 0
        try:
            import winsound

            # 不带 SND_ASYNC / SND_LOOP：同步播完一遍才返回
            flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
            for _ in range(repeat):
                winsound.PlaySound(sound_path, flags)
                played += 1
            return
        except Exception as e:
            logger.debug(f"winsound 播放失败: {e}")
        if played:
            return
        if _play_mci(sound_path, repeat, "waveaudio"):
            return

    if sys.platform == "win32" and ext == ".mp3":
        if _play_mci(sound_path, repeat, "mpegvideo"):
            return

    if sys.platform == "win32":
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass


def play_nhk_news_bell(
    config: Any,
    parsed_data: Optional[Dict[str, Any]] = None,
    *,
    force: bool = False,
) -> None:
    """在后台线程播放 NHK 一级新闻铃（P2PQuake 地震情报且震度 ≥6弱）。"""
    ac = getattr(config, "alert_config", None)
    if ac is None:
        return
    pd = parsed_data or {}
    if not force and not should_play_nhk_news_bell(pd, ac):
        return

    def _run() -> None:
        # 试听不排队：上一轮还在播时忽略新的点击，避免叠成不停地响
        if force:
            if not _play_lock.acquire(blocking=False):
                return
        else:
            _play_lock.acquire()
        try:
            if not force and not should_play_nhk_news_bell(pd, ac):
                return
            if not force and not _tier_enabled("nhk", ac):
                return
            if not force and not should_play_warning_feedback(
                pd, "nhk", policy=_warning_feedback_policy(ac)
            ):
                logger.debug(
                    "跳过重复 NHK 新闻铃: event_id=%s source_type=%s",
                    pd.get("event_id"),
                    pd.get("source_type"),
                )
                return
            sound_path = resolve_sound_path("nhk", ac)
            if not sound_path:
                return
            repeat = _sound_repeat_for_tier("nhk", ac)
            try:
                _play_file(sound_path, repeat)
            except Exception as e:
                logger.debug(f"播放 NHK 新闻铃失败: {e}")
        finally:
            _play_lock.release()

    threading.Thread(target=_run, daemon=True, name="NhkNewsBell").start()


def play_jma_eew_alert_sound(
    config: Any,
    parsed_data: Optional[Dict[str, Any]] = None,
    *,
    force: bool = False,
) -> None:
    """JMA 緊急地震速報：跟踪发报类型，升级为警報时播放专用提示音。"""
    ac = getattr(config, "alert_config", None)
    if ac is None:
        return
    pd = parsed_data or {}
    if not force:
        if is_startup_sync_message(pd):
            return
        if bool(pd.get("cancel")):
            return
        msg_type = (pd.get("type") or "").strip().lower()
        if msg_type not in ("", "warning"):
            return
        st = (pd.get("source_type") or "").strip().lower()
        if st not in JMA_EEW_SOURCE_TYPES:
            return

    def _run() -> None:
        if force:
            if not _play_lock.acquire(blocking=False):
                return
        else:
            _play_lock.acquire()
        try:
            upgraded, _, current = _jma_eew_alert_upgrade_state(pd)
            should_play = force or (
                upgraded
                and bool(getattr(ac, "jma_eew_alert_sound_enabled", True))
                and _tier_enabled("jma_eew_alert", ac)
            )
            if should_play:
                sound_path = resolve_sound_path("jma_eew_alert", ac)
                if sound_path:
                    repeat = _sound_repeat_for_tier("jma_eew_alert", ac)
                    try:
                        _play_file(sound_path, repeat)
                    except Exception as e:
                        logger.debug(f"播放 JMA 警報提示音失败: {e}")
            if current and not force:
                _commit_jma_eew_warn_type(pd)
        finally:
            _play_lock.release()

    threading.Thread(target=_run, daemon=True, name="JmaEewAlertSound").start()
