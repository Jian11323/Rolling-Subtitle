#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Early-est 地震预警适配器（HTML 表格解析）"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils
from utils.logger import get_logger

logger = get_logger()

GQ_POLY_POINTS = [
    [54.145, 121.31], [54.145, 151.25], [15.80, 151.25],
    [15.8, 96.33], [26.27, 96.33], [26.27, 72.5], [51.145, 72.5],
]
GQ_MAGNITUDE_BORDER = 1.0
EARLYEST_WINDOW_MIN = 60


def _is_in_process_area(lat: float, lon: float) -> bool:
    n = len(GQ_POLY_POINTS)
    is_inside = False
    j = n - 1
    for i in range(n):
        lat_i, lon_i = GQ_POLY_POINTS[i]
        lat_j, lon_j = GQ_POLY_POINTS[j]
        if ((lon_i > lon) != (lon_j > lon)) and (
            lat < (lat_j - lat_i) * (lon - lon_i) / (lon_j - lon_i + 1e-10) + lat_i
        ):
            is_inside = not is_inside
        j = i
    return is_inside


class EarlyEstAdapter(BaseAdapter):
    """解析 early-est.rm.ingv.it hypomessage.html 表格，取最新满足条件事件。"""

    response_format = "text"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        if raw_data is None:
            return None
        html = raw_data if isinstance(raw_data, str) else (
            raw_data.decode("utf-8", errors="replace") if isinstance(raw_data, bytes) else None
        )
        if not html:
            return None
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.warning("Early-est 解析需要 beautifulsoup4，请安装后重试")
            return None

        soup = BeautifulSoup(html, "html.parser")
        region_col_index = 30
        try:
            for tr in soup.select("tr"):
                cells = tr.find_all(["th", "td"])
                if not cells:
                    continue
                texts = [c.get_text(strip=True).lower() for c in cells]
                if any("region" in t for t in texts):
                    for idx, t in enumerate(texts):
                        if "region" in t:
                            region_col_index = idx
                            break
                    break
        except Exception:
            region_col_index = 30

        now_utc = datetime.now(timezone.utc)
        candidates: List[Dict[str, Any]] = []

        for row in soup.select("tr[align=right]"):
            link = row.find("a", target=True)
            if not link:
                continue
            eid = f"EARLY_{link.get('target', 'UNK')}"
            tds = row.find_all("td")
            min_cols = max(14, region_col_index + 1)
            if len(tds) < min_cols:
                continue
            try:
                dt_shock_utc = datetime.strptime(
                    tds[9].text.strip(), "%Y.%m.%d-%H:%M:%S"
                ).replace(tzinfo=timezone.utc)
                if abs((now_utc - dt_shock_utc).total_seconds()) > EARLYEST_WINDOW_MIN * 60:
                    continue
                lat = float(tds[10].text.strip())
                lon = float(tds[11].text.strip())
                mag = self._choose_mag(tds)
                if mag is None:
                    continue
                depth = float(tds[13].text.strip())
                shock_time_str = dt_shock_utc.strftime("%Y/%m/%d %H:%M:%S") + "Z"
                loc_seq = tds[1].text.strip()
                region = ""
                if len(tds) > region_col_index:
                    region = tds[region_col_index].get_text(strip=True)
                if (not region) and region_col_index == 30 and len(tds) >= 1:
                    region = tds[-1].get_text(strip=True)
            except Exception:
                continue

            if not (_is_in_process_area(lat, lon) or mag >= GQ_MAGNITUDE_BORDER):
                continue

            report_num_display = int(loc_seq) if str(loc_seq).isdigit() else 1
            display_time = timezone_utils.utc_to_display(
                dt_shock_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00")
            )
            candidates.append({
                "type": "warning",
                "source_type": "early_est",
                "place_name": region or "未知区域",
                "shock_time": display_time,
                "magnitude": round(mag + 1e-9, 1),
                "latitude": lat,
                "longitude": lon,
                "depth": depth,
                "organization": self.get_organization_name(),
                "event_id": eid,
                "updates": report_num_display,
                "raw_data": {
                    "identifier": eid,
                    "otime": shock_time_str,
                    "lat": lat,
                    "lon": lon,
                    "region": region,
                    "mag": mag,
                    "depth": depth,
                    "locSeq": report_num_display,
                },
            })

        if not candidates:
            return None
        return candidates[0]

    def _choose_mag(self, tds) -> Optional[float]:
        def valid(x):
            try:
                return float(x) != -9
            except Exception:
                return False

        try:
            vals = [tds[27].text.strip(), tds[23].text.strip(), tds[21].text.strip()]
            for v in vals:
                if valid(v):
                    return float(v)
        except Exception:
            pass
        return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "warning")
