#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地名修正工具
使用fe_fix.txt文件根据经纬度修正地名
支持usgs, emsc, bcsf, gfz, usp, kma数据源
"""

import sys
import re
from typing import Optional, Dict, List
from pathlib import Path
from utils.logger import get_logger

logger = get_logger()


class PlaceNameFixer:
    """地名修正工具类"""
    
    def __init__(self, fix_file_path: Optional[str] = None):
        """
        初始化地名修正工具
        
        Args:
            fix_file_path: fe_fix.txt文件路径，如果为None则使用默认路径
        """
        if fix_file_path is None:
            # 获取资源文件路径，兼容PyInstaller打包后的情况
            try:
                # PyInstaller打包后会设置sys._MEIPASS，fe_fix.txt在根目录
                base_path = Path(sys._MEIPASS)  # type: ignore
            except (AttributeError, TypeError):
                # 开发环境，使用项目根目录
                try:
                    base_path = Path(__file__).parent.parent
                except Exception:
                    # 如果都失败，使用当前工作目录
                    base_path = Path.cwd()
            fix_file_path = base_path / "fe_fix.txt"
        
        self.fix_file_path = Path(fix_file_path)
        self.fe_numbers: List[List[int]] = []
        self.place_names: List[str] = []
        self._loaded = False
        
        # 支持的数据源
        self.supported_sources = {'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma'}
        
        # 尝试加载文件
        if self.fix_file_path.exists():
            try:
                self._load_fix_file()
            except Exception as e:
                logger.error(f"加载地名修正文件失败: {e}")
        else:
            logger.warning(f"地名修正文件不存在: {self.fix_file_path}")
    
    def _load_fix_file(self):
        """加载fe_fix.txt文件"""
        if self._loaded:
            return
        
        logger.info(f"正在加载地名修正文件: {self.fix_file_path}")
        
        with open(self.fix_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 解析feNumbers数组（二维数组）
        # 查找 const feNumbers = [...] 到 const feNames = [...] 之间的内容
        fe_numbers_match = re.search(
            r'const\s+feNumbers\s*=\s*\[(.*?)\];\s*const\s+feNames',
            content,
            re.DOTALL
        )
        
        if fe_numbers_match:
            fe_numbers_str = fe_numbers_match.group(1)
            # 解析所有子数组 [...]
            array_matches = re.findall(r'\[([^\]]+)\]', fe_numbers_str)
            for array_str in array_matches:
                # 提取数字，支持负数
                numbers = []
                for num_str in re.findall(r'-?\d+', array_str):
                    try:
                        numbers.append(int(num_str))
                    except ValueError:
                        pass
                if numbers:
                    self.fe_numbers.append(numbers)
        else:
            # 备用方法：直接查找所有数字数组
            logger.debug("使用备用方法解析feNumbers")
            array_matches = re.findall(r'\[([\d\s,\-]+)\]', content)
            for array_str in array_matches[:1000]:  # 限制数量
                numbers = []
                for num_str in re.findall(r'-?\d+', array_str):
                    try:
                        numbers.append(int(num_str))
                    except ValueError:
                        pass
                if numbers and len(numbers) >= 10:  # 只添加较长的数组
                    self.fe_numbers.append(numbers)
        
        # 解析feNames数组（地名列表）
        # 查找 const feNames = [...] 到文件结尾
        fe_names_match = re.search(
            r'const\s+feNames\s*=\s*\[(.*?)\];?\s*$',
            content,
            re.DOTALL
        )
        
        if fe_names_match:
            fe_names_str = fe_names_match.group(1)
            # 提取所有引号内的地名
            place_matches = re.findall(r'"([^"]+)"', fe_names_str)
            for place in place_matches:
                # 只添加包含中文字符的地名
                if re.search(r'[\u4e00-\u9fff]', place):
                    self.place_names.append(place)
        else:
            # 备用方法：从feNames开始查找所有地名
            logger.debug("使用备用方法解析feNames")
            fe_names_start = content.find('const feNames')
            if fe_names_start >= 0:
                fe_names_content = content[fe_names_start:]
                place_matches = re.findall(r'"([^"]*[\u4e00-\u9fff][^"]*)"', fe_names_content)
                self.place_names = list(dict.fromkeys(place_matches))  # 去重
        
        self._loaded = True
        logger.info(f"地名修正文件加载完成: feNumbers数组长度={len(self.fe_numbers)}, 地名数量={len(self.place_names)}")
        
        if len(self.fe_numbers) == 0 or len(self.place_names) == 0:
            logger.warning("地名修正文件解析可能不完整")
    
    def _calculate_index(self, latitude: float, longitude: float) -> Optional[int]:
        """
        根据经纬度计算索引
        
        feNumbers数组大小为 180x360，对应经纬度范围：
        - 纬度: -90 到 90 (180个值，索引 0-179)
        - 经度: -180 到 180 (360个值，索引 0-359)
        数组中存储的是feNames地名列表的索引值
        
        Args:
            latitude: 纬度 (-90 到 90)
            longitude: 经度 (-180 到 180)
            
        Returns:
            索引值，如果计算失败返回None
        """
        if not self.fe_numbers or len(self.fe_numbers) == 0:
            return None
        
        # 将经纬度转换为数组索引
        # 纬度: -90 到 90 -> 0 到 len(fe_numbers)-1 (180个值)
        # 经度: -180 到 180 -> 0 到 len(fe_numbers[0])-1 (360个值)
        
        # 确保经纬度在有效范围内
        latitude = max(-90.0, min(90.0, latitude))
        longitude = max(-180.0, min(180.0, longitude))
        
        # 计算纬度索引（从南到北）
        lat_index = int((latitude + 90.0) * len(self.fe_numbers) / 180.0)
        lat_index = max(0, min(lat_index, len(self.fe_numbers) - 1))
        
        # 计算经度索引（从西到东）
        if lat_index < len(self.fe_numbers) and len(self.fe_numbers[lat_index]) > 0:
            lon_index = int((longitude + 180.0) * len(self.fe_numbers[lat_index]) / 360.0)
            lon_index = max(0, min(lon_index, len(self.fe_numbers[lat_index]) - 1))
            
            # 获取索引值
            index_value = self.fe_numbers[lat_index][lon_index]
            return index_value
        
        return None
    
    def fix_place_name(self, place_name: str, latitude: float, longitude: float, 
                       source_type: str) -> str:
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
        # 检查是否支持该数据源
        if source_type.lower() not in self.supported_sources:
            return place_name
        
        # 检查是否已加载
        if not self._loaded:
            try:
                self._load_fix_file()
            except Exception as e:
                logger.error(f"加载地名修正文件失败: {e}")
                return place_name
        
        # 检查是否有有效数据
        if not self.fe_numbers or not self.place_names:
            return place_name
        
        # 计算索引
        index = self._calculate_index(latitude, longitude)
        if index is None:
            logger.debug(f"地名修正: 无法计算索引 (纬度: {latitude}, 经度: {longitude}, 数据源: {source_type})")
            return place_name
        
        # 检查索引是否在有效范围内（索引值可能是-1表示无效，需要排除）
        if index >= 0 and index < len(self.place_names):
            fixed_name = self.place_names[index]
            # 检查修正后的地名是否有效（非空且与原始地名不同）
            if fixed_name and fixed_name.strip() and fixed_name != place_name:
                logger.debug(f"地名修正: {place_name} -> {fixed_name} (索引: {index}, 数据源: {source_type}, 坐标: {latitude}, {longitude})")
                return fixed_name
            else:
                # 索引有效但地名为空或与原始相同，记录调试信息
                logger.debug(f"地名修正: 索引 {index} 对应的地名为空或与原始地名相同 (原始: {place_name}, 数据源: {source_type}, 坐标: {latitude}, {longitude})")
        else:
            # 索引超出范围或为负数（-1表示无效）
            logger.debug(f"地名修正: 索引 {index} 超出范围或无效 (范围: 0-{len(self.place_names)-1}, 数据源: {source_type}, 坐标: {latitude}, {longitude})")
        
        return place_name
    
    def is_supported(self, source_type: str) -> bool:
        """
        检查是否支持该数据源
        
        Args:
            source_type: 数据源类型
            
        Returns:
            是否支持
        """
        return source_type.lower() in self.supported_sources
