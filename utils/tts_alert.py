#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预警/速报 TTS 语音播报（Windows SAPI / pyttsx3，离线）。"""

from __future__ import annotations

import re
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from utils.audio_alert import classify_eew_audio_tier
from utils.logger import get_logger
from utils.warning_feedback_dedup import (
    register_warning_feedback_seen,
    should_play_warning_feedback,
)

logger = get_logger()

_play_lock = threading.Lock()
_thread_local = threading.local()
_tts_state_lock = threading.Lock()
# 按 event_key 记录最近一次 TTS 播报状态
_tts_last_by_event: Dict[str, Dict[str, Any]] = {}
# 已朗读速报快照（用于速报去重）
_tts_spoken_reports: list[Dict[str, Any]] = []
_SPOKEN_REPORTS_MAX = 300
_REPORT_TTS_MAX_AGE_SECONDS = 600  # 发震超过 10 分钟的速报不朗读，避免重连/轮询历史刷屏
_WARNING_TTS_MAX_AGE_SECONDS = 300  # 发震超过 5 分钟的预警不朗读

# TTS 重复策略常量
_TTS_REPEAT_SMART = "smart"
_TTS_REPEAT_FIRST_ONLY = "first_only"
_TTS_REPEAT_ALWAYS = "always"

_SOURCE_NAME_MAP = {
    "cea": "中国地震预警网",
    "cea-pr": "省级地震局",
    "cwa-eew": "台湾中央气象局",
    "jma": "日本气象厅",
    "sa": "美国ShakeAlert",
    "kma-eew": "韩国气象厅",
    "wolfx_jma_eew": "日本气象厅",
    "wolfx_sc_eew": "四川省地震局",
    "wolfx_fj_eew": "福建省地震局",
    "wolfx_cenc_eew": "中国地震台网",
}


def _strip_brackets(text: str) -> str:
    """去掉文本外层【】或 [] 括号。"""
    t = (text or "").strip()
    while len(t) >= 2 and t.startswith("【") and t.endswith("】"):
        t = t[1:-1].strip()
    while len(t) >= 2 and t.startswith("[") and t.endswith("]"):
        t = t[1:-1].strip()
    return t


