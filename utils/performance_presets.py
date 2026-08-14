#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
性能模式预设：低配 / 标准 / 高配一键配置。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from config import (
    DEFAULT_HTTP_POLL_INTERVALS,
    NEW_HTTP_SOURCE_KEYS,
    P2PQUAKE_HTTP_SOURCE_KEYS,
    P2PQUAKE_WSS_URL,
    FANSTUDIO_ALL_URL,
    FANSTUDIO_TYPHOON_HTTP,
    WOLFX_ALL_EEW_URL,
    WOLFX_CWA_EEW_URL,
    WOLFX_CENC_EQLIST_URL,
    WOLFX_JMA_EQLIST_URL,
    EMSC_WSS_URL,
    NOWQUAKE_CENCINT_WSS_URL,
)

PERFORMANCE_MODE_LOW = "low"
PERFORMANCE_MODE_STANDARD = "standard"
PERFORMANCE_MODE_HIGH = "high"
PERFORMANCE_MODE_CUSTOM = "custom"

# 可选性能模式标识（custom 表示用户手动改动后不再跟随预设）
PERFORMANCE_MODES: Tuple[str, ...] = (
    PERFORMANCE_MODE_LOW,
    PERFORMANCE_MODE_STANDARD,
    PERFORMANCE_MODE_HIGH,
    PERFORMANCE_MODE_CUSTOM,
)

PERFORMANCE_MODE_LABELS: Dict[str, str] = {
    PERFORMANCE_MODE_LOW: "低配模式",
    PERFORMANCE_MODE_STANDARD: "标准模式",
    PERFORMANCE_MODE_HIGH: "高配模式",
    PERFORMANCE_MODE_CUSTOM: "自定义（未跟随预设）",
}

# Fan Studio HTTP 辅助数据源
TYPHOON_HTTP = FANSTUDIO_TYPHOON_HTTP


def _base_enabled_sources() -> Dict[str, bool]:
    """与 Config._apply_default_config 对齐的基础数据源开关。"""
    sources: Dict[str, bool] = {
        FANSTUDIO_ALL_URL: True,
    }
    for url in P2PQUAKE_HTTP_SOURCE_KEYS:  # HTTP 键仅兼容旧配置，永不作为持续轮询源
        sources[url] = False
    sources[TYPHOON_HTTP] = True
    sources[WOLFX_ALL_EEW_URL] = True
    sources[WOLFX_CWA_EEW_URL] = False
    sources[WOLFX_CENC_EQLIST_URL] = False
    sources[WOLFX_JMA_EQLIST_URL] = False
    sources[EMSC_WSS_URL] = False
    sources[NOWQUAKE_CENCINT_WSS_URL] = False
    sources[P2PQUAKE_WSS_URL] = False
    for url in NEW_HTTP_SOURCE_KEYS:  # 默认关闭国际 HTTP 源
        sources[url] = False
    return sources


def _low_enabled_sources() -> Dict[str, bool]:
    """低配模式：关闭次要 HTTP/WSS 数据源以减轻负载。"""
    sources = _base_enabled_sources()
    sources[TYPHOON_HTTP] = False
    sources[WOLFX_CWA_EEW_URL] = False
    sources[P2PQUAKE_WSS_URL] = False
    sources[EMSC_WSS_URL] = False
    sources[NOWQUAKE_CENCINT_WSS_URL] = False
    for url in P2PQUAKE_HTTP_SOURCE_KEYS:
        sources[url] = False
    for url in NEW_HTTP_SOURCE_KEYS:
        sources[url] = False
    return sources


def _high_enabled_sources() -> Dict[str, bool]:
    """高配模式：启用全部可选 HTTP/WSS 数据源。"""
    sources = _base_enabled_sources()
    sources[WOLFX_CWA_EEW_URL] = True  # 高配启用台湾 CWA 独立 WebSocket
    sources[WOLFX_CENC_EQLIST_URL] = True
    sources[WOLFX_JMA_EQLIST_URL] = True
    sources[EMSC_WSS_URL] = True
    sources[NOWQUAKE_CENCINT_WSS_URL] = True
    sources[P2PQUAKE_WSS_URL] = True
    for url in P2PQUAKE_HTTP_SOURCE_KEYS:
        sources[url] = False  # 仍不持续轮询；启动补拉由 WSS 管理器完成
    for url in NEW_HTTP_SOURCE_KEYS:
        sources[url] = True
    return sources


