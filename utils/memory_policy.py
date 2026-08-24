#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
性能模式内存策略：目标常驻占用（Windows 任务管理器 Working Set 量级，非精确保证）。

- 低配（CPU）：约 ≤50MB
- 标准（CPU）：约 ≤80MB
- 高配全开（OpenGL）：约 ≤120MB
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

PERFORMANCE_MODE_LOW = "low"
PERFORMANCE_MODE_STANDARD = "standard"
PERFORMANCE_MODE_HIGH = "high"
PERFORMANCE_MODE_CUSTOM = "custom"

MEMORY_TARGET_MB: Dict[str, int] = {
    PERFORMANCE_MODE_LOW: 50,
    PERFORMANCE_MODE_STANDARD: 80,
    PERFORMANCE_MODE_HIGH: 120,  # OpenGL 全开目标
}

# OpenGL / GPU 渲染单独上限（高配与自定义选 GPU 时参考）
OPENGL_MEMORY_TARGET_MB = 120

# 消息队列 / 滚动缓冲容量
QUEUE_BUFFER_LIMITS: Dict[str, Dict[str, int]] = {
    PERFORMANCE_MODE_LOW: {"message_queue_maxsize": 24, "message_buffer_max_size": 12},
    PERFORMANCE_MODE_STANDARD: {"message_queue_maxsize": 45, "message_buffer_max_size": 20},
    PERFORMANCE_MODE_HIGH: {"message_queue_maxsize": 60, "message_buffer_max_size": 28},
}

# 纹理 / 图片缓存上限（OpenGL 高配仍收紧，避免纹理堆叠超 120MB）
GUI_CACHE_LIMITS: Dict[str, Dict[str, int]] = {
    PERFORMANCE_MODE_LOW: {"image_cache_max": 4, "text_texture_cache_max": 3},
    PERFORMANCE_MODE_STANDARD: {"image_cache_max": 6, "text_texture_cache_max": 5},
    PERFORMANCE_MODE_HIGH: {"image_cache_max": 6, "text_texture_cache_max": 5},
}

_WARNING_STORE_KEYS = frozenset(
    {
        "type",
        "source_type",
        "event_id",
        "place_name",
        "shock_time",
        "magnitude",
        "latitude",
        "longitude",
        "depth",
        "intensity",
        "updates",
        "organization",
        "cancel",
        "fanstudio",
        "whews",
        "jian",
        "eqsc",
        "epiIntensity",
        "epi_intensity",
        "wolfx_warn_areas",
        "infoTypeName",
        "isFinal",
        "isCancel",
        "isTraining",
        "isPLUM",
        "is_tsunami",
        "logo_url",
        "title",
    }
)

_WEATHER_STORE_KEYS = frozenset(
    {
        "type",
        "source_type",
        "headline",
        "title",
        "place_name",
        "level",
        "color",
        "img",
        "image",
        "icon",
        "fanstudio",
        "whews",
        "eqsc",
    }
)

_WEATHER_RAW_KEYS = frozenset(
    {"img", "image", "icon", "headline", "title", "type", "level", "description"}
)


def normalize_performance_mode(mode: Any) -> str:
    m = str(mode or PERFORMANCE_MODE_STANDARD).strip().lower()
    if m in MEMORY_TARGET_MB:
        return m
    if m == PERFORMANCE_MODE_CUSTOM:
        return PERFORMANCE_MODE_CUSTOM
    return PERFORMANCE_MODE_STANDARD


def get_memory_target_mb(mode: Any) -> int:
    m = normalize_performance_mode(mode)
    if m == PERFORMANCE_MODE_CUSTOM:
        return OPENGL_MEMORY_TARGET_MB
    return MEMORY_TARGET_MB.get(m, 80)


def get_opengl_memory_target_mb() -> int:
    """GPU（OpenGL）渲染目标常驻上限。"""
    return OPENGL_MEMORY_TARGET_MB


def should_fetch_jian_alllist(mode: Any) -> bool:
    """低配/标准不拉历史列表，减轻建连瞬间内存尖峰。"""
    return normalize_performance_mode(mode) == PERFORMANCE_MODE_HIGH


def limit_bulk_parsed_messages(
    items: List[Dict[str, Any]],
    mode: Any,
) -> List[Dict[str, Any]]:
    """
    限制 initial_all / alllist 等批量快照入队数量。
    - 低配：跳过（仅等实时推送）
    - 标准：每 source_type 保留最新 1 条
    - 高配：总量上限 28 条
    """
    if not items:
        return []
    perf = normalize_performance_mode(mode)
    if perf == PERFORMANCE_MODE_LOW:
        return []
    if perf == PERFORMANCE_MODE_STANDARD:
        latest: Dict[str, Dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            st = str(item.get("source_type") or item.get("type") or "default").strip().lower()
            latest[st] = item
        return list(latest.values())
    cap = 28
    if len(items) <= cap:
        return [i for i in items if isinstance(i, dict)]
    return [i for i in items[-cap:] if isinstance(i, dict)]


def slim_parsed_for_storage(
    parsed_data: Optional[Dict[str, Any]],
    message_type: str,
) -> Optional[Dict[str, Any]]:
    """入队前剔除 raw_data 等大字段，降低缓冲常驻占用。"""
    if not isinstance(parsed_data, dict):
        return None
    mt = str(message_type or parsed_data.get("type") or "report").strip().lower()
    if mt == "warning":
        out = {k: parsed_data[k] for k in _WARNING_STORE_KEYS if k in parsed_data}
        return out or None
    if mt == "weather":
        out = {k: parsed_data[k] for k in _WEATHER_STORE_KEYS if k in parsed_data}
        raw = parsed_data.get("raw_data")
        if isinstance(raw, dict):
            slim_raw = {k: raw[k] for k in _WEATHER_RAW_KEYS if k in raw}
            if slim_raw:
                out["raw_data"] = slim_raw
        return out or None
    # 速报默认仅溯源字段；特殊类型由 main_window 另行扩展
    return None
