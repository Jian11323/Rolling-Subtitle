#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenQuakeAPI 辅助数据源适配器
文档: https://docs.aloys23.link/docs/openquake/overview
WSS: wss://api.aloys23.link/ws/all（聚合推送）

支持：
- gq：GlobalQuake 全球地震
- nmefc：NMEFC 海啸预警
- nmefc-wave：NMEFC 海浪警报
- nmefc-surge：NMEFC 风暴潮警报
- cma：中国气象局气象预警
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger
from utils import timezone_utils
from config import Config

logger = get_logger()

# 直接参与轮播/缓冲识别的 source_type
OPENQUAKE_DIRECT_SOURCE_TYPES = frozenset({
    "openquake_gq",
    "openquake_nmefc",
    "openquake_nmefc_wave",
    "openquake_nmefc_surge",
    "openquake_cma",
})

# API source → message_config 解析开关
_SOURCE_PARSE_FLAGS = {
    "gq": "openquake_parse_gq",
    "nmefc": "openquake_parse_nmefc",
    "nmefc-wave": "openquake_parse_nmefc_wave",
    "nmefc-surge": "openquake_parse_nmefc_surge",
    "cma": "openquake_parse_cma",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转 float。"""
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _strip_html(text: Any) -> str:
    """去掉 HTML 标签并压缩空白。"""
    s = str(text or "")
    if not s:
        return ""
    s = _HTML_TAG_RE.sub("", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _ms_to_display(ms: Any) -> str:
    """毫秒时间戳 → 显示时区字符串。"""
    try:
        if ms is None or ms == "":
            return ""
        return timezone_utils.timestamp_to_display(int(ms))
    except (TypeError, ValueError):
        return ""


class OpenQuakeApiAdapter(BaseAdapter):
    """OpenQuakeAPI WebSocket 适配器（/ws/all 聚合）。"""

    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 RealtimeEvent JSON；忽略 station/status/cluster 等噪声。"""
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
            if source == "nmefc" and event_type == "tsunami":
                return self._parse_nmefc_tsunami(payload, data)
            if source == "nmefc-wave" and event_type == "alert":
                return self._parse_marine_alert(payload, data, kind="wave")
            if source == "nmefc-surge" and event_type == "alert":
                return self._parse_marine_alert(payload, data, kind="surge")
            if source == "cma" and event_type == "weather":
                return self._parse_cma(payload, data)
            return None
        except json.JSONDecodeError as e:
            logger.debug(f"[OpenQuakeAPI] JSON 解析失败: {e}")
            return None
        except Exception as e:
            logger.debug(f"[OpenQuakeAPI] 解析跳过: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型。"""
        return data.get("type", "report")

    @staticmethod
    def _gq_shock_time(payload: Dict[str, Any], raw: Dict[str, Any]) -> str:
        """GQ 发震/事件时间 → 显示时区（originTimeIso / originTimeMs / timestampMs）。"""
        iso = payload.get("originTimeIso")
        if iso:
            # ISO 8601（含 Z）统一走 flexible，与其它 OpenQuake 子源一致
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
                "source_type": "openquake_gq",
                "openquake": True,
                "cancel": True,
                "magnitude": 0.0,
                "latitude": 0.0,
                "longitude": 0.0,
                "depth": 0.0,
                "place_name": "GlobalQuake地震取消",
                "shock_time": self._gq_shock_time(payload, raw),
                "organization": "GlobalQuake地震预警",
                "event_id": f"openquake_gq:{event_id}",
                "raw_data": raw,
            }

        if action not in ("update", "archived", ""):
            return None

        magnitude = _safe_float(payload.get("magnitude"), 0.0)
        mc = Config().message_config
        min_mag = float(getattr(mc, "openquake_gq_min_magnitude", 0.0) or 0.0)
        if min_mag > 0 and magnitude < min_mag:
            return None

        place = str(payload.get("region") or "").strip() or "未知区域"
        intensity = str(payload.get("intensity") or "").strip()
        shock_time = self._gq_shock_time(payload, raw)

        result: Dict[str, Any] = {
            "type": "warning",
            "source_type": "openquake_gq",
            "openquake": True,
            "magnitude": magnitude,
            "latitude": _safe_float(payload.get("latitude"), 0.0),
            "longitude": _safe_float(payload.get("longitude"), 0.0),
            "depth": _safe_float(payload.get("depth"), 0.0),
            "place_name": place,
            "shock_time": shock_time,
            "organization": "GlobalQuake地震预警",
            "event_id": f"openquake_gq:{event_id}",
            "updates": int(_safe_float(payload.get("revisionId"), 0)),
            "raw_data": raw,
        }
        if intensity:
            result["intensity"] = intensity
            result["mmi"] = intensity
        return result

    def _parse_nmefc_tsunami(
        self, payload: Dict[str, Any], raw: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """NMEFC 海啸预警 → report + is_tsunami。"""
        title = str(payload.get("title") or "海啸预警").strip()
        level = str(payload.get("level") or "").strip()
        location = str(payload.get("location") or "").strip()
        code = str(payload.get("code") or payload.get("id") or "").strip()
        issue_time = str(payload.get("issueTime") or "").strip()
        shock_time = ""
        if issue_time:
            shock_time = timezone_utils.flexible_time_to_display(issue_time) or issue_time
        if not shock_time:
            shock_time = _ms_to_display(raw.get("timestampMs"))

        org_unit = str(payload.get("orgUnit") or "国家海洋环境预报中心").strip()
        organization = f"{org_unit}海啸预警"
        if level:
            organization = f"{organization}（{level}）"

        parts = []
        if title:
            parts.append(title)
        if location:
            parts.append(location)
        assessment = _strip_html(payload.get("assessment"))
        eq_desc = _strip_html(payload.get("earthquakeDescription"))
        follow = _strip_html(payload.get("followUpNote"))
        if eq_desc:
            parts.append(eq_desc)
        if assessment:
            parts.append(assessment)
        if follow:
            parts.append(follow)
        water_levels = payload.get("waterLevels")
        if isinstance(water_levels, list) and water_levels:
            wl_bits = []
            for item in water_levels[:6]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("stationName") or "").strip()
                amp = str(item.get("maxAmplitudeCm") or "").strip()
                if name and amp:
                    wl_bits.append(f"{name}最大振幅{amp}厘米")
                elif name:
                    wl_bits.append(name)
            if wl_bits:
                parts.append("水位观测：" + "；".join(wl_bits))
        remarks = "。".join(p for p in parts if p)

        return {
            "type": "report",
            "is_tsunami": True,
            "source_type": "openquake_nmefc",
            "openquake": True,
            "magnitude": _safe_float(payload.get("magnitude"), 0.0),
            "latitude": _safe_float(payload.get("latitude"), 0.0),
            "longitude": _safe_float(payload.get("longitude"), 0.0),
            "depth": _safe_float(payload.get("depthKm"), 0.0),
            "place_name": location or title,
            "shock_time": shock_time,
            "organization": organization,
            "event_id": f"openquake_nmefc:{code or title}:{issue_time}",
            "tsunami_warning_level": level,
            "tsunami_warning_title": title,
            "tsunami_remarks": remarks,
            "raw_data": raw,
        }

    def _parse_marine_alert(
        self, payload: Dict[str, Any], raw: Dict[str, Any], kind: str
    ) -> Optional[Dict[str, Any]]:
        """海浪 / 风暴潮警报 → weather 类型展示。"""
        title = str(payload.get("title") or "").strip()
        subtitle = str(payload.get("subtitle") or "").strip()
        level = str(payload.get("level") or "").strip()
        warn_type = str(payload.get("warnType") or ("海浪" if kind == "wave" else "风暴潮")).strip()
        description = _strip_html(payload.get("description"))
        update_date = str(payload.get("updateDate") or "").strip()
        alarm_date = str(payload.get("alarmDate") or "").strip()
        code = str(payload.get("code") or payload.get("id") or "").strip()
        org_unit = str(
            payload.get("orgUnit") or payload.get("author") or "国家海洋环境预报中心"
        ).strip()

        if not title:
            title = f"{warn_type}{level}警报" if level else f"{warn_type}警报"
        if subtitle and subtitle not in title:
            display_title = f"{title}：{subtitle}"
        else:
            display_title = title

        shock_time = ""
        if update_date:
            shock_time = timezone_utils.flexible_time_to_display(update_date) or update_date
        elif alarm_date:
            shock_time = timezone_utils.flexible_time_to_display(alarm_date) or alarm_date
        if not shock_time:
            shock_time = _ms_to_display(raw.get("timestampMs"))

        source_type = (
            "openquake_nmefc_wave" if kind == "wave" else "openquake_nmefc_surge"
        )
        return {
            "type": "weather",
            "source_type": source_type,
            "openquake": True,
            "magnitude": 0,
            "latitude": 0.0,
            "longitude": 0.0,
            "depth": 0,
            "place_name": display_title,
            "title": display_title,
            "description": description,
            "shock_time": shock_time,
            "organization": org_unit,
            "warning_type": warn_type,
            "weather_level": level,
            "event_id": f"{source_type}:{code or display_title}:{update_date or alarm_date}",
            "raw_data": raw,
        }

    def _parse_cma(
        self, payload: Dict[str, Any], raw: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """中国气象局气象预警。"""
        headline = str(payload.get("headline") or payload.get("title") or "").strip()
        title = str(payload.get("title") or headline).strip()
        description = _strip_html(payload.get("description"))
        effective = str(payload.get("effective") or "").strip()
        event_id = str(payload.get("id") or "").strip()
        if not headline and not title and not description:
            return None

        shock_time = ""
        if effective:
            # 文档示例：2026/07/29 12:45
            shock_time = timezone_utils.flexible_time_to_display(
                effective.replace("/", "-")
            ) or effective
        if not shock_time:
            shock_time = _ms_to_display(raw.get("timestampMs"))

        if not event_id:
            event_id = f"{title}_{effective}"

        return {
            "type": "weather",
            "source_type": "openquake_cma",
            "openquake": True,
            "magnitude": 0,
            "latitude": _safe_float(payload.get("latitude"), 0.0),
            "longitude": _safe_float(payload.get("longitude"), 0.0),
            "depth": 0,
            "place_name": headline or title,
            "title": headline or title,
            "description": description,
            "shock_time": shock_time,
            "organization": "中国气象局",
            "warning_type": str(payload.get("type") or "").strip(),
            "event_id": f"openquake_cma:{event_id}",
            "raw_data": raw,
        }
