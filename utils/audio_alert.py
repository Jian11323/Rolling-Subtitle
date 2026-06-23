#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地震预警声音告警（有感 / 强震分级，仅 warning 类型）。"""

import os
import sys
import threading
import time
from typing import Any, Dict, Optional

from utils.epi_intensity_estimate import effective_epi_for_alert
from utils.logger import get_logger

logger = get_logger()

_play_lock = threading.Lock()

_EEW_MAG_CRITICAL = 4.8
_EEW_INTENSITY_CRITICAL = 7.0

_DEFAULT_SOUND_FILES = {
    "felt": "media/eewalert.wav",
    "critical": "media/eewcritical.wav",
}


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
    if tier == "felt":
        custom = (getattr(alert_config, "felt_sound_path", "") or "").strip()
        default_rel = _DEFAULT_SOUND_FILES["felt"]
    elif tier == "critical":
        custom = (getattr(alert_config, "critical_sound_path", "") or "").strip()
        default_rel = _DEFAULT_SOUND_FILES["critical"]
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
    if tier == "felt":
        repeat = getattr(alert_config, "felt_sound_repeat", 1)
    elif tier == "critical":
        repeat = getattr(alert_config, "critical_sound_repeat", 1)
    else:
        return 1
    try:
        n = int(repeat)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(10, n))


def _tier_enabled(tier: str, alert_config: Any) -> bool:
    if tier == "felt":
        return bool(getattr(alert_config, "felt_sound_enabled", False))
    if tier == "critical":
        return bool(getattr(alert_config, "critical_sound_enabled", False))
    return False


def _play_file(sound_path: str, repeat: int) -> None:
    repeat = max(1, min(10, int(repeat or 1)))
    if not sound_path or not os.path.isfile(sound_path):
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

    played = False
    try:
        from PyQt5.QtCore import QUrl
        from PyQt5.QtMultimedia import QSoundEffect

        effect = QSoundEffect()
        effect.setSource(QUrl.fromLocalFile(os.path.abspath(sound_path)))
        effect.setLoopCount(repeat)
        effect.play()
        while effect.isPlaying():
            time.sleep(0.05)
        played = True
    except Exception:
        pass

    if played:
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
) -> bool:
    """在当前线程播放分级告警音（调用方负责持有 ``_play_lock``）。返回是否已尝试播放。"""
    ac = getattr(config, "alert_config", None)
    if ac is None:
        return False

    if tier:
        tier_key = tier.strip().lower()
        if tier_key not in ("felt", "critical"):
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


def play_alert_sound(
    config: Any,
    message_type: str = "warning",
    parsed_data: Optional[Dict[str, Any]] = None,
    tier: Optional[str] = None,
) -> None:
    """在后台线程播放分级告警音。``tier`` 非空时用于设置页测试按钮。"""
    ac = getattr(config, "alert_config", None)
    if ac is None:
        return

    def _run() -> None:
        with _play_lock:
            _play_alert_sound_impl(config, message_type, parsed_data, tier=tier)

    threading.Thread(target=_run, daemon=True, name="AudioAlert").start()
