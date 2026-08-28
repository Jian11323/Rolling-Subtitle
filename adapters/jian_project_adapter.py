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
    "kma-eew": "kma-eew",
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
    "afad": "afad",
    "kma": "kma",
}

JIAN_WARNING_INTERNAL = frozenset({"cea", "cwa-eew", "jma", "sa", "kma-eew", "early_est"})
JIAN_SKIP_INTERNAL = frozenset()  # CEA 已恢复公开推送
JIAN_UTC9_SOURCES = frozenset({"jma", "jma_eq"})  # JMA 预警/情报：ISO 常为 JST
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
    """
    解析 originTime / shockTime / reportTime。

    - 数值：Unix 毫秒/秒时间戳（绝对时刻）→ 显示时区
    - JMA 字符串：上游原生 JST ISO（含 +09:00）→ 显示时区
    - 其它字符串：带偏移走 ISO；否则按北京时间朴素串
    """
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
            # 秒级时间戳（10 位）与毫秒统一交给 timestamp_to_display
            return timezone_utils.timestamp_to_display(ms)
        except (ValueError, TypeError, OSError, OverflowError):
            return ""
    text = str(raw).strip()
    if not text:
        return ""
    # 带时区偏移的 ISO（含 JMA +09:00）
    if "T" in text and ("+" in text[10:] or text.endswith("Z") or text.endswith("z")):
        converted = timezone_utils.flexible_time_to_display(text)
        if converted:
            return converted
    if source_type in JIAN_UTC9_SOURCES or "+09:00" in text:
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
    if not place_name or (lat == 0.0 and lon == 0.0):
        return place_name
    try:
        from config import Config
        from utils.place_name_utils import should_apply_place_name_fix, should_apply_fe_place_fix

        config = Config()
        if not should_apply_place_name_fix(config):
            return place_name
        if is_warning and source_type in ("sa", "kma-eew"):
            from utils.region_name_fixer import get_sa_region_fixer, get_kma_region_fixer

            fixer = (
                get_sa_region_fixer()
                if source_type == "sa"
                else get_kma_region_fixer()
            )
            if fixer and fixer.is_supported():
                return fixer.fix_place_name(place_name, lat, lon)
        if not is_warning and should_apply_fe_place_fix(source_type):
            from utils.place_name_fixer import get_place_name_fixer

            fixer = get_place_name_fixer()
            if fixer and fixer.is_supported(source_type):
                return fixer.fix_place_name(place_name, lat, lon, source_type)
    except Exception as e:
        logger.debug(f"[Jian] 地名修正失败: {e}")
    return place_name


def _lookup_kma_placename_zh(lat: float, lon: float) -> str:
    """按坐标查韩国行政区中文名；失败返回空串。"""
    if lat == 0.0 and lon == 0.0:
        return ""
    try:
        from config import Config
        from utils.place_name_utils import should_apply_place_name_fix

        if not should_apply_place_name_fix(Config()):
            return ""
        from utils.region_name_fixer import get_kma_region_fixer

        fixer = get_kma_region_fixer()
        if not fixer or not fixer.is_supported():
            return ""
        name = fixer.lookup_zh_name(lat, lon)
        return str(name).strip() if name else ""
    except Exception as e:
        logger.debug(f"[Jian] KMA placename_zh 查表失败: {e}")
        return ""


class JianProjectAdapter(BaseAdapter):
    """Jian Project /all 聚合通道适配器。"""

    def __init__(self, source_type: str, url: str):
        super().__init__(source_type, url)

    def _enabled_internals(self) -> Set[str]:
        """根据设置页 jian_parse_* 开关判断子源是否启用。"""
        try:
            from config import (
                Config,
                jian_internal_enabled,
                jian_short_to_internal,
                JIAN_SHORT_TO_PARSE_FLAG,
            )

            cfg = Config()
            out: Set[str] = set()
            for short in JIAN_SHORT_TO_PARSE_FLAG:
                if not jian_internal_enabled(cfg, jian_short_to_internal(short)):
                    continue
                adapter_internal = JIAN_SOURCE_TO_INTERNAL.get(short)
                if adapter_internal:
                    out.add(adapter_internal)
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

        # KMA 预警：优先服务端 placename_zh，否则本地行政区查表 / 区域修正
        placename_zh = ""
        if internal == "kma-eew":
            placename_zh = str(data.get("placename_zh") or "").strip()
            if not placename_zh:
                placename_zh = _lookup_kma_placename_zh(latitude, longitude)
            if placename_zh:
                place_name = placename_zh
            else:
                place_name = _maybe_fix_place_name(
                    place_name, latitude, longitude, internal, is_warning=True
                )
        else:
            place_name = _maybe_fix_place_name(
                place_name, latitude, longitude, internal, is_warning=True
            )

        intensity = data.get("intensity") or data.get("epiIntensity") or ""
        if internal == "kma-eew" and (intensity is None or intensity == ""):
            intensity = data.get("maxMMI")
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
        if placename_zh:
            result["placename_zh"] = placename_zh
        if updates is not None:
            result["updates"] = updates
        if intensity:
            result["intensity"] = intensity
        # 统一取消标志：下游按 cancel=True 撤回（兼容 isCancel）
        if data.get("isCancel") is not None or data.get("cancel") is not None:
            result["cancel"] = bool(data.get("isCancel") or data.get("cancel"))
        if internal == "kma-eew":
            info_type = str(data.get("infoTypeName") or "").strip()
            if info_type:
                result["info_type"] = info_type
            if "isWarn" in data:
                result["isWarn"] = bool(data.get("isWarn"))
            if data.get("phase") is not None:
                try:
                    result["phase"] = int(data.get("phase"))
                except (TypeError, ValueError):
                    pass
            if data.get("maxMMI") is not None:
                try:
                    result["max_mmi"] = int(data.get("maxMMI"))
                except (TypeError, ValueError):
                    result["max_mmi"] = data.get("maxMMI")
            areas = data.get("maxIntensityArea")
            if isinstance(areas, list) and areas:
                result["affected_areas"] = [str(a).strip() for a in areas if str(a).strip()]
        if internal == "jma":
            for key in ("infoTypeName", "isFinal", "isCancel", "isTraining", "isPLUM", "isWarn"):
                if key in data:
                    result[key] = data.get(key)
            warn_area = data.get("warnArea") or data.get("wolfx_warn_areas")
            if isinstance(warn_area, list) and warn_area:
                result["wolfx_warn_areas"] = warn_area
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

        # KMA 速报：保留原文地名；优先用上游 placename_zh，否则本地查表
        placename_zh = ""
        if internal == "kma":
            placename_zh = str(data.get("placename_zh") or "").strip()
            if not placename_zh:
                placename_zh = _lookup_kma_placename_zh(latitude, longitude)
        else:
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
        if placename_zh:
            result["placename_zh"] = placename_zh
        if info_type:
            result["info_type"] = info_type
        intensity = data.get("intensity") or data.get("maxIntensity")
        if intensity is not None and str(intensity).strip():
            result["intensity"] = str(intensity)
        areas = data.get("intensityAreas")
        if isinstance(areas, list) and areas:
            result["intensity_areas"] = areas
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
