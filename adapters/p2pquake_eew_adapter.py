#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2PQuake 紧急地震速报（code 556）适配器
与 /v2/history?codes=556 及 WebSocket 推送格式一致。
"""

import json
from typing import Any, Dict, List, Optional

from .base_adapter import BaseAdapter
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger
from utils import timezone_utils
from utils.jma_shindo import p2pquake_scale_to_shindo_text

logger = get_logger()


class P2PQuakeEEWAdapter(BaseAdapter):
    """P2PQuake 日本气象厅紧急地震速报（code 556）"""

    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)

    def parse_single_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            if not isinstance(item, dict):
                return None
            if item.get("code") is not None and int(item.get("code")) != 556:
                return None
            if item.get("cancelled") is True:
                return self._parse_cancel(item)

            earthquake = item.get("earthquake") or {}
            hypocenter = earthquake.get("hypocenter") or {}
            if not hypocenter and not earthquake:
                return None

            place_name = (
                str(hypocenter.get("name") or hypocenter.get("reduceName") or "").strip()
            )
            magnitude = self._safe_float(hypocenter.get("magnitude"), 0.0)
            if magnitude is not None and magnitude < 0:
                magnitude = 0.0
            latitude = self._safe_float(hypocenter.get("latitude"), 0.0)
            longitude = self._safe_float(hypocenter.get("longitude"), 0.0)
            depth_raw = self._safe_float(hypocenter.get("depth"), None)
            # depth=-1 表示不明；0 为ごく浅い，保留 0
            depth = 10.0 if depth_raw is None or depth_raw < 0 else depth_raw

            origin_raw = earthquake.get("originTime") or ""
            shock_time = (
                timezone_utils.jst_to_display(str(origin_raw)) if origin_raw else ""
            )

            issue = item.get("issue") or {}
            issue_time_raw = issue.get("time") or item.get("time") or ""
            issue_time = (
                timezone_utils.jst_to_display(str(issue_time_raw))
                if issue_time_raw
                else ""
            )

            serial = issue.get("serial")
            try:
                updates = int(serial) if serial is not None and str(serial).strip() else None
            except (TypeError, ValueError):
                updates = None

            event_id = str(issue.get("eventId") or item.get("id") or "").strip()
            if not event_id:
                event_id = f"p2pquake_eew:{place_name}:{origin_raw}"

            areas = item.get("areas") or []
            max_intensity = self._max_intensity_from_areas(areas)
            warn_areas = self._format_warning_areas(areas)

            organization = self.get_organization_name()
            result: Dict[str, Any] = {
                "type": "warning",
                "source_type": "p2pquake_eew",
                "magnitude": magnitude,
                "latitude": latitude,
                "longitude": longitude,
                "depth": depth,
                "place_name": place_name or "未知地区",
                "shock_time": shock_time or issue_time,
                "organization": organization,
                "event_id": event_id,
                "raw_data": item,
            }
            if updates is not None and updates > 0:
                result["updates"] = updates
            if max_intensity:
                result["epi_intensity"] = max_intensity
                result["epiIntensity"] = max_intensity
            if warn_areas:
                result["warning_areas"] = warn_areas
            return result
        except Exception as e:
            logger.debug(f"[P2PQuake EEW] 解析跳过: {e}")
            return None

    def _parse_cancel(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        issue = item.get("issue") or {}
        event_id = str(issue.get("eventId") or item.get("id") or "").strip()
        if not event_id:
            return None
        return {
            "type": "warning",
            "source_type": "p2pquake_eew",
            "cancel": True,
            "place_name": "紧急地震速报取消",
            "shock_time": timezone_utils.jst_to_display(str(issue.get("time") or "")),
            "organization": self.get_organization_name(),
            "event_id": event_id,
            "magnitude": 0,
            "depth": 0,
            "latitude": 0,
            "longitude": 0,
            "raw_data": item,
        }

    def _max_intensity_from_areas(self, areas: List[Any]) -> str:
        best_code = -1
        for a in areas or []:
            if not isinstance(a, dict):
                continue
            for key in ("scaleTo", "scaleFrom"):
                val = a.get(key)
                try:
                    code = int(val)
                except (TypeError, ValueError):
                    continue
                if code > best_code:
                    best_code = code
        if best_code < 0:
            return ""
        return p2pquake_scale_to_shindo_text(best_code)

    def _format_warning_areas(self, areas: List[Any]) -> str:
        bits: List[str] = []
        for a in (areas or [])[:12]:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name") or a.get("pref") or "").strip()
            if not name:
                continue
            scale_to = a.get("scaleTo")
            shindo = p2pquake_scale_to_shindo_text(scale_to) if scale_to is not None else ""
            if shindo:
                bits.append(f"{name}(震度{shindo})")
            else:
                bits.append(name)
        return "、".join(bits)

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if isinstance(data, dict):
                return self.parse_single_item(data)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("code") == 556:
                        parsed = self.parse_single_item(item)
                        if parsed:
                            return parsed
            return None
        except Exception as e:
            logger.debug(f"[P2PQuake EEW] parse 失败: {e}")
            return None

    def _safe_float(self, value: Any, default: Optional[float] = 0.0) -> Optional[float]:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "warning")
