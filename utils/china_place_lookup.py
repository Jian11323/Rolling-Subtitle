#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中国行政区经纬度查地名（区县级精度，0.05° 栅格）。

索引文件 Region Fe Fix/china_place_index.json 由 tools/build_china_place_index.py 生成。
"""

from __future__ import annotations

import json
import sys
import threading
from array import array
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from utils.logger import get_logger

logger = get_logger()

_REGION_DIR_NAMES = ("Region Fe Fix",)
_INDEX_FILENAME = "china_place_index.json"
_CHINA_ROUGH_BBOX = (73.0, 135.5, 15.5, 54.5)  # lon_min, lon_max, lat_min, lat_max

_loader_lock = threading.Lock()
_loader: Optional["ChinaPlaceLookup"] = None


def _get_base_path() -> Path:
    try:
        return Path(sys._MEIPASS)  # type: ignore
    except (AttributeError, TypeError):
        try:
            return Path(__file__).resolve().parent.parent
        except Exception:
            return Path.cwd()


def _resolve_index_path(index_path: Optional[str] = None) -> Path:
    if index_path:
        return Path(index_path)
    base_path = _get_base_path()
    for dirname in _REGION_DIR_NAMES:
        candidate = base_path / dirname / _INDEX_FILENAME
        if candidate.exists():
            return candidate
    return base_path / _REGION_DIR_NAMES[0] / _INDEX_FILENAME


class ChinaPlaceLookup:
    """中国行政区查表（0.05° 预计算栅格，或 polygon 回退）。"""

    def __init__(self, index_path: Path):
        self.index_path = index_path
        self._regions: List[Dict[str, Any]] = []
        # 扁平栅格用 array('i')，比 Python list[int] 省大量指针开销
        self._grid_table: Sequence[int] = array("i")
        self._grid_meta: Dict[str, float] = {}
        self._grid_rows = 0
        self._grid_cols = 0
        self._loaded = False
        self._load_lock = threading.Lock()

    def _load(self) -> None:
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            self._load_unlocked()

    def _load_unlocked(self) -> None:
        if not self.index_path.exists():
            logger.warning(f"中国行政区索引不存在: {self.index_path}")
            self._loaded = True
            return

        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"加载中国行政区索引失败: {e}")
            self._loaded = True
            return

        self._regions = list(data.get("regions") or [])
        grid = data.get("grid") or {}
        raw_table = grid.get("table") if isinstance(grid, dict) else None
        if isinstance(grid, dict) and isinstance(raw_table, list) and raw_table:
            try:
                self._grid_table = array("i", (int(x) for x in raw_table))
            except (TypeError, ValueError, OverflowError):
                # 回退：偶发非整型时仍用 list，保证可查
                self._grid_table = [int(x) for x in raw_table]
            self._grid_meta = {
                "lat_min": float(grid.get("lat_min", 15.5)),
                "lon_min": float(grid.get("lon_min", 73.0)),
                "lat_step": float(grid.get("lat_step", 0.05)),
                "lon_step": float(grid.get("lon_step", 0.05)),
            }
            self._grid_rows = int(grid.get("rows") or 0)
            self._grid_cols = int(grid.get("cols") or 0)
            # 尽快丢掉 json 大对象引用，便于回收
            raw_table = None
            data = None

        self._loaded = True
        mode = "grid" if self._grid_table else "none"
        logger.info(
            f"中国行政区索引加载完成: {len(self._regions)} 个区域, 模式={mode}, 文件={self.index_path.name}"
        )

    def _lookup_by_grid(self, latitude: float, longitude: float) -> Optional[str]:
        if not self._grid_table or self._grid_rows <= 0 or self._grid_cols <= 0:
            return None

        lat_min = self._grid_meta["lat_min"]
        lon_min = self._grid_meta["lon_min"]
        lat_step = self._grid_meta["lat_step"]
        lon_step = self._grid_meta["lon_step"]

        row = int((latitude - lat_min) / lat_step)
        col = int((longitude - lon_min) / lon_step)
        if row < 0 or col < 0 or row >= self._grid_rows or col >= self._grid_cols:
            return None

        region_idx = self._grid_table[row * self._grid_cols + col]
        if region_idx < 0 or region_idx >= len(self._regions):
            return None

        place_name = self._regions[region_idx].get("place_name")
        return str(place_name) if place_name else None

    def lookup(self, latitude: float, longitude: float) -> Optional[str]:
        """按经纬度返回中文地名；不在中国范围内或未命中时返回 None。"""
        self._load()
        if not self._regions:
            return None

        lon_min, lon_max, lat_min, lat_max = _CHINA_ROUGH_BBOX
        if not (lat_min <= latitude <= lat_max and lon_min <= longitude <= lon_max):
            return None

        return self._lookup_by_grid(latitude, longitude)

    def is_available(self) -> bool:
        self._load()
        return bool(self._regions)


def get_china_place_lookup(index_path: Optional[str] = None) -> ChinaPlaceLookup:
    global _loader
    with _loader_lock:
        if _loader is None:
            _loader = ChinaPlaceLookup(_resolve_index_path(index_path))
        return _loader


def preload_china_place_lookup_async() -> None:
    """后台预加载行政区索引（可选；默认不在启动调用，以节省常驻内存）。"""
    def _run() -> None:
        try:
            get_china_place_lookup().is_available()
        except Exception as e:
            logger.debug(f"预加载中国行政区索引失败（可忽略）: {e}")

    threading.Thread(target=_run, daemon=True, name="ChinaPlacePreload").start()


def unload_china_place_lookup() -> None:
    """释放已加载的中国行政区索引。"""
    global _loader
    with _loader_lock:
        _loader = None


def lookup_china_place_name(
    latitude: float,
    longitude: float,
    index_path: Optional[str] = None,
) -> Optional[str]:
    """对外接口：中国境内返回行政区地名，否则 None。"""
    try:
        return get_china_place_lookup(index_path).lookup(latitude, longitude)
    except Exception as e:
        logger.debug(f"中国行政区查表失败: {e}")
        return None
