#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块 - 优化版
负责加载和管理应用程序配置，支持动态重载和验证
"""

import json
import os
import threading
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from pathlib import Path

from utils.logger import get_logger

logger = get_logger()

# 非 Fan Studio 的 WebSocket 数据源固定顺序（与轮播优先级一致，确保顺序不变）
# Wolfx 聚合源 wss://ws-api.wolfx.jp/all_eew
P2PQUAKE_WSS_URL = "wss://api.p2pquake.net/v2/ws"  # P2PQuake 地震情报 WSS 总开关
WS_URL_CANONICAL_ORDER: List[str] = [  # 公开版固定连接顺序
    "wss://ws.fanstudio.tech/cenc-ir",  # 烈度速报优先
    P2PQUAKE_WSS_URL,  # P2PQuake WSS
    "wss://ws-api.wolfx.jp/all_eew",  # Wolfx 聚合预警
    "wss://ws-api.wolfx.jp/cwa_eew",  # Wolfx CWA 单独通道
]
P2PQUAKE_HTTP_SOURCE_KEYS: List[str] = [  # P2PQuake 启动前/按需 HTTP 拉取
    "https://api.p2pquake.net/v2/history?codes=551&limit=3",
    "https://api.p2pquake.net/v2/jma/tsunami?limit=1",
]

FANSTUDIO_HTTP_SOURCE_KEYS: List[str] = [
    "https://api.fanstudio.tech/we/typhoon.php",
    "https://api.fanstudio.tech/we/aqi.php",
]

BMKG_HTTP_URL = "https://data.bmkg.go.id/DataMKG/TEWS/gempaterkini.json"
GEONET_HTTP_URL = "https://api.geonet.org.nz/quake?MMI=-1"
INGV_HTTP_URL = "https://api.terraquakeapi.com/v1/earthquakes/recent?limit=5"
EARLYEST_HTTP_URL = "http://early-est.rm.ingv.it/hypomessage.html"
JMA_ATOM_LONG_URL = "https://www.data.jma.go.jp/developer/xml/feed/eqvol_l.xml"
PTWC_CAP_URL = "https://www.tsunami.gov/events/xml/PHEBCAP.xml"
PTWC_CAP_URL_LEGACY = "https://www.tsunami.gov/events/xml/PAAQ42.xml"

NEW_HTTP_SOURCE_KEYS: List[str] = [
    BMKG_HTTP_URL,
    GEONET_HTTP_URL,
    INGV_HTTP_URL,
    EARLYEST_HTTP_URL,
    JMA_ATOM_LONG_URL,
    PTWC_CAP_URL,
]

# 各 HTTP 数据源默认轮询间隔（秒）
DEFAULT_HTTP_POLL_INTERVALS: Dict[str, int] = {
    BMKG_HTTP_URL: 30,
    GEONET_HTTP_URL: 30,
    INGV_HTTP_URL: 30,
    EARLYEST_HTTP_URL: 5,
    JMA_ATOM_LONG_URL: 1800,
    PTWC_CAP_URL: 60,
    "https://api.fanstudio.tech/we/typhoon.php": 600,
    "https://api.fanstudio.tech/we/aqi.php": 1800,
    "https://api.p2pquake.net/v2/history?codes=551&limit=3": 2,
    "https://api.p2pquake.net/v2/jma/tsunami?limit=1": 2,
}

ALL_KNOWN_HTTP_SOURCE_KEYS: List[str] = (
    P2PQUAKE_HTTP_SOURCE_KEYS + FANSTUDIO_HTTP_SOURCE_KEYS + NEW_HTTP_SOURCE_KEYS
)


def p2pquake_master_enabled(enabled_sources: Dict[str, Any]) -> bool:
    """
    P2PQuake 总开关：与设置页「P2PQuake（HTTP + WebSocket）」一致。
    以 WSS 项为唯一真值；配置加载时会将两条 HTTP 项同步为与此相同。
    """
    if not isinstance(enabled_sources, dict):
        return False
    return bool(enabled_sources.get(P2PQUAKE_WSS_URL, False))

# 应用版本号（用于更新说明弹窗“仅展示一次”及关于页）
APP_VERSION = "2.6.4"  # 当前程序版本

# 自动更新清单默认 URL（可在设置-关于中修改）
AUTO_UPDATE_MANIFEST_URL_DEFAULT = "https://sismotide.top/rolling-update/manifest.json"  # 默认更新清单地址

# 更新说明（关于页/首次启动弹窗展示，当前版本仅展示一次）
# 每次修改 APP_VERSION 时，请同步修改下方 CHANGELOG_TEXT 的版本标题与更新条目。
CHANGELOG_TEXT = """版本 2.6.4

