#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NIED 数据源适配器（日本防災科研所）
仅 WebSocket：wss://sismotide.top/nied
文档：数据源文档/NIED.html
消息类型：welcome, update（预警数据）, heartbeat, pong
"""

import json
from typing import Dict, Any, Optional
from .base_adapter import BaseAdapter
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger
from utils import timezone_utils

logger = get_logger()


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


class NiedAdapter(BaseAdapter):
    """NIED WebSocket 适配器（update 消息为预警）"""

    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if not isinstance(data, dict):
                return None
            if data.get('type') != 'update':
                return None
            inner = data.get('data')
            if not isinstance(inner, dict):
                return None
            # is_cancel 取消报不展示
            if inner.get('is_cancel') is True:
                return None
            # 文档字段：region_name, magunitude(拼写), depth, origin_time, report_time
            place = inner.get('region_name') or ''
            mag = _safe_float(inner.get('magunitude') or inner.get('magnitude'))
            depth_str = inner.get('depth')
            try:
                depth = _safe_float(str(depth_str).replace('km', '').strip()) if depth_str else 0.0
            except Exception:
                depth = 0.0
            origin_time = inner.get('origin_time') or ''
            shock_time = timezone_utils.jst_to_display(origin_time) if origin_time else ''
            organization = self.get_organization_name()
            return {
                'type': 'warning',
                'source_type': 'nied',
                'organization': organization,
                'place_name': place or '未知',
                'magnitude': mag,
                'latitude': _safe_float(inner.get('latitude')),
                'longitude': _safe_float(inner.get('longitude')),
                'depth': depth,
                'shock_time': shock_time,
                'event_id': inner.get('report_id') or origin_time or '',
                'raw_data': data,
            }
        except Exception as e:
            logger.debug(f"[NIED] 解析跳过: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get('type', 'warning')
