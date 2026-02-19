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

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from adapters import FanStudioAdapter, WolfxAdapter, NiedAdapter
from utils.logger import get_logger

logger = get_logger()


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
        # 检查是否为Fan Studio数据源
        if 'fanstudio.tech' in url or 'fanstudio.hk' in url:
            parts = url.split('/')
            source_type = parts[-1] if parts[-1] else parts[-2]
            adapter = FanStudioAdapter(source_type, url)
            adapter._manager_source_type = source_type
            return adapter
        # Wolfx WebSocket
        if 'ws-api.wolfx.jp' in url:
            parts = url.split('/')
            source_type = parts[-1] if parts[-1] else 'all_eew'
            adapter = WolfxAdapter(source_type, url)
            adapter._manager_source_type = source_type
            return adapter
        # NIED WebSocket
        if 'sismotide.top' in url and '/nied' in url:
            adapter = NiedAdapter('nied', url)
            adapter._manager_source_type = 'nied'
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
            
            # Wolfx/NIED：用 source_type 作为 source 名称，便于优先级与机构名解析
            source_type = parsed_data.get('source_type', '')
            if source_type and (source_type.startswith('wolfx_') or source_type == 'nied'):
                return source_type
            # 根据organization推断
            organization = parsed_data.get('organization', '')
            org_mapping = {
                "中国地震台网中心自动测定/正式测定": "cenc",
                "中国地震预警网": "cea",
                "中国地震预警网-省级预警": "cea-pr",
                "四川地震局": "sichuan",
                "宁夏地震局": "ningxia",
                "广西地震局": "guangxi",
                "山西地震局": "shanxi",
                "北京地震局": "beijing",
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
                # 普通解析（包括update类型、Wolfx、NIED）
                parsed_data = adapter.parse(data)
                if parsed_data:
                    # Wolfx/NIED：用 parsed_data 的 source_type 作为 actual_source
                    pt = parsed_data.get('source_type', '')
                    if pt and (pt.startswith('wolfx_') or pt == 'nied'):
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
    
    async def start_all_connections(self):
        """启动所有数据源连接"""
        config = Config()
        enabled_urls = []
        
        # 获取启用的WebSocket URL
        for url in config.ws_urls:
            if config.enabled_sources.get(url, True):
                enabled_urls.append(url)
                self.enabled_sources[url] = True
        
        if not enabled_urls:
            logger.warning("ws_urls为空，没有可连接的数据源！")
            logger.warning(f"config.ws_urls = {config.ws_urls}")
            logger.warning(f"config.enabled_sources中包含的WebSocket URL: {[url for url in config.enabled_sources.keys() if url.startswith(('ws://', 'wss://'))]}")
        else:
            logger.info(f"准备连接{len(enabled_urls)}个数据源: {enabled_urls}")
        
        # 创建所有连接任务
        tasks = []
        for url in enabled_urls:
            source_name = config.get_source_name(url)
            logger.debug(f"创建连接任务: {url} -> {source_name}")
            task = asyncio.create_task(self.connect_to_source(url, source_name))
            tasks.append(task)
            self._connection_tasks[url] = task
        
        logger.info(f"已创建{len(tasks)}个连接任务，开始连接...")
        
        # 等待所有任务完成（实际上会一直运行）
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 检查是否有任务异常退出
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                url = enabled_urls[i] if i < len(enabled_urls) else "unknown"
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