def _scale_http_poll_intervals(factor: float) -> Dict[str, int]:
    """按倍率缩放 HTTP 轮询间隔（低配模式拉长间隔）。"""
    scaled: Dict[str, int] = {}
    for url, default_sec in DEFAULT_HTTP_POLL_INTERVALS.items():
        scaled[url] = max(1, int(round(default_sec * factor)))
    return scaled


def _message_fields_low() -> Dict[str, Any]:
    """低配模式消息相关配置覆盖项。"""
    return {
        "message_queue_maxsize": 100,
        "message_buffer_max_size": 50,
        "enable_china_intensity": False,
        "enable_felt_alert_flow": False,
        "enable_strong_felt_alert_flow": False,
        "fanstudio_parse_warning": True,
        "fanstudio_parse_report": True,
        "fanstudio_parse_cea": True,
        "fanstudio_parse_cea_pr": True,
        "fanstudio_parse_cwa_eew": True,
        "fanstudio_parse_jma": True,
        "fanstudio_parse_sa": True,
        "fanstudio_parse_kma_eew": True,
        "fanstudio_parse_cenc": True,
        "fanstudio_parse_ningxia": False,
        "fanstudio_parse_guangxi": False,
        "fanstudio_parse_shanxi": False,
        "fanstudio_parse_beijing": False,
        "fanstudio_parse_yunnan": False,
        "fanstudio_parse_cwa": False,
        "fanstudio_parse_hko": False,
        "fanstudio_parse_usgs": False,
        "fanstudio_parse_emsc": False,
        "fanstudio_parse_bcsf": False,
        "fanstudio_parse_gfz": False,
        "fanstudio_parse_usp": False,
        "fanstudio_parse_kma": False,
        "fanstudio_parse_fssn": False,
        "fanstudio_parse_fssn_cmt": False,
        "fanstudio_parse_weatheralarm": False,
        "fanstudio_parse_tsunami": False,
        "whews_parse_jma_eew": True,
        "whews_parse_cwa_eew": True,
        "whews_parse_sa_eew": True,
        "whews_parse_kma_eew": True,
        "whews_parse_cea": True,
        "whews_parse_cea_pr": True,
        "whews_parse_cenc": True,
        "whews_parse_cwa": False,
        "whews_parse_hko": False,
        "whews_parse_usgs": False,
        "whews_parse_emsc": False,
        "whews_parse_bcsf": False,
        "whews_parse_gfz": False,
        "whews_parse_usp": False,
        "whews_parse_kma": False,
        "whews_parse_bmkg": False,
        "whews_parse_geonet": False,
        "whews_parse_tmd": False,
        "whews_parse_ingv": False,
        "whews_parse_nrcan": False,
        "whews_parse_mmd": False,
        "whews_parse_beijing": False,
        "whews_parse_yunnan": False,
        "whews_parse_ningxia": False,
        "whews_parse_jma_volcano": False,
        "whews_parse_tsunami": False,
        "whews_parse_ntwc": False,
        "whews_parse_ptwc": False,
        "whews_parse_incois": False,
        "whews_parse_jma_tsunami": False,
        "whews_parse_phivolcs": False,
        "whews_parse_sgc": False,
        "whews_parse_ga": False,
        "whews_parse_cenais": False,
        "whews_parse_weatheralarm": False,
        "ali_all_parse_nied": True,
        "ali_all_parse_early_est": True,
        "ali_all_parse_jma_volcano": False,
        "ali_all_parse_bmkg": True,
        "ali_all_parse_cq_eew": True,
        "p2pquake_parse_551": True,
        "p2pquake_parse_552": False,
    }


