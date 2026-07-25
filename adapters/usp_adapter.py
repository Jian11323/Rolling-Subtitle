#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""USP（巴西圣保罗大学）FDSN QuakeML 地震速报适配器。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from .fdsn_quakeml import parse_quakeml_latest_event


class UspAdapter(BaseAdapter):
    """解析 USP QuakeML，取最新一条事件。"""

    response_format = "text"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 USP QuakeML XML。"""
        return parse_quakeml_latest_event(
            raw_data,
            source_type="usp",
            organization=self.get_organization_name(),
        )

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（USP 为速报）。"""
        return data.get("type", "report")
