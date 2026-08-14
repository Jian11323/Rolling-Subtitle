#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地理距离计算与区域过滤。"""

import math
import re
from typing import Any, Dict, List, Optional, Set


# 地球平均半径（公里），用于 haversine 距离计算
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """计算两点间大圆距离（公里）。"""
    r = 6371.0  # 地球平均半径（公里）
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))  # haversine 大圆距离


def event_coordinates(parsed_data: Dict[str, Any]) -> Optional[tuple]:
    """从解析结果提取 (lat, lon)。"""
    if not isinstance(parsed_data, dict):
        return None
    try:
        lat = float(parsed_data.get("latitude") or 0)
        lon = float(parsed_data.get("longitude") or 0)
    except (TypeError, ValueError):
        return None
    if lat == 0 and lon == 0:
        return None  # 0,0 视为无效坐标
    return lat, lon


def passes_magnitude_filter(parsed_data: Dict[str, Any], config: Any, message_type: str) -> bool:
    """震级过滤：0 表示不启用。预警/气象不受震级限制。"""
    mc = getattr(config, "message_config", None)
    if mc is None:
        return True
    if message_type in ("warning", "weather"):
        return True  # 预警与气象预警不受震级过滤限制
    try:
        min_mag = float(getattr(mc, "min_report_magnitude", 0) or 0)
    except (TypeError, ValueError):
        min_mag = 0.0
    if min_mag <= 0:
        return True  # 0 表示不限制震级
    try:
        mag = float(parsed_data.get("magnitude") or 0)
    except (TypeError, ValueError):
        return True
    return mag >= min_mag


def passes_geo_filter(parsed_data: Dict[str, Any], config: Any) -> bool:
    """距离过滤：未启用或缺少坐标时放行。"""
    mc = getattr(config, "message_config", None)
    if mc is None or not getattr(mc, "geo_filter_enabled", False):
        return True
    coords = event_coordinates(parsed_data)
    if coords is None:
        return True
    try:
        center_lat = float(getattr(mc, "geo_filter_latitude", 0))
        center_lon = float(getattr(mc, "geo_filter_longitude", 0))
        radius = float(getattr(mc, "geo_filter_radius_km", 1000) or 1000)
    except (TypeError, ValueError):
        return True
    if radius <= 0:
        return True
    dist = haversine_km(center_lat, center_lon, coords[0], coords[1])
    return dist <= radius  # 在半径内则通过


_REGION_SPLIT_RE = re.compile(r"[,，;；、\s]+")
# 单字关键字（如「海」「州」）易在标题中误命中
_MIN_REGION_KEYWORD_LEN = 2
_REGION_SUFFIXES = (
    "自治州",
    "自治县",
    "自治区",
    "地区",
    "林区",
    "市",
    "县",
    "区",
    "旗",
    "盟",
    "州",
)
_LEVEL_CN = {
    "蓝": "blue",
    "蓝色": "blue",
    "黄": "yellow",
    "黄色": "yellow",
    "橙": "orange",
    "橙色": "orange",
    "红": "red",
    "红色": "red",
}
_LEVEL_EN = {
    "blue": "blue",
    "yellow": "yellow",
    "orange": "orange",
    "red": "red",
}
_LEVEL_PATTERN = re.compile(
    r"(红色|橙色|黄色|蓝色|白色|red|orange|yellow|blue)",
    re.IGNORECASE,
)


def _parse_region_keywords(raw: str) -> List[str]:
    """解析用户输入的地区关键字列表（过短关键字易误伤，至少 2 字）。"""
    text = (raw or "").strip()
    if not text:
        return []
    return [p for p in _REGION_SPLIT_RE.split(text) if p and len(p) >= _MIN_REGION_KEYWORD_LEN]


def _region_core(name: str) -> str:
    """去掉市/县/区等后缀，便于「阳江」与「阳江市」互相匹配。"""
    s = (name or "").strip()
    if not s:
        return ""
    for suf in _REGION_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def _region_matches(keyword: str, haystack: str) -> bool:
    """地区关键字是否命中文本（支持有无市县区后缀）。"""
    kw = (keyword or "").strip()
    if not kw or not haystack or len(kw) < _MIN_REGION_KEYWORD_LEN:
        return False
    if kw in haystack:
        return True
    core = _region_core(kw)
    if (
        core
        and core != kw
        and len(core) >= _MIN_REGION_KEYWORD_LEN
        and core in haystack
    ):
        return True
    return False


