#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
区域地名修正工具
使用JSON格式的区域数据文件根据经纬度修正地名
支持USGS (sa) 和 KMA (kma-eew) 数据源的预警消息
"""

import json
import sys
from typing import Optional, Dict, List
from pathlib import Path
from utils.logger import get_logger

logger = get_logger()


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
        self._loaded = False
        
        if json_file_path is None:
            # 获取资源文件路径，兼容PyInstaller打包后的情况
            try:
                # PyInstaller打包后会设置sys._MEIPASS
                base_path = Path(sys._MEIPASS)  # type: ignore
            except (AttributeError, TypeError):
                # 开发环境，使用项目根目录
                try:
                    base_path = Path(__file__).parent.parent
                except Exception:
                    # 如果都失败，使用当前工作目录
                    base_path = Path.cwd()
            
            # 根据数据源类型选择对应的JSON文件
            if self.source_type == 'sa':
                json_file_path = base_path / "SA、KMA-EEW-Fe Fix" / "sa_region_data.json"
            elif self.source_type in ['kma', 'kma-eew']:
                json_file_path = base_path / "SA、KMA-EEW-Fe Fix" / "korea_region_data.json"
            else:
                logger.warning(f"不支持的数据源类型: {source_type}")
                return
        
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
        """加载JSON格式的区域数据文件"""
        if self._loaded:
            return
        
        logger.info(f"正在加载区域地名修正文件: {self.json_file_path}")
        
        with open(self.json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 提取regions数组
        if isinstance(data, dict) and 'regions' in data:
            self.regions = data['regions']
        elif isinstance(data, list):
            self.regions = data
        else:
            logger.warning(f"区域地名修正文件格式不正确: {self.json_file_path}")
            return
        
        self._loaded = True
        logger.info(f"区域地名修正文件加载完成: 区域数量={len(self.regions)}, 数据源: {self.source_type}")
        
        if len(self.regions) == 0:
            logger.warning("区域地名修正文件为空")
    
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
        if not self.regions:
            return place_name
        
        # 查找包含该经纬度的区域
        for region in self.regions:
            lat_min = region.get('lat_min')
            lat_max = region.get('lat_max')
            lon_min = region.get('lon_min')
            lon_max = region.get('lon_max')
            region_name = region.get('name', '')
            
            # 检查经纬度是否在区域内
            if (lat_min is not None and lat_max is not None and
                lon_min is not None and lon_max is not None and
                region_name and
                lat_min <= latitude <= lat_max and
                lon_min <= longitude <= lon_max):
                if region_name != place_name:
                    logger.debug(f"区域地名修正: {place_name} -> {region_name} (数据源: {self.source_type}, 坐标: {latitude}, {longitude})")
                return region_name
        
        return place_name
    
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
    """获取USGS/SA区域地名修正器实例（单例模式）"""
    global _sa_region_fixer
    if _sa_region_fixer is None:
        try:
            _sa_region_fixer = RegionNameFixer(source_type='sa')
        except Exception as e:
            logger.error(f"初始化SA区域地名修正器失败: {e}")
            _sa_region_fixer = None
    return _sa_region_fixer


def get_kma_region_fixer():
    """获取KMA区域地名修正器实例（单例模式）"""
    global _kma_region_fixer
    if _kma_region_fixer is None:
        try:
            _kma_region_fixer = RegionNameFixer(source_type='kma-eew')
        except Exception as e:
            logger.error(f"初始化KMA区域地名修正器失败: {e}")
            _kma_region_fixer = None
    return _kma_region_fixer
