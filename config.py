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
WS_URL_CANONICAL_ORDER: List[str] = [
    "wss://api.p2pquake.net/v2/ws",
    "wss://ws-api.wolfx.jp/all_eew",
]
P2PQUAKE_HTTP_SOURCE_KEYS: List[str] = [
    "https://api.p2pquake.net/v2/history?codes=551&limit=3",
    "https://api.p2pquake.net/v2/jma/tsunami?limit=1",
]

# 应用版本号（用于更新说明弹窗“仅展示一次”及关于页）
APP_VERSION = "2.4.4"

# 更新说明（关于页/首次启动弹窗展示，当前版本仅展示一次）
# 每次修改 APP_VERSION 时，请同步修改下方 CHANGELOG_TEXT 的版本标题与更新条目。
CHANGELOG_TEXT = """版本 2.4.4

1、删除部分数据源，新增部分数据源"""

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
    use_weather_image_nmc: bool = True  # True=气象预警图标优先 NMC 在线，False=仅本地图片
    watermark_text: str = ""  # 背景水印文字，空则不显示
    watermark_angle: str = "horizontal"  # 水印方向："horizontal" 横向，"45" 斜向45度
    watermark_font_family: str = ""  # 水印字体族名，空表示跟随主字体
    watermark_font_size: int = 0  # 水印字体大小，0 表示自动（按主字体比例）
    watermark_position: str = "diagonal"  # 水印位置: diagonal | top_left | top_right | bottom_left | bottom_right
    # 用户所在地（用于中国经验烈度估算）
    site_lat: float = 0.0
    site_lon: float = 0.0
    site_region_name: str = ""  # 可选：所在省市名称，供后续按地区修正使用

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
            return True
        except AssertionError as e:
            logger.error(f"GUI配置验证失败: {e}")
            return False


@dataclass
class MessageConfig:
    """消息处理配置"""
    max_message_length: int = 0
    display_duration: int = 0
    # 预警无活动时长（秒）：当前未使用，仅保留配置兼容；与“发震时间有效期/最少展示时长”无直接对应，默认 10 分钟
    max_warning_inactivity_time: int = 600
    # 预警按发震时间的有效期（秒）：超过此时长的预警入队时丢弃、展示时移除，默认 5 分钟
    warning_shock_validity_seconds: int = 300
    # Wolfx JMA 预警的发震时间有效期（秒），默认 5 分钟
    warning_shock_validity_seconds_nied: int = 300
    # Wolfx 四川地震局预警的发震时间有效期（秒），默认 10 分钟
    warning_shock_validity_seconds_early_est: int = 600
    # 预警最少展示时长（秒）：一旦展示则在此时间内不因发震时间过期被移除，默认 5 分钟
    warning_min_display_seconds: int = 300
    max_report_inactivity_time: int = 300
    max_other_inactivity_time: int = 300
    # 主线程消息队列与展示缓冲区容量（缓解高并发时丢消息）
    message_queue_maxsize: int = 300
    message_buffer_max_size: int = 50
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
            return True
        except AssertionError as e:
            logger.error(f"消息配置验证失败: {e}")
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
    
    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            assert self.reconnect_interval > 0, "重连间隔必须大于0"
            assert self.max_reconnect_attempts >= -1, "最大重连次数必须≥-1"
            assert self.ping_interval > 0, "心跳间隔必须大于0"
            assert self.ping_timeout > 0, "心跳超时必须大于0"
            assert self.close_timeout > 0, "关闭超时必须大于0"
            assert self.connection_timeout > 0, "连接超时必须大于0"
            return True
        except AssertionError as e:
            logger.error(f"WebSocket配置验证失败: {e}")
            return False


