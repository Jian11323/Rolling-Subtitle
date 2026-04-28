#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wolfx 聚合适配器（wss://ws-api.wolfx.jp/all_eew）
当前公开版仅解析以下预警类型：
- jma_eew
- sc_eew
- fj_eew
- cenc_eew
- cq_eew
- cwa_eew
"""

import json
from typing import Any, Dict, Optional

from .base_adapter import BaseAdapter
from config import Config
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


def _to_bool_or_none(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "y", "已到达", "到达", "arrived"):
            return True
        if v in ("false", "0", "no", "n", "未到达", "未到", "not_arrived"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _normalize_warn_areas(warn_area: Any) -> list:
    if not warn_area:
        return []
    rows = []
    src_rows = warn_area if isinstance(warn_area, list) else [warn_area]
    for item in src_rows:
        if not isinstance(item, dict):
            continue
        row: Dict[str, Any] = {}
        chiiki = item.get("Chiiki")
        if chiiki is not None and str(chiiki).strip():
            row["chiiki"] = str(chiiki).strip()
        s1 = item.get("Shindo1")
        if s1 is not None and str(s1).strip():
            row["shindo1"] = str(s1).strip()
        s2 = item.get("Shindo2")
        if s2 is not None and str(s2).strip():
            row["shindo2"] = str(s2).strip()
        t = item.get("Time")
        if t is not None and str(t).strip():
            row["time"] = str(t).strip()
        tp = item.get("Type") or item.get("type")
        if tp is not None and str(tp).strip():
            row["type"] = str(tp).strip()
        arrive = item.get("Arrive")
        arrive_bool = _to_bool_or_none(arrive)
        if arrive_bool is not None:
            row["arrive"] = arrive_bool
        elif arrive is not None and str(arrive).strip():
            row["arrive_text"] = str(arrive).strip()
        if row:
            rows.append(row)
    return rows


def _extract_jma_extra_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    title = data.get("Title")
    code_type = data.get("CodeType")
    if title is not None and str(title).strip():
        out["wolfx_title"] = str(title).strip()
    if code_type is not None and str(code_type).strip():
        out["wolfx_code_type"] = str(code_type).strip()

    issue = data.get("Issue")
    if isinstance(issue, dict):
        src = issue.get("Source")
        status = issue.get("Status")
        if src is not None and str(src).strip():
            out["wolfx_issue_source"] = str(src).strip()
        if status is not None and str(status).strip():
            out["wolfx_issue_status"] = str(status).strip()

    announced = data.get("AnnouncedTime")
    if announced is not None and str(announced).strip():
        out["wolfx_announced_time"] = str(announced).strip()

    accuracy = data.get("Accuracy")
    if isinstance(accuracy, dict):
        epi = accuracy.get("Epicenter")
        dep = accuracy.get("Depth")
        mag = accuracy.get("Magnitude")
        if epi is not None and str(epi).strip():
            out["wolfx_accuracy_epicenter"] = str(epi).strip()
        if dep is not None and str(dep).strip():
            out["wolfx_accuracy_depth"] = str(dep).strip()
        if mag is not None and str(mag).strip():
            out["wolfx_accuracy_magnitude"] = str(mag).strip()

    max_int_change = data.get("MaxIntChange")
    if isinstance(max_int_change, dict):
        s = max_int_change.get("String")
        reason = max_int_change.get("Reason")
        if s is not None and str(s).strip():
            out["wolfx_max_int_change"] = str(s).strip()
        if reason is not None and str(reason).strip():
            out["wolfx_max_int_change_reason"] = str(reason).strip()

    warn_areas = _normalize_warn_areas(data.get("WarnArea"))
    if warn_areas:
        out["wolfx_warn_areas"] = warn_areas
        out["wolfx_warn_area_count"] = len(warn_areas)

    original_text = data.get("OriginalText")
    if original_text is not None and str(original_text).strip():
        out["wolfx_original_text"] = str(original_text).strip()
    pond = data.get("Pond")
    if pond is not None and str(pond).strip():
        out["wolfx_pond"] = str(pond).strip()

    for k in ("isSea", "isTraining", "isAssumption", "isWarn", "isFinal", "isCancel"):
        v = data.get(k)
        if isinstance(v, bool):
            out[f"wolfx_{k[0].lower()}{k[1:]}"] = v
    return out


class WolfxAdapter(BaseAdapter):
    """Wolfx WebSocket all_eew 适配器。"""

    SUPPORTED_TYPES = {"jma_eew", "sc_eew", "fj_eew", "cenc_eew", "cq_eew", "cwa_eew"}

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            if not isinstance(data, dict):
                return None

            source_type = (data.get("type") or "").strip()
            if source_type not in self.SUPPORTED_TYPES:
                return None
            if not self._is_source_enabled(source_type):
                return None

            if source_type == "jma_eew":
                return self._parse_jma_eew(data)
            if source_type == "sc_eew":
                return self._parse_sc_eew(data)
            if source_type == "fj_eew":
                return self._parse_fj_eew(data)
            if source_type == "cenc_eew":
                return self._parse_cenc_eew(data)
            if source_type == "cq_eew":
                return self._parse_cq_eew(data)
            if source_type == "cwa_eew":
                return self._parse_cwa_eew(data)
            return None
        except Exception as e:
            logger.debug(f"[Wolfx] 解析失败: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "unknown")

    def _is_source_enabled(self, source_type: str) -> bool:
        """根据 message_config 开关决定是否解析对应 Wolfx 子源。"""
        try:
            mc = Config().message_config
            mapping = {
                "jma_eew": "ali_all_parse_nied",
                "sc_eew": "ali_all_parse_early_est",
                "fj_eew": "ali_all_parse_jma_volcano",
                "cenc_eew": "ali_all_parse_bmkg",
                "cq_eew": "ali_all_parse_cq_eew",
            }
            field = mapping.get(source_type)
            if not field:
                return True
            return bool(getattr(mc, field, True))
        except Exception:
            return True

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
        ) | {
            "warn_area_type": warned_type,
            "final": bool(data.get("isFinal", False)),
            **_extract_jma_extra_fields(data),
        }

    def _parse_sc_eew(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        shock_time = timezone_utils.cst_to_display((data.get("OriginTime") or "").strip())
        mag = data.get("Magunitude")
        if mag is None:
            mag = data.get("Magnitude")
        return self._build_common_warning(
            source_type="wolfx_sc_eew",
            organization="四川省地震局",
            place_name=(data.get("HypoCenter") or "").strip(),
            magnitude=_safe_float(mag),
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
        mag = data.get("Magunitude")
        if mag is None:
            mag = data.get("Magnitude")
        return self._build_common_warning(
            source_type="wolfx_fj_eew",
            organization="福建省地震局",
            place_name=(data.get("HypoCenter") or "").strip(),
            magnitude=_safe_float(mag),
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

    def _parse_cq_eew(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        shock_time = timezone_utils.cst_to_display((data.get("OriginTime") or "").strip())
        return self._build_common_warning(
            source_type="wolfx_cq_eew",
            organization="重庆市地震局",
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

    def _parse_cwa_eew(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if bool(data.get("isCancel", False)):
            return None
        shock_time = timezone_utils.cst_to_display((data.get("OriginTime") or "").strip())
        return self._build_common_warning(
            source_type="wolfx_cwa_eew",
            organization="台湾中央气象署地震预警",
            place_name=(data.get("HypoCenter") or "").strip(),
            magnitude=_safe_float(data.get("Magunitude")),
            latitude=_safe_float(data.get("Latitude")),
            longitude=_safe_float(data.get("Longitude")),
            depth=_safe_float(data.get("Depth"), 10.0),
            shock_time=shock_time,
            event_id=str(data.get("ID") or ""),
            updates=int(data.get("ReportNum") or 0) if str(data.get("ReportNum") or "").strip() else None,
            raw_data=data,
        ) | {"max_intensity": str(data.get("MaxIntensity") or "")}
