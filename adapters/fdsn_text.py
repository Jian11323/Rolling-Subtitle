#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FDSN text 事件列表解析（BCSF / NRCAN 等）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from utils import timezone_utils


def parse_fdsn_text_events(text: str) -> List[Dict[str, Any]]:
    """
    解析标准 FDSN text（>=13 列）：
    EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|ContributorID|MagType|Magnitude|MagAuthor|EventLocationName|…
    """
    events: List[Dict[str, Any]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 13:
            continue
        try:
            mag = float(parts[10]) if parts[10] else 0.0
            if mag <= 0:
                continue
            shock = timezone_utils.utc_to_display(str(parts[1] or "").strip())
            events.append(
                {
                    "id": parts[0],
                    "shock_time": shock,
                    "latitude": float(parts[2]),
                    "longitude": float(parts[3]),
                    "depth": float(parts[4]) if parts[4] else 0.0,
                    "magnitude": mag,
                    "place_name": (parts[12] or "未知地区").strip() or "未知地区",
                }
            )
        except (ValueError, TypeError, IndexError):
            continue
    return events


def parse_nrcan_text_events(text: str) -> List[Dict[str, Any]]:
    """解析 NRCAN 8 列 text：EventID|Time|Lat|Lon|Depth|MagType|Mag|Location。"""
    events: List[Dict[str, Any]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        try:
            place = (parts[7] or "").split("/", 1)[0].strip() or "未知地区"
            place_l = place.lower()
            if "blast" in place_l or "industry-related" in place_l:
                continue
            mag = float(parts[6]) if parts[6] else 0.0
            if mag <= 0:
                continue
            events.append(
                {
                    "id": parts[0],
                    "shock_time": timezone_utils.utc_to_display(str(parts[1] or "").strip()),
                    "latitude": float(parts[2]),
                    "longitude": float(parts[3]),
                    "depth": float(parts[4]) if parts[4] else 0.0,
                    "magnitude": mag,
                    "place_name": place,
                }
            )
        except (ValueError, TypeError, IndexError):
            continue
    return events


def latest_as_report(
    events: List[Dict[str, Any]],
    *,
    source_type: str,
    organization: str,
    place_cleaner=None,
) -> Optional[Dict[str, Any]]:
    """取列表首条（通常已按时间新→旧）转为标准速报。"""
    if not events:
        return None
    ev = events[0]
    place = str(ev.get("place_name") or "未知地区")
    if callable(place_cleaner):
        place = place_cleaner(place) or place
    return {
        "type": "report",
        "source_type": source_type,
        "place_name": place,
        "shock_time": ev.get("shock_time") or "",
        "magnitude": float(ev.get("magnitude") or 0),
        "latitude": float(ev.get("latitude") or 0),
        "longitude": float(ev.get("longitude") or 0),
        "depth": float(ev.get("depth") or 0),
        "organization": organization,
        "event_id": str(ev.get("id") or ""),
        "raw_data": ev,
        "fanstudio": False,
        "whews": False,
    }
