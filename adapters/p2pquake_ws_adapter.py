#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2PQuake WebSocket 数据源适配器
WSS: wss://api.p2pquake.net/v2/ws
解析 code 551（地震情报）、552（海啸预报）、556（紧急地震速报）；字段与 HTTP API 一致。
"""

import json
from typing import Dict, Any, Optional
from .base_adapter import BaseAdapter
from .p2pquake_adapter import P2PQuakeAdapter
from .p2pquake_tsunami_adapter import P2PQuakeTsunamiAdapter
from .p2pquake_eew_adapter import P2PQuakeEEWAdapter
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger
from config import Config

logger = get_logger()

# 解析的消息代码：551 地震情报、552 海啸预报、556 紧急地震速报
P2PQUAKE_WS_CODES = (551, 552, 556)


class P2PQuakeWebSocketAdapter(BaseAdapter):
    """P2PQuake WebSocket 适配器（551 / 552 / 556）"""

    def __init__(self, source_name: str, source_url: str):
        """初始化适配器，复用地震、海啸与 EEW 子适配器。"""
        super().__init__(source_name, source_url)
        self._eq_adapter = P2PQuakeAdapter('p2pquake', source_url)
        self._tsunami_adapter = P2PQuakeTsunamiAdapter('p2pquake_tsunami', source_url)
        self._eew_adapter = P2PQuakeEEWAdapter('p2pquake_eew', source_url)

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """
        解析 WebSocket 单条 JSON 对象。处理 code 551、552、556，其余忽略。
        """
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if not isinstance(data, dict):
                return None
            code = data.get('code')
            try:
                code = int(code) if code is not None else None
            except (TypeError, ValueError):
                code = None
            if code not in P2PQUAKE_WS_CODES:
                return None  # 非 551/552 忽略
            mc = Config().message_config
            if code == 551:
                if not getattr(mc, "p2pquake_parse_551", False):
                    return None  # 设置页关闭地震情報解析
                parsed = self._eq_adapter._parse_single_item(data)
                if parsed:
                    parsed['source_type'] = 'p2pquake'
                return parsed
            if code == 552:
                if not getattr(mc, "p2pquake_parse_552", True):
                    return None  # 设置页关闭津波予報解析
                return self._tsunami_adapter.parse_single_item(data)
            if code == 556:
                if not getattr(mc, "p2pquake_parse_556", True):
                    return None
                return self._eew_adapter.parse_single_item(data)
            return None
        except json.JSONDecodeError as e:
            logger.debug(f"[P2PQuake WSS] JSON 解析失败: {e}")
            return None
        except Exception as e:
            logger.debug(f"[P2PQuake WSS] 解析跳过: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（551/552→report，556→warning）。"""
        return data.get('type', 'report')
