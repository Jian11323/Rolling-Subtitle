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

# 应用版本号（用于更新说明弹窗“仅展示一次”及关于页）
APP_VERSION = "2.2.1"

# 更新说明（关于页/首次启动弹窗展示，当前版本仅展示一次）
CHANGELOG_TEXT = """版本 2.2.1

1、新增CPU渲染，GPU渲染两种渲染方式
2、设置页面重设计；
3、设置窗口宽度与颜色区对齐优化；
4、关于页数据源列表修正及更新说明弹窗布局优化"""


@dataclass
class GUIConfig:
    """GUI配置类"""
    font_size: int = 40
    text_speed: float = 4.0
    bg_color: str = 'black'
    info_color: str = '#01FF00'
    opacity: float = 1.0
    window_width: int = 1000
    window_height: int = 100
    resizable: bool = True
    vsync_enabled: bool = True  # 垂直同步开关
    target_fps: int = 60  # 目标帧率
    timezone: str = "Asia/Shanghai"  # 显示时区（IANA 名称），默认北京时间
    last_seen_changelog_version: str = ""  # 上次已读的更新说明版本，用于弹窗仅展示一次
    use_gpu_rendering: bool = False  # True=GPU(OpenGL) 渲染，False=CPU(软件) 渲染，默认 CPU
    
    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            assert 10 <= self.font_size <= 100, "字体大小必须在10-100之间"
            assert 0.1 <= self.text_speed <= 20.0, "滚动速度必须在0.1-20.0之间"
            assert 0.1 <= self.opacity <= 1.0, "透明度必须在0.1-1.0之间"
            assert 800 <= self.window_width <= 3000, "窗口宽度必须在800-3000之间"
            assert 100 <= self.window_height <= 500, "窗口高度必须在100-500之间"
            assert 1 <= self.target_fps <= 240, "目标帧率必须在1-240之间"
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
    # 预警最少展示时长（秒）：一旦展示则在此时间内不因发震时间过期被移除，默认 5 分钟
    warning_min_display_seconds: int = 300
    max_report_inactivity_time: int = 300
    max_other_inactivity_time: int = 300
    no_activity_message: str = '系统运行中，等待最新地震信息...'
    custom_text: str = '系统运行中，等待最新地震信息...'
    use_custom_text: bool = False  # True=自定义文本模式(与地震速报二选一)，False=地震速报模式
    warning_color: str = '#FF0000'  # 红色
    report_color: str = '#00FFFF'  # 青色
    custom_text_color: str = '#01FF00'  # 自定义文本颜色（绿色，与默认颜色一致）
    default_color: str = '#01FF00'
    weather_warning_color: str = '#FFF500'
    
    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            assert self.max_message_length >= 0, "消息最大长度不能为负数"
            assert self.display_duration >= 0, "显示持续时间不能为负数"
            assert self.max_warning_inactivity_time > 0, "预警无活动时长必须大于0"
            assert self.warning_shock_validity_seconds > 0, "预警发震时间有效期必须大于0"
            assert self.warning_min_display_seconds > 0, "预警最少展示时长必须大于0"
            assert self.max_report_inactivity_time > 0, "速报无活动时长必须大于0"
            assert self.max_other_inactivity_time > 0, "其他消息无活动时长必须大于0"
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
    """翻译配置类"""
    baidu_app_id: str = ""
    baidu_secret_key: str = ""
    enabled: bool = False  # 是否启用翻译（默认关闭）
    use_place_name_fix: bool = True  # 是否使用地名修正（与百度翻译互斥，默认开启）
    
    def validate(self) -> bool:
        """验证配置有效性"""
        # 如果启用了翻译，检查是否配置了API密钥
        if self.enabled and not self.use_place_name_fix:
            if not self.baidu_app_id or not self.baidu_secret_key:
                logger.warning("翻译已启用但未配置API密钥，翻译功能将不可用")
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
                'text_speed': self.gui_config.text_speed,
                'bg_color': self.gui_config.bg_color,
                'info_color': self.gui_config.info_color,
                'opacity': self.gui_config.opacity,
                'window_width': self.gui_config.window_width,
                'window_height': self.gui_config.window_height,
                'resizable': self.gui_config.resizable,
                'vsync_enabled': self.gui_config.vsync_enabled,
                'target_fps': self.gui_config.target_fps,
                'timezone': self.gui_config.timezone,
                'last_seen_changelog_version': self.gui_config.last_seen_changelog_version,
                'use_gpu_rendering': self.gui_config.use_gpu_rendering,
            },
            'MESSAGE_CONFIG': {
                'max_message_length': self.message_config.max_message_length,
                'display_duration': self.message_config.display_duration,
                'max_warning_inactivity_time': self.message_config.max_warning_inactivity_time,
                'warning_shock_validity_seconds': self.message_config.warning_shock_validity_seconds,
                'warning_min_display_seconds': self.message_config.warning_min_display_seconds,
                'max_report_inactivity_time': self.message_config.max_report_inactivity_time,
                'max_other_inactivity_time': self.message_config.max_other_inactivity_time,
                'no_activity_message': self.message_config.no_activity_message,
                'custom_text': self.message_config.custom_text,
                'use_custom_text': self.message_config.use_custom_text,
                'warning_color': self.message_config.warning_color,
                'report_color': self.message_config.report_color,
                'custom_text_color': self.message_config.custom_text_color,
                'default_color': self.message_config.default_color,
                'weather_warning_color': self.message_config.weather_warning_color,
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
                'baidu_app_id': self.translation_config.baidu_app_id,
                'baidu_secret_key': self.translation_config.baidu_secret_key,
                'enabled': self.translation_config.enabled,
                'use_place_name_fix': self.translation_config.use_place_name_fix,
            },
            'LOG_CONFIG': {
                'output_to_file': self.log_config.output_to_file,
                'clear_log_on_startup': self.log_config.clear_log_on_startup,
                'split_by_date': self.log_config.split_by_date,
                'max_log_size': self.log_config.max_log_size,
            },
            'ENABLED_SOURCES': dict(self.enabled_sources),
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
            
            # 加载数据源配置
            self.enabled_sources = config_data.get('ENABLED_SOURCES', {})
            
            # 确定基础域名和all数据源URL（固定使用fanstudio.tech）
            base_domain = "fanstudio.tech"
            all_url = f"wss://ws.{base_domain}/all"
            
            # 所有数据源列表（默认全部启用）
            all_warning_sources = ['cea', 'cea-pr', 'sichuan', 'cwa-eew', 'jma', 'sa', 'kma-eew']
            all_report_sources = ['cenc', 'ningxia', 'guangxi', 'shanxi', 'beijing', 'cwa', 'hko', 
                                 'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma', 'fssn']
            weather_source = 'weatheralarm'  # 气象预警

            # 如果配置文件中没有数据源配置，使用默认配置（启用所有数据源）
            if not self.enabled_sources:
                self.enabled_sources = {all_url: True}  # all数据源始终启用
                # 添加气象预警数据源
                self.enabled_sources[f"wss://ws.{base_domain}/{weather_source}"] = True
                # 添加所有预警数据源
                for source in all_warning_sources:
                    self.enabled_sources[f"wss://ws.{base_domain}/{source}"] = True
                # 添加所有速报数据源
                for source in all_report_sources:
                    self.enabled_sources[f"wss://ws.{base_domain}/{source}"] = True
                # 添加HTTP数据源
                self.enabled_sources["https://api.p2pquake.net/v2/history?codes=551&limit=3"] = True  # 日本气象厅地震情报
                self.enabled_sources["https://api.p2pquake.net/v2/jma/tsunami?limit=1"] = True  # 日本气象厅海啸预报
                # Wolfx HTTP / WSS、NIED WSS（默认关闭）
                for u in ["https://api.wolfx.jp/sc_eew.json", "https://api.wolfx.jp/jma_eew.json", "https://api.wolfx.jp/fj_eew.json",
                          "https://api.wolfx.jp/cenc_eew.json", "https://api.wolfx.jp/cwa_eew.json",
                          "https://api.wolfx.jp/cenc_eqlist.json", "https://api.wolfx.jp/jma_eqlist.json"]:
                    self.enabled_sources[u] = False
                self.enabled_sources["wss://ws-api.wolfx.jp/all_eew"] = False
                for u in ["wss://ws-api.wolfx.jp/sc_eew", "wss://ws-api.wolfx.jp/jma_eew", "wss://ws-api.wolfx.jp/fj_eew",
                          "wss://ws-api.wolfx.jp/cenc_eew", "wss://ws-api.wolfx.jp/cwa_eew",
                          "wss://ws-api.wolfx.jp/cenc_eqlist", "wss://ws-api.wolfx.jp/jma_eqlist"]:
                    self.enabled_sources[u] = False
                self.enabled_sources["wss://sismotide.top/nied"] = False

                logger.info("配置文件中没有数据源配置，使用默认配置（启用所有数据源）")
            else:
                # 配置文件中已有数据源配置，尊重用户的设置
                # 确保all数据源始终启用（这是必需的，因为实际连接的是all数据源）
                if all_url not in self.enabled_sources:
                    self.enabled_sources[all_url] = True
                    logger.debug(f"添加缺失的all数据源: {all_url}")
                else:
                    # all数据源必须启用，如果用户禁用了，强制启用
                    if not self.enabled_sources.get(all_url, False):
                        logger.warning(f"all数据源被禁用，但这是必需的，已自动启用: {all_url}")
                        self.enabled_sources[all_url] = True
                
                # 对于其他数据源，如果配置文件中没有，则添加并默认启用（向后兼容）
                # 但如果配置文件中已经存在（无论是true还是false），则尊重用户的设置
                weather_url = f"wss://ws.{base_domain}/{weather_source}"
                if weather_url not in self.enabled_sources:
                    self.enabled_sources[weather_url] = True
                    logger.debug(f"添加缺失的气象预警数据源: {weather_source}")
                # 如果已存在，尊重用户的设置，不强制启用
                
                # 确保所有预警数据源在配置中存在（如果不存在则默认启用，如果存在则尊重用户设置）
                for source in all_warning_sources:
                    url = f"wss://ws.{base_domain}/{source}"
                    if url not in self.enabled_sources:
                        self.enabled_sources[url] = True
                        logger.debug(f"添加缺失的预警数据源: {source}")
                # 如果已存在，尊重用户的设置，不强制启用
                
                # 确保所有速报数据源在配置中存在（如果不存在则默认启用，如果存在则尊重用户设置）
                for source in all_report_sources:
                    url = f"wss://ws.{base_domain}/{source}"
                    if url not in self.enabled_sources:
                        self.enabled_sources[url] = True
                        logger.debug(f"添加缺失的速报数据源: {source}")
                # 如果已存在，尊重用户的设置，不强制启用
                
                # 确保HTTP数据源在配置中存在（如果不存在则默认启用，如果存在则尊重用户设置）
                http_sources = {
                    "https://api.p2pquake.net/v2/history?codes=551&limit=3": "日本气象厅地震情报 (p2pquake)",
                }
                for http_url, source_name in http_sources.items():
                    if http_url not in self.enabled_sources:
                        self.enabled_sources[http_url] = True
                        logger.debug(f"添加缺失的HTTP数据源: {source_name}")
                if "https://api.p2pquake.net/v2/jma/tsunami?limit=1" not in self.enabled_sources:
                    self.enabled_sources["https://api.p2pquake.net/v2/jma/tsunami?limit=1"] = True
                    logger.debug("添加缺失的 P2PQuake 海啸预报数据源")
                # Wolfx HTTP 数据源（默认关闭）
                wolfx_http_sources = [
                    "https://api.wolfx.jp/sc_eew.json", "https://api.wolfx.jp/jma_eew.json",
                    "https://api.wolfx.jp/fj_eew.json", "https://api.wolfx.jp/cenc_eew.json",
                    "https://api.wolfx.jp/cwa_eew.json", "https://api.wolfx.jp/cenc_eqlist.json",
                    "https://api.wolfx.jp/jma_eqlist.json",
                ]
                for http_url in wolfx_http_sources:
                    if http_url not in self.enabled_sources:
                        self.enabled_sources[http_url] = False
                        logger.debug(f"添加缺失的 Wolfx HTTP 数据源: {http_url}")
                # Wolfx / NIED WebSocket 数据源（默认关闭）
                wolfx_wss = ["wss://ws-api.wolfx.jp/all_eew",
                             "wss://ws-api.wolfx.jp/sc_eew", "wss://ws-api.wolfx.jp/jma_eew", "wss://ws-api.wolfx.jp/fj_eew",
                             "wss://ws-api.wolfx.jp/cenc_eew", "wss://ws-api.wolfx.jp/cwa_eew",
                             "wss://ws-api.wolfx.jp/cenc_eqlist", "wss://ws-api.wolfx.jp/jma_eqlist",
                             "wss://sismotide.top/nied"]
                for wss_url in wolfx_wss:
                    if wss_url not in self.enabled_sources:
                        self.enabled_sources[wss_url] = False
                        logger.debug(f"添加缺失的 WSS 数据源: {wss_url}")
                # 如果已存在，尊重用户的设置，不强制启用

            # 根据服务器选择更新URL
            self._update_urls_for_server_selection()
            
            # 提取WebSocket URL（只包含all数据源和其他非fanstudio数据源）
            # all数据源必须包含，单项fanstudio数据源不直接连接，只作为过滤器
            base_domain = "fanstudio.tech"
            all_url = f"wss://ws.{base_domain}/all"
            
            # 确保all数据源在enabled_sources中且为True
            self.enabled_sources[all_url] = True
            
            ws_urls = []
            # all数据源必须包含（无论enabled_sources中的状态）
            ws_urls.append(all_url)
            logger.debug(f"已添加all数据源到ws_urls: {all_url}")
            
            # 添加其他非fanstudio数据源
            for url in self.enabled_sources.keys():
                if url.startswith(('ws://', 'wss://')) and url != all_url:
                    if 'fanstudio.tech' not in url and 'fanstudio.hk' not in url:
                        if self.enabled_sources.get(url, False):
                            ws_urls.append(url)
                            logger.debug(f"已添加非fanstudio数据源到ws_urls: {url}")
            
            self.ws_urls = ws_urls
            
            logger.info(f"配置加载成功，启用 {len(self.ws_urls)} 个WebSocket数据源")
            self._notify_config_changed()
            # 缺项补全：仅添加缺失的键并写回，不覆盖用户已有设置
            full = self._get_full_config_dict()
            merged = self._merge_config_file(config_data, full)
            if version_changed:
                merged['config_version'] = APP_VERSION
            if version_changed or self._has_missing_keys(config_data, full):
                try:
                    if self._write_config_dict(merged):
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
                        merged[key] = {**existing.get(key, {}), **our_value}
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
        # 默认启用所有数据源（固定使用fanstudio.tech）
        base_domain = "fanstudio.tech"
        all_url = f"wss://ws.{base_domain}/all"
        # 所有预警和速报数据源（对应Fan Studio预警和Fan Studio速报）
        warning_sources = ['cea', 'cea-pr', 'sichuan', 'cwa-eew', 'jma', 'sa', 'kma-eew']
        report_sources = ['cenc', 'ningxia', 'guangxi', 'shanxi', 'beijing', 'cwa', 'hko', 
                         'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma', 'fssn']
        weather_source = 'weatheralarm'  # 气象预警

        self.enabled_sources = {all_url: True}  # all数据源始终启用
        # 添加气象预警数据源（默认开启）
        self.enabled_sources[f"wss://ws.{base_domain}/{weather_source}"] = True
        # 添加所有预警数据源（Fan Studio预警）
        for source in warning_sources:
            self.enabled_sources[f"wss://ws.{base_domain}/{source}"] = True
        # 添加所有速报数据源（Fan Studio速报）
        for source in report_sources:
            self.enabled_sources[f"wss://ws.{base_domain}/{source}"] = True
        # 添加HTTP数据源
        self.enabled_sources["https://api.p2pquake.net/v2/history?codes=551&limit=3"] = True  # 日本气象厅地震情报
        self.enabled_sources["https://api.p2pquake.net/v2/jma/tsunami?limit=1"] = True  # 日本气象厅海啸预报
        # Wolfx HTTP（默认关闭）
        for u in ["https://api.wolfx.jp/sc_eew.json", "https://api.wolfx.jp/jma_eew.json", "https://api.wolfx.jp/fj_eew.json",
                  "https://api.wolfx.jp/cenc_eew.json", "https://api.wolfx.jp/cwa_eew.json",
                  "https://api.wolfx.jp/cenc_eqlist.json", "https://api.wolfx.jp/jma_eqlist.json"]:
            self.enabled_sources[u] = False
        # Wolfx / NIED WebSocket（默认关闭）
        self.enabled_sources["wss://ws-api.wolfx.jp/all_eew"] = False
        for u in ["wss://ws-api.wolfx.jp/sc_eew", "wss://ws-api.wolfx.jp/jma_eew", "wss://ws-api.wolfx.jp/fj_eew",
                  "wss://ws-api.wolfx.jp/cenc_eew", "wss://ws-api.wolfx.jp/cwa_eew",
                  "wss://ws-api.wolfx.jp/cenc_eqlist", "wss://ws-api.wolfx.jp/jma_eqlist"]:
            self.enabled_sources[u] = False
        self.enabled_sources["wss://sismotide.top/nied"] = False

        # 提取WebSocket URL（只包含all数据源和其他非fanstudio数据源）
        ws_urls = []
        # all数据源必须包含
        ws_urls.append(all_url)
        logger.debug(f"已添加all数据源到ws_urls: {all_url}")
        
        # 添加其他非fanstudio数据源
        for url in self.enabled_sources.keys():
            if url.startswith(('ws://', 'wss://')) and url != all_url:
                if 'fanstudio.tech' not in url and 'fanstudio.hk' not in url:
                    ws_urls.append(url)
                    logger.debug(f"已添加非fanstudio数据源到ws_urls: {url}")
        
        self.ws_urls = ws_urls
        logger.info(f"已应用默认配置，默认启用 {len(self.ws_urls)} 个WebSocket数据源（Fan Studio All + 默认数据源）: {self.ws_urls}")
    
    def update_enabled_sources(self, sources: Dict[str, bool]):
        """更新启用的数据源"""
        self.enabled_sources.update(sources)
        
        # 根据服务器选择更新URL
        self._update_urls_for_server_selection()
        
        # 提取WebSocket URL（只包含all数据源和其他非fanstudio数据源）
        # all数据源必须包含，单项fanstudio数据源不直接连接，只作为过滤器
        base_domain = "fanstudio.tech"
        all_url = f"wss://ws.{base_domain}/all"
        
        # 确保all数据源在enabled_sources中且为True
        self.enabled_sources[all_url] = True
        
        ws_urls = []
        # all数据源必须包含（无论enabled_sources中的状态）
        ws_urls.append(all_url)
        
        # 添加其他非fanstudio数据源
        for url in self.enabled_sources.keys():
            if url.startswith(('ws://', 'wss://')) and url != all_url:
                if 'fanstudio.tech' not in url and 'fanstudio.hk' not in url:
                    if self.enabled_sources.get(url, False):
                        ws_urls.append(url)
        
        self.ws_urls = ws_urls
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
        """获取数据源名称"""
        # 将URL中的域名统一为fanstudio.tech，以便查找
        # 统一使用fanstudio.tech（如果存在fanstudio.hk则替换）
        normalized_url = url.replace('fanstudio.hk', 'fanstudio.tech')
        
        source_name_mapping = {
            "wss://ws.fanstudio.tech/all": "fanstudio",
            "wss://ws.fanstudio.tech/weatheralarm": "weatheralarm",
            "wss://ws.fanstudio.tech/cenc": "cenc",
            "wss://ws.fanstudio.tech/cea": "cea",
            "wss://ws.fanstudio.tech/cea-pr": "cea-pr",
            "wss://ws.fanstudio.tech/sichuan": "sichuan",
            "wss://ws.fanstudio.tech/ningxia": "ningxia",
            "wss://ws.fanstudio.tech/guangxi": "guangxi",
            "wss://ws.fanstudio.tech/shanxi": "shanxi",
            "wss://ws.fanstudio.tech/beijing": "beijing",
            "wss://ws.fanstudio.tech/cwa": "cwa",
            "wss://ws.fanstudio.tech/cwa-eew": "cwa-eew",
            "wss://ws.fanstudio.tech/jma": "jma",
            "wss://ws.fanstudio.tech/hko": "hko",
            "wss://ws.fanstudio.tech/usgs": "usgs",
            "wss://ws.fanstudio.tech/sa": "sa",
            "wss://ws.fanstudio.tech/emsc": "emsc",
            "wss://ws.fanstudio.tech/bcsf": "bcsf",
            "wss://ws.fanstudio.tech/gfz": "gfz",
            "wss://ws.fanstudio.tech/usp": "usp",
            "wss://ws.fanstudio.tech/kma": "kma",
            "wss://ws.fanstudio.tech/kma-eew": "kma-eew",
            "wss://ws.fanstudio.tech/fssn": "fssn",
            "https://api.p2pquake.net/v2/history?codes=551&limit=3": "p2pquake",
            "https://api.p2pquake.net/v2/jma/tsunami?limit=1": "p2pquake_tsunami",
            # Wolfx HTTP
            "https://api.wolfx.jp/sc_eew.json": "wolfx_sc_eew",
            "https://api.wolfx.jp/jma_eew.json": "wolfx_jma_eew",
            "https://api.wolfx.jp/fj_eew.json": "wolfx_fj_eew",
            "https://api.wolfx.jp/cenc_eew.json": "wolfx_cenc_eew",
            "https://api.wolfx.jp/cwa_eew.json": "wolfx_cwa_eew",
            "https://api.wolfx.jp/cenc_eqlist.json": "wolfx_cenc_eqlist",
            "https://api.wolfx.jp/jma_eqlist.json": "wolfx_jma_eqlist",
            # Wolfx WebSocket（all 与单项）
            "wss://ws-api.wolfx.jp/all_eew": "wolfx_all_eew",
            "wss://ws-api.wolfx.jp/sc_eew": "wolfx_sc_eew",
            "wss://ws-api.wolfx.jp/jma_eew": "wolfx_jma_eew",
            "wss://ws-api.wolfx.jp/fj_eew": "wolfx_fj_eew",
            "wss://ws-api.wolfx.jp/cenc_eew": "wolfx_cenc_eew",
            "wss://ws-api.wolfx.jp/cwa_eew": "wolfx_cwa_eew",
            "wss://ws-api.wolfx.jp/cenc_eqlist": "wolfx_cenc_eqlist",
            "wss://ws-api.wolfx.jp/jma_eqlist": "wolfx_jma_eqlist",
            "wss://sismotide.top/nied": "nied",
        }
        
        return source_name_mapping.get(normalized_url, url)
    
    def get_organization_name(self, source_name: str) -> str:
        """获取机构名称"""
        organization_name_mapping = {
            "fanstudio": "Fan Studio数据源",
            "weatheralarm": "气象预警",
            "cenc": "中国地震台网中心自动测定/正式测定",
            "cea": "中国地震预警网",
            "cea-pr": "中国地震预警网-省级预警",
            "sichuan": "四川地震局地震预警",
            "ningxia": "宁夏地震局",
            "guangxi": "广西地震局",
            "shanxi": "山西地震局",
            "beijing": "北京地震局",
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
            # Wolfx
            "wolfx_sc_eew": "Wolfx 四川地震局预警",
            "wolfx_jma_eew": "Wolfx JMA 预警",
            "wolfx_fj_eew": "Wolfx 福建地震局预警",
            "wolfx_cenc_eew": "Wolfx CENC 预警",
            "wolfx_cwa_eew": "Wolfx CWA 预警",
            "wolfx_cenc_eqlist": "Wolfx CENC 速报",
            "wolfx_jma_eqlist": "Wolfx JMA 速报",
            "wolfx_all_eew": "Wolfx 全预警 (WSS)",
            "nied": "NIED 日本防災科研所预警",
        }
        
        return organization_name_mapping.get(source_name, source_name)