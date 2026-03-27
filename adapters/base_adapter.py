#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源适配器基类
定义所有数据源适配器的通用接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime


class BaseAdapter(ABC):
    """数据源适配器基类"""
    
    def __init__(self, source_name: str, source_url: str):
        """
        初始化适配器
        
        Args:
            source_name: 数据源名称
            source_url: 数据源URL
        """
        self.source_name = source_name
        self.source_url = source_url
    
    @abstractmethod
    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """
        解析原始数据
        
        Args:
            raw_data: 原始数据（可能是字符串、字典等）
            
        Returns:
            解析后的标准化数据字典，如果无法解析则返回None
            标准格式：
            {
                'type': 'warning' | 'report' | 'weather',
                'magnitude': float,
                'latitude': float,
                'longitude': float,
                'depth': float,
                'place_name': str,
                'shock_time': str,
                'organization': str,
                'raw_data': Any,  # 原始数据
                ...
            }
        """
        pass
    
    @abstractmethod
    def get_message_type(self, data: Dict[str, Any]) -> str:
        """
        获取消息类型
        
        Args:
            data: 解析后的数据字典
            
        Returns:
            消息类型：'warning'（预警）、'report'（速报）、'weather'（气象）
        """
        pass
    
    def format_time(self, time_str: str, include_date: bool = True) -> str:
        """
        格式化时间字符串
        
        Args:
            time_str: 时间字符串
            include_date: 是否包含日期
            
        Returns:
            格式化后的时间字符串
        """
        try:
            # 尝试多种时间格式
            formats = [
                '%Y-%m-%d %H:%M:%S.%f',  # 支持秒的小数部分，如 2026-02-04 16:18:52.0
                '%Y-%m-%d %H:%M:%S',
                '%Y/%m/%d %H:%M:%S',
                '%Y-%m-%dT%H:%M:%S',
                '%Y-%m-%dT%H:%M:%S.%f',
                '%Y-%m-%dT%H:%M:%S%z',
                '%Y-%m-%dT%H:%M:%S.%f%z',
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(time_str, fmt)
                    if include_date:
                        return dt.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        return dt.strftime('%H:%M:%S')
                except ValueError:
                    continue
            
            # 如果所有格式都失败，返回原字符串
            return time_str
        except Exception:
            return time_str
    
    def get_organization_name(self) -> str:
        """
        获取机构名称
        
        Returns:
            机构名称
        """
        try:
            from config import Config
            config = Config()
            return config.get_organization_name(self.source_name)
        except Exception as e:
            from utils.logger import get_logger
            logger = get_logger()
            logger.debug(f"获取机构名称失败: {e}，返回source_name: {self.source_name}")
            return self.source_name
