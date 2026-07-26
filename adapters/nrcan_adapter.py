#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NRCAN FDSN text 地震速报适配器。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from .fdsn_text import latest_as_report, parse_nrcan_text_events


class NrcanAdapter(BaseAdapter):
    """解析加拿大自然资源部 FDSN text，取最新一条。"""

    response_format = "text"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        text = raw_data if isinstance(raw_data, str) else str(raw_data or "")
        events = parse_nrcan_text_events(text)
        return latest_as_report(
            events,
            source_type="nrcan",
            organization=self.get_organization_name(),
        )

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "report")