def _sanitize_place_name(place_name: str) -> str:
    """清理地名中的括号与多余空白，空值时返回「未知地点」。"""
    text = (place_name or "").strip()
    if not text:
        return "未知地点"
    text = re.sub(r"[【】\[\]()（）｜|]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "未知地点"


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转换为浮点数。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fanstudio_cea_pr_org(province: str) -> str:
    """将省级名称格式化为 TTS 可读机构名（如「四川省地震局」）。"""
    p = (province or "").strip()
    if not p:
        return "省级地震局"
    if p.endswith("地震局"):
        return p
    for suffix in ("省", "市", "壮族自治区", "回族自治区", "维吾尔自治区", "自治区"):
        if p.endswith(suffix):
            return f"{p}地震局"
    if p in ("北京", "上海", "天津", "重庆"):
        return f"{p}市地震局"
    if p in ("北京市", "上海市", "天津市", "重庆市"):
        return f"{p}地震局"
    autonomous_short = {
        "内蒙古": "内蒙古自治区",
        "广西": "广西壮族自治区",
        "西藏": "西藏自治区",
        "宁夏": "宁夏回族自治区",
        "新疆": "新疆维吾尔自治区",
    }
    if p in autonomous_short:
        return f"{autonomous_short[p]}地震局"
    return f"{p}省地震局"


def _warning_org_for_tts(data: Dict[str, Any]) -> str:
    """预警机构名（无方括号），对齐字幕格式。"""
    source_type = (data.get("source_type") or "").strip()
    organization = (data.get("organization") or "").strip()
    province = (data.get("province") or "").strip()
    info_type = (data.get("info_type") or "").strip()

    if data.get("fanstudio"):
        if source_type == "cea":
            return "中国地震预警网"
        if source_type == "cea-pr":
            return _fanstudio_cea_pr_org(province)
        if source_type == "cwa-eew":
            return "台湾省气象署"
        if source_type == "sa":
            return "美国ShakeAlert"
        if source_type == "jma":
            if info_type:
                return f"日本气象厅 {info_type}".strip()
            return "日本气象厅"
        if source_type == "kma-eew":
            return "韩国气象厅"
        if organization:
            if "地震预警" in organization or "地震情报" in organization:
                return _strip_brackets(organization)
            return f"{organization}地震预警".replace("地震预警地震预警", "地震预警")

    if source_type == "wolfx_jma_eew":
        warn_area_type = (data.get("warn_area_type") or "").strip()
        if warn_area_type:
            return f"Wolfx 緊急地震速報 {warn_area_type}"
        return "Wolfx 緊急地震速報"
    if source_type == "cea-pr" and province:
        return _fanstudio_cea_pr_org(province)
    if organization:
        if "地震预警" in organization or "地震情报" in organization:
            return _strip_brackets(organization)
        if organization.endswith("地震预警网"):
            return organization
        if organization.endswith("预警"):
            return organization
        return f"{organization}地震预警"

    default_org = _SOURCE_NAME_MAP.get(source_type, "地震预警")
    return default_org


def _cenc_determination_label(data: Dict[str, Any]) -> str:
    """从 info_type / raw_data 解析 CENC 测定类型（自动测定或正式测定）。"""
    candidates = [
        data.get("info_type"),
        data.get("infoTypeName"),
    ]
    raw = data.get("raw_data")
    if isinstance(raw, dict):
        candidates.append(raw.get("infoTypeName"))
    for item in candidates:
        clean = _strip_brackets(str(item or "").strip())
        if "正式测定" in clean:
            return "正式测定"
        if "自动测定" in clean:
            return "自动测定"
    return ""


def _report_org_for_tts(data: Dict[str, Any]) -> str:
    """速报机构名（无方括号）。"""
    organization = (data.get("organization") or "").strip()
    info_type = (data.get("info_type") or "").strip()
    source_type = (data.get("source_type") or "").strip()

    if data.get("fanstudio"):
        if source_type == "weatheralarm":
            return "中国气象局"
        if source_type == "cenc":
            det = _cenc_determination_label(data)
            if det:
                return f"中国地震台网中心{det}"
            return "中国地震台网中心"
        if organization:
            if "地震信息" in organization or "地震情报" in organization:
                return _strip_brackets(organization)
            return f"{organization}地震信息"

    if organization == "FSSN":
        return "FSSN"
    if organization == "香港天文台":
        return "香港天文台"
    if organization == "美国地质调查局":
        return "美国地质调查局"
    if (
        organization == "中国地震台网中心自动测定/正式测定"
        or source_type == "cenc"
    ):
        det = _cenc_determination_label(data) or _cenc_determination_label(
            {"info_type": info_type}
        )
        if det:
            return f"中国地震台网中心{det}"
        return "中国地震台网中心"
    if organization:
        if "地震信息" in organization or "地震情报" in organization or "海啸" in organization:
            return _strip_brackets(organization)
        return f"{organization}地震信息"
    return "地震信息"


def _format_shock_time_for_tts(shock_time: str) -> str:
    """将发震时间格式化为 TTS 中文读法（年月日时分秒）。"""
    if not shock_time or not str(shock_time).strip():
        return ""
    try:
        from utils import timezone_utils

        dt = timezone_utils.parse_display_time(str(shock_time).strip())
        if dt is None:
            return str(shock_time).strip()
        if sys.platform == "win32":
            return (
                f"{dt.year}年{dt.month}月{dt.day}日"
                f"{dt.hour}时{dt.minute}分{dt.second}秒"
            )
        return dt.strftime("%Y年%-m月%-d日%-H时%-M分%-S秒")
    except Exception:
        return str(shock_time).strip()


def _warning_updates_part(data: Dict[str, Any]) -> str:
    """生成预警报数片段（第 N 报 / 最终报），无报数时返回空串。"""
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
        return ""
    is_final = bool(data.get("final", False))
    if is_final and source_type in ("jma", "wolfx_jma_eew", "wolfx_fj_eew"):
        return "最终报"
    return f"第{updates}报"


def build_warning_tts_script(parsed_data: Dict[str, Any], config: Any = None) -> str:
    """
    预警 TTS：机构 第N报，地点发生X.X级地震
    示例：中国地震预警网 第1报，四川某地发生5.2级地震
    """
    _ = config
    pd = parsed_data or {}
    org = _warning_org_for_tts(pd)
    updates_part = _warning_updates_part(pd)
    place = _sanitize_place_name(str(pd.get("place_name") or ""))
    magnitude = _safe_float(pd.get("magnitude"), 0.0)

    if place and magnitude > 0:
        body = f"{place}发生{magnitude:.1f}级地震"
    elif place:
        body = f"{place}发生地震"
    elif magnitude > 0:
        body = f"发生{magnitude:.1f}级地震"
    else:
        body = "发生地震"

    if updates_part:
        return f"{org} {updates_part}，{body}"
    return f"{org}，{body}"


def build_report_tts_script(parsed_data: Dict[str, Any], config: Any = None) -> str:
    """
    速报 TTS：机构，时间，地点发生X.X级地震，震源深度X公里
    """
    _ = config
    pd = parsed_data or {}
    org = _report_org_for_tts(pd)
    shock_time = _format_shock_time_for_tts(str(pd.get("shock_time") or ""))
    place = _sanitize_place_name(str(pd.get("place_name") or ""))
    magnitude = _safe_float(pd.get("magnitude"), 0.0)
    depth_value = pd.get("depth")
    if depth_value is None:
        depth = 10.0
    else:
        depth = _safe_float(depth_value, 10.0)
        if depth == 0:
            depth = 10.0
    depth_int = int(round(depth, 0))

    if place and magnitude > 0:
        body = f"{place}发生{magnitude:.1f}级地震，震源深度{depth_int}公里"
    elif place:
        body = f"{place}发生地震，震源深度{depth_int}公里"
    elif magnitude > 0:
        body = f"发生{magnitude:.1f}级地震，震源深度{depth_int}公里"
    else:
        body = f"发生地震，震源深度{depth_int}公里"

    if shock_time:
        return f"{org}，{shock_time}，{body}"
    return f"{org}，{body}"


def sanitize_display_text(text: str, config: Any = None) -> str:
    """将滚动字幕显示文本清理为 TTS 可读脚本（与屏幕一致，仅做空白/括号/长度处理）。"""
    t = (text or "").replace("\n", " ").replace("\r", " ").strip()
    if not t:
        return ""
    t = re.sub(r"【([^】]+)】", r"\1，", t)
    t = re.sub(r"\[([^\]]+)\]", r"\1，", t)
    t = re.sub(r"\s+", " ", t).strip("，, ")
    max_len = 0
    if config is not None:
        msg_cfg = getattr(config, "message_config", None)
        if msg_cfg is not None:
            try:
                max_len = int(getattr(msg_cfg, "max_message_length", 0) or 0)
            except (TypeError, ValueError):
                max_len = 0
    if max_len > 0 and len(t) > max_len:
        t = t[:max_len].rstrip() + "…"
    return t


def build_tts_script(
    parsed_data: Dict[str, Any],
    config: Any = None,
    message_type: str = "warning",
) -> str:
    """按消息类型生成 TTS 脚本。"""
    mt = (message_type or "warning").strip().lower()
    if mt == "report":
        return build_report_tts_script(parsed_data, config)
    return build_warning_tts_script(parsed_data, config)


def _tts_tier_enabled(tier: str, alert_config: Any) -> bool:
    """检查指定档位（felt/critical）的 TTS 是否已启用。"""
    tier = (tier or "").strip().lower()
    if tier == "felt":
        return bool(getattr(alert_config, "felt_tts_enabled", False))
    if tier == "critical":
        return bool(getattr(alert_config, "critical_tts_enabled", False))
    return False


def _tts_repeat_for_tier(tier: str, alert_config: Any) -> int:
    """读取指定消息类型的 TTS 重复次数（1–10）。"""
    tier = (tier or "").strip().lower()
    if tier == "felt":
        repeat = getattr(alert_config, "felt_tts_repeat", 1)
    elif tier == "critical":
        repeat = getattr(alert_config, "critical_tts_repeat", 1)
    elif tier == "report":
        repeat = getattr(alert_config, "report_tts_repeat", 1)
    elif tier == "weather":
        repeat = getattr(alert_config, "weather_tts_repeat", 1)
    elif tier == "tsunami":
        repeat = getattr(alert_config, "tsunami_tts_repeat", 1)
    else:
        return 1
    try:
        n = int(repeat)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(10, n))


