#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EMSC 过期过滤与去重（对齐服务器 fused_list_v2.py）。

- 发震时刻超过 EMSC_WSS_MAX_AGE_HOURS（默认 1 小时）丢弃
- 去重库：最新 N 条落盘；同 ID+MD5 / 同 MD5 视为重复不推送；
  同 ID 但 MD5 不同视为参数修订，允许推送并更新库
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Optional

from utils.logger import get_logger

logger = get_logger()

# 与 fused_list_v2.Config 对齐
EMSC_WSS_MAX_AGE_HOURS = 1.0
EMSC_DEDUP_CACHE_SIZE = 20
EMSC_DEDUP_CACHE_FILE = "emsc_dedup_cache.json"


def _cache_dir() -> Path:
    """与 settings / 日志同目录：AppData/Roaming/subtitl。"""
    return Path.home() / "AppData" / "Roaming" / "subtitl"


def parse_emsc_origin_utc(time_value: Any) -> Optional[datetime]:
    """将 EMSC properties.time（ISO 或 epoch 秒/毫秒）解析为 UTC aware datetime。"""
    if time_value is None or time_value == "":
        return None
    try:
        if isinstance(time_value, (int, float)):
            ts = float(time_value)
            if ts > 1e12:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        s = str(time_value).strip()
        if not s:
            return None
        # 纯数字字符串按 epoch 处理
        if s.isdigit() or (s.replace(".", "", 1).isdigit() and s.count(".") <= 1):
            ts = float(s)
            if ts > 1e12:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        # ISO8601
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def emsc_age_hours(origin_dt: Optional[datetime], now: Optional[datetime] = None) -> float:
    """发震时刻距「现在」的年龄（小时）；无法解析视为无穷大。"""
    if origin_dt is None:
        return float("inf")
    if origin_dt.tzinfo is None:
        origin_utc = origin_dt.replace(tzinfo=timezone.utc)
    else:
        origin_utc = origin_dt.astimezone(timezone.utc)
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    else:
        ref = ref.astimezone(timezone.utc)
    return (ref - origin_utc).total_seconds() / 3600.0


def is_emsc_event_expired(
    time_value: Any,
    *,
    max_age_hours: float = EMSC_WSS_MAX_AGE_HOURS,
) -> bool:
    """发震时刻是否超出允许窗口。"""
    origin = parse_emsc_origin_utc(time_value)
    age = emsc_age_hours(origin)
    return age > max_age_hours


def emsc_content_md5(
    event_id: str,
    shock_time: str,
    magnitude: float,
    latitude: float,
    longitude: float,
    depth: float,
) -> str:
    """对 ID+发震时刻+震级+坐标+深度做 MD5（与 fused_list 口径一致）。"""
    try:
        raw = "|".join(
            [
                str(event_id or ""),
                str(shock_time or ""),
                str(magnitude if magnitude is not None else ""),
                f"{float(latitude or 0):.3f}",
                f"{float(longitude or 0):.3f}",
                f"{float(depth or 0):.1f}",
            ]
        )
        return hashlib.md5(raw.encode("utf-8")).hexdigest()
    except (ValueError, TypeError):
        return ""


class EmscDedupStore:
    """EMSC 去重库：最新 N 条落盘；ID + MD5 校验。"""

    _lock = threading.Lock()
    _records: Deque[Dict[str, Any]] = deque()
    _by_id: Dict[str, Dict[str, Any]] = {}
    _by_md5: Dict[str, Dict[str, Any]] = {}
    _loaded = False

    @classmethod
    def _cache_path(cls) -> Path:
        return _cache_dir() / EMSC_DEDUP_CACHE_FILE

    @classmethod
    def _rebuild_index(cls) -> None:
        cls._by_id = {}
        cls._by_md5 = {}
        for rec in cls._records:
            eid = rec.get("id") or ""
            md5 = rec.get("md5") or ""
            if eid:
                cls._by_id[eid] = rec
            if md5:
                cls._by_md5[md5] = rec

    @classmethod
    def load(cls) -> None:
        """启动时从磁盘加载去重库。"""
        path = cls._cache_path()
        with cls._lock:
            cls._records = deque(maxlen=EMSC_DEDUP_CACHE_SIZE)
            cls._by_id.clear()
            cls._by_md5.clear()
            cls._loaded = True
            if not path.exists():
                logger.debug(
                    f"EMSC去重库: 无缓存文件，新建（最多 {EMSC_DEDUP_CACHE_SIZE} 条）"
                )
                return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    return
                kept = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    if not item.get("id") or not item.get("md5"):
                        continue
                    kept.append(
                        {
                            "id": str(item.get("id") or ""),
                            "md5": str(item.get("md5") or ""),
                            "o_time": str(item.get("o_time") or ""),
                            "mag": str(item.get("mag") or ""),
                            "lat": item.get("lat"),
                            "lon": item.get("lon"),
                            "depth": item.get("depth"),
                        }
                    )
                for rec in kept[-EMSC_DEDUP_CACHE_SIZE:]:
                    cls._records.append(rec)
                cls._rebuild_index()
                logger.info(f"EMSC去重库: 已加载 {len(cls._records)} 条（{path}）")
            except Exception as e:
                logger.error(f"EMSC去重库: 加载失败: {e}")

    @classmethod
    def save(cls) -> None:
        path = cls._cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with cls._lock:
                payload = list(cls._records)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"EMSC去重库: 保存失败: {e}")

    @classmethod
    def is_duplicate(
        cls,
        event_id: str,
        shock_time: str,
        magnitude: float,
        latitude: float,
        longitude: float,
        depth: float,
    ) -> bool:
        """同 MD5 或同 ID+MD5 → 重复。同 ID 不同 MD5 → 允许（修订）。"""
        eid = str(event_id or "")
        md5 = emsc_content_md5(eid, shock_time, magnitude, latitude, longitude, depth)
        if not eid or not md5:
            return False
        if not cls._loaded:
            cls.load()
        with cls._lock:
            if md5 in cls._by_md5:
                return True
            prev = cls._by_id.get(eid)
            if prev and prev.get("md5") == md5:
                return True
            return False

    @classmethod
    def remember(
        cls,
        event_id: str,
        shock_time: str,
        magnitude: float,
        latitude: float,
        longitude: float,
        depth: float,
    ) -> None:
        """推送成功后写入去重库并落盘。"""
        eid = str(event_id or "")
        md5 = emsc_content_md5(eid, shock_time, magnitude, latitude, longitude, depth)
        if not eid or not md5:
            return
        if not cls._loaded:
            cls.load()
        rec = {
            "id": eid,
            "md5": md5,
            "o_time": str(shock_time or ""),
            "mag": str(magnitude if magnitude is not None else ""),
            "lat": latitude,
            "lon": longitude,
            "depth": depth,
        }
        with cls._lock:
            filtered = [r for r in cls._records if r.get("id") != eid]
            cls._records = deque(filtered, maxlen=EMSC_DEDUP_CACHE_SIZE)
            cls._records.append(rec)
            cls._rebuild_index()
        cls.save()
