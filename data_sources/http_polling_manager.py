#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP轮询管理器
用于管理HTTP API数据源的定期轮询（台风 / P2P 补拉 / EQSC / 自定义源）
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
    Config,
    APP_VERSION,
    P2PQUAKE_HTTP_SOURCE_KEYS,
    JIAN_TYPHOON_HTTP_KEYS,
    EQSC_HTTP_MASTER,
    EQSC_HTTP_SOURCE_KEYS,
    EQSC_HTTP_URL_TO_SCOPE,
)
from utils.logger import get_logger

logger = get_logger()

HTTP_POLL_STARTUP_STAGGER_SEC = 1.0


def is_http_source_enabled(config: Config, url: str) -> bool:
    """判断指定 HTTP URL 是否应发起轮询。"""
    if not url:
        return False
    low = url.lower()
    lookup_url = url
    if url in P2PQUAKE_HTTP_SOURCE_KEYS or "api.p2pquake.net" in low:
        return False
    if url == EQSC_HTTP_MASTER or url.rstrip("/") == "https://equake.top":
        return False
    custom_url = (config.custom_data_source_url or "").strip()
    if custom_url and url == custom_url:
        return True
    if hasattr(config, "is_url_active_for_provider") and not config.is_url_active_for_provider(lookup_url):
        return False
    if url in EQSC_HTTP_SOURCE_KEYS or "equake.top" in low:
        if not bool(config.enabled_sources.get(EQSC_HTTP_MASTER, False)):
            return False
        if not bool(config.enabled_sources.get(lookup_url, False)):
            return False
        token = (getattr(config.ws_config, "eqsc_login_token", "") or "").strip()
        if not token:
            return False
        return True
    if not config.enabled_sources.get(lookup_url, False):
        return False
    return True


class HTTPPollingConnection:
    """单个HTTP轮询连接管理"""

    def __init__(self, url: str, source_name: str, adapter: Any, config: Config, poll_interval: int = 2):
        self.url = url
        self.source_name = source_name
        self.adapter = adapter
        self.config = config
        self.poll_interval = poll_interval
        self._running = True
        self._last_poll_time = 0
        self._last_data_hash = None
        self._last_error_log_time = 0.0
        self._last_error_msg = ""
        self.last_request_ok = False
        self.last_request_time = 0.0
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': f'EarthquakeScroller/{APP_VERSION}'
        })
        self._session.proxies = {
            'http': None,
            'https': None
        }
        logger.debug(f"[{self.source_name}] 已禁用代理（HTTP数据源）")

    def _request_verify_ssl(self) -> bool:
        custom_url = (self.config.custom_data_source_url or "").strip()
        if custom_url and self.url == custom_url:
            return not bool(getattr(self.config, 'custom_data_source_insecure_ssl', False))
        adapter_verify = getattr(self.adapter, "ssl_verify", True)
        if adapter_verify is False:
            return False
        return True

    def start(
        self,
        message_callback: Callable[[str, Dict], None],
        startup_delay: float = 0.0,
    ):
        """启动轮询线程。"""
        def poll_loop():
            if startup_delay > 0:
                time.sleep(startup_delay)
            while self._running:
                try:
                    now = time.time()
                    if now - self._last_poll_time >= self.poll_interval:
                        self._last_poll_time = now
                        self._poll_once(message_callback)
                except Exception as e:
                    logger.error(f"[{self.source_name}] 轮询循环异常: {e}")
                time.sleep(0.5)

        thread = threading.Thread(target=poll_loop, daemon=True, name=f"HTTPPoll-{self.source_name}")
        thread.start()

    def _poll_once(self, message_callback: Callable[[str, Dict], None]):
        try:
            verify = self._request_verify_ssl()
            response = self._session.get(self.url, timeout=15, verify=verify)
            self.last_request_time = time.time()
            self.last_request_ok = response.status_code == 200
            if response.status_code != 200:
                self._log_error_throttled(f"HTTP {response.status_code}")
                return
            try:
                data = response.json()
            except json.JSONDecodeError:
                data = response.text
            data_hash = hash(str(data))
            if data_hash == self._last_data_hash:
                return
            self._last_data_hash = data_hash
            if hasattr(self.adapter, "parse_all"):
                parsed_list = self.adapter.parse_all(data)
            else:
                one = self.adapter.parse(data)
                parsed_list = [one] if one else []
            for parsed in parsed_list:
                if parsed:
                    pt = parsed.get("source_type") or self.source_name
                    message_callback(pt if pt != "custom" else self.source_name, parsed)
        except Exception as e:
            self.last_request_ok = False
            self.last_request_time = time.time()
            self._log_error_throttled(str(e))

    def _log_error_throttled(self, msg: str):
        now = time.time()
        if msg == self._last_error_msg and now - self._last_error_log_time < 60:
            return
        self._last_error_msg = msg
        self._last_error_log_time = now
        logger.error(f"[{self.source_name}] 轮询失败: {msg}")

    def stop(self):
        self._running = False