@dataclass
class TranslationConfig:
    """地名修正配置类（原翻译配置，公开版仅保留地名修正）"""
    use_place_name_fix: bool = True  # 是否使用地名修正（速报根据经纬度修正地名），默认开启
    use_volcano_translation: bool = False  # 是否对火山情报使用百度翻译（日文→中文）
    baidu_app_id: str = ""  # 百度翻译开放平台 AppID
    baidu_secret: str = ""  # 百度翻译开放平台密钥
    
    def validate(self) -> bool:
        """验证配置有效性"""
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
        self.gui_config = GUIConfig()
        self.message_config = MessageConfig()
        self.ws_config = WebSocketConfig()
        self.translation_config = TranslationConfig()
        self.log_config = LogConfig()

        # 数据源配置
        self.enabled_sources: Dict[str, bool] = {}
        self.ws_urls: List[str] = []
        self.custom_data_source_url: str = ""  # 自定义数据源 URL（http/https/ws/wss），空为关闭
        
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
                'use_weather_image_nmc': self.gui_config.use_weather_image_nmc,
                'watermark_text': self.gui_config.watermark_text,
                'watermark_angle': self.gui_config.watermark_angle,
                'watermark_font_family': getattr(self.gui_config, 'watermark_font_family', ""),
                'watermark_font_size': getattr(self.gui_config, 'watermark_font_size', 0),
                'watermark_position': getattr(self.gui_config, 'watermark_position', "diagonal"),
                'site_lat': getattr(self.gui_config, 'site_lat', 0.0),
                'site_lon': getattr(self.gui_config, 'site_lon', 0.0),
                'site_region_name': getattr(self.gui_config, 'site_region_name', ""),
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
                'max_report_inactivity_time': self.message_config.max_report_inactivity_time,
                'max_other_inactivity_time': self.message_config.max_other_inactivity_time,
                'message_queue_maxsize': getattr(self.message_config, 'message_queue_maxsize', 300),
                'message_buffer_max_size': getattr(self.message_config, 'message_buffer_max_size', 50),
                'no_activity_message': self.message_config.no_activity_message,
                'custom_text': self.message_config.custom_text,
                'use_custom_text': self.message_config.use_custom_text,
                'fanstudio_parse_warning': self.message_config.fanstudio_parse_warning,
                'fanstudio_parse_report': self.message_config.fanstudio_parse_report,
                'ali_all_parse_nied': getattr(self.message_config, 'ali_all_parse_nied', True),
                'ali_all_parse_early_est': getattr(self.message_config, 'ali_all_parse_early_est', True),
                'ali_all_parse_jma_volcano': getattr(self.message_config, 'ali_all_parse_jma_volcano', True),
                'ali_all_parse_bmkg': getattr(self.message_config, 'ali_all_parse_bmkg', True),
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
            },
            'WS_CONFIG': {
                'reconnect_interval': self.ws_config.reconnect_interval,
                'max_reconnect_attempts': self.ws_config.max_reconnect_attempts,
                'ping_interval': self.ws_config.ping_interval,
                'ping_timeout': self.ws_config.ping_timeout,
                'close_timeout': self.ws_config.close_timeout,
                'connection_timeout': self.ws_config.connection_timeout,
            },
            'TRANSLATION_CONFIG': {
                'use_place_name_fix': self.translation_config.use_place_name_fix,
                'use_volcano_translation': getattr(self.translation_config, 'use_volcano_translation', False),
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
        }
    
    def _is_fanstudio_individual_url(self, url: str) -> bool:
        """是否为 Fan Studio 单项数据源 URL（非 all）。仅 all 用于连接，单项不再持久化。"""
        if not url or not isinstance(url, str):
            return False
        if 'fanstudio.tech' not in url and 'fanstudio.hk' not in url:
            return False
        base_domain = "fanstudio.tech"
        all_url = f"wss://ws.{base_domain}/all"
        return url != all_url

    def _is_websocket_url(self, url: str) -> bool:
        """判断 URL 是否为 WebSocket 协议。"""
        return isinstance(url, str) and url.startswith(("ws://", "wss://"))

    def _enforce_public_ws_sources(self) -> List[str]:
        """
        公开版连接策略：仅保留 3 个公开 WebSocket 数据源，
        并仅保留 P2PQuake 的两个 HTTP 拉取配置项。
        Returns:
            被移除的 URL 列表
        """
        base_domain = "fanstudio.tech"
        all_url = f"wss://ws.{base_domain}/all"
        allowed_ws = {all_url, *WS_URL_CANONICAL_ORDER}
        allowed_http = set(P2PQUAKE_HTTP_SOURCE_KEYS)
        removed: List[str] = []
        for url in list(self.enabled_sources.keys()):
            if self._is_websocket_url(url) and url not in allowed_ws:
                removed.append(url)
                del self.enabled_sources[url]
                continue
            if (not self._is_websocket_url(url)) and url not in allowed_http:
                removed.append(url)
                del self.enabled_sources[url]
        # fanstudio all 在公开版中固定启用
        self.enabled_sources[all_url] = True
        return removed

    def _get_persisted_enabled_sources(self) -> Dict[str, bool]:
        """供保存到配置文件的 enabled_sources：仅 all 与非 Fan Studio 数据源（不包含 Fan Studio 单项）。"""
        base_domain = "fanstudio.tech"
        all_url = f"wss://ws.{base_domain}/all"
        allowed_ws = {all_url, *WS_URL_CANONICAL_ORDER}
        allowed_http = set(P2PQUAKE_HTTP_SOURCE_KEYS)
        return {
            k: v
            for k, v in self.enabled_sources.items()
            if (
                (k == all_url or not self._is_fanstudio_individual_url(k))
                and (not self._is_websocket_url(k) or k in allowed_ws)
                and (self._is_websocket_url(k) or k in allowed_http)
            )
        }

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
            
            if 'WS_CONFIG' in config_data:
                ws_data = {k: v for k, v in config_data['WS_CONFIG'].items() if hasattr(self.ws_config, k)}
                # 只更新配置文件中存在的字段，对于不存在的字段保留当前值
                for key, value in ws_data.items():
                    if hasattr(self.ws_config, key):
                        setattr(self.ws_config, key, value)
                if not self.ws_config.validate():
                    success = False
            
            if 'TRANSLATION_CONFIG' in config_data:
                trans_data = {k: v for k, v in config_data['TRANSLATION_CONFIG'].items() if hasattr(self.translation_config, k)}
                # 只更新配置文件中存在的字段，对于不存在的字段保留当前值
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

            # 如果配置文件中没有数据源配置，使用默认配置（仅 all + weather + 非 Fan Studio 单项）
            weather_source = 'weatheralarm'
            if not self.enabled_sources:
                self.enabled_sources = {all_url: True}
                self.enabled_sources[f"wss://ws.{base_domain}/{weather_source}"] = True
                # P2PQuake 仅 WSS + 启动时 HTTP 拉 1 条，不启用 HTTP 轮询
                self.enabled_sources["https://api.p2pquake.net/v2/history?codes=551&limit=3"] = False
                self.enabled_sources["https://api.p2pquake.net/v2/jma/tsunami?limit=1"] = False
                self.enabled_sources["wss://ws-api.wolfx.jp/all_eew"] = True
                self.enabled_sources["wss://api.p2pquake.net/v2/ws"] = False
                logger.info("配置文件中没有数据源配置，使用默认配置（all + 非 Fan Studio）")
            else:
                if all_url not in self.enabled_sources:
                    self.enabled_sources[all_url] = True
                else:
                    if not self.enabled_sources.get(all_url, False):
                        self.enabled_sources[all_url] = True
                # 仅补全非 Fan Studio 数据源缺失项；P2PQuake HTTP 不用于轮询，仅启动时拉 1 条
                if "https://api.p2pquake.net/v2/history?codes=551&limit=3" not in self.enabled_sources:
                    self.enabled_sources["https://api.p2pquake.net/v2/history?codes=551&limit=3"] = False
                if "https://api.p2pquake.net/v2/jma/tsunami?limit=1" not in self.enabled_sources:
                    self.enabled_sources["https://api.p2pquake.net/v2/jma/tsunami?limit=1"] = False
                other_wss_urls = ["wss://ws-api.wolfx.jp/all_eew", "wss://api.p2pquake.net/v2/ws"]
                for wss_url in other_wss_urls:
                    if wss_url not in self.enabled_sources:
                        self.enabled_sources[wss_url] = (wss_url == "wss://ws-api.wolfx.jp/all_eew")
                if f"wss://ws.{base_domain}/fssn-cmt" not in self.enabled_sources:
                    self.enabled_sources[f"wss://ws.{base_domain}/fssn-cmt"] = False
                    logger.debug("添加缺失的 FSSN CMT 数据源")

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
    
    def _apply_default_config(self):
        """应用默认配置"""
        self.gui_config = GUIConfig()
        self.message_config = MessageConfig()
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
        self.enabled_sources["wss://ws-api.wolfx.jp/all_eew"] = True
        self.enabled_sources["wss://api.p2pquake.net/v2/ws"] = False
        self._enforce_public_ws_sources()

        self.ws_urls = self._build_ws_urls_ordered()
        self.custom_data_source_url = ""
        logger.info(f"已应用默认配置（仅聚合/独立源，无 Fan Studio 单项）: {self.ws_urls}")
    
    def _build_ws_urls_ordered(self) -> List[str]:
        """按固定顺序构建 ws_urls：仅连接 fanstudio all + canonical 两个独立源。"""
        base_domain = "fanstudio.tech"
        all_url = f"wss://ws.{base_domain}/all"
        self.enabled_sources[all_url] = True
        self._enforce_public_ws_sources()
        ws_urls = [all_url]
        for url in WS_URL_CANONICAL_ORDER:
            if self.enabled_sources.get(url, False):
                ws_urls.append(url)
        return ws_urls

    def update_enabled_sources(self, sources: Dict[str, bool]):
        """更新启用的数据源"""
        self.enabled_sources.update(sources)
        self._update_urls_for_server_selection()
        self.enabled_sources[f"wss://ws.fanstudio.tech/all"] = True
        removed_ws = self._enforce_public_ws_sources()
        if removed_ws:
            logger.info(f"更新数据源时已清理非公开 WebSocket 数据源: {removed_ws}")
        self.ws_urls = self._build_ws_urls_ordered()
        logger.info(f"更新数据源配置，当前启用 {len(self.ws_urls)} 个WebSocket数据源: {self.ws_urls}")
        self._notify_config_changed()
    
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
        normalized_url = url.replace('fanstudio.hk', 'fanstudio.tech')
        # Fan Studio wss：从 URL 抽 path，用代号查表，避免在代码中写单项 API 链接
        if ('fanstudio.tech' in normalized_url or 'fanstudio.hk' in url) and normalized_url.startswith(('wss://', 'ws://')):
            try:
                path = normalized_url.rstrip('/').split('/')[-1] or 'all'
                fanstudio_path_to_name = {
                    "all": "fanstudio",
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
            "wss://api.p2pquake.net/v2/ws": "p2pquake_ws",
        }
        return url_to_name.get(normalized_url, url)
    
    def get_organization_name(self, source_name: str) -> str:
        """获取机构名称"""
        organization_name_mapping = {
            "custom": "自定义数据源",
            "fanstudio": "Fan Studio数据源",
            "weatheralarm": "气象预警",
            "cenc": "中国地震台网中心自动测定/正式测定",
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
            "wolfx_cenc_eew": "中国地震台网地震预警",
        }
        
        return organization_name_mapping.get(source_name, source_name)