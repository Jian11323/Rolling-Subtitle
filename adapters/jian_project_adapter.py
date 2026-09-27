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

# 列表命令响应 type → API 短名（复合名无法靠 strip list 还原）
_LIST_RESPONSE_TO_SHORT: Dict[str, str] = {
    "jmavolcanolist_response": "jma-volcano",
    "usgsvolcanolist_response": "usgs-volcano",
    "weatherlist_response": "weather",
}

JIAN_WARNING_INTERNAL = frozenset(
    {"cea", "cea-pr", "cwa-eew", "jma", "sa", "kma-eew", "early_est"}
)
JIAN_TSUNAMI_INTERNAL = frozenset(
    {"tsunami", "cwa_tsunami", "jma_tsunami", "usgs_tsunami"}
)
JIAN_VOLCANO_INTERNAL = frozenset({"jma_volcano", "usgs_volcano"})
JIAN_SKIP_INTERNAL = frozenset()  # CEA 已恢复公开推送
JIAN_UTC9_SOURCES = frozenset(
    {"jma", "jma_eq", "jma_tsunami", "jma_volcano"}
)  # JMA 系列：ISO/发表时刻常为 JST

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


def _clean_text(value: Any, *, max_len: int = 0) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    if max_len > 0 and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def _resolve_internal(short: str) -> Optional[str]:
    """短名 → 内部 source_type；以 config 映射为准。"""
    key = _normalize_short(short)
    if not key:
        return None
    try:
        from config import JIAN_SHORT_TO_PARSE_FLAG, jian_short_to_internal

        for alias in (key, key.replace("_", "-"), key.replace("-", "_")):
            if alias in JIAN_SHORT_TO_PARSE_FLAG:
                return jian_short_to_internal(alias)
    except Exception as e:
        logger.debug(f"[Jian] 解析短名映射失败: {e}")
    return None


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
        for key in ("shockTime", "shock_time", "reportTime", "createTime", "effective"):
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
            return timezone_utils.timestamp_to_display(ms)
        except (ValueError, TypeError, OSError, OverflowError):
            return ""
    text = str(raw).strip()
    if not text:
        return ""
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


def _format_weather_display(headline: str) -> str:
    """大陆 NMC 气象预警滚动文案；港澳单独标注。"""
    text = (headline or "").strip()
    if not text:
        return ""
    hk_markers = ("香港", "澳門", "澳门", "HKO", "Hong Kong")
    is_hk = any(m in text for m in hk_markers)
    m = re.match(r"^(.+?)发布(.+)$", text)
    if m:
        region = m.group(1).strip()
        warning = m.group(2).strip()
        if is_hk or any(x in region for x in ("香港", "澳门", "澳門")):
            return f"【港澳气象预警】{region} {warning}"
        return f"{region} {warning}"
    if is_hk:
        return f"【港澳气象预警】{text}"
    return text


def _localize_tsunami_level(level: str) -> str:
    raw = (level or "").strip()
    if not raw:
        return ""
    mapping = {
        "信息": "信息",
        "藍色": "蓝色",
        "蓝色": "蓝色",
        "黃色": "黄色",
        "黄色": "黄色",
        "橙色": "橙色",
        "紅色": "红色",
        "红色": "红色",
        "綠色": "绿色",
        "绿色": "绿色",
        "Information": "信息",
        "Tsunami Warning": "海啸警报",
        "Warning": "警报",
        "Advisory": "注意报",
        "Watch": "监视",
        "津波予報": "海啸预报",
        "津波注意報": "海啸注意报",
        "津波警報": "海啸警报",
        "大津波警報": "大海啸警报",
    }
    return mapping.get(raw, raw)


# 上游 orgUnit 缩写 → 字幕机构名（优先于裸缩写）
_TSUNAMI_ORG_UNIT_NAMES: Dict[str, str] = {
    "NTWC": "美国国家海啸预警中心 (NTWC)",
    "PTWC": "太平洋海啸预警中心 (PTWC)",
    "NWS": "美国国家气象局 (NWS)",
    "気象庁": "日本气象厅海啸预警",
    "氣象署": "台湾气象署海啸信息",
    "中央氣象署": "台湾气象署海啸信息",
}


