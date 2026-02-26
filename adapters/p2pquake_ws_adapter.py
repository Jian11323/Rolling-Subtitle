#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2PQuake WebSocket 数据源适配器
WSS: wss://api.p2pquake.net/v2/ws
仅解析 code 551（地震情报）、552（海啸预报）；字段与 HTTP API 一致。
"""

import json
from typing import Dict, Any, Optional
from .base_adapter import BaseAdapter
from .p2pquake_adapter import P2PQuakeAdapter
from .p2pquake_tsunami_adapter import P2PQuakeTsunamiAdapter
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger

logger = get_logger()

# 仅解析的消息代码：551 地震情报、552 海啸预报
P2PQUAKE_WS_CODES = (551, 552)


class P2PQuakeWebSocketAdapter(BaseAdapter):
    """P2PQuake WebSocket 适配器（仅解析 551、552）"""

    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)
        self._eq_adapter = P2PQuakeAdapter('p2pquake', source_url)
        self._tsunami_adapter = P2PQuakeTsunamiAdapter('p2pquake_tsunami', source_url)

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """
        解析 WebSocket 单条 JSON 对象。仅处理 code 551、552，其余忽略。
        """
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if not isinstance(data, dict):
                return None
            code = data.get('code')
            if code not in P2PQUAKE_WS_CODES:
                return None
            if code == 551:
                parsed = self._eq_adapter._parse_single_item(data)
                if parsed:
                    parsed['source_type'] = 'p2pquake'
                return parsed
            if code == 552:
                return self._tsunami_adapter.parse_single_item(data)
            return None
        except json.JSONDecodeError as e:
            logger.debug(f"[P2PQuake WSS] JSON 解析失败: {e}")
            return None
        except Exception as e:
            logger.debug(f"[P2PQuake WSS] 解析跳过: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get('type', 'report')
