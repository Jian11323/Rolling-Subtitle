#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KMA 韩国气象厅网页地震目录 HTTP 适配器。"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils


class KmaHttpAdapter(BaseAdapter):
    """解析 KMA HTML 表格，取最新一条。"""

    response_format = "text"
    fetch_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; EarthquakeScroller/1.0)",
    }
    fetch_timeout = 25

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        html = raw_data if isinstance(raw_data, str) else str(raw_data or "")
        tds = re.findall(r"<td[^>]*>(.*?)</td>", html, re.S | re.I)
        cells = [re.sub(r"<[^>]+>", "", t).strip() for t in tds]
        i = 0
        while i + 6 < len(cells):
            row_no = cells[i]
            if not re.fullmatch(r"\d+", row_no):
                i += 1
                continue
            time_s = cells[i + 1]
            mag_s = cells[i + 2]
            depth_s = cells[i + 3]
            lat_s = cells[i + 5]
            lon_s = cells[i + 6]
            if not re.match(r"\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}", time_s):
                i += 1
                continue
            try:
                mag = float(mag_s)
                if mag <= 0:
                    i += 10
                    continue
                shock_time = timezone_utils.local_tz_to_display(
                    time_s,
                    "Asia/Seoul",
                    formats=["%Y/%m/%d %H:%M:%S"],
                )
                lat = float(re.sub(r"[^\d.\-]", "", lat_s.split()[0]))
                lon = float(re.sub(r"[^\d.\-]", "", lon_s.split()[0]))
                if "S" in lat_s.upper():
                    lat = -lat
                if "W" in lon_s.upper():
                    lon = -lon
                depth = (
                    float(depth_s)
                    if depth_s not in ("-", "", None) and re.match(r"^-?\d", depth_s)
                    else 0.0
                )
                eid = f"kma_{time_s.replace('/', '').replace(':', '').replace(' ', '')}"
                return {
                    "type": "report",
                    "source_type": "kma",
                    "place_name": "韩国附近",
                    "shock_time": shock_time,
                    "magnitude": mag,
                    "latitude": lat,
                    "longitude": lon,
                    "depth": depth,
                    "organization": self.get_organization_name(),
                    "event_id": eid,
                    "raw_data": {
                        "time": time_s,
                        "mag": mag,
                        "lat": lat,
                        "lon": lon,
                        "depth": depth,
                    },
                    "fanstudio": False,
                    "whews": False,
                }
            except (ValueError, TypeError, IndexError):
                pass
            i += 10
        return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "report")
