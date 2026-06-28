#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地震预警声音告警（有感 / 强震分级，仅 warning 类型）。"""

import os
import sys
import threading
import time
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
from utils.warning_feedback_dedup import event_key, should_play_warning_feedback

logger = get_logger()

_play_lock = threading.Lock()

# 强震判定阈值：震级 ≥4.8 或预估烈度 ≥7 为 critical 档
_EEW_MAG_CRITICAL = 4.8
_EEW_INTENSITY_CRITICAL = 7.0

# 内置默认告警音相对路径
_DEFAULT_SOUND_FILES = {
    "felt": "media/eewalert.wav",
    "critical": "media/eewcritical.wav",
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
    按震级 4.8 与预估烈度 7 判定音频档位。
    返回 ``felt`` / ``critical`` / ``None``（不满足最低震级时不播放）。
    """
    pd = parsed_data or {}
    try:
        magnitude = float(pd.get("magnitude") or 0.0)
    except (TypeError, ValueError):
        return None

    min_mag = float(getattr(alert_config, "min_magnitude", 3.0) or 0.0)
    if magnitude < min_mag:  # 未达最低震级门槛，不播放
        return None

    intensity = effective_epi_for_alert(pd)
    is_critical = magnitude >= _EEW_MAG_CRITICAL
    if intensity is not None and intensity >= _EEW_INTENSITY_CRITICAL:
        is_critical = True
    return "critical" if is_critical else "felt"


def resolve_sound_path(tier: str, alert_config: Any) -> Optional[str]:
    """用户自定义路径优先，否则使用内置 media 默认文件。"""
    tier = (tier or "").strip().lower()
    if tier == "felt":
        custom = (getattr(alert_config, "felt_sound_path", "") or "").strip()
        default_rel = _DEFAULT_SOUND_FILES["felt"]
    elif tier == "critical":
        custom = (getattr(alert_config, "critical_sound_path", "") or "").strip()
        default_rel = _DEFAULT_SOUND_FILES["critical"]
    elif tier == "nhk":
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
    if tier == "felt":
        repeat = getattr(alert_config, "felt_sound_repeat", 1)
    elif tier == "critical":
        repeat = getattr(alert_config, "critical_sound_repeat", 1)
    elif tier == "nhk":
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
    """检查指定档位（felt/critical）的声音告警是否已启用。"""
    if tier == "felt":
        return bool(getattr(alert_config, "felt_sound_enabled", False))
    if tier == "critical":
        return bool(getattr(alert_config, "critical_sound_enabled", False))
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


def _play_mp3_mci(sound_path: str, repeat: int) -> bool:
    """Windows MCI 播放 MP3（可在后台线程使用，不依赖 Qt 事件循环）。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        import uuid

        winmm = ctypes.windll.winmm
        alias = f"eqs_{uuid.uuid4().hex[:8]}"
        path = os.path.abspath(sound_path)
        open_cmd = f'open "{path}" type mpegvideo alias {alias}'
        if winmm.mciSendStringW(open_cmd, None, 0, 0):
            return False
        try:
            for _ in range(repeat):
                if winmm.mciSendStringW(f"play {alias} wait", None, 0, 0):
                    return False
            return True
        finally:
            winmm.mciSendStringW(f"close {alias}", None, 0, 0)
    except Exception:
        return False


def _play_with_qt_media(sound_path: str, repeat: int) -> bool:
    """Qt QMediaPlayer 播放（需已有 QApplication 并在循环中 processEvents）。"""
    try:
        from PyQt5.QtCore import QUrl
        from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False
        abs_path = os.path.abspath(sound_path)
        for _ in range(repeat):
            player = QMediaPlayer()
            player.setMedia(QMediaContent(QUrl.fromLocalFile(abs_path)))
            player.play()
            deadline = time.time() + 120
            while player.state() == QMediaPlayer.PlayingState and time.time() < deadline:
                app.processEvents()
                time.sleep(0.05)
            if player.error() != QMediaPlayer.NoError:
                return False
        return True
    except Exception:
        return False


def _play_file(sound_path: str, repeat: int) -> None:
    """播放音频文件；Windows 优先 winsound/MCI，否则尝试 Qt 多媒体或系统提示音。"""
    repeat = max(1, min(10, int(repeat or 1)))
    if not sound_path or not os.path.isfile(sound_path):  # 文件不存在则跳过
        return

    ext = os.path.splitext(sound_path)[1].lower()
    if sys.platform == "win32" and ext == ".wav":
        try:
            import winsound
            for _ in range(repeat):
                winsound.PlaySound(
                    sound_path,
                    winsound.SND_FILENAME | winsound.SND_NODEFAULT,
                )
            return
        except Exception:
            pass

    if sys.platform == "win32" and ext == ".mp3":
        if _play_mp3_mci(sound_path, repeat):
            return

    played = False
    if ext in (".wav", ".ogg"):
        try:
            from PyQt5.QtCore import QUrl
            from PyQt5.QtMultimedia import QSoundEffect
            from PyQt5.QtWidgets import QApplication

            app = QApplication.instance()
            effect = QSoundEffect()
            effect.setSource(QUrl.fromLocalFile(os.path.abspath(sound_path)))
            load_deadline = time.time() + 1.0
            while not effect.isLoaded() and time.time() < load_deadline:
                if app is not None:
                    app.processEvents()
                time.sleep(0.02)
            if effect.isLoaded():
                effect.setLoopCount(repeat)
                effect.play()
                play_deadline = time.time() + 120
                while effect.isPlaying() and time.time() < play_deadline:
                    if app is not None:
                        app.processEvents()
                    time.sleep(0.05)
                played = True
        except Exception:
            pass

    if not played and ext == ".mp3":
        played = _play_with_qt_media(sound_path, repeat)

    if played:  # Qt 音效已成功播放
        return

    for _ in range(repeat):
        try:
            from PyQt5.QtMultimedia import QSound
            QSound.play(sound_path)
            time.sleep(0.3)
            played = True
        except Exception:
            pass
        if not played:
            if sys.platform == "win32":
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            else:
                os.system('printf "\\a"')
            break
        time.sleep(0.2)


def _play_alert_sound_impl(
    config: Any,
    message_type: str = "warning",
    parsed_data: Optional[Dict[str, Any]] = None,
    tier: Optional[str] = None,
    *,
    force: bool = False,
) -> bool:
    """在当前线程播放分级告警音（调用方负责持有 ``_play_lock``）。返回是否已尝试播放。"""
    ac = getattr(config, "alert_config", None)
    if ac is None:
        return False

    pd = parsed_data or {}

    if tier:
        tier_key = tier.strip().lower()
        if tier_key not in ("felt", "critical", "nhk"):
            return False
        if not _tier_enabled(tier_key, ac):
            return False
        sound_path = resolve_sound_path(tier_key, ac)
        repeat = _sound_repeat_for_tier(tier_key, ac)
    else:
        if message_type != "warning":
            return False
        tier_key = classify_eew_audio_tier(parsed_data, ac)
        if not tier_key or not _tier_enabled(tier_key, ac):
            return False
        if not force and not should_play_warning_feedback(pd, tier_key):  # 同源/跨源重复报文跳过
            logger.debug(
                "跳过重复预警告警音: event_id=%s source_type=%s (同源或跨源同一震次)",
                pd.get("event_id"),
                pd.get("source_type"),
            )
            return False
        sound_path = resolve_sound_path(tier_key, ac)
        repeat = _sound_repeat_for_tier(tier_key, ac)

    if not sound_path:
        return False

    try:
        _play_file(sound_path, repeat)
        return True
    except Exception as e:
        logger.debug(f"播放告警音失败: {e}")
        return False


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
        with _play_lock:
            if not force and not should_play_nhk_news_bell(pd, ac):
                return
            if not force and not _tier_enabled("nhk", ac):
                return
            if not force and not should_play_warning_feedback(pd, "nhk"):
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
        if bool(pd.get("cancel")):
            return
        msg_type = (pd.get("type") or "").strip().lower()
        if msg_type not in ("", "warning"):
            return
        st = (pd.get("source_type") or "").strip().lower()
        if st not in JMA_EEW_SOURCE_TYPES:
            return

    def _run() -> None:
        with _play_lock:
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

    threading.Thread(target=_run, daemon=True, name="JmaEewAlertSound").start()


def play_alert_sound(
    config: Any,
    message_type: str = "warning",
    parsed_data: Optional[Dict[str, Any]] = None,
    tier: Optional[str] = None,
    *,
    force: bool = False,
) -> None:
    """在后台线程播放分级告警音。``tier`` 非空时用于设置页测试；``force`` 跳过去重。"""
    ac = getattr(config, "alert_config", None)
    if ac is None:
        return

    def _run() -> None:
        with _play_lock:
            _play_alert_sound_impl(
                config, message_type, parsed_data, tier=tier, force=force
            )

    threading.Thread(target=_run, daemon=True, name="AudioAlert").start()
