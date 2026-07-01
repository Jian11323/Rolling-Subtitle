#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
区域地名修正工具
使用JSON格式的区域数据文件根据经纬度修正地名
支持USGS (sa) 和 KMA (kma-eew) 数据源的预警消息
"""

import json
import sys
from typing import Optional, Dict, List, Any
from pathlib import Path
from utils.logger import get_logger
from utils.china_place_lookup import lookup_china_place_name

logger = get_logger()

_REGION_DATA_DIR_CANDIDATES = [
    "Region Fe Fix",          # 当前公开版目录名
]


class RegionNameFixer:
    """区域地名修正工具类（基于JSON格式的区域数据）"""
    
    def __init__(self, json_file_path: Optional[str] = None, source_type: str = 'sa'):
        """
        初始化区域地名修正工具
        
        Args:
            json_file_path: JSON文件路径，如果为None则使用默认路径
            source_type: 数据源类型 ('sa' 或 'kma-eew')
        """
        self.source_type = source_type.lower()
        self.regions: List[Dict] = []
        self._grid_table: Optional[List[List[int]]] = None
        self._grid_names: List[str] = []
        self._loaded = False
        
        if json_file_path is None:
            # 获取资源文件路径，兼容 PyInstaller 打包后的情况
            try:
                # PyInstaller 打包后会设置 sys._MEIPASS
                base_path = Path(sys._MEIPASS)  # type: ignore
            except (AttributeError, TypeError):
                # 开发环境，使用项目根目录
                try:
                    base_path = Path(__file__).parent.parent
                except Exception:
                    # 若上述均失败，使用当前工作目录
                    base_path = Path.cwd()
            
            # 根据数据源类型选择对应 JSON 文件，并在多个目录名间自动回退
            if self.source_type == 'sa':  # ShakeAlert 美国区域数据
                target_filename = "sa_region_data.json"
            elif self.source_type in ['kma', 'kma-eew']:  # 韩国气象厅区域数据
                target_filename = "korea_region_data.json"
            else:
                logger.warning(f"不支持的数据源类型: {source_type}")
                return

            resolved_path = None
            for dirname in _REGION_DATA_DIR_CANDIDATES:
                candidate = base_path / dirname / target_filename
                if candidate.exists():
                    resolved_path = candidate
                    break
                # 首次初始化时优先尝试新目录；若均不存在则回落到默认候选路径并告警
                if resolved_path is None:
                    resolved_path = base_path / _REGION_DATA_DIR_CANDIDATES[0] / target_filename
            json_file_path = resolved_path
        
        self.json_file_path = Path(json_file_path)
        
        # 尝试加载文件
        if self.json_file_path.exists():
            try:
                self._load_json_file()
            except Exception as e:
                logger.error(f"加载区域地名修正文件失败: {e}")
        else:
            logger.warning(f"区域地名修正文件不存在: {self.json_file_path}")
    
    def _load_json_file(self):
        """加载 JSON 格式的区域边界数据文件。"""
        if self._loaded:  # 避免重复加载 JSON
            return
        
        logger.info(f"正在加载区域地名修正文件: {self.json_file_path}")
        
        try:
            # 先检查文件是否为空，避免空文件导致 JSONDecodeError 噪音
            try:
                if self.json_file_path.stat().st_size == 0:
                    logger.warning(f"区域地名修正文件为空，将忽略该文件: {self.json_file_path}")
                    return
            except OSError as e:
                logger.warning(f"无法获取区域地名修正文件大小，将直接尝试解析: {e}")
            
            with open(self.json_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError:
            logger.warning(f"区域地名修正文件内容不是合法 JSON，将忽略该文件: {self.json_file_path}")
            return
        except Exception as e:
            logger.error(f"加载区域地名修正文件失败: {e}")
            return
        
        # 提取 regions 数组
        if isinstance(data, dict) and 'regions' in data:
            self.regions = data['regions']
            self._load_grid_lookup(data)
        elif isinstance(data, list):
            self.regions = data
        else:
            logger.warning(f"区域地名修正文件格式不正确: {self.json_file_path}")
            return
        
        self._loaded = True
        logger.info(f"区域地名修正文件加载完成: 区域数量={len(self.regions)}, 数据源: {self.source_type}")
        
        if len(self.regions) == 0:
            logger.warning("区域地名修正文件为空")

    def _load_grid_lookup(self, data: Dict[str, Any]) -> None:
        """加载可选的 F-E 栅格查表数据（fe_fix_region_data.json 的 grid 字段）。"""
        grid = data.get("grid")
        if not isinstance(grid, dict):
            return
        table = grid.get("table")
        names = grid.get("names")
        if not isinstance(table, list) or not table or not isinstance(names, list) or not names:
            return
        self._grid_table = table
        self._grid_names = names
        logger.info(
            f"已加载 F-E 栅格查表: {len(table)}×{len(table[0])}, 地名 {len(names)} 条"
        )

    @staticmethod
    def _bbox_area(region: Dict[str, Any]) -> float:
        lat_min = region.get("lat_min")
        lat_max = region.get("lat_max")
        lon_min = region.get("lon_min")
        lon_max = region.get("lon_max")
        if lat_min is None or lat_max is None or lon_min is None or lon_max is None:
            return float("inf")
        return (lat_max - lat_min) * (lon_max - lon_min)

    @staticmethod
    def _point_in_bbox(region: Dict[str, Any], latitude: float, longitude: float) -> bool:
        lat_min = region.get("lat_min")
        lat_max = region.get("lat_max")
        lon_min = region.get("lon_min")
        lon_max = region.get("lon_max")
        region_name = region.get("name", "")
        return (
            lat_min is not None
            and lat_max is not None
            and lon_min is not None
            and lon_max is not None
            and bool(region_name)
            and lat_min <= latitude <= lat_max
            and lon_min <= longitude <= lon_max
        )

    def _lookup_by_grid(self, latitude: float, longitude: float) -> Optional[str]:
        """按 1° F-E 栅格查表，与 fe_fix.txt 的 feNumbers/feNames 一致。"""
        if not self._grid_table or not self._grid_names:
            return None
        row = int(latitude + 90)
        col = int(longitude + 180)
        row = max(0, min(len(self._grid_table) - 1, row))
        col = max(0, min(len(self._grid_table[0]) - 1, col))
        region_id = self._grid_table[row][col]
        if region_id < 0 or region_id >= len(self._grid_names):
            region_id = len(self._grid_names) - 1
        return self._grid_names[region_id]

    def _lookup_by_bbox(self, latitude: float, longitude: float) -> Optional[str]:
        """bbox 查表：优先非 aggregate 区域，再取面积最小者。"""
        hits = [
            region
            for region in self.regions
            if self._point_in_bbox(region, latitude, longitude)
        ]
        if not hits:
            return None

        leaf_hits = [region for region in hits if not region.get("aggregate")]
        pool = leaf_hits if leaf_hits else hits
        pool.sort(key=self._bbox_area)
        return pool[0].get("name") or None
    
    def fix_place_name(self, place_name: str, latitude: float, longitude: float) -> str:
        """
        根据经纬度修正地名
        
        Args:
            place_name: 原始地名
            latitude: 纬度
            longitude: 经度
            
        Returns:
            修正后的地名，如果无法修正则返回原始地名
        """
        # 检查是否已加载
        if not self._loaded:
            try:
                self._load_json_file()
            except Exception as e:
                logger.error(f"加载区域地名修正文件失败: {e}")
                return place_name
        
        # 检查是否有有效数据
        if not self.regions:  # 无区域数据则无法修正
            return place_name

        # 中国境内优先使用行政区 polygon 查表（区县级精度）
        if self.source_type in ("fe-fix", "fe_fix", "fe"):
            china_name = lookup_china_place_name(latitude, longitude)
            if china_name:
                if china_name != place_name:
                    logger.debug(
                        f"中国行政区地名修正: {place_name} -> {china_name} "
                        f"(坐标: {latitude}, {longitude})"
                    )
                return china_name
        
        region_name = self._lookup_by_grid(latitude, longitude)
        if region_name is None:
            region_name = self._lookup_by_bbox(latitude, longitude)
        if region_name is None:
            return place_name

        if region_name != place_name:
            logger.debug(
                f"区域地名修正: {place_name} -> {region_name} "
                f"(数据源: {self.source_type}, 坐标: {latitude}, {longitude})"
            )
        return region_name
    
    def is_supported(self) -> bool:
        """
        检查是否已加载数据
        
        Returns:
            是否已加载
        """
        return self._loaded and len(self.regions) > 0


# 全局实例（延迟加载）
_sa_region_fixer = None
_kma_region_fixer = None


def get_sa_region_fixer():
    """获取 USGS/SA 区域地名修正器实例（单例模式）。"""
    global _sa_region_fixer
    if _sa_region_fixer is None:
        try:
            _sa_region_fixer = RegionNameFixer(source_type='sa')
        except Exception as e:
            logger.error(f"初始化SA区域地名修正器失败: {e}")
            _sa_region_fixer = None
    return _sa_region_fixer


def get_kma_region_fixer():
    """获取 KMA 区域地名修正器实例（单例模式）。"""
    global _kma_region_fixer
    if _kma_region_fixer is None:
        try:
            _kma_region_fixer = RegionNameFixer(source_type='kma-eew')
        except Exception as e:
            logger.error(f"初始化KMA区域地名修正器失败: {e}")
            _kma_region_fixer = None
    return _kma_region_fixer
