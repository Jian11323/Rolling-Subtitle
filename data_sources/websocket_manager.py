#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebSocket连接管理器
负责管理所有WebSocket数据源的连接、消息接收和发送
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import websockets
from typing import Dict, Callable, Optional, Any, Tuple, List
from collections import defaultdict
from queue import Queue, Empty
import requests

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # 读取全局配置与开关
from config import (
    FANSTUDIO_ALL_URLS,
    fanstudio_ws_url,
    WHEWS_WS_URLS,
    is_whews_url,
    is_whews_dedicated_endpoint,
    is_whews_cea_endpoint,
    is_whews_cea_split_endpoint,
    whews_cea_app_configured,
    is_jian_project_url,
    JIAN_PROJECT_ALL_URL,
    WOLFX_ALL_EEW_URL,
    WOLFX_CWA_EEW_URL,
    WOLFX_CENC_EQLIST_URL,
    WOLFX_JMA_EQLIST_URL,
    NOWQUAKE_CENCINT_WSS_URL,
    EQSC_WS_URL,
    P2PQUAKE_HISTORY_AGGREGATE_URL,
    OPENQUAKE_WS_ALL_URL,
    is_custom_data_source_url,
    is_ws_url_enabled,
)
from utils.logger import get_logger
from utils.message_processor import warning_shock_validity_remaining_seconds
from utils.fanstudio_credentials import (
    build_fanstudio_auth_message,
    parse_fanstudio_auth_response,
)

logger = get_logger()

# P2PQuake HTTP 聚合接口：551 地震情报 / 552 津波预报 / 556 緊急地震速报
P2PQUAKE_HISTORY_URL = P2PQUAKE_HISTORY_AGGREGATE_URL
P2PQUAKE_WSS_URL = "wss://api.p2pquake.net/v2/ws"  # P2PQuake WebSocket 地址
HEARTBEAT_TIMEOUT_SECONDS = {  # 各源心跳超时阈值
    "fanstudio": 45,
    "whews": 90,
    "jian": 90,
    "wolfx": 90,
    "nowquake": 90,  # 服务端约 60s 发一次 heartbeat
    "p2pquake": 120,
    "eqsc": 45,  # 服务端心跳，客户端需原样回传
    "openquake": 120,
}


def _parsed_warning_still_valid(parsed_data: Dict[str, Any]) -> bool:
    """入口侧发震时间窗口校验（WebSocket 回调前丢弃过期预警）。"""
    if parsed_data.get("type") != "warning":
        return True
    rem = warning_shock_validity_remaining_seconds(parsed_data, Config().message_config)
    if rem is None:
        return True
    return rem > 0


def _invalid_status_http_code(exc: Exception) -> Optional[int]:
    """从 WebSocket 连接异常中提取 HTTP 状态码（用于重连退避策略）。"""
    code = getattr(exc, "status_code", None)
    if code is not None:
        try:
            return int(code)
        except (TypeError, ValueError):
            pass
    m = re.search(r"HTTP (\d+)", str(exc))
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _reconnect_wait_seconds(http_code: Optional[int], attempt: int) -> Optional[int]:
    """按 HTTP 状态码计算额外重连等待秒数；429/503/521 使用更长间隔。"""
    if http_code == 429:
        return min(300, 60 + attempt * 30)
    if http_code in (503, 521):
        return min(120, 30 + attempt * 15)
    return None


def _dispatch_parsed_message(
    manager: "WebSocketManager",
    parsed_data: Dict[str, Any],
    actual_source: str,
    ws_source_name: str,
) -> None:
    """校验预警有效期后，将解析结果通过回调下发至 GUI 层。

    过期预警仍下发（带 _ws_expired），供设置页记为「已解析」，但不进入展示队列。
    """
    if not _parsed_warning_still_valid(parsed_data):
        logger.debug(
            "[%s] 预警已过期，WebSocket 层丢弃展示: event_id=%s place=%s",
            actual_source,
            parsed_data.get("event_id"),
            parsed_data.get("place_name"),
        )
        expired = dict(parsed_data)
        expired["_ws_expired"] = True
        manager.message_callback(actual_source, expired)
        return
    msg_type = parsed_data.get("type", "unknown")
    logger.info(f"[{actual_source}] {msg_type}消息")
    manager.message_callback(actual_source, parsed_data)