def _event_key(parsed_data: Dict[str, Any]) -> str:
    """生成 TTS 去重用事件键（优先 event_id）。"""
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
    """提取预警报数值；SA 源无报数字段时视为第 1 报。"""
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


def _tts_state_record(
    parsed_data: Dict[str, Any],
    mag: float,
    tier: str,
    now: float,
) -> Dict[str, Any]:
    """构建 TTS 去重状态快照。"""
    return {
        "time": now,
        "mag": mag,
        "tier": tier,
        "updates": _warning_updates_value(parsed_data),
        "final": bool(parsed_data.get("final", False)),
    }


def _should_speak_warning(parsed_data: Dict[str, Any], tier: str) -> bool:
    """预警：首报、更新报、震级/档位变化即朗读，不使用间隔时间。"""
    return should_play_warning_feedback(parsed_data, tier)


def _cenc_info_type_key(data: Dict[str, Any]) -> str:
    """CENC 测定类型键（来自 infoTypeName / info_type）。"""
    if (data.get("source_type") or "").strip() != "cenc":
        return ""
    info_type = _strip_brackets(
        str(data.get("info_type") or data.get("infoTypeName") or "")
    )
    if "正式测定" in info_type:
        return "official"
    if "自动测定" in info_type:
        return "auto"
    return info_type or "unknown"