def _tsunami_organization(internal: str, org_unit: str, updates: Optional[int], level: str) -> str:
    """海啸字幕机构标头：配置中文名 / orgUnit 映射 + 报次 + 级别。"""
    unit = (org_unit or "").strip()
    base = (
        _TSUNAMI_ORG_UNIT_NAMES.get(unit)
        or _get_organization_name(internal)
        or unit
        or "海啸预警"
    )
    if updates is not None:
        base = f"{base} 第{updates}报".strip()
    if level:
        base = f"{base} {level}".strip()
    return base


def _is_tsunami_product_code(text: str) -> bool:
    """判断是否为 WMO/电文产品码（如 WEAK53、VTSE41、纯数字 EventID），不宜当正文展示。"""
    s = (text or "").strip()
    if not s:
        return True
    if re.fullmatch(r"\d{6,}", s):
        return True
    if re.fullmatch(r"[A-Z]{3,6}\d{0,4}", s, flags=re.IGNORECASE):
        return True
    return False


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
                internal = jian_short_to_internal(short)
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
        if data.get("isCancel") is not None or data.get("cancel") is not None:
            result["cancel"] = bool(data.get("isCancel") or data.get("cancel"))
        if internal == "cea-pr":
            province = str(data.get("province") or "").strip()
            if province:
                result["province"] = province
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

    def _parse_weather(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """中国气象局气象预警（Data.type 为中央台图标码 p00…）。"""
        if not data:
            return None
        event_id = str(data.get("id") or data.get("eventId") or "").strip()
        headline = _clean_text(data.get("headline") or data.get("title"))
        title = _clean_text(data.get("title") or headline)
        if not event_id and headline:
            event_id = f"{headline}_{data.get('originTime') or ''}"
        display_title = _format_weather_display(headline or title)
        shock_time = _parse_origin_time(data, source_type="weatheralarm")
        description = _clean_text(data.get("description"), max_len=120)
        if not display_title and not shock_time:
            return None
        return {
            "type": "weather",
            "magnitude": 0,
            "latitude": _safe_float(data.get("latitude", 0)),
            "longitude": _safe_float(data.get("longitude", 0)),
            "depth": 0,
            "place_name": display_title or title,
            "shock_time": shock_time,
            "organization": _get_organization_name("weatheralarm"),
            "title": display_title or title,
            "description": description,
            "warning_type": str(data.get("type") or "").strip(),
            "event_id": event_id,
            "source_type": "weatheralarm",
            "raw_data": data,
            "jian": True,
        }

    def _parse_tsunami(self, data: Dict[str, Any], internal: str) -> Optional[Dict[str, Any]]:
        """扁平海啸帧：nmefc / cwa / jma / usgs。"""
        if not data:
            return None
        shock_time = _parse_origin_time(data, source_type=internal)
        title = _clean_text(data.get("title"))
        level_raw = str(data.get("level") or "").strip()
        level = _localize_tsunami_level(level_raw)
        # 地点仅保留地理名，勿把 description/area 拼进 place（否则会被 FE 地名修正整段冲掉）
        place = _clean_text(data.get("place") or data.get("placeName") or "")
        if not place and title and "·" not in title and not _is_tsunami_product_code(title):
            # CWA 标题常为「海嘯警報 · 地点」；纯地点 title 可作地名回退
            place = title
        elif not place and title and "·" in title:
            place = title.split("·", 1)[-1].strip() or place
        headline = _clean_text(data.get("headline"))
        description = _clean_text(data.get("description"), max_len=220)
        area = _clean_text(data.get("area"), max_len=200)
        if not shock_time and not title and not place and not description:
            return None

        updates = data.get("number") or data.get("updates")
        try:
            updates_i = int(updates) if updates is not None else None
        except (TypeError, ValueError):
            updates_i = None

        org_unit = str(data.get("orgUnit") or "").strip()
        org = _tsunami_organization(internal, org_unit, updates_i, level)

        lat = _safe_float(data.get("latitude"), 0)
        lon = _safe_float(data.get("longitude"), 0)
        # USGS 英文地点可做 FE 粗分区；JMA/CWA 保留官方地名
        if place and internal == "usgs_tsunami":
            place = _maybe_fix_place_name(place, lat, lon, internal, is_warning=False) or place

        place_name = place or level or "海啸信息"

        result: Dict[str, Any] = {
            "type": "report",
            "is_tsunami": True,
            "source_type": internal,
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": org,
            "magnitude": _safe_float(data.get("magnitude"), 0),
            "depth": _safe_float(data.get("depth"), 0),
            "latitude": lat,
            "longitude": lon,
            "event_id": str(data.get("id") or "").strip(),
            "tsunami_level": level,
            "tsunami_level_raw": level_raw,
            "tsunami_warning_level": level,
            "tsunami_headline": "" if _is_tsunami_product_code(headline) else headline,
            "tsunami_description": description,
            "tsunami_warning_title": title,
            "raw_data": data,
            "jian": True,
        }
        if area:
            result["tsunami_area"] = area
        # 产品码仅作元数据，不进字幕正文
        if headline and _is_tsunami_product_code(headline):
            result["tsunami_product_code"] = headline
        html_url = str(data.get("htmlUrl") or data.get("url") or "").strip()
        if html_url:
            result["detail_url"] = html_url
        if data.get("telegram"):
            result["telegram"] = str(data.get("telegram")).strip()
        return result

    def _parse_volcano(self, data: Dict[str, Any], internal: str) -> Optional[Dict[str, Any]]:
        """JMA / USGS 火山情报。"""
        if not data:
            return None
        volcano = _clean_text(data.get("title") or data.get("volcanoName"))
        headline = _clean_text(data.get("headline"))
        description = _clean_text(
            data.get("description") or data.get("observation") or headline,
            max_len=200,
        )
        shock_time = _parse_origin_time(data, source_type=internal)
        if not volcano and not headline and not description:
            return None

        alert_level = str(data.get("alertLevel") or "").strip()
        color_code = str(data.get("colorCode") or "").strip()
        org = _get_organization_name(internal)
        if internal == "usgs_volcano":
            obs = str(data.get("observatory") or "").strip()
            if obs:
                org = f"{org} ({obs})"
            if color_code or alert_level:
                org = f"{org} {color_code}/{alert_level}".strip(" /")

        title = headline or (
            f"警戒级别 {alert_level}" if alert_level else (color_code or "火山情报")
        )
        return {
            "type": "volcano",
            "source_type": internal,
            "title": title,
            "volcano": volcano,
            "description": description,
            "name": org,
            "shock_time": shock_time,
            "place_name": volcano or title,
            "organization": org,
            "event_id": str(data.get("id") or "").strip(),
            "latitude": _safe_float(data.get("latitude"), 0),
            "longitude": _safe_float(data.get("longitude"), 0),
            "raw_data": data,
            "jian": True,
        }

    def _parse_by_internal(
        self, data: Dict[str, Any], internal: str
    ) -> Optional[Dict[str, Any]]:
        if internal in JIAN_SKIP_INTERNAL:
            return None
        if internal == "weatheralarm":
            return self._parse_weather(data)
        if internal in JIAN_TSUNAMI_INTERNAL:
            return self._parse_tsunami(data, internal)
        if internal in JIAN_VOLCANO_INTERNAL:
            return self._parse_volcano(data, internal)
        if internal in JIAN_WARNING_INTERNAL:
            return self._parse_warning(data, internal)
        return self._parse_report(data, internal)

    def _extract_short_from_frame(self, frame: Dict[str, Any]) -> str:
        short = _normalize_short(frame.get("source") or "")
        if short:
            return short
        msg_type = _normalize_short(frame.get("type") or "")
        if msg_type and msg_type not in ("all", "heartbeat", "ping", "pong", "error"):
            if not msg_type.endswith("_response"):
                return msg_type
        return ""

    @staticmethod
    def _is_list_response(msg_type: str) -> bool:
        return bool(msg_type) and msg_type.endswith("list_response")

    def _short_from_list_response(self, msg_type: str) -> str:
        if msg_type in _LIST_RESPONSE_TO_SHORT:
            return _LIST_RESPONSE_TO_SHORT[msg_type]
        # cenclist_response → cenc；ningxialist_response → ningxia
        base = msg_type[: -len("_response")] if msg_type.endswith("_response") else msg_type
        if base.endswith("list"):
            return base[: -len("list")]
        return base

    def _parse_list_response(self, frame: Dict[str, Any]) -> List[Dict[str, Any]]:
        msg_type = _normalize_short(frame.get("type") or "")
        short = self._short_from_list_response(msg_type)
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
        if msg_type in ("heartbeat", "ping", "pong", "error"):
            return None
        if self._is_list_response(msg_type):
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
                    if self._is_list_response(msg_type):
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
                if self._is_list_response(msg_type):
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
                if self._is_list_response(msg_type):
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
