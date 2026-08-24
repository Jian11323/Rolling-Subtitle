#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FDSN QuakeML 解析工具（GFZ / USP 等共用）。"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

from utils import timezone_utils

QUAKEML_NS = {
    "q": "http://quakeml.org/xmlns/quakeml/1.2",
    "qml": "http://quakeml.org/xmlns/bed/1.2",
}


def _local(tag: str) -> str:
    """去掉 XML Clark 记号中的命名空间，仅保留本地名。"""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _find_text(elem: Optional[ET.Element], *path_names: str) -> str:
    """按本地标签名深度优先查找文本。"""
    if elem is None:
        return ""
    if not path_names:
        return (elem.text or "").strip()
    target = path_names[0]
    for child in list(elem):
        if _local(child.tag) == target:
            return _find_text(child, *path_names[1:])
    return ""


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转换为浮点数。"""
    try:
        if value is None or value == "":
            return default
        s = str(value).strip().lower().replace("km", "").strip()
        m = re.match(r"^([-+]?\d+(?:\.\d+)?)", s)
        if m:
            return float(m.group(1))
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_quakeml_latest_event(
    raw_xml: Any,
    source_type: str,
    organization: str,
) -> Optional[Dict[str, Any]]:
    """
    解析 QuakeML，取第一个 event 为最新速报。

    Args:
        raw_xml: XML 字符串或 bytes
        source_type: 内部 source_type
        organization: 机构显示名
    """
    if isinstance(raw_xml, (bytes, bytearray)):
        text = bytes(raw_xml).decode("utf-8", errors="replace")
    elif isinstance(raw_xml, str):
        text = raw_xml
    else:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None

    event = None
    for elem in root.iter():
        if _local(elem.tag) == "event":
            event = elem
            break
    if event is None:
        return None

    place_name = ""
    for desc in event.iter():
        if _local(desc.tag) != "description":
            continue
        dtype = _find_text(desc, "type").lower()
        dtext = _find_text(desc, "text")
        if dtext and (not place_name or "region" in dtype or dtype == ""):
            place_name = dtext
            if "region" in dtype:
                break

    mag = 0.0
    for mag_el in event.iter():
        if _local(mag_el.tag) != "magnitude":
            continue
        mag = _safe_float(_find_text(mag_el, "mag", "value"), 0.0)
        if mag:
            break

    lat = lon = 0.0
    depth = 10.0
    shock_time = ""
    origin_id = ""
    for origin in event.iter():
        if _local(origin.tag) != "origin":
            continue
        origin_id = (origin.attrib.get("publicID") or "").strip()
        lat = _safe_float(_find_text(origin, "latitude", "value"), 0.0)
        lon = _safe_float(_find_text(origin, "longitude", "value"), 0.0)
        # QuakeML 深度单位为米
        depth_m = _safe_float(_find_text(origin, "depth", "value"), 10000.0)
        depth = depth_m / 1000.0 if depth_m > 100 else depth_m
        if depth <= 0:
            depth = 10.0
        t_raw = _find_text(origin, "time", "value")
        if t_raw:
            shock_time = timezone_utils.utc_to_display(t_raw)
        break

    if not place_name and not shock_time:
        return None

    event_id = (event.attrib.get("publicID") or "").strip() or origin_id
    if not event_id:
        event_id = f"{source_type}_{shock_time}_{lat}_{lon}"

    return {
        "type": "report",
        "source_type": source_type,
        "place_name": place_name or "未知地区",
        "shock_time": shock_time,
        "magnitude": round(mag, 1) if mag else 0.0,
        "latitude": lat,
        "longitude": lon,
        "depth": depth,
        "organization": organization,
        "event_id": event_id,
        "raw_data": {"quakeml_publicID": event_id},
    }
