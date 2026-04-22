#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket连接管理器
负责管理所有WebSocket数据源的连接、消息接收和发送
"""

import asyncio
import json
import re
import websockets
from typing import Dict, Callable, Optional, Any
from collections import defaultdict
from queue import Queue, Empty
import requests

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from adapters import (
    FanStudioAdapter,
    P2PQuakeWebSocketAdapter,
    CustomAdapter,
    P2PQuakeAdapter,
    P2PQuakeTsunamiAdapter,
    WolfxAdapter,
)
from utils.logger import get_logger

logger = get_logger()

# P2PQuake HTTP 聚合接口：同时包含 551 地震情报与 552 津波预报
P2PQUAKE_HISTORY_URL = "https://api.p2pquake.net/v2/history?codes=551&codes=552&limit=10"
P2PQUAKE_WSS_URL = "wss://api.p2pquake.net/v2/ws"
FANSTUDIO_ALL_URLS = ("wss://ws.fanstudio.tech/all")
WOLFX_ALL_EEW_URL = "wss://ws-api.wolfx.jp/all_eew"


class WebSocketManager:
    """WebSocket连接管理器"""
    
    def __init__(self, message_callback: Callable[[str, Dict], None]):
        """
        初始化WebSocket管理器
        
        Args:
            message_callback: 消息回调函数，接收(source_name, parsed_data)
        """
        self.message_callback = message_callback
        self.connections: Dict[str, Any] = {}  # 存储活跃的WebSocket连接 {url: websocket}
        self.reconnect_attempts = defaultdict(int)
        self.enabled_sources: Dict[str, bool] = {}  # 数据源启用状态
        self._send_queues: Dict[str, Queue] = {}  # 每个URL的消息发送队列
        self._connection_tasks: Dict[str, asyncio.Task] = {}  # 连接任务字典
        
        # 加载配置
        config = Config()
        self.max_reconnect_attempts = config.ws_config.max_reconnect_attempts
        self.reconnect_interval = config.ws_config.reconnect_interval
        self.ping_interval = config.ws_config.ping_interval
        self.ping_timeout = config.ws_config.ping_timeout
        self.close_timeout = config.ws_config.close_timeout
        self.open_timeout = config.ws_config.connection_timeout
    
    def get_adapter(self, url: str) -> Optional[Any]:
        """
        根据URL获取对应的适配器
        
        Args:
            url: WebSocket URL
            
        Returns:
            适配器实例
        """
        # Wolfx 聚合预警源
        if 'ws-api.wolfx.jp' in url and url.rstrip('/').endswith('/all_eew'):
            adapter = WolfxAdapter('wolfx_all_eew', url)
            adapter._manager_source_type = 'wolfx_all_eew'
            return adapter
        # 检查是否为Fan Studio数据源
        if 'fanstudio.tech' in url or 'fanstudio.hk' in url:
            parts = url.split('/')
            source_type = parts[-1] if parts[-1] else parts[-2]
            adapter = FanStudioAdapter(source_type, url)
            adapter._manager_source_type = source_type
            return adapter
        # P2PQuake WebSocket（仅解析 551、552）
        if 'api.p2pquake.net' in url and (url.startswith('ws://') or url.startswith('wss://')):
            adapter = P2PQuakeWebSocketAdapter('p2pquake_ws', url)
            adapter._manager_source_type = 'p2pquake_ws'
            return adapter
        # 自定义数据源（WS/WSS）
        config = Config()
        if config.custom_data_source_url and url == config.custom_data_source_url:
            if url.startswith('ws://') or url.startswith('wss://'):
                adapter = CustomAdapter('custom', url)
                adapter._manager_source_type = 'custom'
                return adapter
        # 默认使用Fan Studio适配器
        adapter = FanStudioAdapter('unknown', url)
        adapter._manager_source_type = 'unknown'
        return adapter
    
    def _get_source_name_from_data(self, parsed_data: Dict, default_source: str) -> str:
        """
        从解析后的数据中获取实际的数据源名称
        
        Args:
            parsed_data: 解析后的数据
            default_source: 默认数据源名称
            
        Returns:
            实际的数据源名称
        """
        try:
            config = Config()
            
            # 优先使用source_type字段（适配器已添加）
            source_type = parsed_data.get('source_type', '')
            # Wolfx 与 P2PQuake 子源：直接返回 source_type 参与轮播优先级排序。
            direct_sub_sources = (
                'wolfx_jma_eew',
                'wolfx_sc_eew',
                'wolfx_fj_eew',
                'wolfx_cenc_eew',
            )
            if source_type in direct_sub_sources:
                return source_type
            if source_type:
                return config.get_source_name(f"wss://ws.fanstudio.tech/{source_type}")
            
            # 尝试从raw_data中获取数据源信息
            raw_data = parsed_data.get('raw_data', {})
            if 'source' in raw_data:
                source = raw_data['source']
                return config.get_source_name(f"wss://ws.fanstudio.tech/{source}")
            elif '_update_source' in raw_data:
                source = raw_data['_update_source']
                return config.get_source_name(f"wss://ws.fanstudio.tech/{source}")
            
            # 根据organization推断
            organization = parsed_data.get('organization', '')
            org_mapping = {
                "中国地震台网中心自动测定/正式测定": "cenc",
                "中国地震预警网": "cea",
                "中国地震预警网-省级预警": "cea-pr",
                "宁夏地震局": "ningxia",
                "广西地震局": "guangxi",
                "山西地震局": "shanxi",
                "北京地震局": "beijing",
                "云南地震局": "yunnan",
                "台湾中央气象署": "cwa",
                "台湾中央气象署地震预警": "cwa-eew",
                "日本气象厅": "jma",
                "香港天文台": "hko",
                "美国地质调查局": "usgs",
                "美国ShakeAlert地震预警": "sa",
                "欧洲地中海地震中心": "emsc",
                "法国中央地震研究所": "bcsf",
                "德国地学研究中心": "gfz",
                "巴西圣保罗大学": "usp",
                "韩国气象厅": "kma",
                "韩国气象厅地震预警": "kma-eew",
                "FSSN": "fssn",
                "气象预警": "weatheralarm",
                "自然资源部海啸预警中心": "tsunami",
            }
            source = org_mapping.get(organization, default_source)
            return config.get_source_name(f"wss://ws.fanstudio.tech/{source}") if source != default_source else default_source
        except Exception as e:
            logger.error(f"获取数据源名称失败: {e}")
            return default_source
    
    async def _process_message(self, message: str, adapter: Any, source_name: str, url: str):
        """
        处理接收到的消息
        
        Args:
            message: 原始消息字符串
            adapter: 适配器实例
            source_name: 数据源名称
            url: WebSocket URL
        """
        try:
            # 解析JSON
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                # 尝试清理特殊字符后重新解析
                cleaned_message = re.sub(r'[\x00-\x1F]+', '', message)
                try:
                    data = json.loads(cleaned_message)
                except (json.JSONDecodeError, ValueError, TypeError):
                    logger.warning(f"[{source_name}] JSON解析失败，跳过消息")
                    return
            
            # 跳过心跳消息
            if isinstance(data, dict) and data.get('type') == 'heartbeat':
                logger.debug(f"[{source_name}] 收到心跳消息")
                return
            
            # 获取数据源类型
            data_source_type = getattr(adapter, '_manager_source_type', 'unknown')
            
            # 处理initial_all类型
            if isinstance(data, dict) and data.get('type') == 'initial_all' and data_source_type == 'all':
                logger.info(f"[{source_name}] 收到initial_all类型消息，开始处理所有数据源")
                all_parsed_data = adapter.parse_all_sources(data)
                logger.info(f"[{source_name}] initial_all解析完成，共{len(all_parsed_data)}条有效数据")
                
                for parsed_data in all_parsed_data:
                    if parsed_data:
                        actual_source = self._get_source_name_from_data(parsed_data, source_name)
                        msg_type = parsed_data.get('type', 'unknown')
                        logger.info(f"[{actual_source}] {msg_type}消息")
                        self.message_callback(actual_source, parsed_data)
            else:
                # 普通解析（包括 update 类型、NIED、P2PQuake）
                parsed_data = adapter.parse(data)
                if parsed_data:
                    # Wolfx / P2PQuake WSS：用 parsed_data 的 source_type 作为 actual_source
                    pt = parsed_data.get('source_type', '')
                    direct_sources = (
                        'wolfx_jma_eew',
                        'wolfx_sc_eew',
                        'wolfx_fj_eew',
                        'wolfx_cenc_eew',
                        'p2pquake',
                        'p2pquake_tsunami',
                    )
                    if pt and (pt in direct_sources):
                        actual_source = pt
                    elif isinstance(data, dict) and data.get('type') == 'update':
                        actual_source = self._get_source_name_from_data(parsed_data, source_name)
                    else:
                        actual_source = source_name
                    msg_type = parsed_data.get('type', 'unknown')
                    logger.info(f"[{actual_source}] {msg_type}消息")
                    self.message_callback(actual_source, parsed_data)
                else:
                    logger.debug(f"[{source_name}] 数据无效或被过滤")
        except Exception as e:
            logger.error(f"[{source_name}] 处理消息时出错: {e}", exc_info=True)
    
    async def _send_pending_messages(self, websocket: Any, url: str, source_name: str):
        """
        发送队列中的待发送消息
        
        Args:
            websocket: WebSocket连接对象
            url: WebSocket URL
            source_name: 数据源名称
        """
        try:
            send_queue = self._send_queues.get(url)
            if send_queue:
                while True:
                    try:
                        message_to_send = send_queue.get_nowait()
                        await websocket.send(message_to_send)
                        logger.info(f"[{source_name}] 已发送消息: {message_to_send[:100]}...")
                    except Empty:
                        break
                    except Exception as e:
                        logger.error(f"[{source_name}] 发送消息失败: {e}")
        except (KeyError, AttributeError):
            pass
        except Exception as e:
            logger.debug(f"[{source_name}] 检查发送队列失败: {e}")
    
    async def connect_to_source(self, url: str, source_name: str):
        """
        连接到单个数据源
        
        Args:
            url: WebSocket URL
            source_name: 数据源名称
        """
        adapter = self.get_adapter(url)
        
        while True:
            # 检查是否启用
            if not self.enabled_sources.get(url, True):
                await asyncio.sleep(30)
                continue
            
            try:
                logger.debug(f"[{source_name}] 连接中...")
                
                async with websockets.connect(
                    url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    close_timeout=self.close_timeout,
                    open_timeout=self.open_timeout
                ) as websocket:
                    logger.info(f"[{source_name}] 已连接到 {url}")
                    self.reconnect_attempts[url] = 0
                    self.connections[url] = websocket
                    
                    # 创建发送队列（如果不存在）
                    if url not in self._send_queues:
                        self._send_queues[url] = Queue()
                    
                    # 主消息循环
                    while True:
                        # 发送待发送的消息
                        await self._send_pending_messages(websocket, url, source_name)
                        
                        # 接收消息（使用超时，以便定期检查发送队列）
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=0.5)
                            logger.debug(f"[{source_name}] 收到消息，长度: {len(message) if isinstance(message, str) else len(str(message))}")
                            await self._process_message(message, adapter, source_name, url)
                        except asyncio.TimeoutError:
                            # 超时，继续循环检查发送队列
                            continue
                            
            except websockets.ConnectionClosed as e:
                logger.warning(f"[{source_name}] 连接断开: code={e.code}, reason={getattr(e, 'reason', 'N/A')}")
                self._cleanup_connection(url, source_name)
            except TimeoutError as e:
                logger.warning(f"[{source_name}] 连接超时（握手阶段）: {e}，将按重连间隔重试")
                self._cleanup_connection(url, source_name)
            except Exception as e:
                logger.error(f"[{source_name}] 连接错误: {e}", exc_info=True)
                self._cleanup_connection(url, source_name)
            
            # 重连逻辑
            if not await self._should_reconnect(url, source_name):
                continue
            
            # 等待后重连（指数退避）
            wait_time = min(self.reconnect_attempts[url] * 2, 30)
            attempt = self.reconnect_attempts[url]
            logger.debug(f"[{source_name}] {wait_time}秒后重连(第{attempt}次)")
            await asyncio.sleep(wait_time)
    
    def is_connection_active(self, url: str) -> bool:
        """
        检查指定 URL 的 WebSocket 连接是否处于活跃状态（供设置页状态指示使用）。

        Args:
            url: WebSocket URL

        Returns:
            若该 URL 在 connections 中则视为已连接，否则为未连接
        """
        if url not in self.connections:
            return False
        ws = self.connections[url]
        try:
            return getattr(ws, 'open', True)
        except Exception:
            return True

    def _cleanup_connection(self, url: str, source_name: str):
        """
        清理连接资源

        Args:
            url: WebSocket URL
            source_name: 数据源名称
        """
        if url in self.connections:
            del self.connections[url]
            logger.debug(f"[{source_name}] 已从connections字典移除，当前连接数: {len(self.connections)}")
    
    async def _should_reconnect(self, url: str, source_name: str) -> bool:
        """
        判断是否应该重连
        
        Args:
            url: WebSocket URL
            source_name: 数据源名称
            
        Returns:
            是否应该重连
        """
        self.reconnect_attempts[url] += 1
        
        # 检查是否超过最大重连次数
        if self.max_reconnect_attempts > 0 and self.reconnect_attempts[url] >= self.max_reconnect_attempts:
            logger.warning(f"[{source_name}] 重连失败{self.max_reconnect_attempts}次，暂停")
            self.enabled_sources[url] = False
            return False
        
        return True
    
    async def _fetch_p2p_initial_http(self, config: Config):
        """
        在启用 P2PQuake WebSocket 时，启动阶段先通过 HTTP 拉取一次最新地震与海啸情报。
        """
        try:
            logger.info("P2PQuake WSS 启动前，先通过 HTTP 拉取一次最新地震/海啸情报（聚合 551/552）")

            async def _fetch_history():
                def _request():
                    try:
                        resp = requests.get(
                            P2PQUAKE_HISTORY_URL,
                            timeout=10,
                            proxies={"http": None, "https": None},
                        )
                        resp.raise_for_status()
                        return resp.json()
                    except Exception as e:
                        logger.error(f"[p2pquake] 启动前 HTTP 获取地震/海啸情报失败: {e}")
                        return None

                data = await asyncio.to_thread(_request)
                if not data:
                    return
                if not isinstance(data, list):
                    logger.error(f"[p2pquake] 启动前 HTTP 返回数据格式错误，期望 list，实际 {type(data)}")
                    return
                if not data:
                    logger.info("[p2pquake] 启动前 HTTP 无返回记录")
                    return

                eq_adapter = P2PQuakeAdapter("p2pquake", P2PQUAKE_HISTORY_URL)
                tsu_adapter = P2PQuakeTsunamiAdapter("p2pquake_tsunami", P2PQUAKE_HISTORY_URL)
                eq_count = 0
                tsu_count = 0

                for item in data:
                    if not isinstance(item, dict):
                        continue
                    code = item.get("code")
                    if code == 551:
                        try:
                            parsed = eq_adapter._parse_single_item(item)
                        except Exception as e:
                            logger.error(f"[p2pquake] 启动前 HTTP 解析地震情报单条失败: {e}", exc_info=True)
                            continue
                        if parsed:
                            self.message_callback("p2pquake", parsed)
                            eq_count += 1
                    elif code == 552:
                        try:
                            parsed = tsu_adapter.parse_single_item(item)
                        except Exception as e:
                            logger.error(f"[p2pquake_tsunami] 启动前 HTTP 解析海啸情报单条失败: {e}", exc_info=True)
                            continue
                        if parsed:
                            self.message_callback("p2pquake_tsunami", parsed)
                            tsu_count += 1

                logger.info(f"[p2pquake] 启动前 HTTP 推送 {eq_count} 条地震情报, {tsu_count} 条海啸情报")

            await _fetch_history()
        except Exception as e:
            logger.error(f"P2PQuake 启动前 HTTP 拉取阶段异常: {e}", exc_info=True)

    def _classify_startup_group(self, url: str) -> str:
        """
        启动分组：
        1) fanstudio(all)
        2) p2pquake(wss)
        3) wolfx(all_eew)
        4) 其他
        """
        normalized_url = (url or "").strip().lower()
        if normalized_url in FANSTUDIO_ALL_URLS:
            return "fanstudio"
        if normalized_url == P2PQUAKE_WSS_URL:
            return "p2pquake"
        if normalized_url == WOLFX_ALL_EEW_URL:
            return "wolfx"
        return "other"
    
    async def start_all_connections(self):
        """启动所有数据源连接"""
        config = Config()
        enabled_urls = []
        
        # 获取启用的WebSocket URL
        for url in config.ws_urls:
            if config.enabled_sources.get(url, True):
                enabled_urls.append(url)
                self.enabled_sources[url] = True
        # 自定义数据源（WS/WSS）：URL 非空即启用
        custom_url = (config.custom_data_source_url or "").strip()
        if custom_url and (custom_url.startswith('ws://') or custom_url.startswith('wss://')):
            if custom_url not in enabled_urls:
                enabled_urls.append(custom_url)
                self.enabled_sources[custom_url] = True
                logger.debug(f"添加自定义WebSocket数据源: {custom_url}")
        
        if not enabled_urls:
            logger.warning("ws_urls为空，没有可连接的数据源！")
            logger.warning(f"config.ws_urls = {config.ws_urls}")
            logger.warning(f"config.enabled_sources中包含的WebSocket URL: {[url for url in config.enabled_sources.keys() if url.startswith(('ws://', 'wss://'))]}")
        else:
            logger.info(f"准备连接{len(enabled_urls)}个数据源: {enabled_urls}")
        
        # 创建所有连接任务
        grouped_urls: Dict[str, list] = {
            "fanstudio": [],
            "p2pquake": [],
            "wolfx": [],
            "other": [],
        }
        for url in enabled_urls:
            grouped_urls[self._classify_startup_group(url)].append(url)

        # 启动阶段顺序固定：fanstudio -> p2pquake -> wolfx -> other
        startup_stages = ("fanstudio", "p2pquake", "wolfx", "other")
        tasks = []
        urls_for_tasks = []
        for stage in startup_stages:
            stage_urls = grouped_urls.get(stage, [])
            if not stage_urls:
                continue

            # P2PQuake 在其阶段启动前，先进行一次 HTTP 初始拉取
            if stage == "p2pquake" and P2PQUAKE_WSS_URL in stage_urls:
                try:
                    await self._fetch_p2p_initial_http(config)
                except Exception as e:
                    logger.error(f"P2PQuake 启动前 HTTP 拉取失败: {e}", exc_info=True)

            logger.info(f"启动阶段[{stage}]，准备创建 {len(stage_urls)} 个连接任务")
            for url in stage_urls:
                adapter = self.get_adapter(url)
                if adapter is None:
                    logger.debug(f"跳过无适配器的数据源: {url}")
                    continue
                source_name = config.get_source_name(url)
                logger.debug(f"创建连接任务[{stage}]: {url} -> {source_name}")
                task = asyncio.create_task(self.connect_to_source(url, source_name))
                tasks.append(task)
                urls_for_tasks.append(url)
                self._connection_tasks[url] = task

            # 阶段让步：确保创建顺序稳定且不阻塞事件循环
            await asyncio.sleep(0)
        
        logger.info(f"已创建{len(tasks)}个连接任务，开始连接...")
        
        # 等待所有任务完成（实际上会一直运行）
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 检查是否有任务异常退出
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                url = urls_for_tasks[i] if i < len(urls_for_tasks) else "unknown"
                logger.error(f"连接任务异常退出: {url}, 错误: {result}", exc_info=True)
    
    async def send_message_async(self, url: str, message: str) -> bool:
        """
        异步发送消息到指定的WebSocket连接
        
        Args:
            url: WebSocket URL
            message: 要发送的消息（字符串或JSON字符串）
            
        Returns:
            是否发送成功
        """
        try:
            if url not in self.connections:
                logger.warning(f"连接不存在: {url}")
                return False
            
            websocket = self.connections[url]
            await websocket.send(message)
            logger.info(f"已发送消息到 {url}: {message[:100]}...")
            return True
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False
    
    def send_message(self, url: str, message: str) -> bool:
        """
        同步方法：发送消息到指定的WebSocket连接
        将消息添加到发送队列，由连接循环处理
        
        Args:
            url: WebSocket URL
            message: 要发送的消息（字符串或JSON字符串）
            
        Returns:
            是否成功添加到队列
        """
        try:
            # 检查连接是否存在
            if url not in self.connections:
                logger.warning(f"连接不存在: {url}")
                return False
            
            # 创建发送队列（如果不存在）
            if url not in self._send_queues:
                self._send_queues[url] = Queue()
            
            # 将消息添加到队列
            self._send_queues[url].put(message)
            logger.debug(f"消息已添加到发送队列: {url}")
            return True
        except Exception as e:
            logger.error(f"添加消息到发送队列失败: {e}")
            return False
    
    def update_enabled_sources(self, enabled_sources: Dict[str, bool]):
        """
        更新启用的数据源
        
        Args:
            enabled_sources: 数据源启用状态字典
        """
        self.enabled_sources.update(enabled_sources)