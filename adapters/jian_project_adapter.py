#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jian Project WebSocket 适配器（wss://api.sismotide.top）

帧格式：type + Data + md5；/all 首连为聚合快照，之后按 type 推送增量。
时间字段多为 originTime（毫秒）；JMA 系列为 ISO 8601（JST）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

from .base_adapter import BaseAdapter
from utils.logger import get_logger
from utils import timezone_utils

logger = get_logger()

# Jian 短名 → 内部 source_type
JIAN_SOURCE_TO_INTERNAL: Dict[str, str] = {
    "cea": "cea",
    "cwa-eew": "cwa-eew",
    "jma-eew": "jma",
    "sa": "sa",
    "early-est": "early_est",
    "cenc": "cenc",
    "cwa": "cwa",
    "jma": "jma_eq",
    "hko": "hko",
    "tmd": "tmd",
    "mmd": "mmd",
    "bmkg": "bmkg",
    "geonet": "geonet",
    "usgs": "usgs",
    "emsc": "emsc",
    "gfz": "gfz",
    "bcsf": "bcsf",
    "ingv": "ingv",
    "usp": "usp",
    "nrcan": "nrcan",
}

JIAN_WARNING_INTERNAL = frozenset({"cea", "cwa-eew", "jma", "sa", "early_est"})
JIAN_SKIP_INTERNAL = frozenset({"jma_eq"})  # JMA 情报走 P2PQuake
JIAN_UTC9_WARNING = frozenset({"jma"})
JIAN_LIST_RESPONSE_TYPES = frozenset(
    {
        "cenclist_response",
        "cwalist_response",
        "jmalist_response",
        "hkolist_response",
    }
)

_SOURCE_KEY_RE = re.compile(r"^source[：:]\s*(.+)$", re.IGNORECASE)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_short(value: Any) -> str:
    return str(value or "").strip().lower()


def _resolve_internal(short: str) -> Optional[str]:
    key = _normalize_short(short)
    if not key:
        return None
    for alias in (key, key.replace("_", "-"), key.replace("-", "_")):
        if alias in JIAN_SOURCE_TO_INTERNAL:
            return JIAN_SOURCE_TO_INTERNAL[alias]
    return JIAN_SOURCE_TO_INTERNAL.get(key)


def _get_organization_name(source_type: str) -> str:
    try:
        from config import Config

        return Config().get_organization_name(source_type)
    except Exception:
        return source_type


def _parse_origin_time(
    data: Dict[str, Any],
    *,
    source_type: str,
) -> str:
    """解析 originTime / shockTime / reportTime。"""
    raw = data.get("originTime")
    if raw is None:
        for key in ("shockTime", "shock_time", "reportTime", "createTime"):
            val = data.get(key)
            if val is not None and str(val).strip():
                raw = val
                break
    if raw is None:
        return ""
    if isinstance(raw, (int, float)) or (
        isinstance(raw, str) and raw.strip().isdigit()
    ):
        try:
            ms = int(raw)
            if source_type in JIAN_UTC9_WARNING:
                dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone(timedelta(hours=9)))
                return timezone_utils.jst_to_display(dt.strftime("%Y-%m-%d %H:%M:%S"))
            dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone(timedelta(hours=8)))
            return timezone_utils.cst_to_display(dt.strftime("%Y-%m-%d %H:%M:%S"))
        except (ValueError, TypeError, OSError, OverflowError):
            return ""
    text = str(raw).strip()
    if not text:
        return ""
    if source_type in JIAN_UTC9_WARNING or "+09:00" in text:
        return timezone_utils.jst_to_display(text)
    return timezone_utils.flexible_time_to_display(text) or timezone_utils.cst_to_display(text)


def _maybe_fix_place_name(
    place_name: str,
    lat: float,
    lon: float,
    source_type: str,
    *,
    is_warning: bool,
) -> str:
    if not place_name:
        return place_name
    try:
        from utils.place_name_fixer import get_place_name_fixer

        fixer = get_place_name_fixer()
        if fixer and fixer.is_enabled():
            return fixer.fix_place_name(
                place_name,
                latitude=lat,
                longitude=lon,
                source_type=source_type,
                is_warning=is_warning,
            )
    except Exception:
        pass
    return place_name