def _weather_search_text(parsed_data: Dict[str, Any]) -> str:
    """汇总气象预警可用于地区匹配的文本。"""
    raw = parsed_data.get("raw_data") if isinstance(parsed_data.get("raw_data"), dict) else {}
    parts = [
        parsed_data.get("place_name"),
        parsed_data.get("title"),
        parsed_data.get("description"),
        parsed_data.get("headline"),
        raw.get("headline"),
        raw.get("title"),
        raw.get("description"),
        raw.get("senderName"),
        raw.get("areaDesc"),
        raw.get("area"),
    ]
    return " ".join(str(p).strip() for p in parts if p)


def extract_weather_level(parsed_data: Dict[str, Any]) -> Optional[str]:
    """
    从气象预警数据提取等级：blue / yellow / orange / red。
    无法识别时返回 None。
    """
    if not isinstance(parsed_data, dict):
        return None
    raw = parsed_data.get("raw_data") if isinstance(parsed_data.get("raw_data"), dict) else {}
    candidates = [
        parsed_data.get("warning_type"),
        parsed_data.get("warning_level"),
        parsed_data.get("severity"),
        parsed_data.get("title"),
        parsed_data.get("place_name"),
        parsed_data.get("description"),
        raw.get("type"),
        raw.get("severity"),
        raw.get("headline"),
        raw.get("title"),
        raw.get("description"),
    ]
    text = " ".join(str(c).strip() for c in candidates if c)
    if not text:
        return None

    # type 编码常见形式：11B20_yellow / xxx_orange
    m_code = re.search(r"(?:_|/|-)?(blue|yellow|orange|red)\b", text, re.I)
    if m_code:
        return _LEVEL_EN.get(m_code.group(1).lower())

    m = _LEVEL_PATTERN.search(text)
    if not m:
        return None
    token = m.group(1)
    mapped = _LEVEL_CN.get(token) or _LEVEL_EN.get(token.lower())
    if mapped in ("blue", "yellow", "orange", "red"):
        return mapped
    return None


_LEVEL_RANK = {
    "blue": 1,
    "yellow": 2,
    "orange": 3,
    "red": 4,
}

# 档位 → 最低允许等级（含该等级及以上）
_WEATHER_LEVEL_FILTER_MIN = {
    "none": 0,
    "yellow_up": 2,
    "orange_up": 3,
    "red": 4,
}


def _allowed_weather_levels(mc: Any) -> Optional[Set[str]]:
    """
    根据档位返回允许的等级集合；不过滤时返回 None。
    none / yellow_up / orange_up / red
    """
    mode = (getattr(mc, "weather_level_filter", "none") or "none").strip().lower()
    min_rank = _WEATHER_LEVEL_FILTER_MIN.get(mode, 0)
    if min_rank <= 0:
        return None
    return {name for name, rank in _LEVEL_RANK.items() if rank >= min_rank}


def passes_weather_filter(parsed_data: Dict[str, Any], config: Any, message_type: str) -> bool:
    """气象预警地区/等级过滤；非气象消息直接放行。"""
    if message_type != "weather" and parsed_data.get("source_type") != "weatheralarm":
        return True
    mc = getattr(config, "message_config", None)
    if mc is None:
        return True

    # 地区过滤：启用且关键字非空时，标题/描述等须命中至少一个地区
    if getattr(mc, "weather_region_filter_enabled", False):
        keywords = _parse_region_keywords(getattr(mc, "weather_region_filter", "") or "")
        if keywords:
            haystack = _weather_search_text(parsed_data)
            if not any(_region_matches(kw, haystack) for kw in keywords):
                return False

    # 等级档位：不过滤 / 黄及以上 / 橙及以上 / 仅红；无法识别等级时放行
    allowed = _allowed_weather_levels(mc)
    if allowed is not None:
        level = extract_weather_level(parsed_data)
        if level is not None and level not in allowed:
            return False

    return True


def should_accept_message(
    parsed_data: Dict[str, Any],
    config: Any,
    message_type: str,
) -> bool:
    """综合震级、区域与气象预警过滤。"""
    if not passes_magnitude_filter(parsed_data, config, message_type):
        return False
    if not passes_geo_filter(parsed_data, config):
        return False
    if not passes_weather_filter(parsed_data, config, message_type):
        return False
    return True
