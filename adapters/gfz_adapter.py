#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GFZ Geofon FDSN QuakeML 地震速报适配器。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from .fdsn_quakeml import parse_quakeml_latest_event


class GfzAdapter(BaseAdapter):
    """解析 GFZ QuakeML，取最新一条事件。"""

    response_format = "text"
    # 部分环境对 geofon.gfz.de 证书链校验失败，允许跳过 SSL 校验
    ssl_verify = False

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 GFZ QuakeML XML。"""
        return parse_quakeml_latest_event(
            raw_data,
            source_type="gfz",
            organization=self.get_organization_name(),
        )

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（GFZ 为速报）。"""
        return data.get("type", "report")
