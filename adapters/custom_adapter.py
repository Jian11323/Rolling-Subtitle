#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义数据源适配器
支持两种约定 JSON 格式：平铺格式与 Data 嵌套格式
兼容 beecld mix_all_one_live 等非标准字段（HTML 残留、id 内嵌发震时间、零坐标等）
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SHOCK_IN_TEXT_RE = re.compile(
    r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})[-\sT]+(\d{1,2}):(\d{2}):(\d{2})"
)


def _strip_html(text: str) -> str:
    """去掉字段中残留的 HTML 标签与首尾空白。"""
    return _HTML_TAG_RE.sub("", text or "").strip()


def _normalize_shock_time_raw(raw: str) -> str:
    """将 2026.07.03-08:22:46 等混合格式规范为 YYYY-MM-DD HH:MM:SS。"""
    s = _strip_html(raw)
    if not s:
        return ""
    m = _SHOCK_IN_TEXT_RE.search(s)
    if m:
        y, mo, d, h, mi, sec = m.groups()
        return (
            f"{y}-{int(mo):02d}-{int(d):02d} "
            f"{int(h):02d}:{mi}:{sec}"
        )
    return s


def _parse_shock_time(data: Dict[str, Any]) -> str:
    """从 shockTime / id（EE_ 前缀）/ reportTime 解析发震时间。"""
    for key in ("shockTime", "shock_time"):
        raw = str(data.get(key) or "").strip()
        if raw:
            normalized = _normalize_shock_time_raw(raw)
            return timezone_utils.cst_to_display(normalized) if normalized else ""

    id_raw = _strip_html(str(data.get("id") or ""))
    if id_raw:
        normalized = _normalize_shock_time_raw(id_raw)
        if normalized:
            return timezone_utils.cst_to_display(normalized)

    report_raw = _strip_html(str(data.get("reportTime") or ""))
    if report_raw:
        return timezone_utils.cst_to_display(report_raw)
    return ""


def _parse_updates(data: Dict[str, Any]) -> Optional[int]:
    """解析报数：updates / reportNum。"""
    for key in ("updates", "reportNum"):
        val = data.get(key)
        if val is None:
            continue
        try:
            n = int(val)
            if n > 0:
                return n
        except (TypeError, ValueError):
            continue
    return None


def _parse_organization(data: Dict[str, Any]) -> str:
    """机构名：source / sourceName，默认「自定义」。"""
    for key in ("source", "sourceName"):
        name = _strip_html(str(data.get(key) or ""))
        if name:
            return name
    return "自定义"


def _build_event_id(
    data: Dict[str, Any],
    place_name: str,
    shock_time: str,
) -> str:
    """
    生成稳定 event_id。
    beecld 等源的 id 可能含 HTML 或仅 ``EE_ 发震时间``；无效时用地名+发震时间。
    """
    raw_id = _strip_html(str(data.get("id") or data.get("eventId") or ""))
    if raw_id and "<" not in raw_id and len(raw_id) >= 4:
        if not raw_id.upper().startswith("EE_"):
            return raw_id
        if shock_time:
            return f"custom:{place_name}:{shock_time}"
    if place_name and shock_time:
        return f"custom:{place_name}:{shock_time}"
    return raw_id


class CustomAdapter(BaseAdapter):
    """自定义数据源适配器，解析约定格式的预警 JSON"""

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """
        解析原始数据。支持格式 A（平铺）或格式 B（Data 嵌套）。
        若为数组则取第一条解析。
        """
        if raw_data is None:
            return None
        data = raw_data
        if isinstance(data, list):
            if not data:
                return None
            data = data[0]
        if not isinstance(data, dict):
            return None
        if "Data" in data and isinstance(data["Data"], dict):
            return self._parse_record(data["Data"], raw_data=data)
        return self._parse_record(data, raw_data=data)

    def _parse_record(
        self,
        data: Dict[str, Any],
        *,
        raw_data: Any,
    ) -> Optional[Dict[str, Any]]:
        """解析单条预警记录（平铺或 Data 内层）。"""
        place_name = _strip_html(str(data.get("placeName") or ""))
        if not place_name:
            return None

        shock_time = _parse_shock_time(data)
        magnitude = self._safe_float(data.get("magnitude", 0))
        latitude = self._safe_float(data.get("latitude", 0))
        longitude = self._safe_float(data.get("longitude", 0))
        depth = self._safe_float(data.get("depth", 0))
        updates = _parse_updates(data)
        organization = _parse_organization(data)
        event_id = _build_event_id(data, place_name, shock_time)

        result: Dict[str, Any] = {
            "type": "warning",
            "place_name": place_name,
            "magnitude": magnitude,
            "latitude": latitude,
            "longitude": longitude,
            "depth": depth,
            "shock_time": shock_time,
            "organization": organization,
            "source_type": "custom",
            "updates": updates,
            "raw_data": raw_data,
        }
        if event_id:
            result["event_id"] = event_id

        intensity = data.get("intensity")
        if intensity is not None and str(intensity).strip():
            try:
                result["epiIntensity"] = float(intensity)
            except (TypeError, ValueError):
                pass

        return result

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """安全转换为浮点数。"""
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（自定义源默认为预警）。"""
        return data.get("type", "warning")
