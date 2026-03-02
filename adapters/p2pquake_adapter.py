#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2PQuake数据源适配器
用于解析日本气象厅地震情报API数据
API: https://api.p2pquake.net/v2/history?codes=551&limit=3
"""

import json
from typing import Dict, Any, Optional, List
from .base_adapter import BaseAdapter
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger
from utils import timezone_utils

logger = get_logger()


class P2PQuakeAdapter(BaseAdapter):
    """P2PQuake数据源适配器（日本气象厅地震情报）"""
    
    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)
    
    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """
        解析P2PQuake API返回的数据
        
        Args:
            raw_data: 原始数据（可能是字符串、字典或列表）
            
        Returns:
            解析后的标准化数据字典（返回第一个有效的地震事件）
            如果无法解析则返回None
            
        Note:
            P2PQuake API返回数组，但为了符合基类接口，这里只返回第一个事件
            如果需要处理所有事件，应该在HTTP轮询管理器中调用parse_all方法
        """
        try:
            # 如果输入是字符串，尝试解析JSON
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            
            # API返回的是数组
            if not isinstance(data, list):
                logger.warning(f"【P2PQuake适配器】 数据格式错误，期望数组，得到: {type(data)}")
                return None
            
            # 返回第一个有效的地震事件
            for item in data:
                parsed = self._parse_single_item(item)
                if parsed:
                    return parsed
            
            return None
            
        except json.JSONDecodeError as e:
            logger.error(f"【P2PQuake适配器】 JSON解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"【P2PQuake适配器】 解析数据时出错: {e}")
            return None
    
    def parse_all(self, raw_data: Any) -> List[Dict[str, Any]]:
        """
        解析P2PQuake API返回的所有数据
        
        Args:
            raw_data: 原始数据（可能是字符串、字典或列表）
            
        Returns:
            解析后的标准化数据列表，每个元素是一个地震事件
        """
        try:
            # 如果输入是字符串，尝试解析JSON
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            
            # API返回的是数组
            if not isinstance(data, list):
                logger.warning(f"【P2PQuake适配器】 数据格式错误，期望数组，得到: {type(data)}")
                return []
            
            results = []
            for item in data:
                parsed = self._parse_single_item(item)
                if parsed:
                    results.append(parsed)
            
            return results
            
        except json.JSONDecodeError as e:
            logger.error(f"【P2PQuake适配器】 JSON解析失败: {e}")
            return []
        except Exception as e:
            logger.error(f"【P2PQuake适配器】 解析数据时出错: {e}")
            return []
    
    def _parse_single_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        解析单个地震事件
        
        Args:
            item: 单个地震事件数据
            
        Returns:
            解析后的标准化数据字典
        """
        try:
            # 检查必要字段
            if 'earthquake' not in item:
                return None
            
            earthquake = item.get('earthquake', {})
            hypocenter = earthquake.get('hypocenter', {})
            
            # 提取基本信息
            magnitude = self._safe_float(hypocenter.get('magnitude', 0))
            latitude = self._safe_float(hypocenter.get('latitude', 0))
            longitude = self._safe_float(hypocenter.get('longitude', 0))
            depth = self._safe_float(hypocenter.get('depth', 0))
            place_name = hypocenter.get('name', '未知地区')
            
            # 提取时间（日本气象厅 API 为 JST）
            shock_time = earthquake.get('time', '')
            if shock_time:
                shock_time = timezone_utils.jst_to_display(shock_time)
            
            # 提取震度信息
            max_scale = earthquake.get('maxScale', 0)
            
            # 提取发布信息
            issue = item.get('issue', {})
            issue_time = issue.get('time', '')
            if issue_time:
                issue_time = timezone_utils.jst_to_display(issue_time)
            
            # 获取机构名称
            organization = self.get_organization_name()
            
            # 构建结果
            result = {
                'type': 'report',  # 日本气象厅地震情报属于速报类型
                'magnitude': magnitude,
                'latitude': latitude,
                'longitude': longitude,
                'depth': depth,
                'place_name': place_name,
                'shock_time': shock_time,
                'organization': organization,
                'event_id': item.get('id', ''),
                'raw_data': item,
            }
            
            # 添加特殊字段
            if max_scale:
                result['max_scale'] = max_scale
            if issue_time:
                result['issue_time'] = issue_time
            
            # 添加震度点信息
            points = item.get('points', [])
            if points:
                result['points'] = points
            
            return result
            
        except Exception as e:
            logger.error(f"【P2PQuake适配器】 解析单个事件时出错: {e}")
            return None
    
    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """安全转换为浮点数"""
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型"""
        return data.get('type', 'report')
