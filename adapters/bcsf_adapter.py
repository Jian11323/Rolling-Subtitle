#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BCSF FDSN text 地震速报适配器。"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from .fdsn_text import latest_as_report, parse_fdsn_text_events


def clean_bcsf_place_name(place_name: str) -> str:
    """从 BCSF EventLocationName 提取城市名。"""
    if not place_name or not isinstance(place_name, str):
        return "未知地区"
    s = place_name.strip()
    if not s:
        return "未知地区"
    s = re.sub(
        r"^(?:Earthquake|Event|Quarry blast)\s+of\s+magnitude\s+[\d.]+,?\s*",
        "",
        s,
        flags=re.I,
    )
    m = re.search(r"\bnear\s+(?:of\s+)?(.+)$", s, flags=re.I)
    if m:
        s = m.group(1).strip()
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
    s = re.sub(r",?\s*\([^)]*\)", "", s).strip()
    return s or place_name.strip() or "未知地区"


class BcsfAdapter(BaseAdapter):
    """解析 BCSF FDSN text，取最新一条。"""

    response_format = "text"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        text = raw_data if isinstance(raw_data, str) else str(raw_data or "")
        events = parse_fdsn_text_events(text)
        return latest_as_report(
            events,
            source_type="bcsf",
            organization=self.get_organization_name(),
            place_cleaner=clean_bcsf_place_name,
        )

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "report")
