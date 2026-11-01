#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PancakesAPI 辅助数据源适配器
文档: https://wiki.aloys23.link/wiki/PancakesAPI
WSS: wss://api.aloys23.link/api/v1/alert/ws/all（聚合推送）

当前接入：
- gq：GlobalQuake 全球地震
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger
from utils import timezone_utils
from config import Config

logger = get_logger()

# 直接参与轮播/缓冲识别的 source_type
PANCAKES_DIRECT_SOURCE_TYPES = frozenset({
    "pancakes_gq",
})

# API source → message_config 解析开关
_SOURCE_PARSE_FLAGS = {
    "gq": "pancakes_parse_gq",
}

def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转 float。"""
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _ms_to_display(ms: Any) -> str:
    """毫秒时间戳 → 显示时区字符串。"""
    try:
        if ms is None or ms == "":
            return ""
        return timezone_utils.timestamp_to_display(int(ms))
    except (TypeError, ValueError):
        return ""


class PancakesApiAdapter(BaseAdapter):
    """PancakesAPI WebSocket 适配器（/api/v1/alert/ws/all 聚合）。"""

    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 RealtimeEvent JSON；忽略 station/status/cluster；仅处理 gq。"""
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if not isinstance(data, dict):
                return None

            source = str(data.get("source") or "").strip().lower()
            event_type = str(data.get("type") or "").strip().lower()
            action = str(data.get("action") or "").strip().lower()
            payload = data.get("payload")
            if not isinstance(payload, dict):
                payload = {}

            # 握手/台站/状态等不展示
            if event_type in ("station", "status", "cluster"):
                return None
            if action in ("connected", "disconnected", "info", "intensity", "remove"):
                return None

            mc = Config().message_config
            flag = _SOURCE_PARSE_FLAGS.get(source)
            if flag and not getattr(mc, flag, True):
                return None

            if source == "gq" and event_type == "earthquake":
                return self._parse_gq(payload, action, data)
            return None
        except json.JSONDecodeError as e:
            logger.debug(f"[PancakesAPI] JSON 解析失败: {e}")
            return None
        except Exception as e:
            logger.debug(f"[PancakesAPI] 解析跳过: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型。"""
        return data.get("type", "report")

    @staticmethod
    def _gq_shock_time(payload: Dict[str, Any], raw: Dict[str, Any]) -> str:
        """GQ 发震/事件时间 → 显示时区（originTimeIso / originTimeMs / timestampMs）。"""
        iso = payload.get("originTimeIso")
        if iso:
            shock = timezone_utils.flexible_time_to_display(str(iso))
            if shock:
                return shock
            shock = timezone_utils.utc_to_display(str(iso))
            if shock:
                return shock
        shock = _ms_to_display(payload.get("originTimeMs"))
        if shock:
            return shock
        return _ms_to_display(raw.get("timestampMs"))

    def _parse_gq(
        self, payload: Dict[str, Any], action: str, raw: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """GlobalQuake：update/archived 出预警；cancelled 出取消报（cancel=True）。"""
        event_id = str(payload.get("id") or "").strip()
        if not event_id:
            return None

        if action == "cancelled":
            return {
                "type": "warning",
                "source_type": "pancakes_gq",
                "pancakes": True,
                "cancel": True,
                "magnitude": 0.0,
                "latitude": 0.0,
                "longitude": 0.0,
                "depth": 0.0,
                "place_name": "GlobalQuake地震取消",
                "shock_time": self._gq_shock_time(payload, raw),
                "organization": "GlobalQuake地震预警",
                "event_id": f"pancakes_gq:{event_id}",
                "raw_data": raw,
            }

        if action not in ("update", "archived", ""):
            return None

        magnitude = _safe_float(payload.get("magnitude"), 0.0)
        mc = Config().message_config
        min_mag = float(getattr(mc, "pancakes_gq_min_magnitude", 0.0) or 0.0)
        if min_mag > 0 and magnitude < min_mag:
            return None

        place = str(payload.get("region") or "").strip() or "未知区域"
        intensity = str(payload.get("intensity") or "").strip()
        shock_time = self._gq_shock_time(payload, raw)

        result: Dict[str, Any] = {
            "type": "warning",
            "source_type": "pancakes_gq",
            "pancakes": True,
            "magnitude": magnitude,
            "latitude": _safe_float(payload.get("latitude"), 0.0),
            "longitude": _safe_float(payload.get("longitude"), 0.0),
            "depth": _safe_float(payload.get("depth"), 0.0),
            "place_name": place,
            "shock_time": shock_time,
            "organization": "GlobalQuake地震预警",
            "event_id": f"pancakes_gq:{event_id}",
            "updates": int(_safe_float(payload.get("revisionId"), 0)),
            "raw_data": raw,
        }
        if intensity:
            result["intensity"] = intensity
            result["mmi"] = intensity
        return result
