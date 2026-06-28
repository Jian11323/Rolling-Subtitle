#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地名修正工具
使用 Region Fe Fix/fe_fix_region_data.json 根据经纬度修正地名（区域 bbox，与 korea_region_data.json 同结构）
支持 usgs, emsc, bcsf, gfz, usp, kma 数据源
"""

import sys
from pathlib import Path
from typing import Optional

from utils.logger import get_logger
from utils.region_name_fixer import RegionNameFixer

logger = get_logger()

_REGION_DIR_NAMES = ("Region Fe Fix",)
_FE_FIX_JSON = "fe_fix_region_data.json"


class PlaceNameFixer:
    """地名修正工具类"""

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

        # 支持按经纬度 bbox 修正地名的数据源类型
        self.supported_sources = {
            "usgs", "emsc", "bcsf", "gfz", "usp", "kma",
            "bmkg", "geonet", "ingv", "early_est",
            "p2pquake", "p2pquake_tsunami",
        }

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
        if source_type.lower() not in self.supported_sources:  # 不在白名单内不修正
            return place_name

        if not self._region_fixer.is_supported():  # 区域数据未加载成功
            return place_name

        return self._region_fixer.fix_place_name(place_name, latitude, longitude)

    def is_supported(self, source_type: str) -> bool:
        """
        检查是否支持该数据源

        Args:
            source_type: 数据源类型

        Returns:
            是否支持
        """
        return source_type.lower() in self.supported_sources
