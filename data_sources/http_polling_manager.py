#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP轮询管理器
用于管理HTTP API数据源的定期轮询
"""

import time
import threading
import json
import requests
from typing import Dict, Callable, Optional, Any

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    Config,  # 读取应用配置
    APP_VERSION,  # 用于设置 User-Agent 的版本号
    P2PQUAKE_WSS_URL,  # P2PQuake 总开关对应的 WSS 地址
    FANSTUDIO_HTTP_SOURCE_KEYS,  # Fan Studio HTTP 数据源键集合
    BMKG_HTTP_URL,  # 印尼 BMKG 地震数据地址
    GEONET_HTTP_URL,  # 新西兰 GeoNet 地震数据地址
    INGV_HTTP_URL,  # 意大利 INGV 地震数据地址
    EARLYEST_HTTP_URL,  # INGV Early-est 数据地址
    JMA_ATOM_LONG_URL,  # 日本气象厅火山 XML 地址
    PTWC_CAP_URL,  # PTWC 海啸 CAP 地址
)
from adapters import (
    FanStudioHttpAdapter,
    P2PQuakeAdapter,
    P2PQuakeTsunamiAdapter,
    CustomAdapter,
    BMKGAdapter,
    GeoNetAdapter,
    INGVAdapter,
    EarlyEstAdapter,
    JmaAtomAdapter,
    PtwcAdapter,
)
from utils.logger import get_logger

logger = get_logger()

# 多路 HTTP 数据源同时启动时，各线程首次请求前的错开间隔（秒），减轻瞬时负载
HTTP_POLL_STARTUP_STAGGER_SEC = 1.0  # 启动阶段错峰首包请求


def is_http_source_enabled(config: Config, url: str) -> bool:
    """判断指定 HTTP URL 是否应发起 Get 轮询（与设置页开关、P2PQuake 总开关一致）。"""
    if not url:
        return False
    low = url.lower()
    # 自定义 HTTP：URL 非空即启用（由 start_all_connections 单独判断）
    custom_url = (config.custom_data_source_url or "").strip()
    if custom_url and url == custom_url:
        return True  # 自定义 HTTP 源只要 URL 匹配就允许轮询
    if not config.enabled_sources.get(url, False):
        return False  # 未启用的数据源直接跳过
    if "api.p2pquake.net" in low:
        if not config.enabled_sources.get(P2PQUAKE_WSS_URL, False):
            return False
        mc = config.message_config
        if "history" in low and "551" in low:
            if not getattr(mc, "p2pquake_parse_551", True):
                return False
        if "tsunami" in low:
            if not getattr(mc, "p2pquake_parse_552", True):
                return False
    return True


class HTTPPollingConnection:
    """单个HTTP轮询连接管理"""
    
    def __init__(self, url: str, source_name: str, adapter: Any, config: Config, poll_interval: int = 2):
        """
        初始化HTTP轮询连接
        
        Args:
            url: API URL
            source_name: 数据源名称
            adapter: 数据适配器
            config: 配置对象
            poll_interval: 轮询间隔（秒），默认2秒
        """
        self.url = url
        self.source_name = source_name
        self.adapter = adapter
        self.config = config
        self.poll_interval = poll_interval
        self._running = True  # 连接存活标志
        self._last_poll_time = 0  # 上次轮询时间戳
        self._last_data_hash = None  # 用于检测数据变化
        self._last_error_log_time = 0.0  # 重复错误降噪：上次打 ERROR 的时间
        self._last_error_msg = ""  # 重复错误降噪：上次错误摘要
        self.last_request_ok = False  # 最近一次请求是否成功（供设置页状态指示）
        self.last_request_time = 0.0  # 最近一次请求时间
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': f'EarthquakeScroller/{APP_VERSION}'  # 统一请求标识，便于服务端识别
        })
        
        # 所有HTTP数据源都需要禁用代理
        self._session.proxies = {
            'http': None,
            'https': None
        }  # 强制直连，避免系统代理影响轮询
        logger.debug(f"[{self.source_name}] 已禁用代理（HTTP数据源）")

    def _request_verify_ssl(self) -> bool:
        """自定义 HTTP 源可配置跳过 SSL 校验；其余源始终校验。"""
        custom_url = (self.config.custom_data_source_url or "").strip()
        if custom_url and self.url == custom_url:
            return not bool(getattr(self.config, 'custom_data_source_insecure_ssl', False))
        return True

    def start(
        self,
        message_callback: Callable[[str, Dict], None],
        startup_delay: float = 0.0,
    ):
        """启动轮询

        Args:
            message_callback: 收到数据后的回调
            startup_delay: 线程启动后、首次轮询前的等待秒数（用于多源错开首包请求）
        """
        def poll_loop():
            """轮询线程主循环：按间隔调用 _poll 并处理异常。"""
            if startup_delay and startup_delay > 0:
                time.sleep(startup_delay)
            logger.info(f"[{self.source_name}] HTTP轮询线程已启动，轮询间隔: {self.poll_interval}秒")
            
            while self._running:
                try:
                    # 检查是否应该轮询
                    current_time = time.time()
                    if current_time - self._last_poll_time < self.poll_interval:
                        time.sleep(1)
                        continue
                    
                    # 执行轮询
                    self._poll(message_callback)
                    self._last_poll_time = current_time
                    
                except Exception as e:
                    logger.error(f"[{self.source_name}] 轮询循环出错: {e}")
                    time.sleep(5)  # 出错后等待5秒再继续
        
        thread = threading.Thread(target=poll_loop, daemon=True, name=f"HTTPPoll-{self.source_name}")
        thread.start()
    
    def _poll(self, message_callback: Callable[[str, Dict], None]):
        """执行一次轮询（失败时最多重试3次，每次间隔2秒；同源同错误60秒内只记一次ERROR）"""
        try:
            if not is_http_source_enabled(self.config, self.url):
                logger.debug(f"[{self.source_name}] 数据源已关闭，跳过 Get: {self.url}")
                return
            logger.debug(f"[{self.source_name}] 开始轮询: {self.url}")
            
            # 发送HTTP请求，失败时重试最多3次，每次间隔2秒
            response = None
            for attempt in range(1, 4):
                try:
                    req_headers = dict(getattr(self.adapter, "fetch_headers", None) or {})
                    response = self._session.get(
                        self.url,
                        timeout=30,
                        proxies={'http': None, 'https': None},
                        headers=req_headers if req_headers else None,
                        verify=self._request_verify_ssl(),
                    )
                    response.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    if attempt < 3:
                        time.sleep(2)
                        continue
                    # 所有重试均失败，记录错误（重复错误降噪：60秒内同种错误只记一次ERROR）
                    now = time.time()
                    err_summary = f"{type(e).__name__}: {str(e)[:120]}"
                    if now - self._last_error_log_time < 60 and err_summary == self._last_error_msg:
                        logger.debug(f"[{self.source_name}] HTTP请求失败（已降噪）: {e}")
                    else:
                        is_ssl = isinstance(e, requests.exceptions.SSLError)
                        if is_ssl and not self._request_verify_ssl():
                            logger.warning(
                                f"[{self.source_name}] HTTP请求失败（已跳过 SSL 校验仍失败）: {e}"
                            )
                        elif is_ssl:
                            logger.warning(
                                f"[{self.source_name}] HTTP请求失败（SSL 证书无效）: {e}"
                            )
                        else:
                            logger.error(f"[{self.source_name}] HTTP请求失败: {e}")
                        self._last_error_log_time = now
                        self._last_error_msg = err_summary
                    self.last_request_ok = False
                    return
            
            if response is None:
                self.last_request_ok = False
                return
            
            self.last_request_ok = True
            self.last_request_time = time.time()
            
            # 解析响应（按适配器声明的格式）
            response_format = getattr(self.adapter, "response_format", "json")
            if response_format == "json":
                data = response.json()
            elif response_format == "text":
                data = response.text
            elif response_format == "bytes":
                data = response.content
            else:
                data = response.content
            
            # 计算数据哈希（简单检测是否有新数据）
            import hashlib
            if isinstance(data, (bytes, bytearray)):
                data_hash = hashlib.md5(bytes(data)).hexdigest()
            elif isinstance(data, str):
                data_hash = hashlib.md5(data.encode("utf-8", errors="replace")).hexdigest()
            else:
                data_str = json.dumps(data, sort_keys=True, default=str)
                data_hash = hashlib.md5(data_str.encode()).hexdigest()
            
            # 如果数据没有变化，跳过处理
            if data_hash == self._last_data_hash:
                logger.debug(f"[{self.source_name}] 数据未变化，跳过处理")
                return

            is_first_poll = self._last_data_hash is None
            self._last_data_hash = data_hash
            
            # 使用适配器解析数据（P2PQuake HTTP 等仅需首条时由 parse() 返回单条）
            logger.debug(f"[{self.source_name}] 开始解析数据，数据类型: {type(data)}, 数据长度: {len(data) if isinstance(data, (list, dict)) else 'N/A'}")
            parsed_result = self.adapter.parse(data)
            
            if parsed_result:
                if isinstance(parsed_result, list):
                    for idx, item in enumerate(parsed_result, start=1):
                        if is_first_poll and isinstance(item, dict):
                            item["_suppress_tts"] = True
                        message_callback(self.source_name, item)
                    logger.info(f"[{self.source_name}] 解析成功，处理了{len(parsed_result)}条数据")
                else:
                    if is_first_poll and isinstance(parsed_result, dict):
                        parsed_result["_suppress_tts"] = True
                    logger.info(f"[{self.source_name}] 解析成功，解析结果: type={parsed_result.get('type')}, organization={parsed_result.get('organization')}, place_name={parsed_result.get('place_name')}")
                    message_callback(self.source_name, parsed_result)
                    logger.info(f"[{self.source_name}] 轮询成功，处理了最新1条数据")
            else:
                empty_data = (
                    data is None
                    or (isinstance(data, list) and len(data) == 0)
                    or (isinstance(data, dict) and not data)
                )
                _silent_none_sources = (
                    'p2pquake', 'p2pquake_tsunami',
                    'fanstudio_typhoon', 'early_est',
                )
                if empty_data or self.source_name in _silent_none_sources:
                    logger.debug(
                        f"[{self.source_name}] 轮询成功，无新数据可解析（适配器返回 None）"
                    )
                else:
                    logger.warning(
                        f"[{self.source_name}] 轮询成功，但适配器解析返回None，可能数据格式不正确或解析失败"
                    )
                # 输出更详细的数据信息用于调试
                if isinstance(data, dict):
                    logger.debug(f"[{self.source_name}] 数据键: {list(data.keys())}")
                    logger.debug(f"[{self.source_name}] 数据类型字段: {data.get('type', 'N/A')}")
                    if 'No1' in data:
                        logger.debug(f"[{self.source_name}] No1字段存在，类型: {type(data.get('No1'))}")
                    else:
                        logger.debug(f"[{self.source_name}] No1字段不存在")
                elif isinstance(data, list):
                    logger.debug(f"[{self.source_name}] 数据是列表，长度: {len(data)}")
                    if len(data) > 0:
                        logger.debug(f"[{self.source_name}] 列表第一项类型: {type(data[0])}, 内容预览: {str(data[0])[:300]}")
                else:
                    logger.debug(f"[{self.source_name}] 原始数据预览: {str(data)[:500] if isinstance(data, (str, dict, list)) else type(data)}")
                
        except requests.exceptions.RequestException as e:
            self.last_request_ok = False
            logger.error(f"[{self.source_name}] HTTP请求失败: {e}")
        except Exception as e:
            self.last_request_ok = False
            logger.error(f"[{self.source_name}] 轮询处理失败: {e}")
    
    def stop(self):
        """停止轮询"""
        logger.info(f"[{self.source_name}] 正在停止HTTP轮询...")
        self._running = False
        self._session.close()


class HTTPPollingManager:
    """HTTP轮询管理器"""
    
    def __init__(self, message_callback: Callable[[str, Dict], None]):
        """
        初始化HTTP轮询管理器
        
        Args:
            message_callback: 消息回调函数，接收(source_name, parsed_data)
        """
        self.message_callback = message_callback
        self.config = Config()
        self.connections: Dict[str, HTTPPollingConnection] = {}
        self._running = True
        
        logger.info("HTTP轮询管理器初始化完成")
    
    def get_adapter(self, url: str) -> Optional[Any]:
        """根据URL获取对应的适配器"""
        # 自定义数据源（HTTP/HTTPS）
        if self.config.custom_data_source_url and url == self.config.custom_data_source_url:
            if url.startswith('http://') or url.startswith('https://'):
                return CustomAdapter('custom', url)
        # P2PQuake 海啸预报
        if 'api.p2pquake.net' in url and 'tsunami' in url.lower():
            return P2PQuakeTsunamiAdapter('p2pquake_tsunami', url)
        # Fan Studio 台风 / AQI HTTP 数据源
        if url in FANSTUDIO_HTTP_SOURCE_KEYS:
            if 'typhoon.php' in url:
                return FanStudioHttpAdapter('fanstudio_typhoon', url)
            if 'aqi.php' in url:
                return FanStudioHttpAdapter('fanstudio_aqi', url)
        # P2PQuake 地震情报
        if 'api.p2pquake.net' in url:
            return P2PQuakeAdapter('p2pquake', url)
        if url == BMKG_HTTP_URL:
            return BMKGAdapter('bmkg', url)
        if url == GEONET_HTTP_URL:
            return GeoNetAdapter('geonet', url)
        if url == INGV_HTTP_URL:
            return INGVAdapter('ingv', url)
        if url == EARLYEST_HTTP_URL:
            return EarlyEstAdapter('early_est', url)
        if url == JMA_ATOM_LONG_URL:
            return JmaAtomAdapter('jma_volcano', url)
        if url == PTWC_CAP_URL:
            return PtwcAdapter('ptwc', url)
        # 已下线的 Wolfx HTTP 不提供适配器，跳过
        if 'api.wolfx.jp' in url or 'wolfx' in url.lower():
            return None
        return None
    
    def start_all_connections(self):
        """启动所有HTTP轮询连接"""
        # 从配置中获取启用的HTTP数据源
        http_urls = []
        for url in self.config.enabled_sources.keys():
            if url.startswith('http://') or url.startswith('https://'):
                if is_http_source_enabled(self.config, url):
                    http_urls.append(url)
                    logger.debug(f"发现启用的HTTP数据源: {url}")
                else:
                    logger.debug(f"HTTP数据源已禁用: {url}")
        # 自定义数据源（HTTP/HTTPS）：URL 非空即启用
        custom_url = (self.config.custom_data_source_url or "").strip()
        if custom_url and (custom_url.startswith('http://') or custom_url.startswith('https://')):
            if custom_url not in http_urls:
                http_urls.append(custom_url)
                logger.debug(f"发现自定义HTTP数据源: {custom_url}")
        
        if not http_urls:
            logger.info("没有启用的HTTP数据源")
            return
        
        logger.info(f"开始启动 {len(http_urls)} 个HTTP数据源（错开首包间隔 {HTTP_POLL_STARTUP_STAGGER_SEC}s）...")
        
        http_started_index = 0
        for url in http_urls:
            source_name = self.config.get_source_name(url)
            logger.debug(f"正在为 {url} 创建适配器，数据源名称: {source_name}")
            adapter = self.get_adapter(url)
            
            if adapter is None:
                # 对于未配置适配器的 HTTP 数据源，直接跳过，不再输出错误日志
                continue
            
            poll_interval = self.config.get_http_poll_interval(url)
            connection = HTTPPollingConnection(url, source_name, adapter, self.config, poll_interval=poll_interval)
            self.connections[url] = connection
            
            startup_delay = HTTP_POLL_STARTUP_STAGGER_SEC * http_started_index  # 为多源首轮请求错峰
            http_started_index += 1
            connection.start(self.message_callback, startup_delay=startup_delay)
            
            logger.info(f"已启动HTTP轮询: {source_name}（首包延迟 {startup_delay:.1f}s）")
    
    def get_custom_source_status(self, url: str) -> Optional[str]:
        """
        获取自定义数据源（HTTP/HTTPS）的最近一次请求状态，供设置页状态指示使用。

        Args:
            url: 自定义数据源 URL

        Returns:
            'ok' 表示最近一次请求成功，'error' 表示失败，None 表示该 URL 未在连接中（未配置或未运行）
        """
        if not url or url not in self.connections:
            return None
        conn = self.connections[url]
        return 'ok' if conn.last_request_ok else 'error'
    
    def stop_all(self):
        """停止所有轮询连接"""
        logger.info("正在停止所有HTTP轮询连接...")
        self._running = False
        
        for url, connection in self.connections.items():
            try:
                connection.stop()
                logger.info(f"已停止HTTP轮询: {connection.source_name}")
            except Exception as e:
                logger.error(f"停止HTTP轮询 {url} 时出错: {e}")
        
        self.connections.clear()
        logger.info("所有HTTP轮询连接已停止")

    def update_poll_intervals(self, intervals: Dict[str, int]) -> None:
        """热更新已运行连接的轮询间隔（秒）"""
        for url, connection in self.connections.items():
            if url in intervals:
                connection.poll_interval = max(1, int(intervals[url]))
                logger.info(
                    f"已更新 HTTP 轮询间隔: {connection.source_name} -> {connection.poll_interval}s"
                )