def _message_fields_high() -> Dict[str, Any]:
    """高配模式消息相关配置覆盖项。"""
    return {
        "message_queue_maxsize": 300,
        "message_buffer_max_size": 100,
        "enable_china_intensity": True,
        "enable_felt_alert_flow": False,
        "enable_strong_felt_alert_flow": True,
        "fanstudio_parse_warning": True,
        "fanstudio_parse_report": True,
        "fanstudio_parse_cea": True,
        "fanstudio_parse_cea_pr": True,
        "fanstudio_parse_cwa_eew": True,
        "fanstudio_parse_jma": True,
        "fanstudio_parse_sa": True,
        "fanstudio_parse_kma_eew": True,
        "fanstudio_parse_cenc": True,
        "fanstudio_parse_ningxia": True,
        "fanstudio_parse_guangxi": True,
        "fanstudio_parse_shanxi": True,
        "fanstudio_parse_beijing": True,
        "fanstudio_parse_yunnan": True,
        "fanstudio_parse_cwa": True,
        "fanstudio_parse_hko": True,
        "fanstudio_parse_usgs": True,
        "fanstudio_parse_emsc": True,
        "fanstudio_parse_bcsf": True,
        "fanstudio_parse_gfz": True,
        "fanstudio_parse_usp": True,
        "fanstudio_parse_kma": True,
        "fanstudio_parse_fssn": True,
        "fanstudio_parse_fssn_cmt": True,
        "fanstudio_parse_weatheralarm": True,
        "fanstudio_parse_tsunami": True,
        "whews_parse_jma_eew": True,
        "whews_parse_cwa_eew": True,
        "whews_parse_sa_eew": True,
        "whews_parse_kma_eew": True,
        "whews_parse_cea": True,
        "whews_parse_cea_pr": True,
        "whews_parse_cenc": True,
        "whews_parse_cwa": True,
        "whews_parse_hko": True,
        "whews_parse_usgs": True,
        "whews_parse_emsc": True,
        "whews_parse_bcsf": True,
        "whews_parse_gfz": True,
        "whews_parse_usp": True,
        "whews_parse_kma": True,
        "whews_parse_bmkg": True,
        "whews_parse_geonet": True,
        "whews_parse_tmd": True,
        "whews_parse_ingv": True,
        "whews_parse_nrcan": True,
        "whews_parse_mmd": True,
        "whews_parse_beijing": True,
        "whews_parse_yunnan": True,
        "whews_parse_ningxia": True,
        "whews_parse_jma_volcano": True,
        "whews_parse_tsunami": True,
        "whews_parse_ntwc": True,
        "whews_parse_ptwc": True,
        "whews_parse_incois": True,
        "whews_parse_jma_tsunami": True,
        "whews_parse_phivolcs": True,
        "whews_parse_sgc": True,
        "whews_parse_ga": True,
        "whews_parse_cenais": True,
        "whews_parse_weatheralarm": True,
        "ali_all_parse_nied": True,
        "ali_all_parse_early_est": True,
        "ali_all_parse_jma_volcano": True,
        "ali_all_parse_bmkg": True,
        "ali_all_parse_cq_eew": True,
        "p2pquake_parse_551": True,
        "p2pquake_parse_552": True,
    }


def _gui_fields_low() -> Dict[str, Any]:
    """低配模式 GUI 相关配置覆盖项。"""
    return {
        "render_backend": "cpu",
        "use_gpu_rendering": False,
        "target_fps": 30,
        "vsync_enabled": False,
        "toast_notifications_enabled": False,
        "minimize_to_tray": False,
        "auto_update_check_on_startup": False,
    }


def _gui_fields_high() -> Dict[str, Any]:
    """高配模式 GUI 相关配置覆盖项。"""
    return {
        "render_backend": "opengl",
        "use_gpu_rendering": True,
        "target_fps": 60,
        "vsync_enabled": True,
        "toast_notifications_enabled": True,
        "minimize_to_tray": True,
        "auto_update_check_on_startup": True,
    }


def _alert_fields_low() -> Dict[str, Any]:
    """低配模式告警反馈配置覆盖项（默认关闭声音/TTS）。"""
    return {
        "enabled": False,
        "alert_feedback_mode": "sound",
        "felt_sound_enabled": False,
        "critical_sound_enabled": False,
        "sound_enabled": False,
        "felt_tts_enabled": False,
        "critical_tts_enabled": False,
        "weather_tts_enabled": False,
        "tsunami_tts_enabled": False,
    }