def _apply_bulk_dispatch_limit(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按性能模式限制 initial_all / alllist 等批量入队数量。"""
    if not items:
        return []
    try:
        from utils.memory_policy import limit_bulk_parsed_messages

        cfg = Config()
        mode = getattr(cfg.gui_config, "performance_mode", "standard")
        limited = limit_bulk_parsed_messages(items, mode)
        if len(limited) < len(items):
            logger.info(
                "批量快照已按性能模式限流: %d -> %d (mode=%s)",
                len(items),
                len(limited),
                mode,
            )
        return limited
    except Exception as e:
        logger.debug(f"批量限流失败，使用原始列表: {e}")
        return items

# all_eew 聚合端：建连后查询各子源（不含 CWA；CWA 有独立 wss …/cwa_eew 端点）
# 列表速报 query_cenceqlist / query_jmaeqlist 亦发往 all_eew（见 _wolfx_all_eew_query_commands）
WOLFX_ALL_EEW_QUERY_COMMANDS = (
    "query_sceew",
    "query_jmaeew",
    "query_fjeew",
    "query_cqeew",
    "query_cenceew",
)
# query_cwaeew 仅对应 wss://ws-api.wolfx.jp/cwa_eew，切勿发往 all_eew
WOLFX_CWA_EEW_QUERY_COMMANDS = ("query_cwaeew",)

# Wolfx 建连后错峰查询：发一条 → 等到业务回包（或超时）→ 间隔 1s 再发下一条，避免连发 query 阻塞服务端
WOLFX_QUERY_STAGGER_INTERVAL_SEC = 1.0
WOLFX_QUERY_RESPONSE_DEADLINE_SEC = 20.0
WOLFX_QUERY_RECV_CHUNK_SEC = 2.0
WOLFX_EEW_JSON_TYPES = frozenset(
    {"jma_eew", "sc_eew", "fj_eew", "cenc_eew", "cq_eew", "cwa_eew"}
)
WOLFX_LIST_JSON_TYPES = frozenset({"cenc_eqlist", "jma_eqlist"})
WOLFX_DIRECT_SOURCE_TYPES = (
    "wolfx_jma_eew",
    "wolfx_sc_eew",
    "wolfx_fj_eew",
    "wolfx_cenc_eew",
    "wolfx_cq_eew",
    "wolfx_cwa_eew",
    "wolfx_cenc",
    "wolfx_jma_eqlist",
)
# cwa_eew 建连后等待 all_eew 首轮错峰 query 完成再发 query_cwaeew，避免两条 Wolfx 线并行抢收/抢发
WOLFX_CWA_WAIT_ALL_EEW_BOOTSTRAP_SEC = 120.0
# 热停连时等待 close / cancel 的上限，避免某路卡死拖住整次重载
RELOAD_STOP_TIMEOUT_SEC = 5.0
# 实际建连的 Wolfx 端点：除 CWA 外一律 all_eew
WOLFX_URLS = frozenset(
    {
        WOLFX_ALL_EEW_URL,
        WOLFX_CWA_EEW_URL,
    }
)

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
        self.connection_states: Dict[str, str] = {}  # url -> connected/connecting/disconnected/unconnected
        self.reconnect_attempts = defaultdict(int)
        self.enabled_sources: Dict[str, bool] = {}  # 数据源启用状态
        self._send_queues: Dict[str, Queue] = {}  # 每个URL的消息发送队列
        self._connection_tasks: Dict[str, asyncio.Task] = {}  # 连接任务字典
        self._health_status: Dict[str, Dict[str, Any]] = {}  # 心跳/健康状态快照
        self._wolfx_all_eew_bootstrap_done: Optional[asyncio.Event] = None  # Wolfx 启动放行事件
        self._keepalive_task: Optional[asyncio.Task] = None  # 保持事件循环，供热启停连接
        self._reload_lock: Optional[asyncio.Lock] = None  # 串行化热重载，避免并发停启打架
        self._running = True  # 全局运行标志
        self._connect_error_log: Dict[str, tuple] = {}  # 连接错误降噪记录
        # Fan Studio /all：已发鉴权、等待 auth_success 期间，跳过鉴权前的精简 initial_all
        self._fanstudio_awaiting_auth: Dict[str, bool] = {}
        # Fan Studio /all 鉴权结果：url -> ("none"|"pending"|"ok"|"failed", message)
        self._fanstudio_auth_status: Dict[str, Tuple[str, str]] = {}
        # EQSC 鉴权结果：url -> ("none"|"pending"|"ok"|"failed", message)
        self._eqsc_auth_status: Dict[str, Tuple[str, str]] = {}
        # WeJet CEA App 鉴权：url -> 状态；accessToken；续票任务
        self._whews_cea_auth_status: Dict[str, Tuple[str, str]] = {}
        self._whews_cea_access_token: Dict[str, str] = {}
        self._whews_cea_refresh_tasks: Dict[str, asyncio.Task] = {}
        self._whews_cea_awaiting_auth: Dict[str, bool] = {}
        config = Config()
        self.max_reconnect_attempts = config.ws_config.max_reconnect_attempts  # 最大重连次数
        self.reconnect_interval = config.ws_config.reconnect_interval  # 基础重连间隔
        self.ping_interval = config.ws_config.ping_interval  # WebSocket ping 周期
        self.ping_timeout = config.ws_config.ping_timeout  # ping 超时阈值
        self.close_timeout = config.ws_config.close_timeout  # 关闭等待超时
        self.open_timeout = config.ws_config.connection_timeout  # 握手连接超时

    def _get_source_kind(self, url: str) -> str:
        """按 URL 识别数据源类型（用于心跳策略）"""
        normalized = (url or "").strip().lower().rstrip("/")
        if "fanstudio.tech" in normalized:
            return "fanstudio"
        if is_whews_url(normalized):
            return "whews"
        if is_jian_project_url(normalized):
            return "jian"
        if normalized in WOLFX_URLS:
            return "wolfx"
        if normalized == NOWQUAKE_CENCINT_WSS_URL:
            return "nowquake"
        if normalized == P2PQUAKE_WSS_URL or "p2pquake" in normalized:
            return "p2pquake"
        if "equake.top" in normalized:
            return "eqsc"
        if normalized == OPENQUAKE_WS_ALL_URL or "api.aloys23.link" in normalized:
            return "openquake"
        return "other"

    def _ensure_health_entry(self, url: str, source_name: str = "") -> Dict[str, Any]:
        """获取或初始化指定 URL 的健康状态条目（心跳、超时计数等）。"""
        entry = self._health_status.get(url)
        if entry is None:
            kind = self._get_source_kind(url)
            timeout_seconds = HEARTBEAT_TIMEOUT_SECONDS.get(kind, 0)
            entry = {
                "source_name": source_name,
                "source_kind": kind,
                "timeout_seconds": timeout_seconds,
                "last_message_ts": 0.0,
                "last_heartbeat_ts": 0.0,
                "last_ping_ts": 0.0,
                "last_pong_ts": 0.0,
                "last_auto_ping_ts": 0.0,
                "timeout_count": 0,
                "auto_ping_count": 0,
                "heartbeat_state": "unknown",
            }
            self._health_status[url] = entry
        elif source_name and not entry.get("source_name"):
            entry["source_name"] = source_name
        return entry

    def _mark_message_received(self, url: str, source_name: str):
        """记录收到任意业务或控制消息的时间戳。"""
        entry = self._ensure_health_entry(url, source_name)
        entry["last_message_ts"] = time.time()

    def _mark_heartbeat_received(self, url: str, source_name: str):
        """记录心跳到达时间并将心跳状态置为正常。"""
        now = time.time()
        entry = self._ensure_health_entry(url, source_name)
        entry["last_heartbeat_ts"] = now
        entry["last_message_ts"] = now
        entry["heartbeat_state"] = "ok"

    def _mark_ping_received(self, url: str, source_name: str):
        """记录收到 ping 控制帧的时间戳。"""
        entry = self._ensure_health_entry(url, source_name)
        entry["last_ping_ts"] = time.time()

    def _mark_pong_received(self, url: str, source_name: str):
        """记录收到 pong 响应并将心跳状态置为正常。"""
        now = time.time()
        entry = self._ensure_health_entry(url, source_name)
        entry["last_pong_ts"] = now
        entry["last_message_ts"] = now
        entry["heartbeat_state"] = "ok"

    async def _check_heartbeat_timeout(self, websocket: Any, url: str, source_name: str):
        """心跳超时检测与自动 ping（Fan/Wolfx/WeJet；EQSC 仅监控，靠服务端心跳回显）"""
        entry = self._ensure_health_entry(url, source_name)
        timeout_seconds = int(entry.get("timeout_seconds", 0) or 0)
        if timeout_seconds <= 0:
            return

        now = time.time()
        last_heartbeat = float(entry.get("last_heartbeat_ts", 0.0) or 0.0)
        if last_heartbeat <= 0:
            return
        if (now - last_heartbeat) <= timeout_seconds:
            return

        entry["heartbeat_state"] = "timeout"
        entry["timeout_count"] = int(entry.get("timeout_count", 0) or 0) + 1
        source_kind = entry.get("source_kind", "other")
        # EQSC 需回显服务端 heartbeat，不发客户端 ping
        if source_kind not in ("fanstudio", "wolfx", "whews"):
            return
        # 防止超时后每个循环都发送 ping：最短间隔取阈值一半，至少 10 秒
        min_retry_gap = max(10, timeout_seconds // 2)
        last_auto_ping = float(entry.get("last_auto_ping_ts", 0.0) or 0.0)
        if last_auto_ping > 0 and (now - last_auto_ping) < min_retry_gap:
            return
        try:
            if source_kind == "whews":
                await websocket.send(json.dumps({"type": "ping"}))
            else:
                await websocket.send("ping")
            entry["last_ping_ts"] = now
            entry["last_auto_ping_ts"] = now
            entry["auto_ping_count"] = int(entry.get("auto_ping_count", 0) or 0) + 1
            logger.info(f"[{source_name}] 心跳超时，已自动发送 ping")
        except Exception as e:
            logger.warning(f"[{source_name}] 心跳超时后发送 ping 失败: {e}")
    
    def get_adapter(self, url: str) -> Optional[Any]:
        """
        根据URL获取对应的适配器
        
        Args:
            url: WebSocket URL
            
        Returns:
            适配器实例
        """
        # Wolfx：除 CWA 专线外一律走 all_eew（列表速报亦经聚合端）
        if 'ws-api.wolfx.jp' in url:
            from adapters.wolfx_adapter import WolfxAdapter
            normalized = url.rstrip('/').lower()
            if normalized.endswith('/all_eew'):
                adapter = WolfxAdapter('wolfx_all_eew', url)
                adapter._manager_source_type = 'wolfx_all_eew'
                return adapter
            if normalized.endswith('/cwa_eew'):
                adapter = WolfxAdapter('wolfx_cwa_eew', url)
                adapter._manager_source_type = 'wolfx_cwa_eew'
                return adapter
            # 旧专线 URL 不再建连；若仍出现在配置中则跳过
            return None
        # Nowquake CENC 烈度速报
        if (url or "").strip().lower().rstrip("/") == NOWQUAKE_CENCINT_WSS_URL:
            from adapters.nowquake_cencint_adapter import NowquakeCencintAdapter
            adapter = NowquakeCencintAdapter('cenc-ir', url)
            adapter._manager_source_type = 'cenc-ir'
            return adapter
        # EQSC：官方称 WS 不稳定，公开版仅走 HTTP，拒绝建连
        if (url or "").strip().lower().rstrip("/") == EQSC_WS_URL.strip().lower().rstrip("/"):
            logger.warning(f"已拒绝连接 EQSC WebSocket（请改用 HTTP 轮询）: {url}")
            return None
        # 无界科技（WHEWS 主站 / 备用）
        if is_whews_url(url or ""):
            from adapters.whews_adapter import WhewsAdapter
            path = (url or "").rstrip("/").split("?")[0].split("/")[-1] or "all"
            adapter = WhewsAdapter(f"whews_{path}", url)
            adapter._manager_source_type = "whews_all" if path == "all" else f"whews_{path}"
            return adapter
        # Jian Project 国际源聚合
        if is_jian_project_url(url or ""):
            from adapters.jian_project_adapter import JianProjectAdapter
            adapter = JianProjectAdapter("jian", url)
            adapter._manager_source_type = "jian_all"
            return adapter
        # 检查是否为Fan Studio数据源（公开版仅允许 /all）
        if 'fanstudio.tech' in url:
            from adapters.fanstudio_adapter import FanStudioAdapter
            parts = url.split('/')
            source_type = parts[-1] if parts[-1] else parts[-2]
            if (source_type or '').lower() != 'all':
                logger.warning(f"已拒绝连接已下线的 Fan Studio 路径（仅保留 /all）: {url}")
                return None
            adapter = FanStudioAdapter(source_type, url)
            adapter._manager_source_type = source_type
            return adapter
        # P2PQuake WebSocket（解析 551 / 552 / 556）
        if 'api.p2pquake.net' in url and (url.startswith('ws://') or url.startswith('wss://')):
            from adapters.p2pquake_ws_adapter import P2PQuakeWebSocketAdapter
            adapter = P2PQuakeWebSocketAdapter('p2pquake_ws', url)
            adapter._manager_source_type = 'p2pquake_ws'
            return adapter
        # OpenQuakeAPI WebSocket（/ws/all 聚合）
        if 'api.aloys23.link' in url and (url.startswith('ws://') or url.startswith('wss://')):
            from adapters.openquake_api_adapter import OpenQuakeApiAdapter
            adapter = OpenQuakeApiAdapter('openquake', url)
            adapter._manager_source_type = 'openquake'
            return adapter
        # 自定义数据源（WS/WSS）
        config = Config()
        if is_custom_data_source_url(url, config) and (
            url.startswith("ws://") or url.startswith("wss://")
        ):
            from adapters.custom_adapter import CustomAdapter
            adapter = CustomAdapter("custom", url)
            adapter._manager_source_type = "custom"
            return adapter
        # 未知 URL：不回落到 Fan Studio，避免非 Fan 通道被错误解析
        logger.warning(f"未识别的 WebSocket URL，跳过建连: {url}")
        return None
    
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
            if source_type in WOLFX_DIRECT_SOURCE_TYPES:
                return source_type
            from adapters.eqsc_adapter import EQSC_DIRECT_SOURCE_TYPES
            if source_type in EQSC_DIRECT_SOURCE_TYPES:
                return source_type
            from adapters.openquake_api_adapter import OPENQUAKE_DIRECT_SOURCE_TYPES
            if source_type in OPENQUAKE_DIRECT_SOURCE_TYPES:
                return source_type
            if source_type in ("ptwc", "emsc", "cenc-ir"):
                return source_type
            if source_type:
                if parsed_data.get('whews'):
                    return source_type
                if parsed_data.get('jian') and source_type:
                    return source_type
                if parsed_data.get('openquake') and source_type:
                    return source_type
                return config.get_source_name(fanstudio_ws_url(source_type))
            
            # 尝试从raw_data中获取数据源信息
            raw_data = parsed_data.get('raw_data', {})
            if 'source' in raw_data:
                source = raw_data['source']
                return config.get_source_name(fanstudio_ws_url(source))
            elif '_update_source' in raw_data:
                source = raw_data['_update_source']
                return config.get_source_name(fanstudio_ws_url(source))
            
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
                "福建地震局": "fujian",
                "四川地震局": "sichuan",
                "陕西地震局": "shaanxi",
                "湖北地震局": "hubei",
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
            return config.get_source_name(fanstudio_ws_url(source)) if source != default_source else default_source
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
            self._mark_message_received(url, source_name)
            if isinstance(message, str):
                message_text = message.strip().lower()
                if message_text == "heartbeat":
                    self._mark_heartbeat_received(url, source_name)
                    logger.debug(f"[{source_name}] 收到文本心跳消息")
                    return
                if message_text == "ping":
                    self._mark_ping_received(url, source_name)
                    logger.debug(f"[{source_name}] 收到文本 ping")
                    return
                if message_text == "pong":
                    self._mark_pong_received(url, source_name)
                    logger.debug(f"[{source_name}] 收到文本 pong")
                    return

            # 解析JSON（WeJet 首连数组偶发 updates:016 等非法前导零）
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                cleaned_message = self._sanitize_json_text(message)
                try:
                    data = json.loads(cleaned_message)
                except (json.JSONDecodeError, ValueError, TypeError):
                    logger.warning(f"[{source_name}] JSON解析失败，跳过消息")
                    return
            
            # 跳过心跳消息（记录状态，不下发业务）
            if isinstance(data, dict):
                msg_type = str(data.get('type', '')).strip().lower()
                if msg_type == 'heartbeat':
                    self._mark_heartbeat_received(url, source_name)
                    logger.debug(f"[{source_name}] 收到心跳消息")
                    return
                if msg_type == 'ping':
                    self._mark_ping_received(url, source_name)
                    logger.debug(f"[{source_name}] 收到 ping 消息")
                    return
                if msg_type == 'pong':
                    self._mark_pong_received(url, source_name)
                    logger.debug(f"[{source_name}] 收到 pong 消息")
                    return
                # WeJet CEA App 控制帧（hello / auth_ok / auth_fail / error）
                if is_whews_url(url or "") and msg_type in (
                    "hello",
                    "auth_ok",
                    "auth_fail",
                    "error",
                ):
                    # hello 仅在 CEA 端点或 needAuth 时进入鉴权流程；其它端点忽略
                    if msg_type == "hello" and not is_whews_cea_endpoint(url or ""):
                        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
                        if not bool(payload.get("needAuth", False)):
                            return
                    await self._handle_whews_cea_control(url=url, source_name=source_name, data=data)
                    return
                if int(data.get("code") or 0) == 555:
                    self._mark_heartbeat_received(url, source_name)
                    logger.debug(f"[{source_name}] 收到 P2PQuake 心跳(code=555)")
                    return
                auth_ok, auth_msg = parse_fanstudio_auth_response(data)
                if auth_ok is True:
                    self._fanstudio_awaiting_auth[url] = False
                    self._fanstudio_auth_status[url] = (
                        "ok",
                        auth_msg or "鉴权成功，已接入数据流。",
                    )
                    logger.info(f"[{source_name}] Fan Studio 鉴权成功: {auth_msg}")
                    return
                if auth_ok is False and msg_type == "error":
                    was_awaiting = self._fanstudio_awaiting_auth.pop(url, False)
                    # 鉴权失败或其它服务端错误
                    if was_awaiting or "鉴权" in auth_msg or "auth" in auth_msg.lower() or "key" in auth_msg.lower() or "appid" in auth_msg.lower():
                        self._fanstudio_auth_status[url] = (
                            "failed",
                            auth_msg or "鉴权失败",
                        )
                        logger.warning(f"[{source_name}] Fan Studio 鉴权失败: {auth_msg}")
                    else:
                        logger.warning(f"[{source_name}] Fan Studio 错误: {auth_msg}")
                    return
                # 已发 Key 鉴权、尚未收到结果：跳过鉴权前的精简 initial_all，等完整流
                if self._fanstudio_awaiting_auth.get(url) and msg_type == "initial_all":
                    logger.debug(
                        f"[{source_name}] 等待 Fan Studio 鉴权完成，暂缓处理鉴权前的 initial_all"
                    )
                    return
            
            cfg = Config()
            if not is_ws_url_enabled(cfg, url):
                logger.debug(f"[{source_name}] 该 WebSocket 已在配置中关闭，跳过业务消息: {url}")
                return

            # 获取数据源类型
            data_source_type = getattr(adapter, '_manager_source_type', 'unknown')
            
            # 处理initial_all类型
            if isinstance(data, dict) and data.get('type') == 'initial_all' and data_source_type == 'all':
                logger.info(f"[{source_name}] 收到initial_all类型消息，开始处理所有数据源")
                all_parsed_data = _apply_bulk_dispatch_limit(
                    await asyncio.to_thread(adapter.parse_all_sources, data)
                )
                logger.info(f"[{source_name}] initial_all解析完成，共{len(all_parsed_data)}条有效数据")
                
                for parsed_data in all_parsed_data:
                    if parsed_data:
                        parsed_data["_suppress_tts"] = True
                        actual_source = self._get_source_name_from_data(parsed_data, source_name)
                        _dispatch_parsed_message(self, parsed_data, actual_source, source_name)
            # 无界科技 /ws/all 首连为 JSON 数组
            elif isinstance(data, list) and str(data_source_type).startswith("whews"):
                logger.info(f"[{source_name}] 收到 WeJet 首连数组，共 {len(data)} 帧")
                all_parsed_data = _apply_bulk_dispatch_limit(
                    await asyncio.to_thread(adapter.parse_all_sources, data)
                )
                for parsed_data in all_parsed_data:
                    if parsed_data:
                        parsed_data["_suppress_tts"] = True
                        actual_source = self._get_source_name_from_data(parsed_data, source_name)
                        _dispatch_parsed_message(self, parsed_data, actual_source, source_name)
            elif data_source_type == "jian_all":
                msg_type = ""
                if isinstance(data, dict):
                    msg_type = str(data.get("type", "")).strip().lower()
                if isinstance(data, dict) and msg_type == "all":
                    logger.info(f"[{source_name}] 收到 Jian Project 聚合快照")
                    all_parsed_data = _apply_bulk_dispatch_limit(
                        await asyncio.to_thread(adapter.parse_all_sources, data)
                    )
                elif isinstance(data, list):
                    logger.info(f"[{source_name}] 收到 Jian Project 批量帧，共 {len(data)} 条")
                    all_parsed_data = _apply_bulk_dispatch_limit(
                        await asyncio.to_thread(adapter.parse_all_sources, data)
                    )
                elif isinstance(data, dict) and msg_type.endswith("_response"):
                    all_parsed_data = _apply_bulk_dispatch_limit(
                        await asyncio.to_thread(adapter.parse_all_sources, data)
                    )
                else:
                    one = await asyncio.to_thread(adapter.parse, data)
                    all_parsed_data = [one] if one else []
                for parsed_data in all_parsed_data:
                    if parsed_data:
                        actual_source = self._get_source_name_from_data(
                            parsed_data, source_name
                        )
                        _dispatch_parsed_message(
                            self, parsed_data, actual_source, source_name
                        )
            else:
                # 普通解析（包括 update 类型、NIED、P2PQuake、自定义源）
                if is_custom_data_source_url(url, cfg) and hasattr(adapter, "parse_all"):
                    all_parsed = await asyncio.to_thread(adapter.parse_all, data)
                    if not all_parsed:
                        logger.debug(f"[{source_name}] 数据无效或被过滤")
                        return
                    for parsed_data in all_parsed:
                        if not parsed_data:
                            continue
                        pt = parsed_data.get("source_type", "") or "custom"
                        actual_source = pt if pt not in ("", "custom") else source_name
                        _dispatch_parsed_message(
                            self, parsed_data, actual_source, source_name
                        )
                    return

                parsed_data = await asyncio.to_thread(adapter.parse, data)
                if parsed_data:
                    # EQSC 烈度列表：详情失败则丢弃薄事件，不入队
                    if (
                        parsed_data.get("eqsc_need_intensity_detail")
                        and parsed_data.get("event_id")
                    ):
                        from adapters.eqsc_adapter import EqscAdapter
                        if isinstance(adapter, EqscAdapter):
                            login_key = (
                                getattr(Config().ws_config, "eqsc_login_token", "") or ""
                            ).strip()
                            detail = None
                            if login_key:
                                detail = await asyncio.to_thread(
                                    adapter.fetch_intensity_detail,
                                    str(parsed_data.get("event_id")),
                                    login_key,
                                )
                            if detail:
                                parsed_data = detail
                            else:
                                logger.debug(
                                    f"[{source_name}] EQSC CENC IR 详情失败，丢弃列表摘要"
                                )
                                parsed_data = None
                    if not parsed_data:
                        return
                    # Wolfx / P2PQuake / EMSC / Nowquake / EQSC / OpenQuake：用 parsed_data 的 source_type
                    pt = parsed_data.get('source_type', '')
                    direct_sources = WOLFX_DIRECT_SOURCE_TYPES + (
                        'p2pquake',
                        'p2pquake_tsunami',
                        'p2pquake_eew',
                        'emsc',
                        'cenc-ir',
                    )
                    from adapters.eqsc_adapter import EQSC_DIRECT_SOURCE_TYPES
                    from adapters.openquake_api_adapter import OPENQUAKE_DIRECT_SOURCE_TYPES
                    if pt and (
                        pt in direct_sources
                        or pt in EQSC_DIRECT_SOURCE_TYPES
                        or pt in OPENQUAKE_DIRECT_SOURCE_TYPES
                    ):
                        actual_source = pt
                    elif parsed_data.get("whews") and pt:
                        actual_source = self._get_source_name_from_data(parsed_data, source_name)
                    elif parsed_data.get("jian") and pt:
                        actual_source = self._get_source_name_from_data(parsed_data, source_name)
                    elif parsed_data.get("openquake") and pt:
                        actual_source = pt
                    elif isinstance(data, dict) and data.get('type') == 'update':
                        actual_source = self._get_source_name_from_data(parsed_data, source_name)
                    else:
                        actual_source = source_name
                    _dispatch_parsed_message(self, parsed_data, actual_source, source_name)
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

    @staticmethod
    def _sanitize_json_text(message: str) -> str:
        """清理非法控制字符与 WeJet 偶发的整数前导零（如 updates:016）。"""
        cleaned = re.sub(r"[\x00-\x1F]+", "", message if isinstance(message, str) else str(message))
        # JSON 禁止 016 这类八进制写法；上游火山等帧偶发，导致整段首连数组失败
        cleaned = re.sub(r'("(?:updates|Updates)"\s*:\s*)0+(\d+)\b', r"\1\2", cleaned)
        return cleaned

    @staticmethod
    def _wolfx_normalize_recv_text(message: Any) -> str:
        """将 Wolfx 收到的 WebSocket 帧统一转为 UTF-8 字符串。"""
        if isinstance(message, bytes):
            try:
                return message.decode("utf-8")
            except UnicodeDecodeError:
                return message.decode("utf-8", errors="replace")
        if isinstance(message, str):
            return message
        return str(message)

    def _wolfx_message_is_query_response_frame(self, message: str, adapter: Any) -> bool:
        """
        判断是否为 Wolfx 查询对应的业务回包（非心跳/控制帧，且为 EEW JSON 或适配器可解析为预警）。
        """
        if not message or not message.strip():
            return False
        t = message.strip().lower()
        if t in ("heartbeat", "ping", "pong"):
            return False
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            try:
                data = json.loads(self._sanitize_json_text(message))
            except (json.JSONDecodeError, ValueError, TypeError):
                return False
        if not isinstance(data, dict):
            return False
        msg_type = str(data.get("type", "")).strip().lower()
        if msg_type in ("heartbeat", "ping", "pong", ""):
            return False
        if int(data.get("code") or 0) == 555:
            return False
        if msg_type in WOLFX_EEW_JSON_TYPES or msg_type in WOLFX_LIST_JSON_TYPES:
            return True
        try:
            return adapter.parse(data) is not None
        except Exception:
            return False

    @staticmethod
    def _wolfx_all_eew_query_commands(enabled_sources: Optional[Dict[str, Any]] = None) -> tuple[str, ...]:
        """all_eew 建连后查询指令：固定 EEW + 已勾选的列表速报。"""
        cmds = list(WOLFX_ALL_EEW_QUERY_COMMANDS)
        es = enabled_sources if isinstance(enabled_sources, dict) else {}
        if es.get(WOLFX_CENC_EQLIST_URL, False):
            cmds.append("query_cenceqlist")
        if es.get(WOLFX_JMA_EQLIST_URL, False):
            cmds.append("query_jmaeqlist")
        return tuple(cmds)

    async def _wolfx_run_staggered_queries(
        self,
        websocket: Any,
        url: str,
        source_name: str,
        adapter: Any,
        commands: tuple[str, ...],
    ) -> None:
        """逐条发送 Wolfx 查询指令：每条发送后轮询 recv，直到收到业务 EEW 或超时，再间隔 1s 发下一条。"""
        n = len(commands)
        for idx, cmd in enumerate(commands):
            try:
                await websocket.send(cmd)
            except Exception as e:
                logger.warning(f"[{source_name}] 发送 Wolfx 查询指令失败({cmd}): {e}")
                if idx < n - 1:
                    await asyncio.sleep(WOLFX_QUERY_STAGGER_INTERVAL_SEC)
                continue
            logger.info(f"[{source_name}] 已发送 Wolfx 查询指令: {cmd}")
            deadline = time.monotonic() + WOLFX_QUERY_RESPONSE_DEADLINE_SEC
            got_business = False
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                recv_timeout = min(WOLFX_QUERY_RECV_CHUNK_SEC, max(0.05, remaining))
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=recv_timeout)
                except asyncio.TimeoutError:
                    continue
                msg_str = self._wolfx_normalize_recv_text(raw)
                looks = self._wolfx_message_is_query_response_frame(msg_str, adapter)
                await self._process_message(msg_str, adapter, source_name, url)
                if looks:
                    got_business = True
                    break
            if not got_business:
                logger.warning(
                    f"[{source_name}] 查询指令 {cmd!r} 在等待业务回包时超时"
                    f"（{WOLFX_QUERY_RESPONSE_DEADLINE_SEC:g}s），继续下一条"
                )
            if idx < n - 1:
                await asyncio.sleep(WOLFX_QUERY_STAGGER_INTERVAL_SEC)
    
    async def connect_to_source(self, url: str, source_name: str):
        """
        连接到单个数据源
        
        Args:
            url: WebSocket URL
            source_name: 数据源名称
        """
        adapter = self.get_adapter(url)
        
        while self._running:
            pending_reconnect_wait: Optional[int] = None
            # 检查是否启用
            if not self.enabled_sources.get(url, True):
                self.connection_states[url] = "unconnected"
                # 热停后结束任务；再次启用由 reload_connections 新建任务
                break
            
            try:
                norm_url = url.rstrip("/").lower()
                # CWA 专用线：在 TCP/WebSocket 建连之前就等 all_eew 首轮错峰 query 跑完，避免与 all_eew 并行占线
                if norm_url == WOLFX_CWA_EEW_URL:
                    ev = self._wolfx_all_eew_bootstrap_done
                    if ev is None:
                        logger.warning(
                            f"[{source_name}] 未注册 all_eew 放行事件（应经 start_all_connections 启动），将直接连接"
                        )
                    elif not ev.is_set():
                        logger.info(
                            f"[{source_name}] 等待 all_eew 首轮错峰查询完成后再建立 WebSocket…"
                        )
                        try:
                            await asyncio.wait_for(ev.wait(), timeout=WOLFX_CWA_WAIT_ALL_EEW_BOOTSTRAP_SEC)
                        except asyncio.TimeoutError:
                            logger.warning(
                                f"[{source_name}] 等待 all_eew 首轮错峰查询完成超时"
                                f"（{WOLFX_CWA_WAIT_ALL_EEW_BOOTSTRAP_SEC:g}s），仍将尝试连接 cwa_eew"
                            )
                        else:
                            logger.info(f"[{source_name}] 已放行，开始连接 {url}")

                logger.debug(f"[{source_name}] 连接中...")
                self.connection_states[url] = "connecting"

                connect_url = url
                if is_whews_url(url or ""):
                    token = (getattr(Config().ws_config, "whews_token", "") or "").strip()
                    if not token:
                        # 文件日志只保留 DEBUG/ERROR，故用 error 确保可诊断
                        logger.error(
                            f"[{source_name}] 未配置 WeJet 令牌，暂停连接"
                            "（请统一登录或填写 wat_ 令牌）"
                        )
                        self.connection_states[url] = "unconnected"
                        await asyncio.sleep(30)
                        continue
                    # 鉴权不走 URL 参数：建连后立即发送纯文本 token（须在 5 秒内）
                if self._is_eqsc_url(url):
                    # 公开版拒绝 EQSC WS；此处不应到达（get_adapter 已 return None）
                    logger.warning(
                        f"[{source_name}] EQSC WebSocket 已禁用，跳过连接（请使用 HTTP）"
                    )
                    self._eqsc_auth_status[url] = ("none", "EQSC 仅支持 HTTP 轮询")
                    self.connection_states[url] = "unconnected"
                    await asyncio.sleep(3600)
                    continue
                
                async with websockets.connect(
                    connect_url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    close_timeout=self.close_timeout,
                    open_timeout=self.open_timeout
                ) as websocket:
                    logger.info(f"[{source_name}] 已连接到 {url}")
                    self.reconnect_attempts[url] = 0
                    self.connections[url] = websocket
                    self.connection_states[url] = "connected"
                    health = self._ensure_health_entry(url, source_name)
                    health["heartbeat_state"] = "connected"
                    health["last_message_ts"] = time.time()

                    # 无界科技：连接后首帧发送纯文本令牌
                    if is_whews_url(url or ""):
                        await self._maybe_send_whews_auth(websocket, url, source_name)

                    # Fan Studio /all：连接后发送鉴权（未填 API Key 则仅公开精简流）
                    await self._maybe_send_fanstudio_auth(websocket, url, source_name)

                    # Wolfx：all_eew 错峰查询 EEW+列表；CWA 仅走独立端点
                    if norm_url == WOLFX_ALL_EEW_URL:
                        await self._wolfx_run_staggered_queries(
                            websocket,
                            url,
                            source_name,
                            adapter,
                            self._wolfx_all_eew_query_commands(self.enabled_sources),
                        )
                        ev = self._wolfx_all_eew_bootstrap_done
                        if ev is not None and not ev.is_set():
                            ev.set()
                            logger.info(f"[{source_name}] all_eew 首轮错峰查询已完成，已放行 cwa_eew 建连")
                    elif norm_url == WOLFX_CWA_EEW_URL:
                        await self._wolfx_run_staggered_queries(
                            websocket, url, source_name, adapter, WOLFX_CWA_EEW_QUERY_COMMANDS
                        )

                    # Nowquake：建连后 HTTP 拉取最新一条烈度速报（仅一次，后续靠 WS 推送）
                    if norm_url == NOWQUAKE_CENCINT_WSS_URL:
                        from adapters.nowquake_cencint_adapter import NowquakeCencintAdapter
                        if isinstance(adapter, NowquakeCencintAdapter):
                            await self._nowquake_bootstrap_latest(adapter, source_name)

                    # Jian Project /all：高配模式才拉取历史列表，减轻内存尖峰
                    if is_jian_project_url(url or ""):
                        try:
                            from utils.memory_policy import should_fetch_jian_alllist

                            perf = getattr(
                                Config().gui_config, "performance_mode", "medium"
                            )
                            if should_fetch_jian_alllist(perf):
                                await websocket.send("alllist")
                                logger.info(
                                    f"[{source_name}] 已发送 Jian Project alllist 拉取历史列表"
                                )
                            else:
                                logger.debug(
                                    f"[{source_name}] 当前性能模式({perf})跳过 Jian alllist"
                                )
                        except Exception as e:
                            logger.warning(f"[{source_name}] Jian Project alllist 发送失败: {e}")
                    
                    # 创建发送队列（如果不存在）
                    if url not in self._send_queues:
                        self._send_queues[url] = Queue()
                    
                    # 主消息循环
                    while self._running:
                        # 热重载禁用：主动退出内层循环以关闭连接
                        if not self.enabled_sources.get(url, True):
                            logger.info(f"[{source_name}] 数据源已禁用，主动断开连接")
                            break
                        # 发送待发送的消息
                        await self._send_pending_messages(websocket, url, source_name)
                        
                        # 接收消息（使用超时，以便定期检查发送队列）
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=0.5)
                            logger.debug(f"[{source_name}] 收到消息，长度: {len(message) if isinstance(message, str) else len(str(message))}")
                            await self._process_message(message, adapter, source_name, url)
                        except asyncio.TimeoutError:
                            # 超时：继续循环并执行心跳检查
                            await self._check_heartbeat_timeout(websocket, url, source_name)
                            continue
                    self._cleanup_connection(url, source_name)
                            
            except websockets.ConnectionClosed as e:
                logger.warning(f"[{source_name}] 连接断开: code={e.code}, reason={getattr(e, 'reason', 'N/A')}")
                self._cleanup_connection(url, source_name)
                # 无界科技鉴权失败（4401）：停止重连，避免刷令牌错误
                if int(getattr(e, "code", 0) or 0) == 4401 and is_whews_url(url or ""):
                    logger.error(f"[{source_name}] WeJet 鉴权失败(4401)，已停止重连，请检查令牌")
                    self.enabled_sources[url] = False
                    self.connection_states[url] = "auth_failed"
                    continue
            except TimeoutError as e:
                logger.warning(f"[{source_name}] 连接超时（握手阶段）: {e}，将按重连间隔重试")
                self._cleanup_connection(url, source_name)
            except (ConnectionResetError, ConnectionAbortedError, ConnectionRefusedError, BrokenPipeError) as e:
                logger.warning(
                    f"[{source_name}] 连接被重置或拒绝（握手/建连阶段）: {e}，将按重连间隔重试"
                )
                self._cleanup_connection(url, source_name)
            except OSError as e:
                logger.warning(f"[{source_name}] 网络错误: {e}，将按重连间隔重试")
                self._cleanup_connection(url, source_name)
            except Exception as e:
                err_summary = f"{type(e).__name__}: {str(e)[:120]}"
                now = time.time()
                last = self._connect_error_log.get(url)
                if isinstance(e, websockets.exceptions.InvalidStatus):
                    pending_reconnect_wait = _reconnect_wait_seconds(
                        _invalid_status_http_code(e),
                        self.reconnect_attempts[url] + 1,
                    )
                if last and now - last[0] < 60 and last[1] == err_summary:
                    logger.debug(f"[{source_name}] 连接错误（已降噪）: {e}")
                else:
                    if isinstance(e, websockets.exceptions.InvalidStatus):
                        logger.warning(
                            f"[{source_name}] 连接错误: {e}，将按重连间隔重试"
                        )
                    else:
                        logger.error(f"[{source_name}] 连接错误: {e}")
                    self._connect_error_log[url] = (now, err_summary)
                self._cleanup_connection(url, source_name)
            
            # 重连逻辑
            if not self._running:
                break
            # 已禁用：结束任务（再次启用由 reload_connections 新建）
            if not self.enabled_sources.get(url, True):
                self.connection_states[url] = "unconnected"
                break
            if not await self._should_reconnect(url, source_name):
                continue
            
            # 等待后重连（指数退避；429/5xx 使用更长间隔）
            if pending_reconnect_wait is not None:
                wait_time = pending_reconnect_wait
            else:
                wait_time = min(self.reconnect_attempts[url] * 2, 30)
            attempt = self.reconnect_attempts[url]
            logger.debug(f"[{source_name}] {wait_time}秒后重连(第{attempt}次)")
            if not self._running:
                break
            await asyncio.sleep(wait_time)
    
    async def _run_until_stopped(self) -> None:
        """保持事件循环存活，直到 stop_all；避免全部连接任务结束后线程退出。"""
        while self._running:
            await asyncio.sleep(1.0)

    async def stop_all(self):
        """停止所有 WebSocket 连接任务"""
        if not self._running:
            return
        self._running = False
        logger.info("正在停止所有 WebSocket 连接...")
        if self._keepalive_task and not self._keepalive_task.done():
            self._keepalive_task.cancel()
        for url, task in list(self._connection_tasks.items()):
            if task and not task.done():
                task.cancel()
        wait_tasks = list(self._connection_tasks.values())
        if self._keepalive_task is not None:
            wait_tasks.append(self._keepalive_task)
        if wait_tasks:
            await asyncio.gather(*wait_tasks, return_exceptions=True)
        self._connection_tasks.clear()
        self._keepalive_task = None
        self.connections.clear()
        logger.info("所有 WebSocket 连接已停止")
    
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
        self._fanstudio_awaiting_auth.pop(url, None)
        if self._is_fanstudio_all_url(url):
            self._fanstudio_auth_status[url] = ("none", "连接已断开")
        if self._is_eqsc_url(url):
            self._eqsc_auth_status[url] = ("none", "连接已断开")
        self._cancel_whews_cea_refresh(url)
        self._whews_cea_awaiting_auth.pop(url, None)
        self._whews_cea_access_token.pop(url, None)
        if is_whews_cea_endpoint(url or ""):
            self._whews_cea_auth_status[url] = ("none", "连接已断开")
        self.connection_states[url] = "disconnected"
        entry = self._ensure_health_entry(url, source_name)
        entry["heartbeat_state"] = "disconnected"

    def get_connection_status(self) -> Dict[str, str]:
        """
        获取连接状态快照，供设置页状态指示使用。

        Returns:
            Dict[url, state]，state: connected/connecting/disconnected/unconnected
        """
        status = dict(self.connection_states)
        for url in self.connections.keys():
            status[url] = "connected"
        for url in self.enabled_sources.keys():
            status.setdefault(url, "unconnected")
        return status

    def get_health_status(self) -> Dict[str, Dict[str, Any]]:
        """获取数据源健康状态快照（供设置页状态面板展示）"""
        now = time.time()
        result: Dict[str, Dict[str, Any]] = {}
        for url, entry in self._health_status.items():
            copied = dict(entry)
            enabled = bool(self.enabled_sources.get(url, False))
            connection_state = self.connection_states.get(
                url,
                "connected" if url in self.connections else "unconnected",
            )
            # 已禁用：展示为未连接，勿用过期心跳冒充「心跳超时」
            if not enabled:
                connection_state = "unconnected"
                if copied.get("heartbeat_state") == "timeout":
                    copied["heartbeat_state"] = "disconnected"
            timeout_seconds = int(copied.get("timeout_seconds", 0) or 0)
            last_heartbeat = float(copied.get("last_heartbeat_ts", 0.0) or 0.0)
            # 仅在仍应保持连接时，才按心跳年龄判定超时
            if (
                enabled
                and connection_state == "connected"
                and timeout_seconds > 0
                and last_heartbeat > 0
                and (now - last_heartbeat) > timeout_seconds
            ):
                copied["heartbeat_state"] = "timeout"
            copied["enabled"] = enabled
            copied["connection_state"] = connection_state
            copied["heartbeat_age_seconds"] = (now - last_heartbeat) if last_heartbeat > 0 else None
            result[url] = copied
        for url in self.enabled_sources.keys():
            enabled = bool(self.enabled_sources.get(url, False))
            result.setdefault(
                url,
                {
                    "source_name": "",
                    "source_kind": self._get_source_kind(url),
                    "timeout_seconds": HEARTBEAT_TIMEOUT_SECONDS.get(self._get_source_kind(url), 0),
                    "last_message_ts": 0.0,
                    "last_heartbeat_ts": 0.0,
                    "last_ping_ts": 0.0,
                    "last_pong_ts": 0.0,
                    "last_auto_ping_ts": 0.0,
                    "timeout_count": 0,
                    "auto_ping_count": 0,
                    "heartbeat_state": "unknown",
                    "enabled": enabled,
                    "connection_state": (
                        self.connection_states.get(url, "unconnected")
                        if enabled
                        else "unconnected"
                    ),
                    "heartbeat_age_seconds": None,
                },
            )
        return result
    
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
            logger.info("P2PQuake WSS 启动前，先通过 HTTP 拉取一次最新地震/海啸/EEW 情报（聚合 551/552/556）")

            async def _fetch_history():
                """异步拉取 P2PQuake 历史 HTTP 接口并逐条解析推送。"""
                def _request():
                    """在线程池中执行同步 HTTP GET 请求。"""
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

                from adapters.p2pquake_adapter import P2PQuakeAdapter
                from adapters.p2pquake_tsunami_adapter import P2PQuakeTsunamiAdapter
                from adapters.p2pquake_eew_adapter import P2PQuakeEEWAdapter
                eq_adapter = P2PQuakeAdapter("p2pquake", P2PQUAKE_HISTORY_URL)
                tsu_adapter = P2PQuakeTsunamiAdapter("p2pquake_tsunami", P2PQUAKE_HISTORY_URL)
                eew_adapter = P2PQuakeEEWAdapter("p2pquake_eew", P2PQUAKE_HISTORY_URL)
                eq_count = 0
                tsu_count = 0
                eew_count = 0

                msg_cfg = config.message_config
                parse_551 = getattr(msg_cfg, "p2pquake_parse_551", True)
                parse_552 = getattr(msg_cfg, "p2pquake_parse_552", True)
                parse_556 = getattr(msg_cfg, "p2pquake_parse_556", True)
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    code_raw = item.get("code")
                    try:
                        code = int(code_raw) if code_raw is not None else None
                    except (TypeError, ValueError):
                        code = None
                    if code == 551:
                        if not parse_551:
                            continue
                        try:
                            parsed = eq_adapter._parse_single_item(item)
                        except Exception as e:
                            logger.error(f"[p2pquake] 启动前 HTTP 解析地震情报单条失败: {e}", exc_info=True)
                            continue
                        if parsed:
                            parsed["_suppress_tts"] = True
                            self.message_callback("p2pquake", parsed)
                            eq_count += 1
                    elif code == 552:
                        if not parse_552:
                            continue
                        try:
                            parsed = tsu_adapter.parse_single_item(item)
                        except Exception as e:
                            logger.error(f"[p2pquake_tsunami] 启动前 HTTP 解析海啸情报单条失败: {e}", exc_info=True)
                            continue
                        if parsed:
                            parsed["_suppress_tts"] = True
                            self.message_callback("p2pquake_tsunami", parsed)
                            tsu_count += 1
                    elif code == 556:
                        if not parse_556:
                            continue
                        try:
                            parsed = eew_adapter.parse_single_item(item)
                        except Exception as e:
                            logger.error(f"[p2pquake_eew] 启动前 HTTP 解析 EEW 单条失败: {e}", exc_info=True)
                            continue
                        if parsed:
                            parsed["_suppress_tts"] = True
                            self.message_callback("p2pquake_eew", parsed)
                            eew_count += 1

                logger.info(
                    f"[p2pquake] 启动前 HTTP 推送 {eq_count} 条地震情报, "
                    f"{tsu_count} 条海啸情报, {eew_count} 条緊急地震速报；"
                    "后续由 WSS 长连接接收实时更新"
                )

            await _fetch_history()
        except Exception as e:
            logger.error(f"P2PQuake 启动前 HTTP 拉取阶段异常: {e}", exc_info=True)

    @staticmethod
    def _sort_wolfx_startup_urls(urls: list) -> list:
        """Wolfx 阶段固定顺序：all_eew → cwa_eew。"""
        order = {
            WOLFX_ALL_EEW_URL: 0,
            WOLFX_CWA_EEW_URL: 1,
        }

        def _key(u: str) -> tuple[int, str]:
            """Wolfx 启动排序键。"""
            n = (u or "").strip().lower().rstrip("/")
            return (order.get(n, 50), u or "")

        return sorted(urls, key=_key)

    @staticmethod
    def _is_fanstudio_all_url(url: str) -> bool:
        """判断是否为 Fan Studio /all 聚合通道。"""
        normalized = (url or "").strip().lower().rstrip("/")
        if normalized in {u.rstrip("/").lower() for u in FANSTUDIO_ALL_URLS}:
            return True
        return normalized.endswith("/all") and "fanstudio" in normalized

    @staticmethod
    def _is_eqsc_url(url: str) -> bool:
        """判断是否为 EQSC WebSocket 地址。"""
        normalized = (url or "").strip().lower().rstrip("/")
        return normalized == EQSC_WS_URL.strip().lower().rstrip("/")

    def get_eqsc_auth_status(self) -> Tuple[str, str]:
        """
        返回 EQSC 鉴权状态。

        公开版仅支持 HTTP，WS 路径已禁用；设置页可据此显示「仅 HTTP」。
        """
        return ("none", "EQSC 仅支持 HTTP 轮询")

    async def _maybe_send_whews_auth(self, websocket: Any, url: str, source_name: str) -> None:
        """
        WeJet 建连后立即发送纯文本令牌（首帧）。

        若 5 秒内未发送，服务端以关闭码 4401 断开。
        CEA 端点在令牌鉴权后还会收到 hello，需再发 App auth（见 _handle_whews_cea_control）。
        """
        if not is_whews_url(url or ""):
            return
        token = (getattr(Config().ws_config, "whews_token", "") or "").strip()
        if not token:
            logger.warning(f"[{source_name}] WeJet 令牌为空，无法鉴权")
            return
        try:
            await websocket.send(token)
            logger.info(f"[{source_name}] 已发送 WeJet 纯文本令牌鉴权")
            if is_whews_cea_endpoint(url or ""):
                if whews_cea_app_configured():
                    self._whews_cea_auth_status[url] = ("pending", "等待服务端 hello…")
                else:
                    self._whews_cea_auth_status[url] = (
                        "failed",
                        "未配置 CEA AppId/AppSecret，无法接收预警",
                    )
        except Exception as e:
            logger.warning(f"[{source_name}] 发送 WeJet 令牌失败: {e}")

    def _cancel_whews_cea_refresh(self, url: str) -> None:
        """取消指定连接的 CEA AccessToken 续票任务。"""
        task = self._whews_cea_refresh_tasks.pop(url, None)
        if task and not task.done():
            task.cancel()

    async def _send_whews_cea_app_auth(self, url: str, source_name: str) -> bool:
        """向 CEA 端点发送 appId/appSecret 鉴权帧。"""
        websocket = self.connections.get(url)
        if websocket is None:
            return False
        cfg = Config().ws_config
        try:
            from utils.whews_cea_builtin import apply_builtin_whews_cea_credentials

            apply_builtin_whews_cea_credentials(cfg)
        except Exception:
            pass
        app_id = (getattr(cfg, "whews_cea_app_id", "") or "").strip()
        app_secret = (getattr(cfg, "whews_cea_app_secret", "") or "").strip()
        if not app_id or not app_secret:
            self._whews_cea_auth_status[url] = (
                "failed",
                "未配置 CEA AppId/AppSecret",
            )
            logger.warning(f"[{source_name}] CEA 需要 App 鉴权但未配置凭证")
            return False
        payload = {
            "type": "auth",
            "data": {"appId": app_id, "appSecret": app_secret},
        }
        try:
            self._whews_cea_awaiting_auth[url] = True
            self._whews_cea_auth_status[url] = ("pending", "正在进行 CEA App 鉴权…")
            await websocket.send(json.dumps(payload, ensure_ascii=False))
            logger.info(f"[{source_name}] 已发送 CEA App 鉴权 (cea_all)")
            return True
        except Exception as e:
            self._whews_cea_awaiting_auth.pop(url, None)
            self._whews_cea_auth_status[url] = ("failed", f"发送 App 鉴权失败: {e}")
            logger.warning(f"[{source_name}] 发送 CEA App 鉴权失败: {e}")
            return False

    async def _send_whews_cea_refresh(self, url: str, source_name: str) -> bool:
        """到期前用当前 accessToken 续票。"""
        websocket = self.connections.get(url)
        token = (self._whews_cea_access_token.get(url) or "").strip()
        if websocket is None or not token:
            return False
        payload = {"type": "refresh", "data": {"accessToken": token}}
        try:
            await websocket.send(json.dumps(payload, ensure_ascii=False))
            logger.info(f"[{source_name}] 已发送 CEA AccessToken 续票")
            return True
        except Exception as e:
            logger.warning(f"[{source_name}] CEA 续票发送失败: {e}")
            return False

    def _schedule_whews_cea_refresh(
        self, url: str, source_name: str, expires_in: int
    ) -> None:
        """约在到期前 60 秒续票；expires_in 过短则立即续。"""
        self._cancel_whews_cea_refresh(url)
        try:
            ttl = max(1, int(expires_in or 600))
        except (TypeError, ValueError):
            ttl = 600
        delay = max(5.0, float(ttl) - 60.0)

        async def _runner() -> None:
            try:
                await asyncio.sleep(delay)
                if url not in self.connections:
                    return
                await self._send_whews_cea_refresh(url, source_name)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"[{source_name}] CEA 续票任务异常: {e}")

        self._whews_cea_refresh_tasks[url] = asyncio.create_task(_runner())

    async def _handle_whews_cea_control(
        self, url: str, source_name: str, data: Dict[str, Any]
    ) -> None:
        """处理 WeJet CEA 的 hello / auth_ok / auth_fail / error。"""
        msg_type = str(data.get("type", "")).strip().lower()
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}

        if msg_type == "hello":
            need_auth = bool(payload.get("needAuth", False))
            # 非 CEA 端点且未声明 needAuth：忽略
            if not is_whews_cea_endpoint(url or "") and not need_auth:
                return
            if not need_auth:
                self._whews_cea_auth_status[url] = ("ok", "无需 App 鉴权")
                return
            await self._send_whews_cea_app_auth(url, source_name)
            return

        if msg_type == "auth_ok":
            self._whews_cea_awaiting_auth.pop(url, None)
            access_token = str(payload.get("accessToken") or "").strip()
            if access_token:
                self._whews_cea_access_token[url] = access_token
            expires_in = payload.get("expiresIn", 600)
            try:
                expires_in_i = int(expires_in)
            except (TypeError, ValueError):
                expires_in_i = 600
            self._whews_cea_auth_status[url] = (
                "ok",
                f"CEA App 鉴权成功（约 {expires_in_i}s 有效）",
            )
            logger.info(f"[{source_name}] CEA App 鉴权成功, expiresIn={expires_in_i}")
            self._schedule_whews_cea_refresh(url, source_name, expires_in_i)
            return

        if msg_type == "auth_fail":
            self._whews_cea_awaiting_auth.pop(url, None)
            self._cancel_whews_cea_refresh(url)
            self._whews_cea_access_token.pop(url, None)
            code = str(payload.get("code") or "").strip()
            message = str(payload.get("message") or "鉴权失败").strip()
            detail = f"{code}: {message}" if code else message
            self._whews_cea_auth_status[url] = ("failed", detail)
            logger.warning(f"[{source_name}] CEA App 鉴权失败: {detail}")
            return

        if msg_type == "error":
            # 鉴权相关错误（如 auth_timeout）反映到状态行
            code = str(payload.get("code") or data.get("code") or "").strip()
            message = str(
                payload.get("message") or data.get("message") or "服务端错误"
            ).strip()
            detail = f"{code}: {message}" if code else message
            if self._whews_cea_awaiting_auth.get(url) or is_whews_cea_endpoint(url or ""):
                self._whews_cea_awaiting_auth.pop(url, None)
                self._cancel_whews_cea_refresh(url)
                self._whews_cea_auth_status[url] = ("failed", detail)
                logger.warning(f"[{source_name}] CEA 控制错误: {detail}")
            else:
                logger.warning(f"[{source_name}] WeJet 错误: {detail}")
            return

    def get_whews_cea_auth_status(self) -> Tuple[str, str]:
        """
        返回 WeJet CEA App 鉴权状态（优先已连接的 CEA 端点）。

        Returns:
            (state, message)：state 为 none/pending/ok/failed
        """
        for url in list(self.connections.keys()):
            if is_whews_cea_endpoint(url):
                return self._whews_cea_auth_status.get(url, ("none", ""))
        for url, status in self._whews_cea_auth_status.items():
            if is_whews_cea_endpoint(url):
                return status
        return ("none", "")

    async def _maybe_send_fanstudio_auth(self, websocket: Any, url: str, source_name: str) -> None:
        """
        Fan Studio /all 建连后发送鉴权。

        未配置 API Key 时不发送：服务器仅返回公开精简数据（如 fssn / fssn-cmt）。
        配置了 Key 后发送 {"type":"auth","appId":"...","key":"sk-..."}。
        """
        if not self._is_fanstudio_all_url(url):
            return
        api_key = (getattr(Config().ws_config, "fanstudio_api_key", "") or "").strip()
        if not api_key:
            self._fanstudio_awaiting_auth.pop(url, None)
            self._fanstudio_auth_status[url] = ("none", "未配置 API Key")
            logger.info(
                f"[{source_name}] 未配置 Fan Studio API Key，跳过鉴权"
                "（将仅接收公开精简数据流）"
            )
            return
        try:
            auth_msg = build_fanstudio_auth_message(api_key)
            self._fanstudio_awaiting_auth[url] = True
            self._fanstudio_auth_status[url] = ("pending", "正在连接并鉴权…")
            await websocket.send(auth_msg)
            logger.info(f"[{source_name}] 已发送 Fan Studio 鉴权请求")
        except Exception as e:
            self._fanstudio_awaiting_auth.pop(url, None)
            self._fanstudio_auth_status[url] = ("failed", f"发送鉴权失败: {e}")
            logger.warning(f"[{source_name}] 发送 Fan Studio 鉴权失败: {e}")

    def _classify_startup_group(self, url: str) -> str:
        """
        启动分组：
        1) fanstudio(all)
        2) whews
        3) p2pquake(wss)
        4) wolfx(all_eew)
        5) eqsc
        6) 其他
        """
        normalized_url = (url or "").strip().lower().rstrip("/")
        if normalized_url in FANSTUDIO_ALL_URLS:
            return "fanstudio"
        if is_whews_url(normalized_url) or any(
            normalized_url == u.rstrip("/").lower() for u in WHEWS_WS_URLS
        ):
            return "whews"
        if normalized_url == P2PQUAKE_WSS_URL:
            return "p2pquake"
        if normalized_url in WOLFX_URLS:
            return "wolfx"
        if normalized_url == EQSC_WS_URL.strip().lower().rstrip("/"):
            return "eqsc"
        if normalized_url == OPENQUAKE_WS_ALL_URL.strip().lower().rstrip("/"):
            return "openquake"
        if is_custom_data_source_url(normalized_url):
            return "other"
        if normalized_url == NOWQUAKE_CENCINT_WSS_URL:
            return "other"
        return "other"
    
    async def _nowquake_bootstrap_latest(self, adapter: Any, source_name: str):
        """Nowquake 建连后拉取最新烈度速报并下发（抑制 TTS）。"""
        try:
            parsed = await asyncio.to_thread(adapter.fetch_latest_event)
            if not parsed:
                logger.info(f"[{source_name}] Nowquake 首连无可用烈度速报")
                return
            parsed["_suppress_tts"] = True
            actual_source = parsed.get("source_type") or "cenc-ir"
            logger.info(f"[{source_name}] Nowquake 首连已拉取最新烈度速报: {parsed.get('event_id')}")
            _dispatch_parsed_message(self, parsed, actual_source, source_name)
        except Exception as e:
            logger.warning(f"[{source_name}] Nowquake 首连拉取失败: {e}")

    def _collect_desired_ws_urls(self, config: Config) -> list:
        """按当前配置收集应连接的 WebSocket URL 列表。"""
        # 关闭废弃 cenc / 拆分 cea 线；保留国内站 /ws/cea_all
        if hasattr(config, "_disable_whews_dedicated_endpoints"):
            config._disable_whews_dedicated_endpoints()
        enabled_urls = []
        for url in config.ws_urls:
            if "fanstudio" in (url or "").lower() and not (url or "").rstrip("/").lower().endswith("/all"):
                logger.warning(f"跳过已移除的 Fan Studio 路径: {url}")
                continue
            if is_whews_dedicated_endpoint(url) or is_whews_cea_split_endpoint(url):
                logger.debug(f"跳过已废弃的 WeJet 专用端点: {url}")
                continue
            if hasattr(config, "is_url_active_for_provider") and not config.is_url_active_for_provider(url):
                continue
            if config.enabled_sources.get(url, True):
                enabled_urls.append(url)
        custom_url = (config.custom_data_source_url or "").strip()
        if custom_url and (custom_url.startswith('ws://') or custom_url.startswith('wss://')):
            if custom_url not in enabled_urls:
                enabled_urls.append(custom_url)
                logger.debug(f"添加自定义WebSocket数据源: {custom_url}")
        return enabled_urls

    async def start_all_connections(self):
        """启动所有数据源连接"""
        config = Config()
        enabled_urls = self._collect_desired_ws_urls(config)
        for url in enabled_urls:
            self.enabled_sources[url] = True
        
        if not enabled_urls:
            logger.warning("ws_urls为空，没有可连接的数据源！")
            logger.warning(f"config.ws_urls = {config.ws_urls}")
            logger.warning(f"config.enabled_sources中包含的WebSocket URL: {[url for url in config.enabled_sources.keys() if url.startswith(('ws://', 'wss://'))]}")
        else:
            logger.info(f"准备连接{len(enabled_urls)}个数据源: {enabled_urls}")
        
        # 创建所有连接任务
        grouped_urls: Dict[str, list] = {
            "fanstudio": [],
            "whews": [],
            "p2pquake": [],
            "wolfx": [],
            "eqsc": [],
            "openquake": [],
            "other": [],
        }
        for url in enabled_urls:
            grouped_urls[self._classify_startup_group(url)].append(url)

        # 启动阶段顺序固定：fanstudio -> whews -> p2pquake -> wolfx -> eqsc -> openquake -> other
        startup_stages = ("fanstudio", "whews", "p2pquake", "wolfx", "eqsc", "openquake", "other")
        tasks = []
        urls_for_tasks = []
        stagger = float(getattr(config.ws_config, "startup_stagger_seconds", 1.5) or 0.0)
        if stagger < 0:
            stagger = 0.0
        any_ws_task_started = False

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

            logger.info(
                f"启动阶段[{stage}]，准备创建 {len(stage_urls)} 个连接任务"
                + (f"（相邻任务间隔 {stagger}s）" if stagger > 0 else "（同时发起）")
            )
            if stage == "wolfx" and stage_urls:
                stage_urls = self._sort_wolfx_startup_urls(list(stage_urls))
                self._wolfx_all_eew_bootstrap_done = asyncio.Event()
                if WOLFX_ALL_EEW_URL not in {(u or "").strip().lower().rstrip("/") for u in stage_urls}:
                    self._wolfx_all_eew_bootstrap_done.set()
                    logger.debug("Wolfx 阶段未启用 all_eew，已放行 cwa_eew 首轮查询等待")

            for url in stage_urls:
                adapter = self.get_adapter(url)
                if adapter is None:
                    logger.debug(f"跳过无适配器的数据源: {url}")
                    continue
                if any_ws_task_started and stagger > 0:
                    await asyncio.sleep(stagger)
                source_name = config.get_source_name(url)
                logger.debug(f"创建连接任务[{stage}]: {url} -> {source_name}")
                task = asyncio.create_task(self.connect_to_source(url, source_name))
                tasks.append(task)
                urls_for_tasks.append(url)
                self._connection_tasks[url] = task
                any_ws_task_started = True

            # 阶段让步：确保创建顺序稳定且不阻塞事件循环
            await asyncio.sleep(0)
        
        logger.info(f"已创建{len(tasks)}个连接任务，按序异步建连中...")
        # keepalive：即使连接任务被热停光，事件循环仍保持，供后续热启停
        self._keepalive_task = asyncio.create_task(self._run_until_stopped())
        wait_list = list(tasks) + [self._keepalive_task]
        results = await asyncio.gather(*wait_list, return_exceptions=True)
        
        # 检查是否有任务异常退出（忽略 keepalive 的取消）
        for i, result in enumerate(results):
            if i >= len(urls_for_tasks):
                continue
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                url = urls_for_tasks[i]
                logger.error(f"连接任务异常退出: {url}, 错误: {result}", exc_info=True)

    async def reload_connections(self) -> None:
        """根据当前 Config 热启停 WebSocket（无需重启进程）。并发调用会串行执行。"""
        if not self._running:
            logger.warning("WebSocket 管理器未运行，无法热重载连接")
            return
        if self._reload_lock is None:
            self._reload_lock = asyncio.Lock()
        async with self._reload_lock:
            await self._reload_connections_unlocked()

    async def _reload_connections_unlocked(self) -> None:
        """热启停实现（调用方须已持有 _reload_lock）。"""
        config = Config()
        desired = self._collect_desired_ws_urls(config)
        desired_set = set(desired)
        desired_norm = {(u or "").strip().lower().rstrip("/") for u in desired}

        for url in list(self.enabled_sources.keys()):
            self.enabled_sources[url] = url in desired_set
        for url in desired:
            self.enabled_sources[url] = True

        # 停止不再需要的连接
        for url in list(self._connection_tasks.keys()):
            if url in desired_set:
                continue
            self.enabled_sources[url] = False
            source_name = config.get_source_name(url)
            ws = self.connections.get(url)
            if ws is not None:
                try:
                    await asyncio.wait_for(ws.close(), timeout=RELOAD_STOP_TIMEOUT_SEC)
                except Exception as e:
                    logger.debug(f"关闭 WebSocket 失败 [{source_name}]: {e}")
            task = self._connection_tasks.get(url)
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=RELOAD_STOP_TIMEOUT_SEC)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass
            self._connection_tasks.pop(url, None)
            self._cleanup_connection(url, source_name)
            logger.info(f"已热停止 WebSocket: {source_name} ({url})")

        # 收集需新建的连接（任务已结束或尚未创建）
        to_start: List[str] = []
        for url in desired:
            existing = self._connection_tasks.get(url)
            if existing is not None and not existing.done():
                continue
            adapter = self.get_adapter(url)
            if adapter is None:
                logger.debug(f"热重载跳过无适配器的数据源: {url}")
                continue
            to_start.append(url)

        # 与冷启动一致：分组顺序 + Wolfx all_eew 优先于 cwa_eew
        stage_order = {
            "fanstudio": 0,
            "whews": 1,
            "p2pquake": 2,
            "wolfx": 3,
            "eqsc": 4,
            "openquake": 5,
            "other": 6,
        }

        def _start_key(u: str) -> tuple:
            """热启动排序键：分组 → Wolfx 子顺序 → URL。"""
            group = self._classify_startup_group(u)
            wolfx_extra = 0
            if group == "wolfx":
                n = (u or "").strip().lower().rstrip("/")
                wolfx_extra = 0 if n == WOLFX_ALL_EEW_URL else 1
            return (stage_order.get(group, 9), wolfx_extra, u or "")

        to_start.sort(key=_start_key)

        # 热启 Wolfx：注册 all_eew 放行事件（与 start_all_connections 对齐）
        wolfx_starting = [u for u in to_start if self._classify_startup_group(u) == "wolfx"]
        if wolfx_starting:
            self._wolfx_all_eew_bootstrap_done = asyncio.Event()
            all_eew_in_desired = WOLFX_ALL_EEW_URL in desired_norm
            all_eew_task = self._connection_tasks.get(WOLFX_ALL_EEW_URL)
            all_eew_already_up = (
                all_eew_task is not None
                and not all_eew_task.done()
                and WOLFX_ALL_EEW_URL not in to_start
            )
            if (not all_eew_in_desired) or all_eew_already_up:
                self._wolfx_all_eew_bootstrap_done.set()
                if not all_eew_in_desired:
                    logger.debug("热重载 Wolfx：未启用 all_eew，已放行 cwa_eew")
                else:
                    logger.debug("热重载 Wolfx：all_eew 已在运行，已放行 cwa_eew")

        for url in to_start:
            source_name = config.get_source_name(url)
            self.enabled_sources[url] = True
            self.reconnect_attempts[url] = 0
            task = asyncio.create_task(self.connect_to_source(url, source_name))
            self._connection_tasks[url] = task
            logger.info(f"已热启动 WebSocket: {source_name} ({url})")

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

    def send_fanstudio_auth(self, api_key: str) -> bool:
        """
        向已连接的 Fan Studio /all 发送鉴权。

        鉴权成功后服务器会自动下发完整数据流，无需重连或重启。

        Returns:
            是否成功将鉴权消息加入发送队列（连接不存在时返回 False）
        """
        key = (api_key or "").strip()
        if not key:
            logger.warning("Fan Studio API Key 为空，无法发送鉴权")
            return False
        target_url = None
        for url in list(self.connections.keys()):
            if self._is_fanstudio_all_url(url):
                target_url = url
                break
        if not target_url:
            logger.info("Fan Studio /all 尚未连接，鉴权将在下次建连时自动发送")
            return False
        try:
            auth_msg = build_fanstudio_auth_message(key)
            self._fanstudio_awaiting_auth[target_url] = True
            self._fanstudio_auth_status[target_url] = ("pending", "正在连接并鉴权…")
            ok = self.send_message(target_url, auth_msg)
            if ok:
                logger.info(f"已向 Fan Studio /all 热发送鉴权请求: {target_url}")
            else:
                self._fanstudio_awaiting_auth.pop(target_url, None)
                self._fanstudio_auth_status[target_url] = ("failed", "鉴权消息发送失败")
            return ok
        except Exception as e:
            if target_url:
                self._fanstudio_awaiting_auth.pop(target_url, None)
                self._fanstudio_auth_status[target_url] = ("failed", f"热发送鉴权失败: {e}")
            logger.error(f"热发送 Fan Studio 鉴权失败: {e}")
            return False

    def get_fanstudio_auth_status(self) -> Tuple[str, str]:
        """
        返回 Fan Studio /all 当前鉴权状态。

        Returns:
            (state, message)：state 为 none/pending/ok/failed
        """
        for url in list(self.connections.keys()):
            if self._is_fanstudio_all_url(url):
                return self._fanstudio_auth_status.get(url, ("none", ""))
        for url, status in self._fanstudio_auth_status.items():
            if self._is_fanstudio_all_url(url):
                return status
        return ("none", "")

    def update_enabled_sources(self, enabled_sources: Dict[str, bool]):
        """
        更新启用的数据源（仅更新标志；完整热启停请用 reload_connections）
        
        Args:
            enabled_sources: 数据源启用状态字典
        """
        self.enabled_sources.update(enabled_sources)