def _is_cenc_same_report(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """CENC：同一 eventId + 同一 infoTypeName 视为同一速报；自动/正式测定分别朗读。"""
    if (a.get("source_type") or "").strip() != "cenc":
        return False
    if (b.get("source_type") or "").strip() != "cenc":
        return False

    type_a = _cenc_info_type_key(a)
    type_b = _cenc_info_type_key(b)
    if type_a != type_b:
        return False

    event_id_a = str(a.get("event_id") or a.get("id") or "").strip()
    event_id_b = str(b.get("event_id") or b.get("id") or "").strip()
    if event_id_a and event_id_b and event_id_a == event_id_b:
        return True

    shock_a = str(a.get("shock_time") or "").strip()
    shock_b = str(b.get("shock_time") or "").strip()
    return bool(shock_a and shock_b and shock_a == shock_b)


def _is_same_report_event(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """判断两条速报是否同一事件（CENC 自动/正式测定视为不同事件）。"""
    if _is_cenc_same_report(a, b):
        return True

    source_a = (a.get("source_type") or "").strip()
    source_b = (b.get("source_type") or "").strip()

    event_id_a = str(a.get("event_id") or a.get("id") or "").strip()
    event_id_b = str(b.get("event_id") or b.get("id") or "").strip()
    if event_id_a and event_id_b and event_id_a == event_id_b:
        if source_a == "cenc" and source_b == "cenc":
            if _cenc_info_type_key(a) != _cenc_info_type_key(b):
                return False
        return True

    shock_a = str(a.get("shock_time") or "").strip()
    shock_b = str(b.get("shock_time") or "").strip()
    if source_a and source_a == source_b and shock_a and shock_a == shock_b:
        if source_a == "cenc" and _cenc_info_type_key(a) != _cenc_info_type_key(b):
            return False
        place_a = _sanitize_place_name(str(a.get("place_name") or ""))
        place_b = _sanitize_place_name(str(b.get("place_name") or ""))
        if place_a and place_b and (place_a == place_b or place_a in place_b or place_b in place_a):
            return True

    if source_a == "cenc" and source_b == "cenc":
        if _cenc_info_type_key(a) != _cenc_info_type_key(b):
            return False

    try:
        from utils.event_dedup import find_duplicate_index

        idx = find_duplicate_index(a, [{"parsed_data": b, "received_at_ts": 0}])
        if idx is not None:
            return True
    except Exception:
        pass
    return False


def _find_spoken_report_index(parsed_data: Dict[str, Any]) -> Optional[int]:
    """在已朗读速报列表中查找与当前数据同一事件的索引。"""
    for idx in range(len(_tts_spoken_reports) - 1, -1, -1):
        if _is_same_report_event(parsed_data, _tts_spoken_reports[idx]):
            return idx
    return None


def _report_shock_age_seconds(parsed_data: Dict[str, Any]) -> Optional[float]:
    """发震至今秒数；无发震时间或无法解析时返回 None。"""
    shock_time_str = str((parsed_data or {}).get("shock_time") or "").strip()
    if not shock_time_str:
        return None
    try:
        from utils import timezone_utils

        shock_time = timezone_utils.parse_display_time(shock_time_str)
        if shock_time is None:
            return None
        return (timezone_utils.now_in_display_tz() - shock_time).total_seconds()
    except Exception:
        return None


def _is_report_too_old_for_tts(parsed_data: Dict[str, Any]) -> bool:
    """速报发震时间是否已超过允许朗读的最大年龄。"""
    age = _report_shock_age_seconds(parsed_data)
    if age is None:
        return False
    return age > _REPORT_TTS_MAX_AGE_SECONDS


def _is_warning_too_old_for_tts(parsed_data: Dict[str, Any]) -> bool:
    """预警发震时间是否已超过允许朗读的最大年龄。"""
    age = _report_shock_age_seconds(parsed_data)
    if age is None:
        return False
    return age > _WARNING_TTS_MAX_AGE_SECONDS


def _should_suppress_tts(parsed_data: Dict[str, Any], message_type: str) -> bool:
    """启动批量同步或过期消息：仅展示字幕，不朗读。"""
    pd = parsed_data or {}
    if pd.get("_suppress_tts"):
        return True
    mt = (message_type or "").strip().lower()
    if mt == "warning":
        return _is_warning_too_old_for_tts(pd)
    if mt == "report" and not pd.get("is_tsunami"):
        return _is_report_too_old_for_tts(pd)
    return False


def _register_tts_seen(
    parsed_data: Dict[str, Any],
    message_type: str,
    config: Any,
    *,
    tier: Optional[str] = None,
) -> None:
    """启动同步等场景：跳过朗读但仍写入去重状态，避免后续 update 重复播报。"""
    pd = dict(parsed_data or {})
    mt = (message_type or "").strip().lower()
    if not pd or not mt:
        return

    ac = getattr(config, "alert_config", None)

    if mt == "report" and not pd.get("is_tsunami"):
        with _tts_state_lock:
            if _find_spoken_report_index(pd) is None:
                _tts_spoken_reports.append(dict(pd))
                if len(_tts_spoken_reports) > _SPOKEN_REPORTS_MAX:
                    del _tts_spoken_reports[:-_SPOKEN_REPORTS_MAX]
        return

    tier_key = (tier or "").strip().lower()
    if mt == "warning":
        if not tier_key and ac is not None:
            tier_key = classify_eew_audio_tier(pd, ac) or "felt"
        if not tier_key:
            tier_key = "felt"
        register_warning_feedback_seen(pd, tier_key)
        return
    elif mt == "weather":
        tier_key = "weather"
    elif mt == "report" and pd.get("is_tsunami"):
        tier_key = "tsunami"
    else:
        return

    try:
        mag = float(pd.get("magnitude") or 0.0)
    except (TypeError, ValueError):
        mag = 0.0

    key = _event_key(pd)
    with _tts_state_lock:
        _tts_last_by_event[key] = _tts_state_record(pd, mag, tier_key, time.time())


def _should_speak_report(parsed_data: Dict[str, Any]) -> bool:
    """速报：收到即朗读；同一事件仅朗读一次（CENC 自动/正式测定分别计数）。"""
    with _tts_state_lock:
        if _find_spoken_report_index(parsed_data) is not None:
            return False
        _tts_spoken_reports.append(dict(parsed_data))
        if len(_tts_spoken_reports) > _SPOKEN_REPORTS_MAX:
            del _tts_spoken_reports[:-_SPOKEN_REPORTS_MAX]
        return True


def _should_speak_event(
    parsed_data: Dict[str, Any],
    alert_config: Any,
    tier: str,
) -> bool:
    """气象/海啸等非预警类消息的重复策略（保留最短间隔设置）。"""
    policy = str(getattr(alert_config, "tts_repeat_policy", _TTS_REPEAT_SMART) or _TTS_REPEAT_SMART)
    try:
        cooldown = max(0, int(getattr(alert_config, "tts_cooldown_seconds", 60) or 60))
    except (TypeError, ValueError):
        cooldown = 60

    key = _event_key(parsed_data)
    try:
        mag = float(parsed_data.get("magnitude") or 0.0)
    except (TypeError, ValueError):
        mag = 0.0

    now = time.time()
    with _tts_state_lock:
        prev = _tts_last_by_event.get(key)
        record = _tts_state_record(parsed_data, mag, tier, now)

        if prev is None:
            _tts_last_by_event[key] = record
            return True

        if policy == _TTS_REPEAT_FIRST_ONLY:
            return False

        if policy == _TTS_REPEAT_ALWAYS:
            if now - float(prev.get("time") or 0) < max(10, cooldown):
                return False
            _tts_last_by_event[key] = record
            return True

        elapsed = now - float(prev.get("time") or 0)
        prev_tier = str(prev.get("tier") or "")
        prev_mag = float(prev.get("mag") or 0.0)
        tier_changed = prev_tier and prev_tier != tier
        mag_changed = abs(prev_mag - mag) >= 0.5

        if tier_changed or mag_changed:
            _tts_last_by_event[key] = record
            return True
        if elapsed >= cooldown:
            _tts_last_by_event[key] = record
            return True
        return False


def _get_engine():
    """获取当前线程的 pyttsx3 引擎实例（线程本地缓存）。"""
    if not hasattr(_thread_local, "engine"):
        import pyttsx3

        if sys.platform == "win32":
            engine = pyttsx3.init("sapi5")
        else:
            engine = pyttsx3.init()
        _thread_local.engine = engine
    return _thread_local.engine


def _apply_engine_settings(alert_config: Any) -> None:
    """将语速、音量、语音角色等设置应用到 TTS 引擎。"""
    engine = _get_engine()
    try:
        rate = int(getattr(alert_config, "tts_rate", 150) or 150)
    except (TypeError, ValueError):
        rate = 150
    rate = max(80, min(300, rate))
    try:
        engine.setProperty("rate", rate)
    except Exception:
        pass

    try:
        volume_pct = int(getattr(alert_config, "sound_volume", 100) or 100)
    except (TypeError, ValueError):
        volume_pct = 100
    volume_pct = max(0, min(100, volume_pct))
    try:
        engine.setProperty("volume", volume_pct / 100.0)
    except Exception:
        pass

    voice_id = (getattr(alert_config, "tts_voice", "") or "").strip()
    if voice_id:
        try:
            engine.setProperty("voice", voice_id)
        except Exception:
            pass


def list_tts_voices() -> Tuple[str, ...]:
    """列举系统可用 TTS 语音 ID。"""
    try:
        engine = _get_engine()
        voices = engine.getProperty("voices") or []
        return tuple(getattr(v, "id", "") or "" for v in voices if getattr(v, "id", ""))
    except Exception as e:
        logger.debug(f"列举 TTS 语音失败: {e}")
        return ()


def has_chinese_tts_voice() -> bool:
    """检测系统是否安装了中文 TTS 语音包。"""
    try:
        engine = _get_engine()
        for voice in engine.getProperty("voices") or []:
            name = f"{getattr(voice, 'name', '')} {getattr(voice, 'id', '')}".lower()
            if "chinese" in name or "zh-" in name or "huihui" in name or "kangkang" in name:
                return True
    except Exception:
        pass
    return False


def _speak_blocking(text: str, alert_config: Any, repeat: int = 1) -> None:
    """在当前线程阻塞式朗读文本（仅 Windows SAPI）。"""
    script = (text or "").strip()
    if not script:
        return
    if sys.platform != "win32":
        logger.debug("TTS 当前仅支持 Windows SAPI")
        return
    repeat = max(1, min(10, int(repeat or 1)))
    try:
        _apply_engine_settings(alert_config)
        engine = _get_engine()
        for _ in range(repeat):
            engine.say(script)
            engine.runAndWait()
    except Exception as e:
        logger.debug(f"TTS 播报失败: {e}")


def _feedback_mode(alert_config: Any) -> str:
    """读取告警反馈模式：sound（声音）或 tts（语音）。"""
    mode = str(getattr(alert_config, "alert_feedback_mode", "sound") or "sound").strip().lower()
    if mode not in ("sound", "tts"):
        legacy = str(getattr(alert_config, "tts_playback_mode", "") or "").strip().lower()
        if legacy == "replace":
            return "tts"
        if getattr(alert_config, "felt_tts_enabled", False) or getattr(
            alert_config, "critical_tts_enabled", False
        ):
            return "tts"
        return "sound"
    return mode


def _run_tts_feedback(
    config: Any,
    message_type: str,
    parsed_data: Optional[Dict[str, Any]],
    *,
    tier: Optional[str] = None,
    display_text: Optional[str] = None,
    test_script: Optional[str] = None,
    test_repeat: int = 1,
) -> None:
    """TTS 播报主逻辑：按消息类型生成脚本并阻塞朗读。"""
    ac = getattr(config, "alert_config", None)
    if ac is None:
        return
    if _feedback_mode(ac) != "tts" and test_script is None:
        return

    pd = parsed_data or {}
    mt = (message_type or "warning").strip().lower()

    if test_script is not None:
        with _play_lock:
            _speak_blocking(test_script, ac, test_repeat)
        return

    if mt == "weather":
        if not bool(getattr(ac, "weather_tts_enabled", True)):
            return
        if _should_suppress_tts(pd, mt):
            _register_tts_seen(pd, mt, config)
            logger.debug("启动同步或策略跳过气象 TTS")
            return
        script = sanitize_display_text(display_text or "", config)
        if not script:
            return
        if pd and not _should_speak_event(pd, ac, "weather"):
            return
        repeat = _tts_repeat_for_tier("weather", ac)
        with _play_lock:
            _speak_blocking(script, ac, repeat)
        return

    if mt == "report":
        if pd.get("is_tsunami"):
            if not bool(getattr(ac, "tsunami_tts_enabled", True)):
                return
            if _should_suppress_tts(pd, mt):
                _register_tts_seen(pd, mt, config)
                logger.debug("启动同步跳过海啸 TTS")
                return
            script = sanitize_display_text(display_text or "", config)
            if not script:
                return
            if pd and not _should_speak_event(pd, ac, "tsunami"):
                return
            repeat = _tts_repeat_for_tier("tsunami", ac)
            with _play_lock:
                _speak_blocking(script, ac, repeat)
            return

        if not bool(getattr(ac, "report_tts_enabled", True)):
            return
        msg_cfg = getattr(config, "message_config", None)
        if msg_cfg is not None:
            try:
                min_mag = float(getattr(msg_cfg, "min_report_magnitude", 0) or 0)
            except (TypeError, ValueError):
                min_mag = 0.0
            if min_mag > 0:
                try:
                    mag = float(pd.get("magnitude") or 0)
                except (TypeError, ValueError):
                    mag = 0.0
                if mag < min_mag:
                    return
        if _should_suppress_tts(pd, mt):
            _register_tts_seen(pd, mt, config)
            logger.debug(
                "启动同步或过期速报，跳过 TTS: source=%s, shock_time=%s",
                pd.get("source_type"),
                pd.get("shock_time"),
            )
            return
        if pd and not _should_speak_report(pd):
            return
        script = build_report_tts_script(pd, config)
        repeat = _tts_repeat_for_tier("report", ac)
        with _play_lock:
            _speak_blocking(script, ac, repeat)
        return

    if mt != "warning":
        return

    tier_key = (tier or "").strip().lower() or classify_eew_audio_tier(pd, ac)
    if not tier_key or not _tts_tier_enabled(tier_key, ac):
        return
    if _should_suppress_tts(pd, mt):
        _register_tts_seen(pd, mt, config, tier=tier_key)
        logger.debug(
            "预警发震时间已超过 %s 秒或启动同步，跳过 TTS: source=%s, shock_time=%s",
            _WARNING_TTS_MAX_AGE_SECONDS,
            pd.get("source_type"),
            pd.get("shock_time"),
        )
        return
    script = build_warning_tts_script(pd, config)
    repeat = _tts_repeat_for_tier(tier_key, ac)
    with _play_lock:
        if pd and not pd.get("_simulate") and not _should_speak_warning(pd, tier_key):
            return
        _speak_blocking(script, ac, repeat)


def trigger_alert_feedback(
    config: Any,
    message_type: str = "warning",
    parsed_data: Optional[Dict[str, Any]] = None,
    display_text: Optional[str] = None,
) -> None:
    """TTS 模式下在后台线程朗读预警/速报/气象/海啸。"""
    ac = getattr(config, "alert_config", None)
    if ac is None or _feedback_mode(ac) != "tts":
        return
    if message_type not in ("warning", "report", "weather"):
        return

    def _run() -> None:
        try:
            _run_tts_feedback(
                config, message_type, parsed_data, display_text=display_text
            )
        except Exception as e:
            logger.debug(f"TTS 播报失败: {e}")

    threading.Thread(target=_run, daemon=True, name="TtsAlert").start()


def _entry_is_tsunami(entry: Dict[str, Any]) -> bool:
    """判断历史条目是否为海啸类速报。"""
    pd = entry.get("parsed_data") or {}
    if not isinstance(pd, dict):
        return False
    if pd.get("is_tsunami"):
        return True
    source_type = str(pd.get("source_type") or "").strip().lower()
    return source_type in ("tsunami", "p2pquake_tsunami")


def _entry_is_cenc(entry: Dict[str, Any]) -> bool:
    """是否为 Fan Studio CENC 地震速报（不含 cenc-ir 烈度速报）。"""
    pd = entry.get("parsed_data") or {}
    if not isinstance(pd, dict):
        return False
    source_type = str(pd.get("source_type") or "").strip().lower()
    if source_type == "cenc":
        return True
    source_name = str(entry.get("source_name") or "").strip().lower()
    if source_name == "cenc":
        return True
    org = str(pd.get("organization") or "")
    if "中国地震台网中心" in org and "烈度速报" not in org:
        return True
    return False


def find_latest_tts_entry(
    history: Optional[List[Dict[str, Any]]],
    kind: str,
) -> Optional[Dict[str, Any]]:
    """从历史记录中查找指定类型的最新一条（预警/速报/气象/海啸）。"""
    target = (kind or "").strip().lower()
    if not history or not target:
        return None
    if target == "warning":
        fallback: Optional[Dict[str, Any]] = None
        for entry in reversed(history):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("message_type") or "").lower() != "warning":
                continue
            pd = entry.get("parsed_data") or {}
            if isinstance(pd, dict) and (
                pd.get("_cea_test_seed")
                or str(pd.get("source_type") or "").strip() == "cea"
            ):
                return entry
            if fallback is None:
                fallback = entry
        return fallback
    for entry in reversed(history):
        if not isinstance(entry, dict):
            continue
        mt = str(entry.get("message_type") or "").lower()
        if target == "weather" and mt == "weather":
            return entry
        if target == "tsunami" and mt == "report" and _entry_is_tsunami(entry):
            return entry
        if (
            target == "report"
            and mt == "report"
            and not _entry_is_tsunami(entry)
            and _entry_is_cenc(entry)
        ):
            return entry
    return None


def _resolve_tts_display_text(
    entry: Dict[str, Any],
    config: Any,
    *,
    message_type: str = "",
) -> str:
    """优先从 parsed_data 还原完整滚动字幕，其次使用 scroll_text / message_text。"""
    pd = entry.get("parsed_data") or {}
    mt = (message_type or entry.get("message_type") or "").strip().lower()
    if isinstance(pd, dict) and pd:
        fmt_type = mt or str(pd.get("type") or "").strip().lower()
        if pd.get("is_tsunami"):
            fmt_type = "report"
        if fmt_type in ("weather", "report", "warning"):
            try:
                from utils.message_processor import MessageProcessor

                formatted = MessageProcessor().format_message(
                    {**pd, "type": fmt_type or pd.get("type")},
                    ignore_warning_expiry=True,
                )
                if formatted and str(formatted).strip():
                    return str(formatted).strip()
            except Exception:
                pass
    return str(entry.get("scroll_text") or entry.get("message_text") or "").strip()


def _start_tts_test_from_entry(
    config: Any,
    entry: Dict[str, Any],
    kind: str,
) -> bool:
    """根据历史条目启动测试朗读；脚本与正式播报一致。"""
    ac = getattr(config, "alert_config", None)
    pd = dict(entry.get("parsed_data") or {}) if isinstance(entry.get("parsed_data"), dict) else {}
    target = (kind or "").strip().lower()

    if target == "warning":
        script = build_warning_tts_script(pd, config)
        tier = classify_eew_audio_tier(pd, ac) if ac is not None else "felt"
        tier = tier or "felt"
        repeat = _tts_repeat_for_tier(tier, ac) if ac is not None else 1
        message_type = "warning"
    elif target == "report":
        script = build_report_tts_script(pd, config)
        repeat = _tts_repeat_for_tier("report", ac) if ac is not None else 1
        message_type = "report"
    elif target == "weather":
        display = _resolve_tts_display_text(entry, config, message_type="weather")
        script = sanitize_display_text(display, config)
        repeat = _tts_repeat_for_tier("weather", ac) if ac is not None else 1
        message_type = "weather"
    elif target == "tsunami":
        display = _resolve_tts_display_text(entry, config, message_type="report")
        script = sanitize_display_text(display, config)
        repeat = _tts_repeat_for_tier("tsunami", ac) if ac is not None else 1
        message_type = "report"
        pd["is_tsunami"] = True
    else:
        return False

    if not (script or "").strip():
        return False

    def _run() -> None:
        try:
            _run_tts_feedback(
                config,
                message_type,
                pd,
                display_text=display if target in ("weather", "tsunami") else None,
                test_script=script,
                test_repeat=repeat,
            )
        except Exception as e:
            logger.debug(f"TTS 测试失败 ({target}): {e}")

    threading.Thread(
        target=_run, daemon=True, name=f"TtsTest-{target}"
    ).start()
    return True


def test_tts_from_latest(
    config: Any,
    history: Optional[List[Dict[str, Any]]],
    kind: str,
) -> bool:
    """设置页测试：朗读历史中最新的预警/速报/气象/海啸条目。"""
    entry = find_latest_tts_entry(history, kind)
    if entry is None:
        return False
    return _start_tts_test_from_entry(config, entry, kind)


def test_tts_alert(
    config: Any,
    history: Optional[List[Dict[str, Any]]] = None,
    tier: str = "felt",
) -> bool:
    """设置页测试：朗读历史中最新的预警条目。"""
    _ = tier
    return test_tts_from_latest(config, history, "warning")


def test_tts_report(
    config: Any,
    history: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """设置页测试：朗读历史中最新的 CENC 速报条目。"""
    return test_tts_from_latest(config, history, "report")


def test_tts_weather(
    config: Any,
    history: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """设置页测试：朗读历史中最新的气象预警条目。"""
    return test_tts_from_latest(config, history, "weather")


def test_tts_tsunami(
    config: Any,
    history: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """设置页测试：朗读历史中最新的海啸条目。"""
    return test_tts_from_latest(config, history, "tsunami")
