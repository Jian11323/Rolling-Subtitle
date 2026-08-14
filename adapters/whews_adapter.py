#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeJet（WHEWS：api.2v8.cn / 备用 api.beecld.com）数据源适配器。

帧格式：{"Data": {...}, "md5": "...", "source": "cenc"}
聚合 /ws/all 首连为 JSON 数组，之后为单对象；心跳 type=heartbeat。
JMA 预警（jma_eew）随主服务解析；JMA 情报（jma）不解析，统一走 P2PQuake。

本适配器独立完成字段解析，不依赖 FanStudioAdapter。

注意：上游 API 的 source 字段大小写混杂（如 CENC / cenc / Cenc），
解析时一律规范化为小写后再映射；待上游统一后再可简化。
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Set

from .base_adapter import BaseAdapter
from utils.logger import get_logger
from utils import timezone_utils

logger = get_logger()

# JMA 情报仅使用 P2PQuake；预警由主服务（WeJet）解析
WHEWS_SKIP_SOURCES = frozenset({"jma"})

# 省级地震局情报（api.beecld.com：仅北京 / 云南 / 宁夏；福建/四川/陕西/湖北已下架）
WHEWS_PROVINCIAL_SOURCES = (
    "beijing",
    "yunnan",
    "ningxia",
)

# WHEWS source 短名 → 内部 source_type（与展示层一致）
# 键一律小写；实际查找走 _WHEWS_SOURCE_LOOKUP（兼容大小写与 -/_）
WHEWS_SOURCE_TO_INTERNAL = {
    "jma_eew": "jma",
    "cwa_eew": "cwa-eew",
    "sa_eew": "sa",
    "kma_eew": "kma-eew",
    "cea": "cea",
    "cea-pr": "cea-pr",
    "cenc": "cenc",
    "cwa": "cwa",
    "hko": "hko",
    "usgs": "usgs",
    "emsc": "emsc",
    "bcsf": "bcsf",
    "gfz": "gfz",
    "usp": "usp",
    "kma": "kma",
    "bmkg": "bmkg",
    "geonet": "geonet",
    "tmd": "tmd",
    "ingv": "ingv",
    "nrcan": "nrcan",
    "mmd": "mmd",
    "phivolcs": "phivolcs",
    "sgc": "sgc",
    "ga": "ga",
    "cenais": "cenais",
    "tsunami": "tsunami",
    "ntwc": "ntwc",
    "ptwc": "ptwc",
    "incois": "incois",
    "jma_tsunami": "jma_tsunami",
    "weatheralarm": "weatheralarm",
    "va": "jma_volcano",
}
for _prov in WHEWS_PROVINCIAL_SOURCES:
    WHEWS_SOURCE_TO_INTERNAL[_prov] = _prov


def _build_whews_source_lookup() -> Dict[str, str]:
    """构建 source 短名查找表：小写，并同时登记 - / _ 两种写法。"""
    out: Dict[str, str] = {}
    for key, internal in WHEWS_SOURCE_TO_INTERNAL.items():
        kl = str(key).strip().lower()
        if not kl:
            continue
        for alias in (kl, kl.replace("_", "-"), kl.replace("-", "_")):
            out.setdefault(alias, internal)
    return out


_WHEWS_SOURCE_LOOKUP = _build_whews_source_lookup()


def normalize_whews_source(value: Any) -> str:
    """将 API source 规范为小写短名（兼容大小写混杂）。"""
    return str(value or "").strip().lower()


def resolve_whews_internal_source(short: str) -> Optional[str]:
    """将规范化后的 source 短名解析为内部 source_type。"""
    key = normalize_whews_source(short)
    if not key:
        return None
    return _WHEWS_SOURCE_LOOKUP.get(key)


# 内部 source_type → message_config.whews_parse_* 字段名
WHEWS_SOURCE_FLAG_FIELD = {
    "jma": "whews_parse_jma_eew",
    "cwa-eew": "whews_parse_cwa_eew",
    "sa": "whews_parse_sa_eew",
    "kma-eew": "whews_parse_kma_eew",
    "cea": "whews_parse_cea",
    "cea-pr": "whews_parse_cea_pr",
    "cenc": "whews_parse_cenc",
    "cwa": "whews_parse_cwa",
    "hko": "whews_parse_hko",
    "usgs": "whews_parse_usgs",
    "emsc": "whews_parse_emsc",
    "bcsf": "whews_parse_bcsf",
    "gfz": "whews_parse_gfz",
    "usp": "whews_parse_usp",
    "kma": "whews_parse_kma",
    "bmkg": "whews_parse_bmkg",
    "geonet": "whews_parse_geonet",
    "tmd": "whews_parse_tmd",
    "ingv": "whews_parse_ingv",
    "nrcan": "whews_parse_nrcan",
    "mmd": "whews_parse_mmd",
    "phivolcs": "whews_parse_phivolcs",
    "sgc": "whews_parse_sgc",
    "ga": "whews_parse_ga",
    "cenais": "whews_parse_cenais",
    "tsunami": "whews_parse_tsunami",
    "ntwc": "whews_parse_ntwc",
    "ptwc": "whews_parse_ptwc",
    "incois": "whews_parse_incois",
    "jma_tsunami": "whews_parse_jma_tsunami",
    "weatheralarm": "whews_parse_weatheralarm",
    "jma_volcano": "whews_parse_jma_volcano",
}
for _prov in WHEWS_PROVINCIAL_SOURCES:
    WHEWS_SOURCE_FLAG_FIELD[_prov] = f"whews_parse_{_prov}"

