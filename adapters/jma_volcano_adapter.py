#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JMA 火山情报数据源适配器
WebSocket: wss://sismotide.top/jma-long
报文类型: initial（初报）、update（更新报）
"""

import json
from typing import Dict, Any, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .base_adapter import BaseAdapter
from utils.logger import get_logger
from utils import timezone_utils

logger = get_logger()


class JmaVolcanoAdapter(BaseAdapter):
    """JMA 火山情报 WebSocket 适配器"""

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
            msg_type = data.get("type")
            if msg_type not in ("initial", "update"):
                return None
            inner = data.get("data")
            if not isinstance(inner, dict):
                return None
            payload = inner.get("Data")
            if not isinstance(payload, dict):
                return None
            raw_id = payload.get("id", "")
            title = payload.get("title", "") or ""
            time_str = payload.get("time", "") or ""
            name = payload.get("name", "") or ""
            volcano = payload.get("volcano", "") or ""
            description = payload.get("description", "") or ""
            # 时间为 UTC ISO（如 2026-03-08T11:00:00Z）
            shock_time = timezone_utils.utc_to_display(time_str) if time_str else ""
            organization = self.get_organization_name()
            return {
                "type": "volcano",
                "source_type": "jma_volcano",
                "report_type": msg_type,  # "initial" 或 "update"
                "event_id": raw_id,
                "title": title,
                "description": description,
                "organization": organization,
                "shock_time": shock_time,
                "name": name,
                "volcano": volcano,
                "raw_data": data,
            }
        except Exception as e:
            logger.debug(f"[JMA Volcano] 解析跳过: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "volcano")
