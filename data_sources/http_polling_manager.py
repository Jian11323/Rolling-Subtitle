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

from config import Config, APP_VERSION
from adapters import P2PQuakeAdapter, P2PQuakeTsunamiAdapter, WolfxAdapter
from utils.logger import get_logger

logger = get_logger()


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
        self._running = True
        self._last_poll_time = 0
        self._last_data_hash = None  # 用于检测数据变化
        self._last_error_log_time = 0.0  # 重复错误降噪：上次打 ERROR 的时间
        self._last_error_msg = ""  # 重复错误降噪：上次错误摘要
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': f'EarthquakeScroller/{APP_VERSION}'
        })
        
        # 所有HTTP数据源都需要禁用代理
        self._session.proxies = {
            'http': None,
            'https': None
        }
        logger.debug(f"[{self.source_name}] 已禁用代理（HTTP数据源）")
    
    def start(self, message_callback: Callable[[str, Dict], None]):
        """启动轮询"""
        def poll_loop():
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
            logger.debug(f"[{self.source_name}] 开始轮询: {self.url}")
            
            # 发送HTTP请求，失败时重试最多3次，每次间隔2秒
            response = None
            for attempt in range(1, 4):
                try:
                    response = self._session.get(
                        self.url, timeout=10, proxies={'http': None, 'https': None}
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
                        logger.error(f"[{self.source_name}] HTTP请求失败: {e}")
                        self._last_error_log_time = now
                        self._last_error_msg = err_summary
                    return
            
            if response is None:
                return
            
            # 解析响应
            data = response.json()
            
            # 计算数据哈希（简单检测是否有新数据）
            import hashlib
            data_str = json.dumps(data, sort_keys=True)
            data_hash = hashlib.md5(data_str.encode()).hexdigest()
            
            # 如果数据没有变化，跳过处理
            if data_hash == self._last_data_hash:
                logger.debug(f"[{self.source_name}] 数据未变化，跳过处理")
                return
            
            self._last_data_hash = data_hash
            
            # 使用适配器解析数据
            # 只处理最新的一条数据（列表中的第一条）
            logger.debug(f"[{self.source_name}] 开始解析数据，数据类型: {type(data)}, 数据长度: {len(data) if isinstance(data, (list, dict)) else 'N/A'}")
            parsed_result = self.adapter.parse(data)
            
            if parsed_result:
                logger.info(f"[{self.source_name}] 解析成功，解析结果: type={parsed_result.get('type')}, organization={parsed_result.get('organization')}, place_name={parsed_result.get('place_name')}")
                # 只处理最新的一条数据
                message_callback(self.source_name, parsed_result)
                logger.info(f"[{self.source_name}] 轮询成功，处理了最新1条数据")
            else:
                logger.warning(f"[{self.source_name}] 轮询成功，但适配器解析返回None，可能数据格式不正确或解析失败")
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
            logger.error(f"[{self.source_name}] HTTP请求失败: {e}")
        except Exception as e:
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
        # P2PQuake 海啸预报
        if 'api.p2pquake.net' in url and 'tsunami' in url.lower():
            return P2PQuakeTsunamiAdapter('p2pquake_tsunami', url)
        # P2PQuake 地震情报
        if 'api.p2pquake.net' in url:
            return P2PQuakeAdapter('p2pquake', url)
        # Wolfx HTTP API: https://api.wolfx.jp/{sc_eew,jma_eew,...}.json
        if 'api.wolfx.jp' in url:
            path = url.split('/')[-1] or url.rstrip('/').split('/')[-1]
            source_type = path.replace('.json', '') if path.endswith('.json') else path
            return WolfxAdapter(source_type, url)
        return None
    
    def start_all_connections(self):
        """启动所有HTTP轮询连接"""
        # 从配置中获取启用的HTTP数据源
        http_urls = []
        for url in self.config.enabled_sources.keys():
            if url.startswith('http://') or url.startswith('https://'):
                if self.config.enabled_sources.get(url, False):
                    http_urls.append(url)
                    logger.debug(f"发现启用的HTTP数据源: {url}")
                else:
                    logger.debug(f"HTTP数据源已禁用: {url}")
        
        if not http_urls:
            logger.info("没有启用的HTTP数据源")
            return
        
        logger.info(f"开始启动 {len(http_urls)} 个HTTP数据源...")
        
        for url in http_urls:
            source_name = self.config.get_source_name(url)
            logger.debug(f"正在为 {url} 创建适配器，数据源名称: {source_name}")
            adapter = self.get_adapter(url)
            
            if adapter is None:
                logger.error(f"无法找到适配器 for {url}")
                continue
            
            # 轮询间隔：Wolfx 速报 5 秒，其余 2 秒
            poll_interval = 5 if 'eqlist' in url and 'wolfx' in url.lower() else 2
            connection = HTTPPollingConnection(url, source_name, adapter, self.config, poll_interval=poll_interval)
            self.connections[url] = connection
            
            # 启动轮询
            connection.start(self.message_callback)
            
            logger.info(f"已启动HTTP轮询: {source_name}")
    
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