def _alert_fields_high() -> Dict[str, Any]:
    """高配模式告警反馈配置覆盖项。"""
    return {
        "enabled": True,
        "alert_feedback_mode": "sound",
        "felt_sound_enabled": True,
        "critical_sound_enabled": True,
        "sound_enabled": True,
        "felt_tts_enabled": False,
        "critical_tts_enabled": False,
    }


def _translation_fields_low() -> Dict[str, Any]:
    """低配模式翻译/地名修正配置覆盖项。"""
    return {
        "enabled": False,
        "use_place_name_fix": True,
    }


def _translation_fields_high() -> Dict[str, Any]:
    """高配模式翻译/地名修正配置覆盖项。"""
    return {
        "enabled": False,
        "use_place_name_fix": True,
    }


def get_preset_payload(mode: str) -> Dict[str, Any]:
    """返回指定性能模式的配置覆盖项（不含 custom）。"""
    if mode == PERFORMANCE_MODE_LOW:
        return {
            "gui": _gui_fields_low(),
            "message": _message_fields_low(),
            "alert": _alert_fields_low(),
            "translation": _translation_fields_low(),
            "enabled_sources": _low_enabled_sources(),
            "http_poll_intervals": _scale_http_poll_intervals(2.5),
        }
    if mode == PERFORMANCE_MODE_STANDARD:
        return {
            "gui": {
                "render_backend": "cpu",
                "use_gpu_rendering": False,
                "target_fps": 60,
                "vsync_enabled": True,
                "toast_notifications_enabled": False,
                "minimize_to_tray": False,
                "auto_update_check_on_startup": True,
            },
            "message": {},
            "alert": {},
            "translation": {},
            "enabled_sources": _base_enabled_sources(),
            "http_poll_intervals": dict(DEFAULT_HTTP_POLL_INTERVALS),
        }
    if mode == PERFORMANCE_MODE_HIGH:
        return {
            "gui": _gui_fields_high(),
            "message": _message_fields_high(),
            "alert": _alert_fields_high(),
            "translation": _translation_fields_high(),
            "enabled_sources": _high_enabled_sources(),
            "http_poll_intervals": dict(DEFAULT_HTTP_POLL_INTERVALS),
        }
    raise ValueError(f"未知性能模式: {mode}")


