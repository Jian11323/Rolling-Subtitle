#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地名修正工具
使用 Region Fe Fix/fe_fix_region_data.json 根据经纬度修正地名（区域 bbox，与 korea_region_data.json 同结构）。
中国境内优先使用同目录下 china_place_index.json（0.05° 区县级栅格查表）。

规则：
- CENC / CWA / JMA / HKO / P2PQuake 等保留原文，不修正
- 国外数据源优先使用 FE 地名修正
"""

import sys
import threading
from pathlib import Path
from typing import Optional

from utils.logger import get_logger
from utils.place_name_utils import should_apply_fe_place_fix
from utils.region_name_fixer import RegionNameFixer

logger = get_logger()

_REGION_DIR_NAMES = ("Region Fe Fix",)
_FE_FIX_JSON = "fe_fix_region_data.json"

# 进程内单例：避免每条消息重复读盘加载 fe_fix_region_data.json
_place_name_fixer: Optional["PlaceNameFixer"] = None
_place_name_fixer_lock = threading.Lock()


def get_place_name_fixer() -> Optional["PlaceNameFixer"]:
    """懒加载地名修正器单例；初始化失败时返回 None。"""
    global _place_name_fixer
    if _place_name_fixer is not None:
        return _place_name_fixer
    with _place_name_fixer_lock:
        if _place_name_fixer is not None:
            return _place_name_fixer
        try:
            _place_name_fixer = PlaceNameFixer()
        except Exception as e:
            logger.debug(f"初始化地名修正器失败: {e}")
            _place_name_fixer = None
        return _place_name_fixer


class PlaceNameFixer:
    """地名修正工具类（国外数据源 → FE 区域名）。"""

    def __init__(self, fix_file_path: Optional[str] = None):
        """
        初始化地名修正工具

        Args:
            fix_file_path: fe_fix_region_data.json 文件路径，如果为 None 则使用默认路径
        """
        if fix_file_path is None:  # 未指定路径时自动查找打包/源码目录
            try:
                # PyInstaller 打包后的资源根目录
                base_path = Path(sys._MEIPASS)  # type: ignore
            except (AttributeError, TypeError):
                try:
                    base_path = Path(__file__).parent.parent
                except Exception:
                    base_path = Path.cwd()
            resolved: Optional[Path] = None
            for dirname in _REGION_DIR_NAMES:
                candidate = base_path / dirname / _FE_FIX_JSON
                if candidate.exists():  # 找到首个存在的区域数据文件
                    resolved = candidate
                    break
            if resolved is None:
                resolved = base_path / _REGION_DIR_NAMES[0] / _FE_FIX_JSON
            fix_file_path = str(resolved)
        else:
            fix_file_path = str(Path(fix_file_path))

        self.fix_file_path = Path(fix_file_path)
        self._region_fixer = RegionNameFixer(
            json_file_path=str(self.fix_file_path),
            source_type="fe-fix",
        )

        if not self.fix_file_path.exists():
            logger.warning(f"地名修正文件不存在: {self.fix_file_path}")

    def fix_place_name(
        self,
        place_name: str,
        latitude: float,
        longitude: float,
        source_type: str,
    ) -> str:
        """
        修正地名

        Args:
            place_name: 原始地名
            latitude: 纬度
            longitude: 经度
            source_type: 数据源类型

        Returns:
            修正后的地名，如果无法修正则返回原始地名
        """
        if not should_apply_fe_place_fix(source_type):
            return place_name

        if not self._region_fixer.is_supported():  # 区域数据未加载成功
            return place_name

        return self._region_fixer.fix_place_name(place_name, latitude, longitude)

    def is_supported(self, source_type: str) -> bool:
        """
        检查该数据源是否应走 FE 地名修正

        Args:
            source_type: 数据源类型

        Returns:
            是否支持
        """
        return should_apply_fe_place_fix(source_type)