WHEWS_WARNING_INTERNAL = frozenset({"jma", "cwa-eew", "sa", "cea", "cea-pr", "kma-eew"})

# 发震时间为 UTC+9（JST/KST）的预警源
WHEWS_UTC9_WARNING = frozenset({"jma", "kma-eew"})



def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转换为浮点数。"""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _resolve_event_id(
    data: Dict[str, Any],
    source_type: str,
    place_name: str = "",
    shock_time: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
) -> str:
    """eventId/id 缺失时用稳定字段合成。"""
    for key in ("eventId", "uniEventId", "id"):
        val = data.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    parts = [
        source_type or "",
        (place_name or "").strip(),
        (shock_time or "").strip(),
    ]
    if latitude or longitude:
        parts.append(f"{latitude:.4f},{longitude:.4f}")
    joined = ":".join(p for p in parts if p)
    return joined or f"{source_type}:unknown"


def _get_organization_name(source_type: str) -> str:
    """按内部 source_type 取机构名。"""
    try:
        from config import Config

        return Config().get_organization_name(source_type)
    except Exception as e:
        logger.debug(f"[WHEWS] 获取机构名称失败: {e}")
        return source_type


def _extract_cwa_location(data: Dict[str, Any]) -> str:
    """提取 CWA 速报地名（括号内「位於…」优先）。"""
    location_raw = data.get("loc", data.get("placeName", "未知地区"))
    if not location_raw or not isinstance(location_raw, str):
        location_raw = "未知地区"
    bracket_match = re.search(r"\(([^)]+)\)", location_raw)
    if bracket_match:
        location = bracket_match.group(1).replace("位於", "")
        location = re.sub(r"\s+", " ", location).strip()
    else:
        location = location_raw.strip()
    return location or location_raw.strip()


def _maybe_fix_place_name(
    place_name: str,
    latitude: float,
    longitude: float,
    source_type: str,
    *,
    is_warning: bool = False,
) -> str:
    """按配置尝试地名修正（失败则返回原名）。"""
    if not place_name or not latitude or not longitude:
        return place_name
    try:
        from config import Config
        from utils.place_name_utils import should_apply_place_name_fix

        config = Config()
        if not should_apply_place_name_fix(config):
            return place_name
        if is_warning and source_type == "sa":
            from utils.region_name_fixer import get_sa_region_fixer

            fixer = get_sa_region_fixer()
            if fixer and fixer.is_supported():
                return fixer.fix_place_name(place_name, latitude, longitude)
        if is_warning and source_type in ("kma", "kma-eew"):
            from utils.region_name_fixer import get_kma_region_fixer

            fixer = get_kma_region_fixer()
            if fixer and fixer.is_supported():
                return fixer.fix_place_name(place_name, latitude, longitude)
        if not is_warning:
            from utils.place_name_fixer import get_place_name_fixer
            from utils.place_name_utils import should_apply_fe_place_fix

            if should_apply_fe_place_fix(source_type):
                fixer = get_place_name_fixer()
                if fixer and fixer.is_supported(source_type):
                    return fixer.fix_place_name(
                        place_name, latitude, longitude, source_type
                    )
    except Exception as e:
        logger.debug(f"[WHEWS] 地名修正失败: {e}")
    return place_name


class WhewsAdapter(BaseAdapter):
    """WeJet WebSocket 适配器（独立解析）。"""

    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)
        path = (source_url or "").rstrip("/").split("/")[-1].split("?")[0].lower()
        self.endpoint = path or "all"

    def _enabled_internal_sources(self) -> Set[str]:
        """根据配置返回当前允许解析的内部 source_type 集合。"""
        from config import Config, is_whews_url

        config = getattr(self, "_config", None) or Config()
        enabled_sources = getattr(self, "_enabled_sources", None) or config.enabled_sources
        if not any(bool(v) and is_whews_url(k) for k, v in (enabled_sources or {}).items()):
            return set()
        msg = getattr(config, "message_config", None)
        if msg is None:
            return set()
        host = ""
        try:
            host = config.get_whews_host()
        except Exception:
            host = ""
        from config import whews_host_supports_cea

        allow_cea = whews_host_supports_cea(host)
        out: Set[str] = set()
        for internal, field in WHEWS_SOURCE_FLAG_FIELD.items():
            if internal in ("cea", "cea-pr") and not allow_cea:
                continue
            if getattr(msg, field, True):
                out.add(internal)
        return out

    @staticmethod
    def _dict_get_ci(d: Any, *keys: str) -> Any:
        """按候选键取值；键名大小写不敏感。"""
        if not isinstance(d, dict) or not keys:
            return None
        wanted = {str(k).lower() for k in keys}
        for k, v in d.items():
            if isinstance(k, str) and k.lower() in wanted:
                return v
        return None

    @classmethod
    def _extract_source_short(cls, frame: Dict[str, Any]) -> str:
        """从帧中提取 WHEWS source 短名（值与键名均兼容大小写）。"""
        src = cls._dict_get_ci(frame, "source")
        if src is not None and str(src).strip():
            return normalize_whews_source(src)
        data = cls._dict_get_ci(frame, "Data", "data")
        if isinstance(data, dict):
            inner = cls._dict_get_ci(data, "source")
            if inner is not None and str(inner).strip():
                return normalize_whews_source(inner)
        return ""

    # ------------------------------------------------------------------
    # 独立字段解析
    # ------------------------------------------------------------------

    def _parse_warning(self, data: Dict[str, Any], source_type: str) -> Optional[Dict[str, Any]]:
        """解析地震预警（jma_eew / cwa_eew / sa_eew / cea / cea-pr / kma_eew）。"""
        place_name = (
            data.get("placeName")
            or data.get("place_name")
            or data.get("location")
            or data.get("loc")
            or data.get("epicenter")
            or data.get("locationDesc")
            or ""
        )
        if source_type == "kma-eew" and not place_name:
            place_name = data.get("placeNameKo") or ""

        shock_time = (
            data.get("shockTime")
            or data.get("shock_time")
            or data.get("createTime")
            or data.get("time")
            or data.get("timestamp")
            or ""
        )
        # kma_eew 可用 epoch 毫秒补全
        if not shock_time and source_type == "kma-eew":
            origin_ms = data.get("originTime")
            if origin_ms is not None:
                try:
                    from datetime import datetime, timezone, timedelta

                    ms = int(origin_ms)
                    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone(timedelta(hours=9)))
                    shock_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError, OSError):
                    pass

        if not place_name and not shock_time:
            event_id = data.get("eventId", data.get("id", "unknown"))
            logger.warning(
                f"[WHEWS] 预警缺少 placeName/shockTime: source_type={source_type}, eventId={event_id}"
            )

        magnitude = _safe_float(data.get("magnitude", 0))
        latitude = _safe_float(data.get("latitude", 0))
        longitude = _safe_float(data.get("longitude", 0))
        depth = _safe_float(data.get("depth", 0))

        place_name = _maybe_fix_place_name(
            str(place_name), latitude, longitude, source_type, is_warning=True
        )

        if shock_time:
            if source_type in WHEWS_UTC9_WARNING:
                shock_time = timezone_utils.jst_to_display(str(shock_time))
            else:
                shock_time = timezone_utils.cst_to_display(str(shock_time))

        intensity = data.get("epiIntensity") or data.get("maxIntensity") or ""
        if source_type == "kma-eew":
            intensity = data.get("maxMmi")
            if intensity is None or intensity == "":
                intensity = data.get("maxMmiLabel") or ""
        if isinstance(intensity, (int, float)):
            intensity = str(intensity)

        updates = data.get("updates", 1)
        if isinstance(updates, str):
            try:
                updates = int(updates)
            except (ValueError, TypeError):
                updates = 1

        result: Dict[str, Any] = {
            "type": "warning",
            "magnitude": magnitude,
            "latitude": latitude,
            "longitude": longitude,
            "depth": depth,
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": _get_organization_name(source_type),
            "event_id": data.get("eventId", data.get("id", "")),
            "intensity": intensity,
            "updates": updates,
            "source_type": source_type,
            "raw_data": data,
        }

        if source_type == "jma":
            if "infoTypeName" in data:
                result["info_type"] = data.get("infoTypeName")
            if "final" in data:
                result["final"] = data.get("final", False)
            if "cancel" in data:
                result["cancel"] = data.get("cancel", False)

        if source_type == "cea-pr" and "province" in data:
            result["province"] = data.get("province")

        if source_type == "cwa-eew" and "locationDesc" in data:
            result["location_desc"] = data.get("locationDesc")

        if source_type == "kma-eew":
            areas = data.get("maxAreasZh") or data.get("affectedAreas")
            if areas:
                result["affected_areas"] = areas
            if data.get("infoType"):
                result["info_type"] = data.get("infoType")

        return result

    def _parse_report(self, data: Dict[str, Any], source_type: str) -> Optional[Dict[str, Any]]:
        """解析地震速报（国际/国内台网与省级）。"""
        if source_type == "cwa":
            place_name = _extract_cwa_location(data)
        else:
            place_name = data.get("placeName", data.get("title", "")) or ""

        shock_time = data.get("shockTime", data.get("createTime", "")) or ""
        if not place_name and not shock_time:
            return None

        raw_mag = data.get("magnitude")
        if raw_mag is None:
            raw_mag = data.get("magnitudel")
        magnitude = _safe_float(raw_mag, 0)
        latitude = _safe_float(data.get("latitude", 0))
        longitude = _safe_float(data.get("longitude", 0))
        depth = _safe_float(data.get("depth", 0))

        place_name = _maybe_fix_place_name(
            str(place_name), latitude, longitude, source_type, is_warning=False
        )

        if shock_time:
            shock_time = timezone_utils.cst_to_display(str(shock_time))

        event_id = _resolve_event_id(
            data, source_type, place_name, shock_time, latitude, longitude
        )
        info_type = (
            data.get("infoTypeName", "")
            if source_type not in ("hko", "usgs")
            else ""
        )

        result: Dict[str, Any] = {
            "type": "report",
            "magnitude": magnitude,
            "latitude": latitude,
            "longitude": longitude,
            "depth": depth,
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": _get_organization_name(source_type),
            "event_id": event_id,
            "source_type": source_type,
            "raw_data": data,
        }
        if info_type:
            result["info_type"] = info_type

        intensity = data.get("maxIntensity") or data.get("epiIntensity")
        if intensity is not None and intensity != "":
            result["intensity"] = intensity if isinstance(intensity, str) else str(intensity)

        if source_type == "hko" and "region" in data:
            result["region"] = data.get("region")
        if source_type == "usgs" and "url" in data:
            result["url"] = data.get("url")

        return result

    def _parse_weather(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析气象预警。"""
        event_id = data.get("id", data.get("eventId", ""))
        if not event_id:
            title = data.get("title", data.get("headline", ""))
            effective = data.get("effective", "")
            if title and effective:
                event_id = f"{title}_{effective}"

        eff_raw = data.get("effective", "")
        eff_display = (
            timezone_utils.flexible_time_to_display(str(eff_raw)) if eff_raw else ""
        )
        return {
            "type": "weather",
            "magnitude": 0,
            "latitude": _safe_float(data.get("latitude", 0)),
            "longitude": _safe_float(data.get("longitude", 0)),
            "depth": 0,
            "place_name": data.get("headline", data.get("title", "")),
            "shock_time": eff_display or str(eff_raw).strip(),
            "organization": _get_organization_name("weatheralarm"),
            "title": data.get("title", data.get("headline", "")),
            "description": data.get("description", ""),
            "warning_type": data.get("type", ""),
            "event_id": event_id,
            "source_type": "weatheralarm",
            "raw_data": data,
        }

    def _parse_volcano(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析日本气象厅火山情报（source=va）。"""
        if not data or not isinstance(data, dict):
            return None
        volcano = str(data.get("volcanoName") or "").strip()
        title = str(
            data.get("kindName") or data.get("title") or data.get("infoKind") or ""
        ).strip()
        description = str(
            data.get("observation")
            or data.get("headline")
            or data.get("activity")
            or ""
        ).strip()
        name = str(data.get("publishingOffice") or "日本气象厅").strip()
        report_time = data.get("reportTime") or data.get("targetTime") or ""
        shock_time = ""
        if report_time:
            try:
                shock_time = timezone_utils.jst_to_display(str(report_time))
            except Exception:
                shock_time = str(report_time).strip()
        if not volcano and not title and not description:
            return None
        return {
            "type": "volcano",
            "source_type": "jma_volcano",
            "title": title,
            "volcano": volcano,
            "description": description,
            "name": name,
            "shock_time": shock_time,
            "place_name": volcano or title,
            "organization": _get_organization_name("jma_volcano"),
            "event_id": str(data.get("id") or ""),
            "latitude": _safe_float(data.get("latitude"), 0),
            "longitude": _safe_float(data.get("longitude"), 0),
            "raw_data": data,
        }

    @staticmethod
    def _clean_ws_text(value: Any) -> str:
        """压缩空白，保留可读标点。"""
        text = str(value or "").strip()
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _append_report_suffix(org: str, updates: Any, level: str = "") -> str:
        """统一追加「第N报」与级别后缀。"""
        out = (org or "").strip()
        if updates not in (None, "", 0, "0"):
            try:
                out = f"{out} 第{int(updates)}报"
            except (TypeError, ValueError):
                out = f"{out} 第{updates}报"
        level = (level or "").strip()
        if level:
            out = f"{out} {level}".strip()
        return out

    @staticmethod
    def _build_tsunami_detail(
        warning_info: Dict[str, Any],
        shock_info: Dict[str, Any],
        forecasts: List[Dict[str, Any]],
        *,
        include_level: bool = False,
    ) -> str:
        """拼接 NMEFC 海啸详细说明（地点 + 浪高 + 预报区）。"""
        parts: List[str] = []
        level = (warning_info.get("level") or "").strip()
        if include_level and level:
            parts.append(level + " ")
        place = (
            (shock_info.get("placeName") or warning_info.get("subtitle") or "").strip()
        )
        if place:
            parts.append(place)
        flist = [x for x in (forecasts or []) if isinstance(x, dict)]
        max_height_str = None
        for f in flist:
            if f.get("maxWaveHeight"):
                max_height_str = f.get("maxWaveHeight")
                break
        if isinstance(max_height_str, str):
            mh = max_height_str.strip()
            if mh and not any(u in mh for u in ("厘米", "cm", "CM", "米", "m", "M")):
                max_height_str = f"{mh}厘米"
        region_bits = []
        for f in flist[:8]:
            # 文档：forecasts[i] 含 province / forecastArea / forecastPoint / ETA / maxWaveHeight / warningLevel
            prov = (
                str(f.get("province") or "").strip()
                or str(f.get("forecastArea") or "").strip()
                or str(f.get("forecastPoint") or "").strip()
                or str(f.get("warningLevel") or "").strip()
            )
            eta = str(f.get("estimatedArrivalTime") or "").strip()
            if not prov:
                continue
            region_bits.append(f"{prov}({eta})" if eta else prov)
        if max_height_str or region_bits:
            if parts:
                parts.append("。")
            if max_height_str:
                parts.append(f"预计浪高约{max_height_str}。")
            if region_bits:
                parts.append("、".join(region_bits))
        return "".join(parts).strip() or (place or level or "海啸信息")

    @staticmethod
    def _fetch_tsunami_remarks(html_url: str) -> str:
        """从 details.htmlUrl 拉取备注正文。"""
        if not html_url or not isinstance(html_url, str):
            return ""
        try:
            req = urllib.request.Request(
                html_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                raw = resp.read()
            html = raw.decode("utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"[WHEWS][海啸] 拉取 htmlUrl 失败: {html_url[:60]}..., {e}")
            return ""
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return ""
        try:
            soup = BeautifulSoup(html, "html.parser")
            full_text = soup.get_text(separator="\n", strip=True)
        except Exception as e:
            logger.debug(f"[WHEWS][海啸] 解析 HTML 失败: {e}")
            return ""
        if not full_text:
            return ""

        def _strip_note_section(s: str) -> str:
            for note_marker in ("注：", "注:"):
                if note_marker in s:
                    s = s.split(note_marker)[0].strip()
                    break
            return s

        for marker in ("|| 备注:", "备注:", "|| 备注：", "备注："):
            idx = full_text.find(marker)
            if idx >= 0:
                remarks = full_text[idx + len(marker) :].strip()
                remarks = re.sub(r"\n+", "。", remarks)
                remarks = re.sub(r"\s+", " ", remarks).strip()
                remarks = _strip_note_section(remarks)
                return remarks if remarks else ""
        full_clean = re.sub(r"\n+", "。", re.sub(r"\s+", " ", full_text).strip())
        return _strip_note_section(full_clean)

    def _parse_tsunami(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析自然资源部海啸预警（/ws/tsunami，嵌套结构，UTC+8）。"""
        if not data or not isinstance(data, dict):
            return None
        warning_info = data.get("warningInfo") or {}
        if not isinstance(warning_info, dict):
            warning_info = {}
        time_info = data.get("timeInfo") or {}
        if not isinstance(time_info, dict):
            time_info = {}
        shock_info = data.get("shockInfo") or {}
        if not isinstance(shock_info, dict):
            shock_info = {}
        details = data.get("details") or {}
        if not isinstance(details, dict):
            details = {}
        forecasts = data.get("forecasts") or []
        water_level_monitoring = data.get("waterLevelMonitoring") or []
        shock_time = shock_info.get("shockTime") or time_info.get("alarmDate") or ""
        if not shock_time:
            return None
        shock_time = timezone_utils.cst_to_display(str(shock_time))
        organization = warning_info.get("orgUnit") or _get_organization_name("tsunami")
        batch = str(details.get("batch") or "").strip()
        title = (warning_info.get("title") or "海啸信息").strip()
        level = (warning_info.get("level") or "").strip()
        # 标头：机构 + 第N报 + 级别（信息/蓝/黄/橙/红/解除），与海外海啸一致
        organization = self._append_report_suffix(organization, batch or None, level)

        place_name = self._build_tsunami_detail(
            warning_info, shock_info, forecasts, include_level=False
        )
        logo_url = (details.get("logoUrl") or "").strip()
        if logo_url and not logo_url.startswith(("http://", "https://")):
            html_url_for_base = (details.get("htmlUrl") or "").strip()
            if html_url_for_base:
                logo_url = urllib.parse.urljoin(html_url_for_base, logo_url)
        if logo_url and "obs.nmefc.cn" in logo_url:
            try:
                parsed_logo = urllib.parse.urlparse(logo_url)
                path_decoded = urllib.parse.unquote(parsed_logo.path, encoding="utf-8")
                path_encoded = urllib.parse.quote(path_decoded, safe="/", encoding="utf-8")
                scheme = "https" if parsed_logo.scheme == "http" else parsed_logo.scheme
                logo_url = urllib.parse.urlunparse(
                    (
                        scheme,
                        parsed_logo.netloc,
                        path_encoded,
                        parsed_logo.params,
                        parsed_logo.query,
                        parsed_logo.fragment,
                    )
                )
            except Exception:
                pass

        maps = details.get("maps") if isinstance(details.get("maps"), dict) else {}
        result: Dict[str, Any] = {
            "type": "report",
            "is_tsunami": True,
            "source_type": "tsunami",
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": organization,
            "magnitude": _safe_float(shock_info.get("magnitude"), 0),
            "depth": _safe_float(shock_info.get("depth"), 0),
            "latitude": _safe_float(shock_info.get("latitude"), 0),
            "longitude": _safe_float(shock_info.get("longitude"), 0),
            "event_id": data.get("id") or data.get("code") or "",
            "tsunami_code": data.get("code", ""),
            "tsunami_warning_level": level,
            "tsunami_level": level,
            "tsunami_warning_title": title,
            "tsunami_warning_subtitle": (warning_info.get("subtitle") or "").strip(),
            "tsunami_place": (
                (shock_info.get("placeName") or warning_info.get("subtitle") or "").strip()
            ),
            "tsunami_update_time": (time_info.get("updateDate") or "").strip(),
            "tsunami_alarm_time": (time_info.get("alarmDate") or "").strip(),
            "tsunami_forecasts": forecasts if isinstance(forecasts, list) else [],
            "tsunami_water_level_monitoring": (
                water_level_monitoring if isinstance(water_level_monitoring, list) else []
            ),
            "tsunami_maps": maps,
            "raw_data": data,
        }
        if logo_url:
            result["logo_url"] = logo_url
        html_url = (details.get("htmlUrl") or "").strip()
        if html_url:
            result["detail_url"] = html_url
            remarks = self._fetch_tsunami_remarks(html_url)
            if remarks:
                result["tsunami_remarks"] = remarks
        return result

    def _parse_by_internal(
        self, data_obj: Dict[str, Any], internal: str
    ) -> Optional[Dict[str, Any]]:
        """按内部 source_type 分发到独立解析函数。"""
        if internal == "weatheralarm":
            return self._parse_weather(data_obj)
        if internal == "tsunami":
            return self._parse_tsunami(data_obj)
        if internal in ("ntwc", "ptwc", "incois"):
            return self._parse_overseas_tsunami(data_obj, internal)
        if internal == "jma_tsunami":
            return self._parse_jma_tsunami(data_obj)
        if internal == "jma_volcano":
            return self._parse_volcano(data_obj)
        if internal in WHEWS_WARNING_INTERNAL:
            return self._parse_warning(data_obj, internal)
        return self._parse_report(data_obj, internal)

    @staticmethod
    def _localize_overseas_tsunami_level(level: str) -> str:
        """将 NTWC/PTWC/INCOIS 英文等级译为中文展示名。"""
        raw = (level or "").strip()
        if not raw:
            return ""
        key = re.sub(r"[\s_\-]+", "", raw).lower()
        mapping = {
            "information": "信息",
            "info": "信息",
            "advisory": "咨询",
            "watch": "注意报",
            "warning": "警报",
            "alert": "警报",  # INCOIS Alert
            "threat": "威胁",
            "cancellation": "解除",
            "cancel": "解除",
            "cancelled": "解除",
            "canceled": "解除",
        }
        return mapping.get(key, raw)

    @staticmethod
    def _normalize_overseas_place(place: str) -> str:
        """清理 CAP/公报式地点前缀（如 in Colombia）。"""
        text = (place or "").strip()
        if not text:
            return ""
        text = re.sub(
            r"^(?:in|near|off(?:\s+the)?|offshore(?:\s+of)?)\s+",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip(" ,.-")
        return text or (place or "").strip()

    @staticmethod
    def _localize_jma_tsunami_kind(kind: str) -> str:
        """将 JMA 海啸警报种类译为中文展示名。"""
        raw = (kind or "").strip()
        if not raw:
            return ""
        mapping = {
            "大津波警報": "大海啸警报",
            "津波警報": "海啸警报",
            "津波注意報": "海啸注意报",
            "津波予報": "海啸预报",
            "津波情報": "海啸情报",
        }
        return mapping.get(raw, raw)

    def _build_jma_tsunami_detail(
        self,
        areas: List[Dict[str, Any]],
        *,
        title: str = "",
        headline: str = "",
        cancel: bool = False,
    ) -> str:
        """按区域拼 JMA 海啸正文：级别 + 浪高 + 区域(到达时刻)。"""
        if cancel:
            lead = "解除"
        else:
            lead = ""
        flist = [a for a in (areas or []) if isinstance(a, dict)]
        kind_rank = {
            "大津波警報": 4,
            "津波警報": 3,
            "津波注意報": 2,
            "津波予報": 1,
        }
        top_kind = ""
        top_rank = -1
        max_height_desc = ""
        max_height_rank = -1
        for a in flist:
            kind = str(a.get("kind") or "").strip()
            rank = kind_rank.get(kind, 0)
            if rank > top_rank:
                top_rank = rank
                top_kind = kind
            mh = str(a.get("maxHeightDesc") or "").strip()
            hv = str(a.get("maxHeight") or "").strip()
            desc = ""
            if mh:
                desc = mh
            elif hv:
                desc = hv if re.search(r"[mｍメートル米]", hv, re.I) else f"{hv}m"
            if desc and rank >= max_height_rank:
                max_height_rank = rank
                max_height_desc = desc
        parts: List[str] = []
        kind_zh = self._localize_jma_tsunami_kind(top_kind)
        if lead:
            parts.append(lead + " ")
        elif kind_zh:
            parts.append(kind_zh + " ")
        if max_height_desc:
            parts.append(f"预计浪高约{max_height_desc}。")
        region_bits: List[str] = []
        for a in flist[:8]:
            name = str(a.get("name") or "").strip()
            if not name:
                continue
            arrival = str(a.get("arrivalTime") or "").strip()
            condition = str(a.get("condition") or "").strip()
            eta = ""
            if arrival:
                try:
                    dt_str = timezone_utils.jst_to_display(arrival)
                    eta = dt_str.split(" ")[1][:5] if " " in dt_str else arrival
                except Exception:
                    eta = arrival[-8:-3] if len(arrival) >= 8 else arrival
            elif condition:
                eta = condition
            region_bits.append(f"{name}({eta})" if eta else name)
        if region_bits:
            parts.append("、".join(region_bits))
        detail = "".join(parts).strip()
        if detail:
            return detail
        fallback = self._clean_ws_text(headline) or self._clean_ws_text(title)
        return fallback or "海啸信息"

    def _parse_overseas_tsunami(
        self, data: Dict[str, Any], source_type: str
    ) -> Optional[Dict[str, Any]]:
        """解析 NTWC / PTWC / INCOIS 海啸（扁平帧，UTC+8）。"""
        if not data or not isinstance(data, dict):
            return None
        shock_time_raw = data.get("shockTime") or data.get("issueTime") or ""
        if not shock_time_raw:
            return None
        # 文档：shockTime / issueTime 均为 UTC+8
        shock_time = timezone_utils.cst_to_display(str(shock_time_raw))
        issue_time_raw = str(data.get("issueTime") or "").strip()
        issue_time = (
            timezone_utils.cst_to_display(issue_time_raw) if issue_time_raw else ""
        )
        level_raw = str(data.get("level") or "").strip()
        level = self._localize_overseas_tsunami_level(level_raw)
        headline = self._clean_ws_text(data.get("headline") or data.get("title"))
        description = self._clean_ws_text(data.get("description"))
        instruction = self._clean_ws_text(data.get("instruction"))
        # 地点单独存，避免 FE/翻译把「地点+标题」整段覆盖
        place = self._normalize_overseas_place(str(data.get("placeName") or ""))
        updates = data.get("updates")
        org = self._append_report_suffix(
            _get_organization_name(source_type), updates, level
        )
        place_name = place or level or "海啸信息"
        event_id = str(data.get("eventId") or data.get("id") or "").strip()
        maps = data.get("maps") if isinstance(data.get("maps"), dict) else {}
        result: Dict[str, Any] = {
            "type": "report",
            "is_tsunami": True,
            "source_type": source_type,
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": org,
            "magnitude": _safe_float(data.get("magnitude"), 0),
            "depth": _safe_float(data.get("depth"), 0),
            "latitude": _safe_float(data.get("latitude"), 0),
            "longitude": _safe_float(data.get("longitude"), 0),
            "event_id": event_id,
            "tsunami_level": level,
            "tsunami_level_raw": level_raw,
            "tsunami_warning_level": level,  # 统一走级别着色
            "tsunami_headline": headline,
            "tsunami_description": description,
            "tsunami_instruction": instruction,
            "tsunami_mag_type": str(data.get("magType") or "").strip(),
            "tsunami_issue_time": issue_time,
            "tsunami_bulletin_type": str(data.get("bulletinType") or "").strip(),
            "tsunami_maps": maps,
            "raw_data": data,
        }
        for url_key, out_key in (
            ("capUrl", "cap_url"),
            ("bulletinUrl", "bulletin_url"),
            ("detailUrl", "detail_url"),
        ):
            url = str(data.get(url_key) or "").strip()
            if url:
                result[out_key] = url
        return result

    def _parse_jma_tsunami(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析日本气象厅海啸预警（/ws/jma_tsunami，UTC+9）。"""
        if not data or not isinstance(data, dict):
            return None
        create_time = data.get("createTime") or ""
        if not create_time:
            return None
        # 文档：时间为 UTC+9
        shock_time = timezone_utils.jst_to_display(str(create_time))
        title = str(data.get("title") or "").strip()
        headline = self._clean_ws_text(data.get("headline"))
        info_type = str(data.get("infoTypeName") or "").strip()
        cancel = bool(data.get("cancel")) or info_type == "取消"
        updates = data.get("updates")
        areas_raw = data.get("areas") or []
        areas: List[Dict[str, Any]] = (
            [a for a in areas_raw if isinstance(a, dict)]
            if isinstance(areas_raw, list)
            else []
        )
        kind_rank = {
            "大津波警報": 4,
            "津波警報": 3,
            "津波注意報": 2,
            "津波予報": 1,
        }
        top_kind = ""
        top_rank = -1
        for a in areas:
            kind = str(a.get("kind") or "").strip()
            rank = kind_rank.get(kind, 0)
            if rank > top_rank:
                top_rank = rank
                top_kind = kind
        level_zh = "解除" if cancel else self._localize_jma_tsunami_kind(top_kind)
        org = self._append_report_suffix(
            _get_organization_name("jma_tsunami"), updates, level_zh or info_type
        )
        place_name = self._build_jma_tsunami_detail(
            areas, title=title, headline=headline, cancel=cancel
        )
        return {
            "type": "report",
            "is_tsunami": True,
            "source_type": "jma_tsunami",
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": org,
            "magnitude": 0,
            "depth": 0,
            "latitude": 0,
            "longitude": 0,
            "event_id": str(data.get("id") or "").strip(),
            "tsunami_cancel": cancel,
            "tsunami_headline": headline,
            "tsunami_title": title,
            "tsunami_info_type": info_type,
            "tsunami_level": level_zh,
            "tsunami_warning_level": level_zh,
            "tsunami_areas": areas,
            "raw_data": data,
        }

    # ------------------------------------------------------------------
    # 帧入口
    # ------------------------------------------------------------------

    def _parse_one_frame(self, frame: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析单帧业务数据。"""
        if not isinstance(frame, dict):
            return None
        msg_type = normalize_whews_source(self._dict_get_ci(frame, "type") or "")
        if msg_type in ("heartbeat", "ping", "pong"):
            return None
        data_obj = self._dict_get_ci(frame, "Data", "data")
        if data_obj is None:
            return None

        short = self._extract_source_short(frame)
        if not short and self.endpoint in ("cea_all", "cea", "cea-pr"):
            short = "cea" if self.endpoint != "cea-pr" else "cea-pr"
            if isinstance(data_obj, dict) and self._dict_get_ci(data_obj, "province"):
                short = "cea-pr"
        if not short and self.endpoint == "cenc":
            short = "cenc"
        if not short:
            logger.debug("[WHEWS] 无法识别 source，跳过")
            return None

        if short in WHEWS_SKIP_SOURCES:
            logger.debug(f"[WHEWS] source={short}（JMA 情报）由 P2PQuake 负责，跳过")
            return None

        internal = resolve_whews_internal_source(short)
        if not internal:
            logger.info(f"[WHEWS] 未支持的 source={short}，跳过")
            return None

        enabled = self._enabled_internal_sources()
        if internal not in enabled:
            logger.debug(f"[WHEWS] source={short}({internal}) 未勾选解析，跳过")
            return None

        if not isinstance(data_obj, dict) or not data_obj:
            return None

        parsed = self._parse_by_internal(data_obj, internal)
        if not parsed:
            return None
        parsed["fanstudio"] = False
        parsed["whews"] = True
        # 溯源：规范化短名写入 raw 旁注，便于调试
        parsed.setdefault("update_source", short)
        return parsed

    def parse_all_sources(self, raw_data: Any) -> List[Dict[str, Any]]:
        """解析首连补发的数组帧。"""
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if not isinstance(data, list):
                one = self._parse_one_frame(data) if isinstance(data, dict) else None
                return [one] if one else []
            results: List[Dict[str, Any]] = []
            for item in data:
                parsed = self._parse_one_frame(item) if isinstance(item, dict) else None
                if parsed:
                    results.append(parsed)
            if results:
                logger.info(f"[WHEWS] 首连数组解析出 {len(results)} 条")
            return results
        except Exception as e:
            logger.error(f"[WHEWS] parse_all_sources 失败: {e}")
            return []

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析单条消息；若为数组则返回第一条有效数据（完整列表走 parse_all_sources）。"""
        try:
            if isinstance(raw_data, str):
                try:
                    data = json.loads(raw_data)
                except (json.JSONDecodeError, TypeError, ValueError):
                    logger.debug("[WHEWS] 非 JSON 字符串，跳过")
                    return None
            else:
                data = raw_data
            if isinstance(data, list):
                all_parsed = self.parse_all_sources(data)
                return all_parsed[0] if all_parsed else None
            if isinstance(data, dict):
                return self._parse_one_frame(data)
            return None
        except Exception as e:
            logger.error(f"[WHEWS] parse 失败: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型。"""
        return data.get("type", "report") if isinstance(data, dict) else "report"