1、修复预设音频多次重复播放问题"""

# 应用声明（更新说明弹窗与设置-关于页共用；修改时请两处效果一致）
APP_DECLARATION_TEXT = (
    "本软件依托第三方接口获取数据，内容时效性、准确性不作保证\n"
    "所有参考内容仅作娱乐查阅使用，官方公告为最终标准！\n"
    "严禁盗用、转载及各类商业化牟利使用！\n"
    "本软件为免费开源软件，严禁任何形式的收费行为！"
)

@dataclass
class GUIConfig:
    """GUI配置类"""
    font_size: int = 40
    font_family: str = "SimSun"
    font_bold: bool = False
    font_italic: bool = False
    text_speed: float = 4.0
    bg_color: str = 'black'
    info_color: str = '#01FF00'
    opacity: float = 1.0
    window_width: int = 1000
    window_height: int = 100
    # 主窗口位置：均为 -1 表示从未保存，启动时居中；否则为上次关闭时的坐标（支持多屏负坐标）
    window_x: int = -1
    window_y: int = -1
    resizable: bool = True
    vsync_enabled: bool = True  # 垂直同步开关
    target_fps: int = 60  # 目标帧率
    timezone: str = "Asia/Shanghai"  # 显示时区（IANA 名称），默认北京时间
    last_seen_changelog_version: str = ""  # 上次已读的更新说明版本，用于弹窗仅展示一次
    use_gpu_rendering: bool = False  # True=GPU 渲染，False=CPU(软件) 渲染，与 render_backend 同步
    render_backend: str = "cpu"  # "cpu" | "opengl"，默认 cpu
    always_on_top: bool = False  # 窗口置顶
    watermark_text: str = ""  # 背景水印文字，空则不显示
    watermark_angle: str = "horizontal"  # 水印方向："horizontal" 横向，"45" 斜向45度
    watermark_font_family: str = ""  # 水印字体族名，空表示跟随主字体
    watermark_font_size: int = 0  # 水印字体大小，0 表示自动（按主字体比例）
    watermark_position: str = "diagonal"  # 水印位置: diagonal | top_left | top_right | bottom_left | bottom_right
    # 自动更新（仅 PyInstaller 打包 exe 生效；启动时拉取清单比对 APP_VERSION）
    auto_update_check_on_startup: bool = True
    auto_update_upgrade_only: bool = True  # True：仅当服务器版本高于本地时更新；False：版本不一致即更新（含降级）
    auto_update_manifest_url: str = AUTO_UPDATE_MANIFEST_URL_DEFAULT
    auto_update_timeout_seconds: int = 15
    auto_update_package_kind: str = "installer"  # installer | zip（zip 为便携目录结构，与一键打包 onedir 一致）
    # 启动时「发现新版本」弹窗用户点否后记录的服务器版本，避免同版本每次启动反复询问
    last_dismissed_update_offer_version: str = ""
    minimize_to_tray: bool = False
    toast_notifications_enabled: bool = False
    performance_mode: str = "standard"  # low | standard | high | custom
    auto_save_settings: bool = False  # Auto-save settings window changes to disk

    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            assert 10 <= self.font_size <= 100, "字体大小必须在10-100之间"
            assert 0.1 <= self.text_speed <= 20.0, "滚动速度必须在0.1-20.0之间"
            assert 0.1 <= self.opacity <= 1.0, "透明度必须在0.1-1.0之间"
            # 窗口尺寸不受系统分辨率限制，允许超出屏幕；仅做合理范围校验
            assert 800 <= self.window_width <= 20000, "窗口宽度必须在800-20000之间"
            assert 100 <= self.window_height <= 5000, "窗口高度必须在100-5000之间"
            wx = getattr(self, "window_x", -1)
            wy = getattr(self, "window_y", -1)
            for name, v in (("window_x", wx), ("window_y", wy)):
                if v != -1 and not (-32768 <= v <= 32767):
                    logger.warning(f"{name}={v} 超出范围，重置为 -1")
                    setattr(self, name, -1)
            if (getattr(self, "window_x", -1) == -1) != (getattr(self, "window_y", -1) == -1):
                self.window_x, self.window_y = -1, -1
            assert 1 <= self.target_fps <= 240, "目标帧率必须在1-240之间"
            assert self.render_backend in ("cpu", "opengl"), "render_backend 必须为 cpu 或 opengl"
            pm = (getattr(self, "performance_mode", "standard") or "standard").strip().lower()
            if pm not in ("low", "standard", "high", "custom"):
                pm = "standard"
            self.performance_mode = pm
            if getattr(self, 'watermark_angle', 'horizontal') not in ("horizontal", "45"):
                self.watermark_angle = "horizontal"
            try:
                if getattr(self, 'watermark_font_size', 0) < 0:
                    self.watermark_font_size = 0
            except Exception:
                self.watermark_font_size = 0
            allowed_positions = {"diagonal", "top_left", "top_right", "bottom_left", "bottom_right"}
            if getattr(self, 'watermark_position', 'diagonal') not in allowed_positions:
                self.watermark_position = "diagonal"
            if getattr(self, 'auto_update_package_kind', 'installer') not in ('installer', 'zip'):
                self.auto_update_package_kind = 'installer'
            try:
                tout = int(getattr(self, 'auto_update_timeout_seconds', 15))
                if tout < 5 or tout > 120:
                    self.auto_update_timeout_seconds = 15
            except (TypeError, ValueError):
                self.auto_update_timeout_seconds = 15
            mu = (getattr(self, 'auto_update_manifest_url', '') or '').strip()
            if not mu:
                self.auto_update_manifest_url = AUTO_UPDATE_MANIFEST_URL_DEFAULT
            elif len(mu) > 2048:
                self.auto_update_manifest_url = mu[:2048]
            else:
                self.auto_update_manifest_url = mu
            return True
        except AssertionError as e:
            logger.error(f"GUI配置验证失败: {e}")
            return False


@dataclass
class MessageConfig:
    """消息处理配置"""
    max_message_length: int = 0
    display_duration: int = 0
    # 预警无活动时长（秒）：自最后一次收到该事件更新报起，超过此时长且无更新则视为过期（默认 10 分钟）
    max_warning_inactivity_time: int = 600
    # 预警按发震时间的有效期（秒）：超过此时长的预警入队时丢弃、展示时移除，默认 5 分钟
    warning_shock_validity_seconds: int = 300
    # Wolfx JMA 预警的发震时间有效期（秒），默认 5 分钟
    warning_shock_validity_seconds_nied: int = 300
    # Wolfx 四川地震局预警的发震时间有效期（秒），默认 10 分钟
    warning_shock_validity_seconds_early_est: int = 600
    # 预警最少展示时长（秒）：一旦展示则在此时间内不因发震时间过期被移除，默认 5 分钟
    warning_min_display_seconds: int = 300
    # 测试用：为 True 时跳过发震时间窗口与「展示满最少时长即移除」等过期判定（勿在生产长期开启）
    disable_warning_expiry_for_test: bool = False
    max_report_inactivity_time: int = 300
    max_other_inactivity_time: int = 300
    # 主线程消息队列与展示缓冲区容量（缓解高并发时丢消息）
    message_queue_maxsize: int = 300
    message_buffer_max_size: int = 100
    no_activity_message: str = '系统运行中，等待最新地震信息...'
    custom_text: str = '系统运行中，等待最新地震信息...'
    use_custom_text: bool = False  # True=自定义文本模式(与地震速报二选一)，False=地震速报模式
    # Fan Studio All 数据源：勾选则解析对应类型，不勾选则不解析（不写单项 URL）
    fanstudio_parse_warning: bool = True  # 勾选则解析所有预警数据源
    fanstudio_parse_report: bool = True   # 勾选则解析所有速报数据源（含气象预警）
    # Wolfx 聚合源 (ws-api.wolfx.jp/all_eew)：勾选则解析对应子源，不勾选则不解析
    ali_all_parse_nied: bool = True         # 解析 JMA 緊急地震速報
    ali_all_parse_early_est: bool = True    # 解析 四川省地震局预警
    ali_all_parse_jma_volcano: bool = True  # 解析 福建省地震局预警
    ali_all_parse_bmkg: bool = True         # 解析 中国地震台网地震预警
    ali_all_parse_cq_eew: bool = True       # 解析 重庆市地震局预警
    warning_color: str = '#FF0000'  # 红色
    report_color: str = '#00FFFF'  # 青色
    custom_text_color: str = '#01FF00'  # 自定义文本颜色（绿色，与默认颜色一致）
    default_color: str = '#01FF00'
    weather_warning_color: str = '#FFF500'
    # 收到预警更新报立即切换：开启则同事件更新报立即打断并替换，否则仅后台替换；默认关闭
    show_one_alert_per_received: bool = False
    # 强制单行：将数据源中的换行符替换为空格，保证滚动字幕单行显示；默认开启
    force_single_line: bool = True
    # 预警后限时显示速报再回自定义：仅在「自定义文本」模式下生效；速报连续显示 custom_text_return_seconds 秒后自动恢复为仅显示自定义文本
    custom_text_return_after_warning: bool = False
    custom_text_return_seconds: int = 300  # 限时秒数，默认 5 分钟；仅当 custom_text_return_after_warning 为 True 时生效
    # 中国经验烈度与有感/强有感红屏流程
    enable_china_intensity: bool = False  # 是否启用中国预估烈度算法
    enable_felt_alert_flow: bool = False  # 有感地震是否启用红屏提示
    enable_strong_felt_alert_flow: bool = True  # 强有感地震是否启用红屏提示
    felt_alert_stage1_ms: int = 1500  # 有感阶段一时长
    felt_alert_stage2_ms: int = 2500  # 有感阶段二时长
    strong_felt_stage1_ms: int = 1500  # 强有感阶段一时长
    strong_felt_stage2_ms: int = 2500  # 强有感阶段二时长
    alert_flash_interval_ms: int = 400  # 红色背景闪烁间隔
    # Fan Studio 单项数据源解析开关（基于 All 通道按子源细分）
    # 预警类
    fanstudio_parse_cea: bool = True
    fanstudio_parse_cea_pr: bool = True
    fanstudio_parse_cwa_eew: bool = True
    fanstudio_parse_jma: bool = True
    fanstudio_parse_sa: bool = True
    fanstudio_parse_kma_eew: bool = True
    # 速报 / 其他类
    fanstudio_parse_cenc: bool = True
    fanstudio_parse_ningxia: bool = True
    fanstudio_parse_guangxi: bool = True
    fanstudio_parse_shanxi: bool = True
    fanstudio_parse_beijing: bool = True
    fanstudio_parse_yunnan: bool = True
    fanstudio_parse_cwa: bool = True
    fanstudio_parse_hko: bool = True
    fanstudio_parse_usgs: bool = True
    fanstudio_parse_emsc: bool = True
    fanstudio_parse_bcsf: bool = True
    fanstudio_parse_gfz: bool = True
    fanstudio_parse_usp: bool = True
    fanstudio_parse_kma: bool = True
    fanstudio_parse_fssn: bool = True
    fanstudio_parse_fssn_cmt: bool = True
    fanstudio_parse_weatheralarm: bool = True
    fanstudio_parse_tsunami: bool = True
    # P2PQuake WSS：同一连接下按 code 分别控制是否解析（551 地震情報 / 552 津波予報）；HTTP 聚合拉取逻辑不变
    p2pquake_parse_551: bool = True
    p2pquake_parse_552: bool = True
    # 速报震级过滤（0 表示不限制）
    min_report_magnitude: float = 0.0
    # 关注区域过滤（以经纬度为圆心、半径 km 内才显示）
    geo_filter_enabled: bool = False
    geo_filter_latitude: float = 39.9042
    geo_filter_longitude: float = 116.4074
    geo_filter_radius_km: float = 1000.0
    # 事件历史环形缓冲容量（仅本地查看/导出，不对外推送）
    event_history_max_entries: int = 500

    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            assert self.max_message_length >= 0, "消息最大长度不能为负数"
            assert self.display_duration >= 0, "显示持续时间不能为负数"
            assert self.max_warning_inactivity_time > 0, "预警无活动时长必须大于0"
            assert self.warning_shock_validity_seconds > 0, "预警发震时间有效期必须大于0"
            if getattr(self, 'warning_shock_validity_seconds_nied', 0) <= 0:
                self.warning_shock_validity_seconds_nied = self.warning_shock_validity_seconds
            if getattr(self, 'warning_shock_validity_seconds_early_est', 0) <= 0:
                self.warning_shock_validity_seconds_early_est = max(
                    self.warning_shock_validity_seconds,
                    self.warning_shock_validity_seconds_nied,
                )
            assert self.warning_min_display_seconds > 0, "预警最少展示时长必须大于0"
            assert self.max_report_inactivity_time > 0, "速报无活动时长必须大于0"
            assert self.max_other_inactivity_time > 0, "其他消息无活动时长必须大于0"
            assert 1 <= self.custom_text_return_seconds <= 3600, "custom_text_return_seconds 必须在 1–3600 之间"
            self.disable_warning_expiry_for_test = bool(
                getattr(self, "disable_warning_expiry_for_test", False)
            )
            eh = int(getattr(self, "event_history_max_entries", 500) or 500)
            self.event_history_max_entries = max(50, min(5000, eh))
            return True
        except AssertionError as e:
            logger.error(f"消息配置验证失败: {e}")
            return False


@dataclass
class AlertConfig:
    """
    预警告警闪烁与有感/强有感提示配置。

    单位约定：
    - ``flash_interval_ms``：左侧「地震预警」条明灭间隔。
    - 提示期兜底时长由报文发震时间与 ``MessageConfig.warning_shock_validity_seconds*`` 决定，不再单独配置。
    """
    enabled: bool = False
    min_magnitude: float = 3.0
    flash_interval_ms: int = 400
    flash_scope: str = "scrolling_only"
    flash_target_screen: int = -1
    flash_color: str = "#FF0000"
    flash_max_alpha: int = 180
    sound_enabled: bool = False
    sound_path: str = ""
    sound_volume: int = 100
    sound_warnings_only: bool = True
    felt_sound_enabled: bool = False
    felt_sound_path: str = ""
    felt_sound_repeat: int = 1
    critical_sound_enabled: bool = False
    critical_sound_path: str = ""
    critical_sound_repeat: int = 1
    # 已废弃：速报不再使用预设 WAV，保留字段仅为兼容旧配置
    ciev_sound_enabled: bool = False
    ciev_sound_path: str = ""
    ciev_sound_repeat: int = 1
    nhk_news_bell_enabled: bool = False
    nhk_news_bell_path: str = ""
    nhk_news_bell_repeat: int = 1
    jma_eew_alert_sound_enabled: bool = True
    jma_eew_alert_sound_path: str = ""
    jma_eew_alert_sound_repeat: int = 2
    alert_feedback_mode: str = "sound"
    felt_tts_enabled: bool = False
    critical_tts_enabled: bool = False
    felt_tts_repeat: int = 1
    critical_tts_repeat: int = 1
    report_tts_enabled: bool = True
    report_tts_repeat: int = 1
    weather_tts_enabled: bool = True
    weather_tts_repeat: int = 1
    tsunami_tts_enabled: bool = True
    tsunami_tts_repeat: int = 1
    tts_playback_mode: str = "supplement"
    tts_rate: int = 150
    tts_voice: str = ""
    tts_include_safety_hint: bool = True
    tts_repeat_policy: str = "smart"
    tts_cooldown_seconds: int = 60
    # 预警主反馈去重：first_received=本程序首条视为内部第1报仅播一次；smart=更新报/震级变化可再播
    warning_feedback_policy: str = "first_received"

    def validate(self) -> bool:
        try:
            if self.min_magnitude < 0:
                self.min_magnitude = 0.0
            if self.flash_interval_ms < 50:
                self.flash_interval_ms = 50
            if self.flash_interval_ms > 2000:
                self.flash_interval_ms = 2000
            # 仅保留字幕条左侧「地震预警」标识闪烁，不再使用主窗口四边叠加
            self.flash_scope = "scrolling_only"
            try:
                self.flash_target_screen = int(self.flash_target_screen)
            except (TypeError, ValueError):
                self.flash_target_screen = -1
            if not isinstance(self.flash_color, str) or not self.flash_color.strip():
                self.flash_color = "#FF0000"
            if self.flash_max_alpha < 30:
                self.flash_max_alpha = 30
            if self.flash_max_alpha > 255:
                self.flash_max_alpha = 255
            self.felt_sound_path = (self.felt_sound_path or "").strip()
            self.critical_sound_path = (self.critical_sound_path or "").strip()
            self.ciev_sound_path = (self.ciev_sound_path or "").strip()
            self.nhk_news_bell_path = (self.nhk_news_bell_path or "").strip()
            self.jma_eew_alert_sound_path = (self.jma_eew_alert_sound_path or "").strip()
            try:
                self.felt_sound_repeat = int(self.felt_sound_repeat)
            except (TypeError, ValueError):
                self.felt_sound_repeat = 1
            try:
                self.critical_sound_repeat = int(self.critical_sound_repeat)
            except (TypeError, ValueError):
                self.critical_sound_repeat = 1
            try:
                self.ciev_sound_repeat = int(self.ciev_sound_repeat)
            except (TypeError, ValueError):
                self.ciev_sound_repeat = 1
            try:
                self.nhk_news_bell_repeat = int(self.nhk_news_bell_repeat)
            except (TypeError, ValueError):
                self.nhk_news_bell_repeat = 1
            try:
                self.jma_eew_alert_sound_repeat = int(self.jma_eew_alert_sound_repeat)
            except (TypeError, ValueError):
                self.jma_eew_alert_sound_repeat = 2
            self.felt_sound_repeat = max(1, min(10, self.felt_sound_repeat))
            self.critical_sound_repeat = max(1, min(10, self.critical_sound_repeat))
            self.ciev_sound_repeat = max(1, min(10, self.ciev_sound_repeat))
            self.nhk_news_bell_repeat = max(1, min(10, self.nhk_news_bell_repeat))
            self.jma_eew_alert_sound_repeat = max(1, min(10, self.jma_eew_alert_sound_repeat))
            self.alert_feedback_mode = (self.alert_feedback_mode or "sound").strip().lower()
            if self.alert_feedback_mode not in ("sound", "tts"):
                self.alert_feedback_mode = "sound"
            try:
                self.felt_tts_repeat = int(self.felt_tts_repeat)
            except (TypeError, ValueError):
                self.felt_tts_repeat = 1
            try:
                self.critical_tts_repeat = int(self.critical_tts_repeat)
            except (TypeError, ValueError):
                self.critical_tts_repeat = 1
            try:
                self.report_tts_repeat = int(self.report_tts_repeat)
            except (TypeError, ValueError):
                self.report_tts_repeat = 1
            try:
                self.weather_tts_repeat = int(self.weather_tts_repeat)
            except (TypeError, ValueError):
                self.weather_tts_repeat = 1
            try:
                self.tsunami_tts_repeat = int(self.tsunami_tts_repeat)
            except (TypeError, ValueError):
                self.tsunami_tts_repeat = 1
            self.felt_tts_repeat = max(1, min(10, self.felt_tts_repeat))
            self.critical_tts_repeat = max(1, min(10, self.critical_tts_repeat))
            self.report_tts_repeat = max(1, min(10, self.report_tts_repeat))
            self.weather_tts_repeat = max(1, min(10, self.weather_tts_repeat))
            self.tsunami_tts_repeat = max(1, min(10, self.tsunami_tts_repeat))
            self.tts_playback_mode = (self.tts_playback_mode or "supplement").strip().lower()
            if self.tts_playback_mode not in ("supplement", "replace"):
                self.tts_playback_mode = "supplement"
            self.tts_voice = (self.tts_voice or "").strip()
            self.tts_repeat_policy = (self.tts_repeat_policy or "smart").strip().lower()
            if self.tts_repeat_policy not in ("smart", "first_only", "always"):
                self.tts_repeat_policy = "smart"
            self.warning_feedback_policy = (
                self.warning_feedback_policy or "first_received"
            ).strip().lower()
            if self.warning_feedback_policy in ("first_report_only", "first_only"):
                self.warning_feedback_policy = "first_received"
            if self.warning_feedback_policy not in ("smart", "first_received"):
                self.warning_feedback_policy = "first_received"
            try:
                self.tts_rate = int(self.tts_rate)
            except (TypeError, ValueError):
                self.tts_rate = 150
            self.tts_rate = max(80, min(300, self.tts_rate))
            try:
                self.tts_cooldown_seconds = int(self.tts_cooldown_seconds)
            except (TypeError, ValueError):
                self.tts_cooldown_seconds = 60
            self.tts_cooldown_seconds = max(0, min(600, self.tts_cooldown_seconds))
            return True
        except Exception as e:
            logger.error(f"告警配置验证失败: {e}")
            return False


@dataclass
class WebSocketConfig:
    """WebSocket配置类"""
    reconnect_interval: int = 5
    max_reconnect_attempts: int = -1
    ping_interval: int = 30
    ping_timeout: int = 10
    close_timeout: int = 5
    connection_timeout: int = 10
    # 启动时相邻两路 WebSocket 建连任务之间的间隔（秒），0 表示不间隔（与旧版同时发起）
    startup_stagger_seconds: float = 1.5
    
    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            assert self.reconnect_interval > 0, "重连间隔必须大于0"
            assert self.max_reconnect_attempts >= -1, "最大重连次数必须≥-1"
            assert self.ping_interval > 0, "心跳间隔必须大于0"
            assert self.ping_timeout > 0, "心跳超时必须大于0"
            assert self.close_timeout > 0, "关闭超时必须大于0"
            assert self.connection_timeout > 0, "连接超时必须大于0"
            assert self.startup_stagger_seconds >= 0, "启动建连间隔不能为负"
            return True
        except AssertionError as e:
            logger.error(f"WebSocket配置验证失败: {e}")
            return False


@dataclass
class TranslationConfig:
    """地名处理配置：地名修正与百度翻译二选一。"""
    use_place_name_fix: bool = True  # 非中文数据源使用地名修正（与百度翻译互斥），默认开启
    enabled: bool = False  # 非中文数据源使用百度翻译（与地名修正互斥）
    baidu_app_id: str = ""  # 百度翻译开放平台 AppID
    baidu_secret: str = ""  # 百度翻译开放平台密钥
    # 兼容旧版配置（仅加载时使用，不再持久化）
    use_volcano_translation: bool = False

    def validate(self) -> bool:
        """验证配置有效性，并强制地名修正与百度翻译互斥。"""
        if self.enabled and self.use_place_name_fix:
            self.use_place_name_fix = False
        if self.enabled and not self.baidu_app_id.strip():
            logger.warning("百度翻译已启用但未配置 AppID，翻译功能将不可用")
        if self.enabled and not self.baidu_secret.strip():
            logger.warning("百度翻译已启用但未配置密钥，翻译功能将不可用")
        return True


@dataclass
class LogConfig:
    """日志配置类"""
    output_to_file: bool = True  # 是否输出日志到文件（默认开启）
    clear_log_on_startup: bool = True  # 每次程序启动前是否清空日志（默认开启）
    split_by_date: bool = False  # 是否按日期分割日志（默认关闭）
    max_log_size: int = 10  # 日志文件最大大小（MB，默认10MB）
    
    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            assert self.max_log_size > 0, "日志大小必须大于0"
            assert self.max_log_size <= 1000, "日志大小不能超过1000MB"
            return True
        except AssertionError as e:
            logger.error(f"日志配置验证失败: {e}")
            return False


class Config:
    """配置管理类 - 单例模式，支持动态重载"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Config, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        # 配置实例
        self.gui_config = GUIConfig()  # GUI 相关配置
        self.message_config = MessageConfig()
        self.alert_config = AlertConfig()
        self.ws_config = WebSocketConfig()
        self.translation_config = TranslationConfig()
        self.log_config = LogConfig()

        # 数据源配置
        self.enabled_sources: Dict[str, bool] = {}
        self.ws_urls: List[str] = []
        self.custom_data_source_url: str = ""  # 自定义数据源 URL（http/https/ws/wss），空为关闭
        self.custom_data_source_insecure_ssl: bool = False  # 自定义 HTTP 源跳过 SSL 证书校验
        self.http_poll_intervals: Dict[str, int] = dict(DEFAULT_HTTP_POLL_INTERVALS)
        
        # 配置变更回调
        self._config_callbacks: List[Callable] = []
        
        # 配置文件路径：C:\Users\账户名\AppData\Roaming\subtitl\settings.json
        # 日志文件：C:\Users\账户名\AppData\Roaming\subtitl\log.txt（或log_YYYYMMDD.txt）
        # 翻译缓存：C:\Users\账户名\AppData\Roaming\subtitl\translation_cache.json
        # 注意：日志文件和翻译缓存都在同一个文件夹（subtitl目录）中
        try:
            config_dir = Path.home() / 'AppData' / 'Roaming' / 'subtitl'
            
            # 如果目录不存在，自动创建（使用try-except避免阻塞）
            if not config_dir.exists():
                try:
                    config_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"已创建配置目录: {config_dir}")
                except (OSError, PermissionError) as e:
                    logger.warning(f"无法创建配置目录 {config_dir}: {e}，使用默认配置")
            else:
                logger.debug(f"配置目录已存在: {config_dir}")
            
            self.config_file = config_dir / 'settings.json'
        except Exception as e:
            logger.error(f"配置目录初始化失败: {e}，使用默认配置")
            self.config_file = None
        
        # 加载配置（使用try-except避免阻塞）
        try:
            self.load_config()
        except Exception as e:
            logger.error(f"配置加载失败: {e}，使用默认配置")
            self._apply_default_config()
        
        self._initialized = True
        logger.debug("配置管理器初始化完成")
    
    def add_config_callback(self, callback: Callable):
        """添加配置变更回调"""
        self._config_callbacks.append(callback)
    
    def remove_config_callback(self, callback: Callable):
        """移除配置变更回调"""
        if callback in self._config_callbacks:
            self._config_callbacks.remove(callback)
    
    def _notify_config_changed(self):
        """通知配置变更"""
        for callback in self._config_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"配置变更回调执行失败: {e}")
    
    def _get_full_config_dict(self) -> Dict[str, Any]:
        """根据当前内存中的各 config 对象生成完整配置 dict（与 save 结构一致）"""
        return {
            'config_version': APP_VERSION,
            'GUI_CONFIG': {
                'font_size': self.gui_config.font_size,
                'font_family': self.gui_config.font_family,
                'font_bold': self.gui_config.font_bold,
                'font_italic': self.gui_config.font_italic,
                'text_speed': self.gui_config.text_speed,
                'bg_color': self.gui_config.bg_color,
                'info_color': self.gui_config.info_color,
                'opacity': self.gui_config.opacity,
                'window_width': self.gui_config.window_width,
                'window_height': self.gui_config.window_height,
                'window_x': getattr(self.gui_config, 'window_x', -1),
                'window_y': getattr(self.gui_config, 'window_y', -1),
                'resizable': self.gui_config.resizable,
                'vsync_enabled': self.gui_config.vsync_enabled,
                'target_fps': self.gui_config.target_fps,
                'timezone': self.gui_config.timezone,
                'last_seen_changelog_version': self.gui_config.last_seen_changelog_version,
                'use_gpu_rendering': self.gui_config.use_gpu_rendering,
                'render_backend': self.gui_config.render_backend,
                'always_on_top': self.gui_config.always_on_top,
                'watermark_text': self.gui_config.watermark_text,
                'watermark_angle': self.gui_config.watermark_angle,
                'watermark_font_family': getattr(self.gui_config, 'watermark_font_family', ""),
                'watermark_font_size': getattr(self.gui_config, 'watermark_font_size', 0),
                'watermark_position': getattr(self.gui_config, 'watermark_position', "diagonal"),
                'auto_update_check_on_startup': getattr(self.gui_config, 'auto_update_check_on_startup', True),
                'auto_update_upgrade_only': getattr(self.gui_config, 'auto_update_upgrade_only', True),
                'auto_update_manifest_url': getattr(self.gui_config, 'auto_update_manifest_url', "") or AUTO_UPDATE_MANIFEST_URL_DEFAULT,
                'auto_update_timeout_seconds': getattr(self.gui_config, 'auto_update_timeout_seconds', 15),
                'auto_update_package_kind': getattr(self.gui_config, 'auto_update_package_kind', "installer"),
                'last_dismissed_update_offer_version': getattr(
                    self.gui_config, 'last_dismissed_update_offer_version', ""
                ),
                'minimize_to_tray': getattr(self.gui_config, 'minimize_to_tray', False),
                'toast_notifications_enabled': getattr(
                    self.gui_config, 'toast_notifications_enabled', False
                ),
                'performance_mode': getattr(self.gui_config, 'performance_mode', 'standard'),
                'auto_save_settings': getattr(self.gui_config, 'auto_save_settings', False),
            },
            'MESSAGE_CONFIG': {
                'max_message_length': self.message_config.max_message_length,
                'display_duration': self.message_config.display_duration,
                'max_warning_inactivity_time': self.message_config.max_warning_inactivity_time,
                'warning_shock_validity_seconds': self.message_config.warning_shock_validity_seconds,
                'warning_shock_validity_seconds_nied': getattr(
                    self.message_config,
                    'warning_shock_validity_seconds_nied',
                    self.message_config.warning_shock_validity_seconds,
                ),
                'warning_shock_validity_seconds_early_est': getattr(
                    self.message_config,
                    'warning_shock_validity_seconds_early_est',
                    max(
                        self.message_config.warning_shock_validity_seconds,
                        getattr(
                            self.message_config,
                            'warning_shock_validity_seconds_nied',
                            self.message_config.warning_shock_validity_seconds,
                        ),
                    ),
                ),
                'warning_min_display_seconds': self.message_config.warning_min_display_seconds,
                'disable_warning_expiry_for_test': getattr(
                    self.message_config, "disable_warning_expiry_for_test", False
                ),
                'max_report_inactivity_time': self.message_config.max_report_inactivity_time,
                'max_other_inactivity_time': self.message_config.max_other_inactivity_time,
                'message_queue_maxsize': getattr(self.message_config, 'message_queue_maxsize', 300),
                'message_buffer_max_size': getattr(self.message_config, 'message_buffer_max_size', 100),
                'no_activity_message': self.message_config.no_activity_message,
                'custom_text': self.message_config.custom_text,
                'use_custom_text': self.message_config.use_custom_text,
                'fanstudio_parse_warning': self.message_config.fanstudio_parse_warning,
                'fanstudio_parse_report': self.message_config.fanstudio_parse_report,
                'ali_all_parse_nied': getattr(self.message_config, 'ali_all_parse_nied', True),
                'ali_all_parse_early_est': getattr(self.message_config, 'ali_all_parse_early_est', True),
                'ali_all_parse_jma_volcano': getattr(self.message_config, 'ali_all_parse_jma_volcano', True),
                'ali_all_parse_bmkg': getattr(self.message_config, 'ali_all_parse_bmkg', True),
                'ali_all_parse_cq_eew': getattr(self.message_config, 'ali_all_parse_cq_eew', True),
                'p2pquake_parse_551': getattr(self.message_config, 'p2pquake_parse_551', True),
                'p2pquake_parse_552': getattr(self.message_config, 'p2pquake_parse_552', True),
                'warning_color': self.message_config.warning_color,
                'report_color': self.message_config.report_color,
                'custom_text_color': self.message_config.custom_text_color,
                'default_color': self.message_config.default_color,
                'weather_warning_color': self.message_config.weather_warning_color,
                'show_one_alert_per_received': self.message_config.show_one_alert_per_received,
                'force_single_line': getattr(self.message_config, 'force_single_line', True),
                'custom_text_return_after_warning': getattr(self.message_config, 'custom_text_return_after_warning', False),
                'custom_text_return_seconds': getattr(self.message_config, 'custom_text_return_seconds', 300),
                'enable_china_intensity': getattr(self.message_config, 'enable_china_intensity', False),
                'enable_felt_alert_flow': getattr(self.message_config, 'enable_felt_alert_flow', False),
                'enable_strong_felt_alert_flow': getattr(self.message_config, 'enable_strong_felt_alert_flow', True),
                'felt_alert_stage1_ms': getattr(self.message_config, 'felt_alert_stage1_ms', 1500),
                'felt_alert_stage2_ms': getattr(self.message_config, 'felt_alert_stage2_ms', 2500),
                'strong_felt_stage1_ms': getattr(self.message_config, 'strong_felt_stage1_ms', 1500),
                'strong_felt_stage2_ms': getattr(self.message_config, 'strong_felt_stage2_ms', 2500),
                'alert_flash_interval_ms': getattr(self.message_config, 'alert_flash_interval_ms', 400),
                # Fan Studio 子源细粒度开关
                'fanstudio_parse_cea': getattr(self.message_config, 'fanstudio_parse_cea', True),
                'fanstudio_parse_cea_pr': getattr(self.message_config, 'fanstudio_parse_cea_pr', True),
                'fanstudio_parse_cwa_eew': getattr(self.message_config, 'fanstudio_parse_cwa_eew', True),
                'fanstudio_parse_jma': getattr(self.message_config, 'fanstudio_parse_jma', True),
                'fanstudio_parse_sa': getattr(self.message_config, 'fanstudio_parse_sa', True),
                'fanstudio_parse_kma_eew': getattr(self.message_config, 'fanstudio_parse_kma_eew', True),
                'fanstudio_parse_cenc': getattr(self.message_config, 'fanstudio_parse_cenc', True),
                'fanstudio_parse_ningxia': getattr(self.message_config, 'fanstudio_parse_ningxia', True),
                'fanstudio_parse_guangxi': getattr(self.message_config, 'fanstudio_parse_guangxi', True),
                'fanstudio_parse_shanxi': getattr(self.message_config, 'fanstudio_parse_shanxi', True),
                'fanstudio_parse_beijing': getattr(self.message_config, 'fanstudio_parse_beijing', True),
                'fanstudio_parse_yunnan': getattr(self.message_config, 'fanstudio_parse_yunnan', True),
                'fanstudio_parse_cwa': getattr(self.message_config, 'fanstudio_parse_cwa', True),
                'fanstudio_parse_hko': getattr(self.message_config, 'fanstudio_parse_hko', True),
                'fanstudio_parse_usgs': getattr(self.message_config, 'fanstudio_parse_usgs', True),
                'fanstudio_parse_emsc': getattr(self.message_config, 'fanstudio_parse_emsc', True),
                'fanstudio_parse_bcsf': getattr(self.message_config, 'fanstudio_parse_bcsf', True),
                'fanstudio_parse_gfz': getattr(self.message_config, 'fanstudio_parse_gfz', True),
                'fanstudio_parse_usp': getattr(self.message_config, 'fanstudio_parse_usp', True),
                'fanstudio_parse_kma': getattr(self.message_config, 'fanstudio_parse_kma', True),
                'fanstudio_parse_fssn': getattr(self.message_config, 'fanstudio_parse_fssn', True),
                'fanstudio_parse_fssn_cmt': getattr(self.message_config, 'fanstudio_parse_fssn_cmt', True),
                'fanstudio_parse_weatheralarm': getattr(self.message_config, 'fanstudio_parse_weatheralarm', True),
                'fanstudio_parse_tsunami': getattr(self.message_config, 'fanstudio_parse_tsunami', True),
                'min_report_magnitude': getattr(self.message_config, 'min_report_magnitude', 0.0),
                'geo_filter_enabled': getattr(self.message_config, 'geo_filter_enabled', False),
                'geo_filter_latitude': getattr(self.message_config, 'geo_filter_latitude', 39.9042),
                'geo_filter_longitude': getattr(self.message_config, 'geo_filter_longitude', 116.4074),
                'geo_filter_radius_km': getattr(self.message_config, 'geo_filter_radius_km', 1000.0),
                'event_history_max_entries': getattr(
                    self.message_config, 'event_history_max_entries', 500
                ),
            },
            'ALERT_CONFIG': {
                'enabled': self.alert_config.enabled,
                'min_magnitude': self.alert_config.min_magnitude,
                'flash_interval_ms': self.alert_config.flash_interval_ms,
                'flash_scope': self.alert_config.flash_scope,
                'flash_target_screen': self.alert_config.flash_target_screen,
                'flash_color': self.alert_config.flash_color,
                'flash_max_alpha': self.alert_config.flash_max_alpha,
                'sound_enabled': getattr(self.alert_config, 'sound_enabled', False),
                'sound_path': getattr(self.alert_config, 'sound_path', ''),
                'sound_volume': getattr(self.alert_config, 'sound_volume', 100),
                'sound_warnings_only': getattr(self.alert_config, 'sound_warnings_only', True),
                'felt_sound_enabled': getattr(self.alert_config, 'felt_sound_enabled', False),
                'felt_sound_path': getattr(self.alert_config, 'felt_sound_path', ''),
                'felt_sound_repeat': getattr(self.alert_config, 'felt_sound_repeat', 1),
                'critical_sound_enabled': getattr(self.alert_config, 'critical_sound_enabled', False),
                'critical_sound_path': getattr(self.alert_config, 'critical_sound_path', ''),
                'critical_sound_repeat': getattr(self.alert_config, 'critical_sound_repeat', 1),
                'ciev_sound_enabled': getattr(self.alert_config, 'ciev_sound_enabled', False),
                'ciev_sound_path': getattr(self.alert_config, 'ciev_sound_path', ''),
                'ciev_sound_repeat': getattr(self.alert_config, 'ciev_sound_repeat', 1),
                'nhk_news_bell_enabled': getattr(self.alert_config, 'nhk_news_bell_enabled', False),
                'nhk_news_bell_path': getattr(self.alert_config, 'nhk_news_bell_path', ''),
                'nhk_news_bell_repeat': getattr(self.alert_config, 'nhk_news_bell_repeat', 1),
                'jma_eew_alert_sound_enabled': getattr(self.alert_config, 'jma_eew_alert_sound_enabled', True),
                'jma_eew_alert_sound_path': getattr(self.alert_config, 'jma_eew_alert_sound_path', ''),
                'jma_eew_alert_sound_repeat': getattr(self.alert_config, 'jma_eew_alert_sound_repeat', 2),
                'alert_feedback_mode': getattr(self.alert_config, 'alert_feedback_mode', 'sound'),
                'felt_tts_enabled': getattr(self.alert_config, 'felt_tts_enabled', False),
                'critical_tts_enabled': getattr(self.alert_config, 'critical_tts_enabled', False),
                'felt_tts_repeat': getattr(self.alert_config, 'felt_tts_repeat', 1),
                'critical_tts_repeat': getattr(self.alert_config, 'critical_tts_repeat', 1),
                'report_tts_enabled': getattr(self.alert_config, 'report_tts_enabled', True),
                'report_tts_repeat': getattr(self.alert_config, 'report_tts_repeat', 1),
                'weather_tts_enabled': getattr(self.alert_config, 'weather_tts_enabled', True),
                'weather_tts_repeat': getattr(self.alert_config, 'weather_tts_repeat', 1),
                'tsunami_tts_enabled': getattr(self.alert_config, 'tsunami_tts_enabled', True),
                'tsunami_tts_repeat': getattr(self.alert_config, 'tsunami_tts_repeat', 1),
                'tts_playback_mode': getattr(self.alert_config, 'tts_playback_mode', 'supplement'),
                'tts_rate': getattr(self.alert_config, 'tts_rate', 150),
                'tts_voice': getattr(self.alert_config, 'tts_voice', ''),
                'tts_include_safety_hint': getattr(self.alert_config, 'tts_include_safety_hint', True),
                'tts_repeat_policy': getattr(self.alert_config, 'tts_repeat_policy', 'smart'),
                'tts_cooldown_seconds': getattr(self.alert_config, 'tts_cooldown_seconds', 60),
                'warning_feedback_policy': getattr(
                    self.alert_config, 'warning_feedback_policy', 'first_received'
                ),
            },
            'WS_CONFIG': {
                'reconnect_interval': self.ws_config.reconnect_interval,
                'max_reconnect_attempts': self.ws_config.max_reconnect_attempts,
                'ping_interval': self.ws_config.ping_interval,
                'ping_timeout': self.ws_config.ping_timeout,
                'close_timeout': self.ws_config.close_timeout,
                'connection_timeout': self.ws_config.connection_timeout,
                'startup_stagger_seconds': self.ws_config.startup_stagger_seconds,
            },
            'TRANSLATION_CONFIG': {
                'use_place_name_fix': self.translation_config.use_place_name_fix,
                'enabled': self.translation_config.enabled,
                'baidu_app_id': getattr(self.translation_config, 'baidu_app_id', ''),
                'baidu_secret': getattr(self.translation_config, 'baidu_secret', ''),
            },
            'LOG_CONFIG': {
                'output_to_file': self.log_config.output_to_file,
                'clear_log_on_startup': self.log_config.clear_log_on_startup,
                'split_by_date': self.log_config.split_by_date,
                'max_log_size': self.log_config.max_log_size,
            },
            'ENABLED_SOURCES': self._get_persisted_enabled_sources(),
            'CUSTOM_DATA_SOURCE_URL': self.custom_data_source_url,
            'CUSTOM_DATA_SOURCE_INSECURE_SSL': bool(
                getattr(self, 'custom_data_source_insecure_ssl', False)
            ),
            'HTTP_POLL_INTERVALS': dict(self.http_poll_intervals),
        }
    
    def _is_fanstudio_individual_url(self, url: str) -> bool:
        """是否为应剔除持久化的 Fan Studio 单项 URL（历史遗留：除 all 外的 path 源）。

        公开版中 ``WS_URL_CANONICAL_ORDER`` 内的 Fan Studio 独立源（如 cenc-ir）仍需写入
        ``ENABLED_SOURCES``，否则用户关闭后重启会被加载逻辑重新默认开启。
        """
        if not url or not isinstance(url, str):
            return False
        if 'fanstudio.tech' not in url and 'fanstudio.hk' not in url:
            return False
        # Fan Studio HTTP 源（如 typhoon.php、aqi.php）不应被视为“历史遗留的单项 URL”，
        # 它们需要持久化开关状态，否则用户关闭后重启会被恢复为默认启用。
        if url.startswith('http://') or url.startswith('https://'):
            return False
        base_domain = "fanstudio.tech"
        all_url = f"wss://ws.{base_domain}/all"
        nu = url.replace('fanstudio.hk', 'fanstudio.tech').rstrip("/").lower()
        if nu == all_url.rstrip("/").lower():
            return False
        canon_fs = {
            u.replace("fanstudio.hk", "fanstudio.tech").rstrip("/").lower()
            for u in WS_URL_CANONICAL_ORDER
            if "fanstudio" in u.lower()
        }
        if nu in canon_fs:
            return False
        return True

    def _is_websocket_url(self, url: str) -> bool:
        """判断 URL 是否为 WebSocket 协议。"""
        return isinstance(url, str) and url.startswith(("ws://", "wss://"))

    def _sync_p2pquake_http_with_wss(self) -> None:
        """总开关以 WSS 为准，两条 HTTP 拉取与之一致（单一复选框同时控制 HTTP + WSS）。"""
        master = bool(self.enabled_sources.get(P2PQUAKE_WSS_URL, False))
        for u in P2PQUAKE_HTTP_SOURCE_KEYS:
            self.enabled_sources[u] = master

    def _enforce_public_ws_sources(self) -> List[str]:
        """
        公开版连接策略：仅保留 3 个公开 WebSocket 数据源，
        并仅保留 P2PQuake 与 Fan Studio 的 HTTP 拉取配置项。
        Returns:
            被移除的 URL 列表
        """
        base_domain = "fanstudio.tech"
        all_url = f"wss://ws.{base_domain}/all"
        allowed_ws = {all_url, *WS_URL_CANONICAL_ORDER}
        allowed_http = set(ALL_KNOWN_HTTP_SOURCE_KEYS)
        removed: List[str] = []
        for url in list(self.enabled_sources.keys()):
            if self._is_websocket_url(url) and url not in allowed_ws:
                removed.append(url)
                del self.enabled_sources[url]
                continue
            if (not self._is_websocket_url(url)) and url not in allowed_http:
                removed.append(url)
                del self.enabled_sources[url]
        return removed

    def _get_persisted_enabled_sources(self) -> Dict[str, bool]:
        """供保存到配置文件的 enabled_sources：仅 all 与非 Fan Studio 数据源（不包含 Fan Studio 单项）。"""
        base_domain = "fanstudio.tech"
        all_url = f"wss://ws.{base_domain}/all"
        allowed_ws = {all_url, *WS_URL_CANONICAL_ORDER}
        allowed_http = set(ALL_KNOWN_HTTP_SOURCE_KEYS)
        return {
            k: v
            for k, v in self.enabled_sources.items()
            if (
                (k == all_url or not self._is_fanstudio_individual_url(k))
                and (not self._is_websocket_url(k) or k in allowed_ws)
                and (self._is_websocket_url(k) or k in allowed_http)
            )
        }

    def get_http_poll_interval(self, url: str) -> int:
        """获取指定 HTTP 数据源的轮询间隔（秒），最低 1 秒。"""
        if self.custom_data_source_url and url == self.custom_data_source_url:
            custom_key = "__custom_http__"
            if custom_key in self.http_poll_intervals:
                return max(1, int(self.http_poll_intervals[custom_key]))
            return 1
        try:
            val = self.http_poll_intervals.get(url, DEFAULT_HTTP_POLL_INTERVALS.get(url, 2))
            return max(1, int(val))
        except (TypeError, ValueError):
            return max(1, DEFAULT_HTTP_POLL_INTERVALS.get(url, 2))

    def _ensure_http_poll_interval_defaults(self) -> None:
        """补全已知 HTTP 源的默认轮询间隔（不覆盖用户已设值）。"""
        for url, default_sec in DEFAULT_HTTP_POLL_INTERVALS.items():
            if url not in self.http_poll_intervals:
                self.http_poll_intervals[url] = default_sec
        if "__custom_http__" not in self.http_poll_intervals:
            self.http_poll_intervals["__custom_http__"] = 1

    def _ensure_new_http_source_defaults(self) -> None:
        """补全五路新 HTTP 数据源开关缺项，默认关闭。"""
        self._migrate_legacy_ptwc_url()
        for url in NEW_HTTP_SOURCE_KEYS:
            if url not in self.enabled_sources:
                self.enabled_sources[url] = False

    def _migrate_legacy_ptwc_url(self) -> None:
        """将已失效的 PTWC CAP 地址 PAAQ42.xml 迁移为官方 PHEBCAP.xml。"""
        if PTWC_CAP_URL_LEGACY not in self.enabled_sources:
            if PTWC_CAP_URL_LEGACY in self.http_poll_intervals:
                self.http_poll_intervals[PTWC_CAP_URL] = self.http_poll_intervals.pop(PTWC_CAP_URL_LEGACY)
            return
        enabled = self.enabled_sources.pop(PTWC_CAP_URL_LEGACY)
        if PTWC_CAP_URL not in self.enabled_sources:
            self.enabled_sources[PTWC_CAP_URL] = enabled
        elif enabled:
            self.enabled_sources[PTWC_CAP_URL] = True
        if PTWC_CAP_URL_LEGACY in self.http_poll_intervals:
            self.http_poll_intervals.setdefault(
                PTWC_CAP_URL,
                self.http_poll_intervals.pop(PTWC_CAP_URL_LEGACY),
            )
        logger.info(f"已迁移 PTWC CAP 地址: {PTWC_CAP_URL_LEGACY} -> {PTWC_CAP_URL}")

    def _merge_config_file(self, existing: Dict[str, Any], full: Dict[str, Any]) -> Dict[str, Any]:
        """仅对 existing 做缺项补全：只补 full 中有而 existing 中没有的键，不删除 existing 中任何键。"""
        import copy
        merged = copy.deepcopy(existing)
        for key, full_value in full.items():
            if key not in merged:
                merged[key] = copy.deepcopy(full_value)
            elif isinstance(full_value, dict) and isinstance(merged.get(key), dict):
                # 嵌套 dict：只补全缺失的子键
                for subkey, subval in full_value.items():
                    if subkey not in merged[key]:
                        merged[key][subkey] = copy.deepcopy(subval)
        return merged
    
    def _has_missing_keys(self, existing: Dict[str, Any], full: Dict[str, Any]) -> bool:
        """检查 existing 是否缺少 full 中的键（用于决定是否写回补全后的配置）。"""
        for key in full:
            if key not in existing:
                return True
            if isinstance(full[key], dict) and isinstance(existing.get(key), dict):
                for subkey in full[key]:
                    if subkey not in existing[key]:
                        return True
        return False

    def _remove_legacy_jian_project_settings(self, config_data: Dict[str, Any]) -> bool:
        """
        清理 settings.json 中遗留的 Jian Project 配置项。
        返回值:
            True: 本次有清理动作
            False: 无需清理
        """
        changed = False
        try:
            # 1) 删除历史顶层块（若存在）
            for top_key in ("JIAN_PROJECT_CONFIG", "JIANPROJECT_CONFIG", "ALI_ALL_CONFIG"):
                if top_key in config_data:
                    del config_data[top_key]
                    changed = True
            if "INTEGRATION_CONFIG" in config_data:
                del config_data["INTEGRATION_CONFIG"]
                changed = True

            # 2) 删除 MESSAGE_CONFIG 中已废弃的 Jian 子源开关
            msg_cfg = config_data.get("MESSAGE_CONFIG")
            if isinstance(msg_cfg, dict):
                deprecated_msg_keys = (
                    "ali_all_parse_geonet",
                    "ali_all_parse_ptwc",
                )
                for key in deprecated_msg_keys:
                    if key in msg_cfg:
                        del msg_cfg[key]
                        changed = True

            # 3) 删除 ENABLED_SOURCES 中所有 sismotide URL
            enabled = config_data.get("ENABLED_SOURCES")
            if isinstance(enabled, dict):
                for k in list(enabled.keys()):
                    if "sismotide.top" in (k or "").lower():
                        del enabled[k]
                        changed = True
        except Exception as e:
            logger.debug(f"清理遗留 Jian Project 配置失败(可忽略): {e}")
        return changed
    
    def _write_config_dict(self, config_data: Dict[str, Any]) -> bool:
        """将配置 dict 原子写入配置文件。"""
        if not self.config_file:
            return False
        import shutil
        temp_file = self.config_file.with_suffix('.tmp')
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            shutil.move(str(temp_file), str(self.config_file))
            return True
        except Exception as e:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            logger.warning(f"写回配置文件失败: {e}")
            return False
    
    def load_config(self) -> bool:
        """加载配置文件"""
        try:
            if self.config_file is None or not self.config_file.exists():
                logger.warning(f"配置文件不存在，使用默认配置")
                self._apply_default_config()
                return True
            
            # 使用try-except包裹文件读取，避免阻塞
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except (OSError, PermissionError, json.JSONDecodeError) as e:
                logger.warning(f"读取配置文件失败: {e}，使用默认配置")
                self._apply_default_config()
                return False
            
            # 版本不一致或缺少版本时，仅备份并继续按 section 合并加载（缺项补全，保留用户自定义）
            saved_version = config_data.get('config_version') or config_data.get('app_version') or ''
            version_changed = (saved_version != APP_VERSION)
            legacy_jian_settings_removed = self._remove_legacy_jian_project_settings(config_data)
            if version_changed:
                logger.info(f"配置版本({saved_version or '无'})与当前程序版本({APP_VERSION})不一致，将合并加载并补全缺失项，保留用户设置")
                try:
                    if self.config_file and self.config_file.exists():
                        bak = self.config_file.with_suffix('.json.bak')
                        import shutil
                        shutil.copy2(str(self.config_file), str(bak))
                        logger.debug(f"已备份旧配置到 {bak}")
                except Exception as e:
                    logger.debug(f"备份旧配置失败(可忽略): {e}")
            
            # 加载各模块配置（缺失的键保持 dataclass 默认值）
            success = True
            
            if 'GUI_CONFIG' in config_data:
                gui_data = {k: v for k, v in config_data['GUI_CONFIG'].items() if hasattr(self.gui_config, k)}
                # 只更新配置文件中存在的字段，对于不存在的字段保留当前值
                for key, value in gui_data.items():
                    if hasattr(self.gui_config, key):
                        setattr(self.gui_config, key, value)
                # 兼容旧配置：无 render_backend 时根据 use_gpu_rendering 推导
                if 'render_backend' not in config_data.get('GUI_CONFIG', {}):
                    self.gui_config.render_backend = "opengl" if self.gui_config.use_gpu_rendering else "cpu"
                # 规范化并迁移：统一为小写，不支持的取值改为 opengl
                backend = (self.gui_config.render_backend or "").strip().lower()
                if backend in ("cpu", "opengl"):
                    self.gui_config.render_backend = backend
                else:
                    self.gui_config.render_backend = "opengl"
                # 根据 render_backend 同步 use_gpu_rendering，保证一致
                self.gui_config.use_gpu_rendering = (self.gui_config.render_backend == "opengl")
                if not self.gui_config.validate():
                    success = False
            
            if 'MESSAGE_CONFIG' in config_data:
                msg_data = {k: v for k, v in config_data['MESSAGE_CONFIG'].items() if hasattr(self.message_config, k)}
                # 只更新配置文件中存在的字段，对于不存在的字段保留当前值
                for key, value in msg_data.items():
                    if hasattr(self.message_config, key):
                        setattr(self.message_config, key, value)
                if not self.message_config.validate():
                    success = False
                # 迁移逻辑：当老配置仅有 fanstudio_parse_warning / fanstudio_parse_report 时，
                # 按这两个总开关初始化各 Fan Studio 子源细粒度开关，避免升级后行为变化。
                try:
                    parse_warning_flag = getattr(self.message_config, 'fanstudio_parse_warning', True)
                    parse_report_flag = getattr(self.message_config, 'fanstudio_parse_report', True)
                    # 预警类子源字段名
                    warning_fields = [
                        'fanstudio_parse_cea',
                        'fanstudio_parse_cea_pr',
                        'fanstudio_parse_cwa_eew',
                        'fanstudio_parse_jma',
                        'fanstudio_parse_sa',
                        'fanstudio_parse_kma_eew',
                    ]
                    # 速报/其他类子源字段名
                    report_fields = [
                        'fanstudio_parse_cenc',
                        'fanstudio_parse_ningxia',
                        'fanstudio_parse_guangxi',
                        'fanstudio_parse_shanxi',
                        'fanstudio_parse_beijing',
                        'fanstudio_parse_yunnan',
                        'fanstudio_parse_cwa',
                        'fanstudio_parse_hko',
                        'fanstudio_parse_usgs',
                        'fanstudio_parse_emsc',
                        'fanstudio_parse_bcsf',
                        'fanstudio_parse_gfz',
                        'fanstudio_parse_usp',
                        'fanstudio_parse_kma',
                        'fanstudio_parse_fssn',
                        'fanstudio_parse_fssn_cmt',
                        'fanstudio_parse_weatheralarm',
                        'fanstudio_parse_tsunami',
                    ]
                    # 如果配置文件中没有对应键，则根据总开关初始化，已有键则保留用户设置
                    msg_cfg_section = config_data.get('MESSAGE_CONFIG', {})
                    for field in warning_fields:
                        if field not in msg_cfg_section:
                            setattr(self.message_config, field, bool(parse_warning_flag))
                    for field in report_fields:
                        if field not in msg_cfg_section:
                            setattr(self.message_config, field, bool(parse_report_flag))
                except Exception as e:
                    logger.debug(f"迁移 Fan Studio 子源解析开关失败(可忽略): {e}")
            
            # 加载 ALERT_CONFIG（若不存在，则触发一次旧字段迁移）
            if 'ALERT_CONFIG' in config_data:
                alert_section = config_data.get('ALERT_CONFIG') or {}
                alert_data = {
                    k: v for k, v in alert_section.items()
                    if hasattr(self.alert_config, k)
                }
                for key, value in alert_data.items():
                    setattr(self.alert_config, key, value)
                self._migrate_tiered_sound_fields(alert_section)
                self._migrate_alert_feedback_mode(alert_section)
            else:
                self._migrate_legacy_alert_fields(config_data)
            if not self.alert_config.validate():
                success = False

            if 'WS_CONFIG' in config_data:
                ws_data = {k: v for k, v in config_data['WS_CONFIG'].items() if hasattr(self.ws_config, k)}
                # 只更新配置文件中存在的字段，对于不存在的字段保留当前值
                for key, value in ws_data.items():
                    if hasattr(self.ws_config, key):
                        setattr(self.ws_config, key, value)
                if not self.ws_config.validate():
                    success = False
            
            if 'TRANSLATION_CONFIG' in config_data:
                raw_trans = config_data['TRANSLATION_CONFIG']
                # 兼容旧版：use_volcano_translation → enabled
                if 'enabled' not in raw_trans and raw_trans.get('use_volcano_translation'):
                    raw_trans = dict(raw_trans)
                    raw_trans['enabled'] = True
                    raw_trans['use_place_name_fix'] = False
                # 兼容 PySide6 版密钥字段名
                if 'baidu_secret_key' in raw_trans and 'baidu_secret' not in raw_trans:
                    raw_trans = dict(raw_trans)
                    raw_trans['baidu_secret'] = raw_trans.pop('baidu_secret_key')
                trans_data = {k: v for k, v in raw_trans.items() if hasattr(self.translation_config, k)}
                for key, value in trans_data.items():
                    if hasattr(self.translation_config, key):
                        setattr(self.translation_config, key, value)
                if not self.translation_config.validate():
                    success = False
            
            if 'LOG_CONFIG' in config_data:
                log_data = {k: v for k, v in config_data['LOG_CONFIG'].items() if hasattr(self.log_config, k)}
                # 只更新配置文件中存在的字段，对于不存在的字段保留当前值
                for key, value in log_data.items():
                    if hasattr(self.log_config, key):
                        setattr(self.log_config, key, value)
                if not self.log_config.validate():
                    success = False

            # 加载数据源配置（仅持久化 all 与非 Fan Studio 数据源，Fan Studio 单项已移除）
            raw_sources = config_data.get('ENABLED_SOURCES', {})
            base_domain = "fanstudio.tech"
            all_url = f"wss://ws.{base_domain}/all"
            self.enabled_sources = {
                k: v for k, v in raw_sources.items()
                if k == all_url or not self._is_fanstudio_individual_url(k)
            }
            # 确保内存中不保留任何 Fan Studio 单项 URL
            for k in list(self.enabled_sources.keys()):
                if self._is_fanstudio_individual_url(k):
                    del self.enabled_sources[k]
            removed_ws = self._enforce_public_ws_sources()
            if removed_ws:
                logger.info(f"已清理非公开 WebSocket 数据源: {removed_ws}")
            self.custom_data_source_url = (config_data.get('CUSTOM_DATA_SOURCE_URL') or "").strip()
            self.custom_data_source_insecure_ssl = bool(
                config_data.get('CUSTOM_DATA_SOURCE_INSECURE_SSL', False)
            )

            raw_poll = config_data.get('HTTP_POLL_INTERVALS', {})
            if isinstance(raw_poll, dict) and raw_poll:
                try:
                    self.http_poll_intervals = {
                        k: max(1, int(v)) for k, v in raw_poll.items()
                    }
                except (TypeError, ValueError):
                    self.http_poll_intervals = dict(DEFAULT_HTTP_POLL_INTERVALS)
            else:
                self.http_poll_intervals = dict(DEFAULT_HTTP_POLL_INTERVALS)
            self._ensure_http_poll_interval_defaults()

            # 如果配置文件中没有数据源配置，使用默认配置（仅 all + weather + 非 Fan Studio 单项）
            weather_source = 'weatheralarm'
            if not self.enabled_sources:
                self.enabled_sources = {all_url: True}
                self.enabled_sources[f"wss://ws.{base_domain}/{weather_source}"] = True
                # P2PQuake 仅 WSS + 启动时 HTTP 拉 1 条，不启用 HTTP 轮询
                self.enabled_sources["https://api.p2pquake.net/v2/history?codes=551&limit=3"] = False
                self.enabled_sources["https://api.p2pquake.net/v2/jma/tsunami?limit=1"] = False
                self.enabled_sources["https://api.fanstudio.tech/we/typhoon.php"] = True
                self.enabled_sources["https://api.fanstudio.tech/we/aqi.php"] = True
                self.enabled_sources["wss://ws-api.wolfx.jp/all_eew"] = True
                self.enabled_sources["wss://api.p2pquake.net/v2/ws"] = False
                self.enabled_sources["wss://ws.fanstudio.tech/cenc-ir"] = False
                logger.info("配置文件中没有数据源配置，使用默认配置（all + 非 Fan Studio）")
            else:
                if all_url not in self.enabled_sources:
                    self.enabled_sources[all_url] = True
                # 若配置中已有 all_url，尊重用户关闭聚合连接的设置，不再强制为 True
                # 仅补全非 Fan Studio 数据源缺失项；P2PQuake HTTP 不用于轮询，仅启动时拉 1 条
                if "https://api.p2pquake.net/v2/history?codes=551&limit=3" not in self.enabled_sources:
                    self.enabled_sources["https://api.p2pquake.net/v2/history?codes=551&limit=3"] = False
                if "https://api.p2pquake.net/v2/jma/tsunami?limit=1" not in self.enabled_sources:
                    self.enabled_sources["https://api.p2pquake.net/v2/jma/tsunami?limit=1"] = False
                if "https://api.fanstudio.tech/we/typhoon.php" not in self.enabled_sources:
                    self.enabled_sources["https://api.fanstudio.tech/we/typhoon.php"] = True
                if "https://api.fanstudio.tech/we/aqi.php" not in self.enabled_sources:
                    self.enabled_sources["https://api.fanstudio.tech/we/aqi.php"] = True
                other_wss_urls = [
                    "wss://ws.fanstudio.tech/cenc-ir",
                    "wss://ws-api.wolfx.jp/all_eew",
                    "wss://ws-api.wolfx.jp/cwa_eew",
                    "wss://api.p2pquake.net/v2/ws",
                ]
                for wss_url in other_wss_urls:
                    if wss_url not in self.enabled_sources:
                        # 缺省仅与 _apply_default_config 对齐：Wolfx 聚合默认开；烈度速报等独立源缺键视为关，
                        # 避免旧配置无 cenc-ir 项时每轮加载被强行当作「已开启」。
                        self.enabled_sources[wss_url] = wss_url == "wss://ws-api.wolfx.jp/all_eew"
                if f"wss://ws.{base_domain}/fssn-cmt" not in self.enabled_sources:
                    self.enabled_sources[f"wss://ws.{base_domain}/fssn-cmt"] = False
                    logger.debug("添加缺失的 FSSN CMT 数据源")

            # P2PQuake：一个总开关，两条 HTTP 拉取与 WSS 项保持一致
            self._sync_p2pquake_http_with_wss()
            self._ensure_new_http_source_defaults()

            # 根据服务器选择更新URL
            self._update_urls_for_server_selection()
            removed_ws = self._enforce_public_ws_sources()
            if removed_ws:
                logger.info(f"URL 规范化后再次清理非公开 WebSocket 数据源: {removed_ws}")
            
            # 按固定顺序构建 ws_urls，确保轮播数据源顺序不变
            self.ws_urls = self._build_ws_urls_ordered()
            for u in self.ws_urls:
                logger.debug(f"已添加数据源到ws_urls: {u}")
            logger.info(f"配置加载成功，启用 {len(self.ws_urls)} 个WebSocket数据源")
            self._notify_config_changed()
            # 缺项补全：仅添加缺失的键并写回，不覆盖用户已有设置；ENABLED_SOURCES 使用过滤后的值
            full = self._get_full_config_dict()
            merged = self._merge_config_file(config_data, full)
            merged['ENABLED_SOURCES'] = full['ENABLED_SOURCES']
            if version_changed:
                merged['config_version'] = APP_VERSION
            if version_changed or self._has_missing_keys(config_data, full) or legacy_jian_settings_removed:
                try:
                    if self._write_config_dict(merged):
                        if legacy_jian_settings_removed:
                            logger.info("已清理 settings.json 中遗留的 Jian Project 配置并写回")
                        else:
                            logger.info("已补全缺失配置项并写回，保留用户自定义设置")
                    else:
                        logger.warning("补全配置写回失败(可忽略)")
                except Exception as e:
                    logger.warning(f"写回补全配置失败(可忽略): {e}")
            return success
            
        except json.JSONDecodeError as e:
            logger.error(f"配置文件格式错误: {e}")
            self._apply_default_config()
            return False
        except Exception as e:
            logger.error(f"配置加载失败: {e}")
            self._apply_default_config()
            return False
    
    def save_config(self) -> bool:
        """保存当前配置到文件（合并写入：程序已知键用内存值更新，文件中多出的键保留）"""
        import threading
        import shutil
        
        if not hasattr(self, '_save_lock'):
            self._save_lock = threading.Lock()
        
        if not self._save_lock.acquire(timeout=5):
            logger.error("配置保存失败: 无法获取文件锁，可能正在被其他线程使用")
            return False
        
        try:
            our_config = self._get_full_config_dict()
            # 若配置文件存在，先读取再合并，保留用户自定义键
            if self.config_file and self.config_file.exists():
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                except (OSError, json.JSONDecodeError):
                    existing = {}
                # 逐 section 合并：existing 中多出的键保留，程序已知键用内存值覆盖
                merged = dict(existing)
                for key, our_value in our_config.items():
                    if key == 'ENABLED_SOURCES':
                        # 写入过滤后的数据源，避免历史敏感 WS URL 被保留
                        merged[key] = dict(our_value)
                    elif isinstance(our_value, dict):
                        merged[key] = {**existing.get(key, {}), **our_value}
                    else:
                        merged[key] = our_value
                config_data = merged
            else:
                config_data = our_config
            
            if self.config_file:
                if self._write_config_dict(config_data):
                    logger.info("配置保存成功")
                    return True
                raise RuntimeError("_write_config_dict 返回 False")
            logger.error("配置保存失败: 配置文件路径未设置")
            return False
        except Exception as e:
            logger.error(f"配置保存失败: {e}", exc_info=True)
            return False
        finally:
            self._save_lock.release()
    
    def _migrate_tiered_sound_fields(self, alert_section: Dict[str, Any]) -> None:
        """从旧版单层 sound_enabled/sound_path 迁移到分级预警声音字段。"""
        if not isinstance(alert_section, dict):
            return
        has_new = (
            'felt_sound_enabled' in alert_section
            or 'critical_sound_enabled' in alert_section
        )
        if has_new:
            return
        old_enabled = bool(alert_section.get('sound_enabled', False))
        old_path = (alert_section.get('sound_path') or '').strip()
        self.alert_config.felt_sound_enabled = old_enabled
        self.alert_config.critical_sound_enabled = old_enabled
        if old_path:
            self.alert_config.felt_sound_path = old_path

    def _migrate_alert_feedback_mode(self, alert_section: Dict[str, Any]) -> None:
        """从旧版 tts_playback_mode / TTS 开关迁移到 alert_feedback_mode。"""
        if not isinstance(alert_section, dict):
            return
        if "alert_feedback_mode" in alert_section:
            return
        legacy = str(alert_section.get("tts_playback_mode") or "").strip().lower()
        tts_on = bool(
            alert_section.get("felt_tts_enabled")
            or alert_section.get("critical_tts_enabled")
        )
        if legacy == "replace" or tts_on:
            self.alert_config.alert_feedback_mode = "tts"
        else:
            self.alert_config.alert_feedback_mode = "sound"

    def _migrate_legacy_alert_fields(self, config_data: Dict[str, Any]) -> None:
        """
        从旧版 GUI_CONFIG / MESSAGE_CONFIG 中迁移告警相关字段到新的 ``AlertConfig``。

        触发条件：``ALERT_CONFIG`` 节缺失（首次升级）。
        旧字段保留在原 section 中以保证降级兼容；下个版本会清理。
        """
        try:
            msg_section = config_data.get('MESSAGE_CONFIG', {}) or {}

            enable_china = bool(msg_section.get('enable_china_intensity', False))
            self.alert_config.enabled = enable_china

            self.alert_config.flash_interval_ms = int(
                msg_section.get('alert_flash_interval_ms', 400) or 400
            )
            self.alert_config.flash_scope = "scrolling_only"
            logger.info("已从旧版字段迁移 AlertConfig（首次升级）")
        except Exception as e:
            logger.warning(f"迁移旧版告警配置失败（使用默认值）: {e}")

    def _apply_default_config(self):
        """应用默认配置"""
        self.gui_config = GUIConfig()
        self.message_config = MessageConfig()
        self.alert_config = AlertConfig()
        self.ws_config = WebSocketConfig()
        self.translation_config = TranslationConfig()
        self.log_config = LogConfig()
        # 默认数据源：仅聚合/独立源，不加入 Fan Studio 单项 wss URL（实际只连 /all）
        base_domain = "fanstudio.tech"
        all_url = f"wss://ws.{base_domain}/all"
        weather_source = 'weatheralarm'

        self.enabled_sources = {all_url: True}
        self.enabled_sources[f"wss://ws.{base_domain}/{weather_source}"] = True
        # P2PQuake 仅 WSS + 启动时 HTTP 拉 1 条，不启用 HTTP 轮询
        self.enabled_sources["https://api.p2pquake.net/v2/history?codes=551&limit=3"] = False
        self.enabled_sources["https://api.p2pquake.net/v2/jma/tsunami?limit=1"] = False
        self.enabled_sources["https://api.fanstudio.tech/we/typhoon.php"] = True
        self.enabled_sources["https://api.fanstudio.tech/we/aqi.php"] = True
        self.enabled_sources["wss://ws-api.wolfx.jp/all_eew"] = True
        self.enabled_sources["wss://ws-api.wolfx.jp/cwa_eew"] = False
        self.enabled_sources["wss://api.p2pquake.net/v2/ws"] = False
        self.enabled_sources["wss://ws.fanstudio.tech/cenc-ir"] = True
        self._ensure_new_http_source_defaults()
        self._ensure_http_poll_interval_defaults()
        self._enforce_public_ws_sources()

        self.ws_urls = self._build_ws_urls_ordered()
        self.custom_data_source_url = ""
        self.custom_data_source_insecure_ssl = False
        logger.info(f"已应用默认配置（仅聚合/独立源，无 Fan Studio 单项）: {self.ws_urls}")
    
    def _build_ws_urls_ordered(self) -> List[str]:
        """按固定顺序构建 ws_urls：已启用的 fanstudio all + canonical 独立源。"""
        base_domain = "fanstudio.tech"
        all_url = f"wss://ws.{base_domain}/all"
        self._enforce_public_ws_sources()
        ws_urls: List[str] = []
        if self.enabled_sources.get(all_url, False):
            ws_urls.append(all_url)
        for url in WS_URL_CANONICAL_ORDER:
            if self.enabled_sources.get(url, False):
                ws_urls.append(url)
        return ws_urls

    def update_enabled_sources(self, sources: Dict[str, bool]):
        """更新启用的数据源"""
        self.enabled_sources.update(sources)
        self._update_urls_for_server_selection()
        removed_ws = self._enforce_public_ws_sources()
        if removed_ws:
            logger.info(f"更新数据源时已清理非公开 WebSocket 数据源: {removed_ws}")
        self.ws_urls = self._build_ws_urls_ordered()
        logger.info(f"更新数据源配置，当前启用 {len(self.ws_urls)} 个WebSocket数据源: {self.ws_urls}")
        self._notify_config_changed()

    def apply_performance_preset(self, mode: str) -> Dict[str, Any]:
        """应用低配/标准/高配性能预设，返回是否需重启等信息。"""
        from utils.performance_presets import apply_performance_preset

        result = apply_performance_preset(self, mode)
        self._notify_config_changed()
        logger.info(
            "已应用性能模式 %s（render_changed=%s, sources_changed=%s）",
            mode,
            result.get("render_backend_changed"),
            result.get("sources_changed"),
        )
        return result
    
    def _update_urls_for_server_selection(self):
        """
        根据服务器选择（正式/备用）更新URL中的域名
        将fanstudio.tech和fanstudio.hk互相替换
        """
        try:
            if not hasattr(self, 'enabled_sources'):
                return
            
            # 创建新的enabled_sources字典，将所有fanstudio.hk替换为fanstudio.tech
            new_enabled_sources = {}
            for url, enabled in self.enabled_sources.items():
                # 只替换fanstudio.hk为fanstudio.tech
                if 'fanstudio.hk' in url:
                    new_url = url.replace('fanstudio.hk', 'fanstudio.tech')
                    new_enabled_sources[new_url] = enabled
                    logger.debug(f"已更新URL: {url} -> {new_url}")
                else:
                    # 其他URL保持不变
                    new_enabled_sources[url] = enabled
            
            self.enabled_sources = new_enabled_sources
            logger.debug("已将所有fanstudio.hk URL更新为fanstudio.tech")
        except Exception as e:
            logger.error(f"更新URL失败: {e}")
    
    def get_source_name(self, url: str) -> str:
        """获取数据源名称。Fan Studio 子源用 path 代号映射（不写完整 wss URL），其余用完整 URL 映射。"""
        if self.custom_data_source_url and url == self.custom_data_source_url:
            return "custom"
        normalized_url = url.replace('fanstudio.hk', 'fanstudio.tech').rstrip('/')
        http_url_to_name = {
            "https://api.fanstudio.tech/we/typhoon.php": "fanstudio_typhoon",
            "https://api.fanstudio.tech/we/aqi.php": "fanstudio_aqi",
            "https://api.p2pquake.net/v2/history?codes=551&limit=3": "p2pquake",
            "https://api.p2pquake.net/v2/jma/tsunami?limit=1": "p2pquake_tsunami",
            BMKG_HTTP_URL: "bmkg",
            GEONET_HTTP_URL: "geonet",
            INGV_HTTP_URL: "ingv",
            EARLYEST_HTTP_URL: "early_est",
            JMA_ATOM_LONG_URL: "jma_volcano",
        }
        if normalized_url in http_url_to_name:
            return http_url_to_name[normalized_url]
        # Fan Studio wss：从 URL 抽 path，用代号查表，避免在代码中写单项 API 链接
        if ('fanstudio.tech' in normalized_url or 'fanstudio.hk' in url) and normalized_url.startswith(('wss://', 'ws://')):
            try:
                path = normalized_url.rstrip('/').split('/')[-1] or 'all'
                fanstudio_path_to_name = {
                    "all": "fanstudio",
                    "cenc-ir": "cenc-ir",
                    "weatheralarm": "weatheralarm",
                    "tsunami": "海啸信息",
                    "cenc": "cenc", "cea": "cea", "cea-pr": "cea-pr",
                    "ningxia": "ningxia", "guangxi": "guangxi",
                    "shanxi": "shanxi", "beijing": "beijing", "yunnan": "yunnan",
                    "cwa": "cwa", "cwa-eew": "cwa-eew", "jma": "jma", "hko": "hko",
                    "usgs": "usgs", "sa": "sa", "emsc": "emsc", "bcsf": "bcsf",
                    "gfz": "gfz", "usp": "usp", "kma": "kma", "kma-eew": "kma-eew", "fssn": "fssn",
                    "fssn-cmt": "fssn-cmt",
                }
                if path in fanstudio_path_to_name:
                    return fanstudio_path_to_name[path]
            except Exception:
                pass
        # 非 Fan Studio：仅保留需完整 URL 的数据源（P2PQuake WSS、Wolfx All 等）
        url_to_name = {
            "wss://ws-api.wolfx.jp/all_eew": "wolfx_all_eew",
            "wss://ws-api.wolfx.jp/cwa_eew": "wolfx_cwa_eew",
            "wss://api.p2pquake.net/v2/ws": "p2pquake_ws",
            PTWC_CAP_URL: "ptwc",
            BMKG_HTTP_URL: "bmkg",
            GEONET_HTTP_URL: "geonet",
            INGV_HTTP_URL: "ingv",
            EARLYEST_HTTP_URL: "early_est",
            JMA_ATOM_LONG_URL: "jma_volcano",
        }
        return url_to_name.get(normalized_url, url)
    
    def get_organization_name(self, source_name: str) -> str:
        """获取机构名称"""
        organization_name_mapping = {
            "custom": "自定义数据源",
            "fanstudio": "Fan Studio数据源",
            "weatheralarm": "气象预警",
            "cenc": "中国地震台网中心自动测定/正式测定",
            "cenc-ir": "中国地震台网中心地震烈度速报",
            "cea": "中国地震预警网",
            "cea-pr": "中国地震预警网-省级预警",
            "ningxia": "宁夏地震局",
            "guangxi": "广西地震局",
            "shanxi": "山西地震局",
            "beijing": "北京地震局",
            "yunnan": "云南地震局",
            "tsunami": "自然资源部海啸预警中心",
            "海啸信息": "自然资源部海啸预警中心",
            "cwa": "台湾中央气象署",
            "cwa-eew": "台湾中央气象署地震预警",
            "jma": "日本气象厅地震预警",
            "p2pquake": "日本气象厅地震情报",
            "p2pquake_tsunami": "日本气象厅海啸预报",
            "hko": "香港天文台",
            "fanstudio_typhoon": "台风实时与历史数据",
            "fanstudio_aqi": "城市空气质量指数",
            "usgs": "美国地质调查局",
            "sa": "美国ShakeAlert地震预警",
            "emsc": "欧洲地中海地震中心",
            "bcsf": "法国中央地震研究所",
            "gfz": "德国地学研究中心",
            "usp": "巴西圣保罗大学",
            "kma": "韩国气象厅",
            "kma-eew": "韩国气象厅地震预警",
            "fssn": "FSSN",
            "fssn-cmt": "FSSN 矩心矩张量解",
            "p2pquake_ws": "日本气象厅地震/海啸 (P2PQuake WSS)",
            "wolfx_jma_eew": "緊急地震速報",
            "wolfx_sc_eew": "四川省地震局",
            "wolfx_fj_eew": "福建省地震局",
            "wolfx_cenc_eew": "中国地震台网",
            "wolfx_cq_eew": "重庆市地震局",
            "wolfx_cwa_eew": "台湾中央气象署",
            "bmkg": "印尼气象气候和地球物理局",
            "geonet": "新西兰 GeoNet",
            "ingv": "意大利国家地球物理与火山学研究所",
            "early_est": "Early-est",
            "jma_volcano": "日本气象厅火山情报",
            "ptwc": "太平洋海啸预警中心 (PTWC)",
        }
        
        return organization_name_mapping.get(source_name, source_name)