def _data_source_snapshot(config) -> tuple:
    """采集当前数据源开关与解析标志的快照，用于检测预设应用后连接范围是否变化。"""
    mc = config.message_config
    flags = (
        getattr(mc, "use_custom_text", False),
        getattr(mc, "fanstudio_parse_cea", True),
        getattr(mc, "fanstudio_parse_cea_pr", True),
        getattr(mc, "fanstudio_parse_cwa_eew", True),
        getattr(mc, "fanstudio_parse_jma", True),
        getattr(mc, "fanstudio_parse_sa", True),
        getattr(mc, "fanstudio_parse_kma_eew", True),
        getattr(mc, "fanstudio_parse_cenc", True),
        getattr(mc, "fanstudio_parse_ningxia", True),
        getattr(mc, "fanstudio_parse_guangxi", True),
        getattr(mc, "fanstudio_parse_shanxi", True),
        getattr(mc, "fanstudio_parse_beijing", True),
        getattr(mc, "fanstudio_parse_yunnan", True),
        getattr(mc, "fanstudio_parse_cwa", True),
        getattr(mc, "fanstudio_parse_hko", True),
        getattr(mc, "fanstudio_parse_usgs", True),
        getattr(mc, "fanstudio_parse_emsc", True),
        getattr(mc, "fanstudio_parse_bcsf", True),
        getattr(mc, "fanstudio_parse_gfz", True),
        getattr(mc, "fanstudio_parse_usp", True),
        getattr(mc, "fanstudio_parse_kma", True),
        getattr(mc, "fanstudio_parse_fssn", True),
        getattr(mc, "fanstudio_parse_fssn_cmt", True),
        getattr(mc, "fanstudio_parse_weatheralarm", True),
        getattr(mc, "fanstudio_parse_tsunami", True),
        getattr(mc, "whews_parse_jma_eew", True),
        getattr(mc, "whews_parse_cwa_eew", True),
        getattr(mc, "whews_parse_sa_eew", True),
        getattr(mc, "whews_parse_kma_eew", True),
        getattr(mc, "whews_parse_cea", True),
        getattr(mc, "whews_parse_cea_pr", True),
        getattr(mc, "whews_parse_cenc", True),
        getattr(mc, "whews_parse_cwa", True),
        getattr(mc, "whews_parse_hko", True),
        getattr(mc, "whews_parse_usgs", True),
        getattr(mc, "whews_parse_emsc", True),
        getattr(mc, "whews_parse_bcsf", True),
        getattr(mc, "whews_parse_gfz", True),
        getattr(mc, "whews_parse_usp", True),
        getattr(mc, "whews_parse_kma", True),
        getattr(mc, "whews_parse_bmkg", True),
        getattr(mc, "whews_parse_geonet", True),
        getattr(mc, "whews_parse_tmd", True),
        getattr(mc, "whews_parse_ingv", True),
        getattr(mc, "whews_parse_nrcan", True),
        getattr(mc, "whews_parse_mmd", True),
        getattr(mc, "whews_parse_beijing", True),
        getattr(mc, "whews_parse_yunnan", True),
        getattr(mc, "whews_parse_ningxia", True),
        getattr(mc, "whews_parse_jma_volcano", True),
        getattr(mc, "whews_parse_tsunami", True),
        getattr(mc, "whews_parse_ntwc", True),
        getattr(mc, "whews_parse_ptwc", True),
        getattr(mc, "whews_parse_incois", True),
        getattr(mc, "whews_parse_jma_tsunami", True),
        getattr(mc, "whews_parse_phivolcs", True),
        getattr(mc, "whews_parse_sgc", True),
        getattr(mc, "whews_parse_ga", True),
        getattr(mc, "whews_parse_cenais", True),
        getattr(mc, "whews_parse_weatheralarm", True),
        getattr(mc, "ali_all_parse_nied", True),
        getattr(mc, "ali_all_parse_early_est", True),
        getattr(mc, "ali_all_parse_jma_volcano", True),
        getattr(mc, "ali_all_parse_bmkg", True),
        getattr(mc, "ali_all_parse_cq_eew", True),
        getattr(mc, "p2pquake_parse_551", True),
        getattr(mc, "p2pquake_parse_552", True),
    )
    return (
        tuple(config.ws_urls),
        tuple(sorted(config.enabled_sources.items())),
        (config.custom_data_source_url or "").strip(),
        getattr(config, "data_provider", "fanstudio"),
        flags,
    )


