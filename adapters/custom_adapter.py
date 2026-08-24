#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义数据源适配器
支持两种约定 JSON 格式：平铺格式与 Data 嵌套格式
兼容 beecld mix_all_one_live 等非标准字段（HTML 残留、id 内嵌发震时间、零坐标等）
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

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


def _epoch_ms_to_display(ms: int) -> str:
    """毫秒时间戳转展示时间（默认东八区）。"""
    try:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone(timedelta(hours=8)))
        return timezone_utils.cst_to_display(dt.strftime("%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError, OSError, OverflowError):
        return ""


def _parse_shock_time(data: Dict[str, Any]) -> str:
    """从 originTime / shockTime / id（EE_ 前缀）/ reportTime 解析发震时间。"""
    for key in ("originTime", "shockTime", "shock_time"):
        raw = data.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)) or (
            isinstance(raw, str) and raw.strip().isdigit()
        ):
            text = _epoch_ms_to_display(int(raw))
            if text:
                return text
        raw_str = str(raw).strip()
        if raw_str:
            normalized = _normalize_shock_time_raw(raw_str)
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
    """机构名：source / sourceName / 嵌套 source 对象，默认「自定义」。"""
    nested = data.get("source")
    if isinstance(nested, dict):
        for key in ("name", "sourceName", "title"):
            name = _strip_html(str(nested.get(key) or ""))
            if name:
                return name
    for key in ("source", "sourceName"):
        val = data.get(key)
        if isinstance(val, dict):
            continue
        name = _strip_html(str(val or ""))
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
    raw_id = _strip_html(
        str(data.get("id") or data.get("eventId") or data.get("eventID") or "")
    )
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

    def parse_all(self, raw_data: Any) -> List[Dict[str, Any]]:
        """解析单条或多条记录（数组时返回全部有效项）。"""
        if raw_data is None:
            return []
        if isinstance(raw_data, list):
            results: List[Dict[str, Any]] = []
            for item in raw_data:
                if not isinstance(item, dict):
                    continue
                if "Data" in item and isinstance(item.get("Data"), dict):
                    one = self._parse_record(item["Data"], raw_data=item)
                else:
                    one = self._parse_record(item, raw_data=item)
                if one:
                    results.append(one)
            return results
        if isinstance(raw_data, dict):
            if "Data" in raw_data and isinstance(raw_data.get("Data"), dict):
                one = self._parse_record(raw_data["Data"], raw_data=raw_data)
            else:
                one = self._parse_record(raw_data, raw_data=raw_data)
            return [one] if one else []
        return []

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """
        解析原始数据。支持格式 A（平铺）或格式 B（Data 嵌套）。
        若为数组则取第一条有效记录。
        """
        items = self.parse_all(raw_data)
        return items[0] if items else None

    def _parse_record(
        self,
        data: Dict[str, Any],
        *,
        raw_data: Any,
    ) -> Optional[Dict[str, Any]]:
        """解析单条预警记录（平铺或 Data 内层）。"""
        place_name = _strip_html(str(data.get("placeName") or ""))
        if not place_name:
            lat = self._safe_float(data.get("latitude"), default=None)
            lon = self._safe_float(data.get("longitude"), default=None)
            if lat is not None and lon is not None:
                place_name = f"{lat:.2f}°N, {lon:.2f}°E" if lat >= 0 else f"{abs(lat):.2f}°S, {lon:.2f}°E"
            else:
                return None

        shock_time = _parse_shock_time(data)
        magnitude = self._safe_float(data.get("magnitude", 0))
        latitude = self._safe_float(data.get("latitude", 0))
        longitude = self._safe_float(data.get("longitude", 0))
        depth = self._safe_float(data.get("depth", 0))
        updates = _parse_updates(data)
        organization = _parse_organization(data)
        event_id = _build_event_id(data, place_name, shock_time)
        org_lower = organization.lower()
        source_type = (
            "globalquake"
            if "globalquake" in org_lower or "地震预警" in organization
            else "custom"
        )

        result: Dict[str, Any] = {
            "type": "warning",
            "place_name": place_name,
            "magnitude": magnitude,
            "latitude": latitude,
            "longitude": longitude,
            "depth": depth,
            "shock_time": shock_time,
            "organization": organization,
            "source_type": source_type,
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

    def _safe_float(self, value: Any, default: Optional[float] = 0.0) -> Optional[float]:
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
