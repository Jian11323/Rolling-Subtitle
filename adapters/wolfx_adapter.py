#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wolfx 聚合适配器（wss://ws-api.wolfx.jp/all_eew）
当前公开版仅解析以下预警类型：
- jma_eew
- sc_eew
- fj_eew
- cenc_eew
"""

import json
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils
from utils.logger import get_logger

logger = get_logger()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


class WolfxAdapter(BaseAdapter):
    """Wolfx WebSocket all_eew 适配器。"""

    SUPPORTED_TYPES = {"jma_eew", "sc_eew", "fj_eew", "cenc_eew"}

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            if not isinstance(data, dict):
                return None

            source_type = (data.get("type") or "").strip()
            if source_type not in self.SUPPORTED_TYPES:
                return None

            if source_type == "jma_eew":
                return self._parse_jma_eew(data)
            if source_type == "sc_eew":
                return self._parse_sc_eew(data)
            if source_type == "fj_eew":
                return self._parse_fj_eew(data)
            if source_type == "cenc_eew":
                return self._parse_cenc_eew(data)
            return None
        except Exception as e:
            logger.debug(f"[Wolfx] 解析失败: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "unknown")

    @staticmethod
    def _build_common_warning(
        *,
        source_type: str,
        organization: str,
        place_name: str,
        magnitude: float,
        latitude: float,
        longitude: float,
        depth: float,
        shock_time: str,
        event_id: str,
        updates: Optional[int],
        raw_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "type": "warning",
            "source_type": source_type,
            "organization": organization,
            "place_name": place_name or "未知地区",
            "magnitude": magnitude,
            "latitude": latitude,
            "longitude": longitude,
            "depth": depth,
            "shock_time": shock_time,
            "event_id": event_id or "",
            "raw_data": raw_data,
        }
        if updates is not None and updates > 0:
            result["updates"] = int(updates)
        return result

    def _parse_jma_eew(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # 取消报直接忽略
        if bool(data.get("isCancel", False)):
            return None

        warned_type = ""
        warn_area = data.get("WarnArea")
        if isinstance(warn_area, dict):
            warned_type = (warn_area.get("Type") or "").strip()

        shock_time = timezone_utils.jst_to_display((data.get("OriginTime") or "").strip())
        return self._build_common_warning(
            source_type="wolfx_jma_eew",
            organization="緊急地震速報",
            place_name=(data.get("Hypocenter") or "").strip(),
            magnitude=_safe_float(data.get("Magunitude")),
            latitude=_safe_float(data.get("Latitude")),
            longitude=_safe_float(data.get("Longitude")),
            depth=_safe_float(data.get("Depth"), 10.0),
            shock_time=shock_time,
            event_id=(data.get("EventID") or "").strip(),
            updates=int(data.get("Serial") or 0) if str(data.get("Serial") or "").strip() else None,
            raw_data=data,
        ) | {"warn_area_type": warned_type, "final": bool(data.get("isFinal", False))}

    def _parse_sc_eew(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        shock_time = timezone_utils.cst_to_display((data.get("OriginTime") or "").strip())
        return self._build_common_warning(
            source_type="wolfx_sc_eew",
            organization="四川省地震局",
            place_name=(data.get("HypoCenter") or "").strip(),
            magnitude=_safe_float(data.get("Magunitude")),
            latitude=_safe_float(data.get("Latitude")),
            longitude=_safe_float(data.get("Longitude")),
            depth=_safe_float(data.get("Depth"), 10.0),
            shock_time=shock_time,
            event_id=(data.get("EventID") or "").strip() or str(data.get("ID") or ""),
            updates=int(data.get("ReportNum") or 0) if str(data.get("ReportNum") or "").strip() else None,
            raw_data=data,
        )

    def _parse_fj_eew(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        shock_time = timezone_utils.cst_to_display((data.get("OriginTime") or "").strip())
        return self._build_common_warning(
            source_type="wolfx_fj_eew",
            organization="福建省地震局",
            place_name=(data.get("HypoCenter") or "").strip(),
            magnitude=_safe_float(data.get("Magunitude")),
            latitude=_safe_float(data.get("Latitude")),
            longitude=_safe_float(data.get("Longitude")),
            depth=10.0,
            shock_time=shock_time,
            event_id=(data.get("EventID") or "").strip() or str(data.get("ID") or ""),
            updates=int(data.get("ReportNum") or 0) if str(data.get("ReportNum") or "").strip() else None,
            raw_data=data,
        ) | {"final": bool(data.get("isFinal", False))}

    def _parse_cenc_eew(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        shock_time = timezone_utils.cst_to_display((data.get("OriginTime") or "").strip())
        return self._build_common_warning(
            source_type="wolfx_cenc_eew",
            organization="中国地震台网地震预警",
            place_name=(data.get("HypoCenter") or "").strip(),
            magnitude=_safe_float(data.get("Magnitude")),
            latitude=_safe_float(data.get("Latitude")),
            longitude=_safe_float(data.get("Longitude")),
            depth=_safe_float(data.get("Depth"), 10.0),
            shock_time=shock_time,
            event_id=(data.get("EventID") or "").strip() or str(data.get("ID") or ""),
            updates=int(data.get("ReportNum") or 0) if str(data.get("ReportNum") or "").strip() else None,
            raw_data=data,
        )