def apply_performance_preset(config, mode: str) -> Dict[str, Any]:
    """
    将性能预设写入 Config 实例。

    Returns:
        dict: render_backend_changed, sources_changed, needs_restart（恒为 False，已改为热重载）
    """
    if mode not in (
        PERFORMANCE_MODE_LOW,
        PERFORMANCE_MODE_STANDARD,
        PERFORMANCE_MODE_HIGH,
    ):
        raise ValueError(f"无法应用性能模式: {mode}")

    old_backend = getattr(config.gui_config, "render_backend", "cpu") or "cpu"
    old_sources_snapshot = _data_source_snapshot(config)
    payload = get_preset_payload(mode)

    for key, value in payload.get("gui", {}).items():
        if hasattr(config.gui_config, key):
            setattr(config.gui_config, key, value)

    for key, value in payload.get("message", {}).items():
        if hasattr(config.message_config, key):
            setattr(config.message_config, key, value)

    if mode == PERFORMANCE_MODE_STANDARD:
        from config import AlertConfig, MessageConfig

        defaults_msg = MessageConfig()
        defaults_alert = AlertConfig()
        for field_name in (
            "message_queue_maxsize",
            "message_buffer_max_size",
            "enable_china_intensity",
            "enable_felt_alert_flow",
            "enable_strong_felt_alert_flow",
        ):
            if hasattr(config.message_config, field_name):
                setattr(config.message_config, field_name, getattr(defaults_msg, field_name))
        for field_name in (
            "fanstudio_parse_warning",
            "fanstudio_parse_report",
            "fanstudio_parse_cea",
            "fanstudio_parse_cea_pr",
            "fanstudio_parse_cwa_eew",
            "fanstudio_parse_jma",
            "fanstudio_parse_sa",
            "fanstudio_parse_kma_eew",
            "fanstudio_parse_cenc",
            "fanstudio_parse_ningxia",
            "fanstudio_parse_guangxi",
            "fanstudio_parse_shanxi",
            "fanstudio_parse_beijing",
            "fanstudio_parse_yunnan",
            "fanstudio_parse_cwa",
            "fanstudio_parse_hko",
            "fanstudio_parse_usgs",
            "fanstudio_parse_emsc",
            "fanstudio_parse_bcsf",
            "fanstudio_parse_gfz",
            "fanstudio_parse_usp",
            "fanstudio_parse_kma",
            "fanstudio_parse_fssn",
            "fanstudio_parse_fssn_cmt",
            "fanstudio_parse_weatheralarm",
            "fanstudio_parse_tsunami",
            "whews_parse_jma_eew",
            "whews_parse_cwa_eew",
            "whews_parse_sa_eew",
            "whews_parse_kma_eew",
            "whews_parse_cea",
            "whews_parse_cea_pr",
            "whews_parse_cenc",
            "whews_parse_cwa",
            "whews_parse_hko",
            "whews_parse_usgs",
            "whews_parse_emsc",
            "whews_parse_bcsf",
            "whews_parse_gfz",
            "whews_parse_usp",
            "whews_parse_kma",
            "whews_parse_bmkg",
            "whews_parse_geonet",
            "whews_parse_tmd",
            "whews_parse_ingv",
            "whews_parse_nrcan",
            "whews_parse_mmd",
            "whews_parse_beijing",
            "whews_parse_yunnan",
            "whews_parse_ningxia",
            "whews_parse_jma_volcano",
            "whews_parse_tsunami",
            "whews_parse_ntwc",
            "whews_parse_ptwc",
            "whews_parse_incois",
            "whews_parse_jma_tsunami",
            "whews_parse_phivolcs",
            "whews_parse_sgc",
            "whews_parse_ga",
            "whews_parse_cenais",
            "whews_parse_weatheralarm",
            "ali_all_parse_nied",
            "ali_all_parse_early_est",
            "ali_all_parse_jma_volcano",
            "ali_all_parse_bmkg",
            "ali_all_parse_cq_eew",
            "p2pquake_parse_551",
            "p2pquake_parse_552",
        ):
            if hasattr(config.message_config, field_name):
                setattr(config.message_config, field_name, getattr(defaults_msg, field_name))
        for field_name in (
            "enabled",
            "alert_feedback_mode",
            "felt_sound_enabled",
            "critical_sound_enabled",
            "sound_enabled",
            "felt_tts_enabled",
            "critical_tts_enabled",
            "weather_tts_enabled",
            "tsunami_tts_enabled",
        ):
            if hasattr(config.alert_config, field_name):
                setattr(config.alert_config, field_name, getattr(defaults_alert, field_name))

    for key, value in payload.get("alert", {}).items():
        if hasattr(config.alert_config, key):
            setattr(config.alert_config, key, value)

    for key, value in payload.get("translation", {}).items():
        if hasattr(config.translation_config, key):
            setattr(config.translation_config, key, value)

    for url, enabled in payload.get("enabled_sources", {}).items():
        config.enabled_sources[url] = enabled

    config._sync_p2pquake_http_with_wss()
    config._ensure_new_http_source_defaults()

    poll_overrides = payload.get("http_poll_intervals") or {}
    for url, interval in poll_overrides.items():
        config.http_poll_intervals[url] = max(1, int(interval))
    config._ensure_http_poll_interval_defaults()

    config.gui_config.performance_mode = mode
    config.gui_config.validate()
    config.message_config.validate()
    config.alert_config.validate()
    config.translation_config.validate()

    config.ws_urls = config._build_ws_urls_ordered()
    new_sources_snapshot = _data_source_snapshot(config)

    render_backend_changed = old_backend != config.gui_config.render_backend
    sources_changed = old_sources_snapshot != new_sources_snapshot

    return {
        "render_backend_changed": render_backend_changed,
        "sources_changed": sources_changed,
        "needs_restart": False,
        "mode": mode,
    }