class JianProjectAdapter(BaseAdapter):
    """Jian Project /all 聚合通道适配器。"""

    def __init__(self, source_type: str, url: str):
        super().__init__(source_type, url)

    def _enabled_internals(self) -> Set[str]:
        """根据设置页 HTTP 逻辑键（兼容旧配置）判断子源是否启用。"""
        try:
            from config import Config, jian_internal_enabled

            cfg = Config()
            out: Set[str] = set()
            for short, internal in JIAN_SOURCE_TO_INTERNAL.items():
                if jian_internal_enabled(cfg, internal):
                    out.add(internal)
            return out
        except Exception as e:
            logger.debug(f"[Jian] 读取子源开关失败: {e}")
            return set()

    def _parse_warning(self, data: Dict[str, Any], internal: str) -> Optional[Dict[str, Any]]:
        place_name = str(
            data.get("placeName")
            or data.get("place_name")
            or data.get("location")
            or ""
        ).strip()
        shock_time = _parse_origin_time(data, source_type=internal)
        if not place_name and not shock_time:
            return None

        magnitude = _safe_float(data.get("magnitude", 0))
        latitude = _safe_float(data.get("latitude", 0))
        longitude = _safe_float(data.get("longitude", 0))
        depth = _safe_float(data.get("depth", 0))
        place_name = _maybe_fix_place_name(
            place_name, latitude, longitude, internal, is_warning=True
        )

        intensity = data.get("intensity") or data.get("epiIntensity") or ""
        if isinstance(intensity, (int, float)):
            intensity = str(intensity)

        updates = data.get("number") or data.get("updates") or data.get("serial")
        try:
            updates = int(updates) if updates is not None else None
        except (TypeError, ValueError):
            updates = None

        event_id = str(data.get("id") or data.get("eventId") or "").strip()
        result: Dict[str, Any] = {
            "type": "warning",
            "magnitude": magnitude,
            "latitude": latitude,
            "longitude": longitude,
            "depth": depth,
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": _get_organization_name(internal),
            "event_id": event_id,
            "source_type": internal,
            "raw_data": data,
            "jian": True,
        }
        if updates is not None:
            result["updates"] = updates
        if intensity:
            result["intensity"] = intensity
        if internal == "jma":
            for key in ("infoTypeName", "isFinal", "isCancel", "isTraining", "isPLUM"):
                if key in data:
                    result[key] = data.get(key)
        return result

    def _parse_report(self, data: Dict[str, Any], internal: str) -> Optional[Dict[str, Any]]:
        place_name = str(data.get("placeName") or data.get("title") or "").strip()
        shock_time = _parse_origin_time(data, source_type=internal)
        if not place_name and not shock_time:
            return None

        magnitude = _safe_float(data.get("magnitude", 0))
        latitude = _safe_float(data.get("latitude", 0))
        longitude = _safe_float(data.get("longitude", 0))
        depth = _safe_float(data.get("depth", 0))
        place_name = _maybe_fix_place_name(
            place_name, latitude, longitude, internal, is_warning=False
        )

        event_id = str(data.get("id") or data.get("eventId") or "").strip()
        info_type = str(data.get("infoTypeName") or "").strip()

        result: Dict[str, Any] = {
            "type": "report",
            "magnitude": magnitude,
            "latitude": latitude,
            "longitude": longitude,
            "depth": depth,
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": _get_organization_name(internal),
            "event_id": event_id or f"{internal}:{shock_time}",
            "source_type": internal,
            "raw_data": data,
            "jian": True,
        }
        if info_type:
            result["info_type"] = info_type
        intensity = data.get("intensity") or data.get("maxIntensity")
        if intensity is not None and str(intensity).strip():
            result["intensity"] = str(intensity)
        return result

    def _parse_by_internal(
        self, data: Dict[str, Any], internal: str
    ) -> Optional[Dict[str, Any]]:
        if internal in JIAN_SKIP_INTERNAL:
            return None
        if internal in JIAN_WARNING_INTERNAL:
            return self._parse_warning(data, internal)
        return self._parse_report(data, internal)

    def _extract_short_from_frame(self, frame: Dict[str, Any]) -> str:
        short = _normalize_short(frame.get("source") or "")
        if short:
            return short
        msg_type = _normalize_short(frame.get("type") or "")
        if msg_type and msg_type not in ("all", "heartbeat", "ping", "pong"):
            if not msg_type.endswith("_response"):
                return msg_type
        return ""

    def _parse_list_response(self, frame: Dict[str, Any]) -> List[Dict[str, Any]]:
        msg_type = _normalize_short(frame.get("type") or "")
        short = msg_type.replace("_response", "").replace("list", "")
        if msg_type == "cenclist_response":
            short = "cenc"
        elif msg_type == "cwalist_response":
            short = "cwa"
        elif msg_type == "jmalist_response":
            short = "jma"
        elif msg_type == "hkolist_response":
            short = "hko"
        internal = _resolve_internal(short)
        if not internal or internal in JIAN_SKIP_INTERNAL:
            return []
        if internal not in self._enabled_internals():
            return []
        items = frame.get("Data")
        if not isinstance(items, list):
            return []
        results: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            parsed = self._parse_by_internal(item, internal)
            if parsed:
                results.append(parsed)
        return results

    def _parse_aggregate_snapshot(self, frame: Dict[str, Any]) -> List[Dict[str, Any]]:
        """解析 type=all 首连快照（source：xxx 键）。"""
        enabled = self._enabled_internals()
        results: List[Dict[str, Any]] = []
        for key, payload in frame.items():
            if not isinstance(key, str):
                continue
            m = _SOURCE_KEY_RE.match(key.strip())
            if not m:
                continue
            short = _normalize_short(m.group(1))
            internal = _resolve_internal(short)
            if not internal or internal not in enabled or internal in JIAN_SKIP_INTERNAL:
                continue
            if not isinstance(payload, dict):
                continue
            data_obj = payload.get("Data") if isinstance(payload.get("Data"), dict) else payload
            if not isinstance(data_obj, dict) or not data_obj:
                continue
            parsed = self._parse_by_internal(data_obj, internal)
            if parsed:
                results.append(parsed)
        return results

    def _parse_one_frame(self, frame: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(frame, dict):
            return None
        msg_type = _normalize_short(frame.get("type") or "")
        if msg_type in ("heartbeat", "ping", "pong"):
            return None
        if msg_type in JIAN_LIST_RESPONSE_TYPES:
            items = self._parse_list_response(frame)
            return items[0] if items else None
        if msg_type == "all":
            items = self._parse_aggregate_snapshot(frame)
            return items[0] if items else None

        data_obj = frame.get("Data")
        if not isinstance(data_obj, dict) or not data_obj:
            return None
        short = self._extract_short_from_frame(frame)
        internal = _resolve_internal(short)
        if not internal or internal in JIAN_SKIP_INTERNAL:
            return None
        if internal not in self._enabled_internals():
            return None
        return self._parse_by_internal(data_obj, internal)

    def parse_all_sources(self, raw_data: Any) -> List[Dict[str, Any]]:
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if isinstance(data, list):
                results: List[Dict[str, Any]] = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    msg_type = _normalize_short(item.get("type") or "")
                    if msg_type in JIAN_LIST_RESPONSE_TYPES:
                        results.extend(self._parse_list_response(item))
                    elif msg_type == "all":
                        results.extend(self._parse_aggregate_snapshot(item))
                    else:
                        one = self._parse_one_frame(item)
                        if one:
                            results.append(one)
                if results:
                    logger.info(f"[Jian] 批量解析 {len(results)} 条")
                return results
            if isinstance(data, dict):
                msg_type = _normalize_short(data.get("type") or "")
                if msg_type == "all":
                    return self._parse_aggregate_snapshot(data)
                if msg_type in JIAN_LIST_RESPONSE_TYPES:
                    return self._parse_list_response(data)
                one = self._parse_one_frame(data)
                return [one] if one else []
            return []
        except Exception as e:
            logger.error(f"[Jian] parse_all_sources 失败: {e}")
            return []

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        try:
            if isinstance(raw_data, str):
                try:
                    data = json.loads(raw_data)
                except (json.JSONDecodeError, TypeError, ValueError):
                    return None
            else:
                data = raw_data
            if isinstance(data, list):
                all_parsed = self.parse_all_sources(data)
                return all_parsed[0] if all_parsed else None
            if isinstance(data, dict):
                msg_type = _normalize_short(data.get("type") or "")
                if msg_type in JIAN_LIST_RESPONSE_TYPES:
                    items = self._parse_list_response(data)
                    return items[0] if items else None
                if msg_type == "all":
                    items = self._parse_aggregate_snapshot(data)
                    return items[0] if items else None
                return self._parse_one_frame(data)
            return None
        except Exception as e:
            logger.error(f"[Jian] parse 失败: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "report")