class HTTPPollingManager:
    """HTTP轮询管理器"""

    def __init__(self, message_callback: Optional[Callable] = None):
        self.message_callback = message_callback
        self.config = Config()
        self.connections: Dict[str, HTTPPollingConnection] = {}
        self._running = True
        logger.info("HTTP轮询管理器初始化完成")

    def get_adapter(self, url: str) -> Optional[Any]:
        """根据URL获取对应的适配器。"""
        from config import is_custom_data_source_url
        if is_custom_data_source_url(url, self.config) and url.startswith(
            ("http://", "https://")
        ):
            from adapters.custom_adapter import CustomAdapter
            return CustomAdapter("custom", url)
        if 'api.p2pquake.net' in url and 'tsunami' in url.lower():
            from adapters.p2pquake_tsunami_adapter import P2PQuakeTsunamiAdapter
            return P2PQuakeTsunamiAdapter('p2pquake_tsunami', url)
        if "typhoon.php" in (url or "").lower() and "sismotide.top" in (url or "").lower():
            from adapters.jian_typhoon_http_adapter import JianTyphoonHttpAdapter
            return JianTyphoonHttpAdapter('jian_typhoon', url)
        if 'api.p2pquake.net' in url:
            from adapters.p2pquake_adapter import P2PQuakeAdapter
            return P2PQuakeAdapter('p2pquake', url)
        if "equake.top" in url:
            from adapters.eqsc_adapter import EqscAdapter
            scope = EQSC_HTTP_URL_TO_SCOPE.get(url, "")
            return EqscAdapter(scope or "eqsc", url)
        if 'api.wolfx.jp' in url or 'wolfx' in url.lower():
            return None
        return None

    def start_all_connections(self):
        """启动所有HTTP轮询连接"""
        http_urls = self._collect_desired_http_urls()
        if not http_urls:
            logger.info("没有启用的HTTP数据源")
            return

        if any("equake.top" in (u or "").lower() for u in http_urls):
            login = (getattr(self.config.ws_config, "eqsc_login_token", "") or "").strip()
            if login:
                try:
                    from utils.eqsc_credentials import warm_eqsc_access_token
                    ok, msg = warm_eqsc_access_token(login)
                    if ok:
                        logger.info("EQSC AccessToken 预热成功")
                    else:
                        logger.warning(f"EQSC AccessToken 预热失败: {msg}")
                except Exception as e:
                    logger.warning(f"EQSC AccessToken 预热异常: {e}")

        logger.info(f"开始启动 {len(http_urls)} 个HTTP数据源（错开首包间隔 {HTTP_POLL_STARTUP_STAGGER_SEC}s）...")
        self._start_urls(http_urls, stagger=True)

    def _collect_desired_http_urls(self) -> list:
        """按当前配置收集应轮询的 HTTP URL 列表。"""
        http_urls = []
        for url in self.config.enabled_sources.keys():
            if url.startswith('http://') or url.startswith('https://'):
                if url in P2PQUAKE_HTTP_SOURCE_KEYS or "api.p2pquake.net" in url.lower():
                    logger.debug(f"跳过 P2PQuake HTTP 持续轮询（仅启动补拉）: {url}")
                    continue
                if url in JIAN_TYPHOON_HTTP_KEYS:
                    if is_http_source_enabled(self.config, url):
                        http_urls.append(url)
                elif is_http_source_enabled(self.config, url):
                    http_urls.append(url)
        custom_url = (self.config.custom_data_source_url or "").strip()
        if custom_url and custom_url.startswith(('http://', 'https://')):
            if custom_url not in http_urls:
                http_urls.append(custom_url)
        return http_urls

    def _start_urls(self, http_urls: list, stagger: bool = True) -> None:
        http_started_index = len(self.connections)
        for url in http_urls:
            if url in self.connections:
                continue
            source_name = self.config.get_source_name(url)
            adapter = self.get_adapter(url)
            if adapter is None:
                continue
            poll_interval = self.config.get_http_poll_interval(url)
            connection = HTTPPollingConnection(
                url, source_name, adapter, self.config, poll_interval=poll_interval
            )
            self.connections[url] = connection
            startup_delay = (
                HTTP_POLL_STARTUP_STAGGER_SEC * http_started_index if stagger else 0.0
            )
            http_started_index += 1
            connection.start(self.message_callback, startup_delay=startup_delay)
            logger.info(f"已启动HTTP轮询: {source_name}（首包延迟 {startup_delay:.1f}s）")

    def reload_connections(self):
        """根据当前配置重载 HTTP 轮询连接。"""
        self.config = Config()
        for conn in list(self.connections.values()):
            conn.stop()
        self.connections.clear()
        if self.message_callback:
            self.start_all_connections()

    def get_custom_source_status(self, url: str) -> str:
        """自定义 HTTP 源连接状态（供设置页展示）。"""
        conn = self.connections.get(url)
        if conn is None:
            return "unknown"
        if conn.last_request_ok:
            return "ok"
        if conn.last_request_time > 0:
            return "error"
        return "unknown"

    def stop_all(self):
        """停止所有轮询。"""
        for conn in self.connections.values():
            conn.stop()
        self.connections.clear()
        self._running = False
