#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fan Studio数据源适配器
根据Fan Studio数据服务 API文档实现
支持所有数据源：
- 地震速报：cenc, ningxia, guangxi, shanxi, beijing, cwa, hko, usgs, emsc, bcsf, gfz, usp, kma, fssn
- 地震预警：cea, cea-pr, sichuan, cwa-eew, jma, sa, kma-eew
- 气象预警：weatheralarm
"""

import json
import re
from typing import Dict, Any, Optional, List
from datetime import datetime
from .base_adapter import BaseAdapter
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger
from utils import timezone_utils

logger = get_logger()

# 地名修正工具（延迟加载）
_place_name_fixer = None

def get_place_name_fixer():
    """获取地名修正工具实例（单例模式）"""
    global _place_name_fixer
    if _place_name_fixer is None:
        try:
            from utils.place_name_fixer import PlaceNameFixer
            _place_name_fixer = PlaceNameFixer()
        except Exception as e:
            logger.error(f"初始化地名修正工具失败: {e}")
            _place_name_fixer = None
    return _place_name_fixer


class FanStudioAdapter(BaseAdapter):
    """Fan Studio数据源适配器"""
    
    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)
        # 从URL或source_name中提取数据源类型
        self.data_source_type = self._extract_source_type()
    
    def _extract_source_type(self) -> str:
        """从URL或source_name中提取数据源类型"""
        # 如果source_name是URL的一部分，提取路径
        if 'fanstudio.tech' in self.source_url:
            # 从URL中提取路径，如 wss://ws.fanstudio.tech/cenc -> cenc
            parts = self.source_url.split('/')
            if len(parts) > 3:
                return parts[-1] if parts[-1] else parts[-2]
        # 如果source_name直接是类型名
        return self.source_name.lower()
    
    def parse_all_sources(self, raw_data: Any) -> List[Dict[str, Any]]:
        """
        解析initial_all类型的所有数据源，返回所有有效数据的列表
        只解析启用的数据源，未启用的数据源将被跳过
        
        Args:
            raw_data: 原始数据
            
        Returns:
            所有有效数据的列表
        """
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            
            if data.get('type') != 'initial_all':
                return []
            
            # 获取启用的数据源列表
            enabled_sources = getattr(self, '_enabled_sources', {})
            config = getattr(self, '_config', None)
            if config is None:
                from config import Config
                config = Config()
                enabled_sources = config.enabled_sources
            
            # 获取启用的数据源名称集合（用于快速查找）
            enabled_source_names = set()
            base_domain = "fanstudio.tech"
            all_url = f"wss://ws.{base_domain}/all"
            for url, enabled in enabled_sources.items():
                if enabled and url != all_url:
                    # 提取数据源名称（统一使用fanstudio.tech）
                    if 'fanstudio.tech' in url or 'fanstudio.hk' in url:
                        parts = url.split('/')
                        source_name = parts[-1] if parts[-1] else parts[-2]
                        enabled_source_names.add(source_name)
                        logger.debug(f"[FanStudio适配器] 从URL提取数据源名称: {url} -> {source_name}")
                    elif 'p2pquake.net' in url:
                        enabled_source_names.add('p2pquake')
                        logger.debug(f"[FanStudio适配器] 从URL提取数据源名称: {url} -> p2pquake")
            
            # 特殊处理：当仅连接 /all 且 enabled_source_names 为空时，
            # 将 initial_all 中存在的所有子数据源视为启用（确保 cea-pr 等能被解析）
            if not enabled_source_names and enabled_sources.get(all_url, False):
                for source_type in data.keys():
                    if source_type != 'type' and isinstance(data.get(source_type), dict):
                        obj = data[source_type]
                        if isinstance(obj, dict) and obj.get('Data'):
                            enabled_source_names.add(source_type)
                logger.info(f"[FanStudio适配器] 连接 /all 且无子源配置，启用 initial_all 中所有数据源: {sorted(enabled_source_names)}")
            
            logger.info(f"[FanStudio适配器] 启用的数据源名称集合: {sorted(enabled_source_names)}")
            
            results = []
            # 所有数据源（按优先级排序）
            priority_sources = [
                # 地震预警（优先级最高）
                'cea', 'cea-pr', 'sichuan', 'cwa-eew', 'jma', 'sa', 'kma-eew',
                # 地震速报
                'cenc', 'ningxia', 'guangxi', 'shanxi', 'beijing', 'cwa', 'hko', 
                'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma', 'fssn',
                # 气象预警
                'weatheralarm'
            ]
            
            # 处理所有有效数据源（只处理启用的）
            for source_type in priority_sources:
                # 检查该数据源是否启用
                if source_type not in enabled_source_names:
                    logger.debug(f"[FanStudio] 数据源 {source_type} 未启用（enabled_source_names={sorted(enabled_source_names)}），跳过")
                    continue  # 跳过未启用的数据源
                
                if source_type in data:
                    data_obj = data[source_type]
                    if 'Data' in data_obj and data_obj['Data']:
                        parsed = self._parse_specific_source(data_obj['Data'], source_type)
                        if parsed:
                            results.append(parsed)
                        else:
                            logger.debug(f"[FanStudio] 数据源 {source_type} 解析返回None（可能数据格式不正确或为空）")
                    else:
                        logger.debug(f"[FanStudio] 数据源 {source_type} 的Data字段为空或不存在")
                else:
                    logger.debug(f"[FanStudio] 数据源 {source_type} 在initial_all数据中不存在")
            
            if results:
                logger.info(f"[FanStudio] initial_all解析出{len(results)}条数据（已过滤未启用的数据源），启用的数据源: {sorted(enabled_source_names)}")
            else:
                logger.warning(f"[FanStudio] initial_all未解析出任何数据，启用的数据源: {sorted(enabled_source_names)}")
            return results
        except Exception as e:
            logger.error(f"【FanStudio适配器】 解析initial_all所有数据源时出错: {e}")
            return []
    
    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """
        解析Fan Studio数据
        
        数据格式根据不同的数据源类型有所不同：
        - initial_all: 包含所有数据源的初始数据
        - update: 单个数据源的更新数据
        - heartbeat: 心跳数据，忽略
        
        注意：当 data_source_type == 'all' 时，initial_all 会返回第一个有效的数据源数据
        实际应用中，initial_all 应该在 websocket_manager 中特殊处理，多次调用适配器
        """
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            
            # 处理错误消息
            if data.get('type') == 'error':
                error_message = data.get('message', '未知错误')
                logger.warning(f"[FanStudio] 错误: {error_message}")
                return None
            
            # 处理心跳数据
            if data.get('type') == 'heartbeat':
                return None
            
            # 处理initial_all类型
            if data.get('type') == 'initial_all':
                # 如果适配器类型是 'all'，需要处理所有数据源
                if self.data_source_type == 'all':
                    # 遍历所有数据源，返回第一个有效的数据
                    # 优先级：预警 > 速报 > 气象预警
                    priority_sources = [
                        # 地震预警（优先级最高）
                        'cea', 'cea-pr', 'sichuan', 'cwa-eew', 'jma', 'sa', 'kma-eew',
                        # 地震速报
                        'cenc', 'ningxia', 'guangxi', 'shanxi', 'beijing', 'cwa', 'p2pquake', 'hko', 
                        'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma', 'fssn',
                        # 气象预警
                        'weatheralarm'
                    ]
                    
                    # 获取启用的数据源列表
                    enabled_sources = getattr(self, '_enabled_sources', {})
                    config = getattr(self, '_config', None)
                    if config is None:
                        from config import Config
                        config = Config()
                        enabled_sources = config.enabled_sources
                    
                    # 获取启用的数据源名称集合（用于快速查找）
                    enabled_source_names = set()
                    base_domain = "fanstudio.tech"
                    for url, enabled in enabled_sources.items():
                        if enabled and url != f"wss://ws.{base_domain}/all":
                            # 提取数据源名称（统一使用fanstudio.tech）
                            if 'fanstudio.tech' in url or 'fanstudio.hk' in url:
                                parts = url.split('/')
                                source_name = parts[-1] if parts[-1] else parts[-2]
                                enabled_source_names.add(source_name)
                            elif 'p2pquake.net' in url:
                                enabled_source_names.add('p2pquake')
                    
                    # 按优先级查找第一个有效数据（只查找启用的数据源）
                    for source_type in priority_sources:
                        # 检查该数据源是否启用
                        if source_type not in enabled_source_names:
                            continue  # 跳过未启用的数据源
                        
                        if source_type in data:
                            data_obj = data[source_type]
                            if 'Data' in data_obj and data_obj['Data']:
                                parsed = self._parse_specific_source(data_obj['Data'], source_type)
                                if parsed:
                                    logger.debug(f"[FanStudio] 解析{source_type}成功")
                                    return parsed
                    logger.debug(f"[FanStudio] initial_all中无有效数据（或所有数据源均未启用）")
                    return None
                else:
                    # 从initial_all中提取对应数据源的数据
                    source_type = self.data_source_type
                    if source_type in data:
                        data_obj = data[source_type]
                        if 'Data' in data_obj and data_obj['Data']:
                            parsed = self._parse_specific_source(data_obj['Data'], source_type)
                            return parsed
                    return None
            
            # 处理update类型
            if data.get('type') == 'update':
                source = data.get('source', '')
                # 如果适配器类型是 'all'，需要检查该数据源是否启用
                if self.data_source_type == 'all':
                    # 获取启用的数据源列表
                    enabled_sources = getattr(self, '_enabled_sources', {})
                    config = getattr(self, '_config', None)
                    if config is None:
                        from config import Config
                        config = Config()
                        enabled_sources = config.enabled_sources
                    
                    # 检查该数据源是否启用
                    base_domain = "fanstudio.tech"
                    source_url = f"wss://ws.{base_domain}/{source}"
                    if not enabled_sources.get(source_url, False):
                        logger.debug(f"[FanStudio] update类型数据源 {source} 未启用，跳过")
                        return None
                
                # 如果适配器类型是 'all'，处理所有数据源的更新
                # 否则只处理匹配的数据源
                if (self.data_source_type == 'all' or source == self.data_source_type) and 'Data' in data:
                    # 如果适配器类型是 'all'，使用消息中的 source 字段
                    actual_source = source if self.data_source_type == 'all' else self.data_source_type
                    parsed = self._parse_specific_source(data['Data'], actual_source, update_source=source)
                    if parsed:
                        # 确保raw_data包含完整的update消息（包括source字段），以便后续提取source_name
                        if 'raw_data' in parsed:
                            # 如果raw_data是字典，添加source字段
                            if isinstance(parsed['raw_data'], dict):
                                parsed['raw_data']['_update_source'] = source
                    return parsed
                return None
            
            # 直接处理单个数据源的数据
            if 'Data' in data:
                return self._parse_specific_source(data['Data'], self.data_source_type)
            
            return None
        except Exception as e:
            logger.error(f"【FanStudio适配器】 解析数据时出错: {e}")
            return None
    
    def _parse_specific_source(self, data: Dict[str, Any], source_type: str, update_source: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        解析特定数据源的数据
        
        Args:
            data: 数据字典（通常是Data字段的内容）
            source_type: 数据源类型
            update_source: 如果是update类型，传入原始的source字段（用于保存到raw_data）
        """
        try:
            # 检查数据是否为空
            if not data or (isinstance(data, dict) and len(data) == 0):
                return None
            
            # 根据数据源类型选择不同的解析方法
            if source_type == 'weatheralarm':
                result = self._parse_weather(data)
            elif source_type in ['cenc', 'ningxia', 'guangxi', 'shanxi', 'beijing', 'cwa',
                                'hko', 'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma', 'fssn']:
                result = self._parse_earthquake_report(data, source_type)
            elif source_type in ['cea', 'cea-pr', 'sichuan', 'cwa-eew', 'jma', 'sa', 'kma-eew']:
                result = self._parse_earthquake_warning(data, source_type)
            else:
                # 默认按速报处理
                result = self._parse_earthquake_report(data, source_type)
            
            # 如果是update类型，确保raw_data包含source字段，以便后续提取source_name
            if result and update_source and 'raw_data' in result:
                if isinstance(result['raw_data'], dict):
                    result['raw_data']['_update_source'] = update_source
            
            return result
        except Exception as e:
            logger.error(f"【FanStudio适配器】 解析{source_type}数据时出错: {e}")
            return None
    
    def _extract_cwa_location(self, data: Dict[str, Any]) -> str:
        """
        提取CWA数据源的地名（参考fused_list_v2.py的实现）
        
        Args:
            data: CWA数据字典
            
        Returns:
            提取后的地名
        """
        # CWA数据源使用 'loc' 字段而不是 'placeName'
        location_raw = data.get('loc', data.get('placeName', '未知地区'))
        
        if not location_raw or not isinstance(location_raw, str):
            location_raw = '未知地区'
        
        # 使用正则表达式匹配括号内的内容
        bracket_match = re.search(r'\(([^)]+)\)', location_raw)
        if bracket_match:
            # 提取括号内的内容，移除"位於"字符串
            location = bracket_match.group(1).replace('位於', '')
            # 清理多余空格
            location = re.sub(r'\s+', ' ', location).strip()
        else:
            location = location_raw.strip()
        
        # 如果提取后为空，回退到原始字符串
        if not location:
            location = location_raw.strip()
        
        # 转换为简体中文（如果需要）
        # 注意：这里暂时不进行繁体转简体，因为翻译服务可能未初始化
        # 如果需要，可以在后续处理中通过翻译服务转换
        
        return location
    
    def _parse_earthquake_report(self, data: Dict[str, Any], source_type: str) -> Dict[str, Any]:
        """解析地震速报数据"""
        # CWA数据源使用特殊的地名提取逻辑
        if source_type == 'cwa':
            place_name = self._extract_cwa_location(data)
        # FSSN数据源优先使用placeName_zh字段
        elif source_type == 'fssn':
            place_name = data.get('placeName_zh', data.get('placeName', data.get('title', '')))
        else:
            place_name = data.get('placeName', data.get('title', ''))
        
        shock_time = data.get('shockTime', data.get('createTime', ''))
        
        # 如果缺少必要字段，返回None
        if not place_name and not shock_time:
            return None
        
        # 通用字段提取
        magnitude = self._safe_float(data.get('magnitude', 0))
        latitude = self._safe_float(data.get('latitude', 0))
        longitude = self._safe_float(data.get('longitude', 0))
        depth = self._safe_float(data.get('depth', 0))
        
        # 应用地名修正（针对usgs, emsc, bcsf, gfz, usp, kma数据源）
        # 只有在配置中启用了地名修正时才应用
        if place_name and latitude and longitude:
            try:
                from config import Config
                config = Config()
                if config.translation_config.use_place_name_fix:
                    place_name_fixer = get_place_name_fixer()
                    if place_name_fixer and place_name_fixer.is_supported(source_type):
                        try:
                            place_name = place_name_fixer.fix_place_name(
                                place_name, latitude, longitude, source_type
                            )
                        except Exception as e:
                            logger.debug(f"地名修正失败: {e}")
            except Exception as e:
                logger.debug(f"检查地名修正配置失败: {e}")
        
        # 特殊字段处理
        event_id = data.get('eventId', data.get('id', ''))
        info_type = data.get('infoTypeName', '')
        
        # 格式化时间
        if shock_time:
            shock_time = self.format_time(shock_time)
        
        # 获取机构名称：如果适配器类型是 'all'，使用实际的 source_type
        if self.data_source_type == 'all':
            organization = self._get_organization_name_by_type(source_type)
        else:
            organization = self.get_organization_name()
        
        result = {
            'type': 'report',
            'magnitude': magnitude,
            'latitude': latitude,
            'longitude': longitude,
            'depth': depth,
            'place_name': place_name,
            'shock_time': shock_time,
            'organization': organization,
            'event_id': event_id,
            'source_type': source_type,  # 添加数据源类型
            'raw_data': data,
        }
        
        # 添加特殊字段
        if info_type:
            result['info_type'] = info_type
        if source_type == 'kma' and 'epiIntensity' in data:
            result['intensity'] = data.get('epiIntensity')
        if source_type == 'hko' and 'region' in data:
            result['region'] = data.get('region')
        if source_type == 'usgs' and 'url' in data:
            result['url'] = data.get('url')
        
        return result
    
    def _parse_earthquake_warning(self, data: Dict[str, Any], source_type: str) -> Dict[str, Any]:
        """解析地震预警数据"""
        # 检查必要字段是否存在，尝试多种可能的字段名
        place_name = (data.get('placeName', '') or data.get('place_name', '') or 
                     data.get('location', '') or data.get('loc', '') or 
                     data.get('epicenter', '') or data.get('locationDesc', ''))
        shock_time = (data.get('shockTime', '') or data.get('shock_time', '') or 
                     data.get('createTime', '') or data.get('time', '') or 
                     data.get('timestamp', '') or data.get('originTime', ''))
        
        # 如果既没有地点也没有时间，记录警告但继续解析（可能只有震级等信息）
        # 让格式化函数来处理缺失的字段，而不是直接返回None
        if not place_name and not shock_time:
            event_id = data.get('eventId', data.get('id', 'unknown'))
            logger.warning(f"预警数据缺少必要字段（placeName和shockTime），数据源: {source_type}, eventId: {event_id}")
            # 继续解析，让格式化函数处理缺失字段
        
        magnitude = self._safe_float(data.get('magnitude', 0))
        latitude = self._safe_float(data.get('latitude', 0))
        longitude = self._safe_float(data.get('longitude', 0))
        depth = self._safe_float(data.get('depth', 0))
        
        # 应用地名修正（针对USGS/SA和KMA数据源的预警消息）
        # 只有在配置中启用了地名修正时才应用
        if place_name and latitude and longitude:
            try:
                from config import Config
                config = Config()
                if config.translation_config.use_place_name_fix:
                    # 对于USGS/SA，使用JSON格式的区域数据修正
                    if source_type == 'sa':
                        try:
                            from utils.region_name_fixer import get_sa_region_fixer
                            region_fixer = get_sa_region_fixer()
                            if region_fixer and region_fixer.is_supported():
                                place_name = region_fixer.fix_place_name(place_name, latitude, longitude)
                        except Exception as e:
                            logger.debug(f"SA区域地名修正失败: {e}")
                    # 对于KMA/KMA-EEW，使用JSON格式的区域数据修正
                    elif source_type in ['kma', 'kma-eew']:
                        try:
                            from utils.region_name_fixer import get_kma_region_fixer
                            region_fixer = get_kma_region_fixer()
                            if region_fixer and region_fixer.is_supported():
                                place_name = region_fixer.fix_place_name(place_name, latitude, longitude)
                        except Exception as e:
                            logger.debug(f"KMA区域地名修正失败: {e}")
            except Exception as e:
                logger.debug(f"检查地名修正配置失败: {e}")
        
        # 格式化时间
        if shock_time:
            # 对于JMA（日本气象厅），将日本时间（JST）转为显示时区
            if source_type == 'jma':
                shock_time = timezone_utils.jst_to_display(shock_time)
            else:
                shock_time = self.format_time(shock_time)
        
        # 获取强度信息（不同数据源字段名不同）
        intensity = data.get('epiIntensity') or data.get('maxIntensity') or ''
        if isinstance(intensity, (int, float)):
            intensity = str(intensity)
        
        # 获取报数
        updates = data.get('updates', 1)
        if isinstance(updates, str):
            try:
                updates = int(updates)
            except (ValueError, TypeError):
                updates = 1
        
        # 获取机构名称：如果适配器类型是 'all'，使用实际的 source_type
        if self.data_source_type == 'all':
            organization = self._get_organization_name_by_type(source_type)
        else:
            organization = self.get_organization_name()
        
        result = {
            'type': 'warning',
            'magnitude': magnitude,
            'latitude': latitude,
            'longitude': longitude,
            'depth': depth,
            'place_name': place_name,
            'shock_time': shock_time,
            'organization': organization,
            'event_id': data.get('eventId', data.get('id', '')),
            'intensity': intensity,
            'updates': updates,
            'source_type': source_type,  # 添加数据源类型
            'raw_data': data,
        }
        
        # JMA特殊字段
        if source_type == 'jma':
            if 'infoTypeName' in data:
                result['info_type'] = data.get('infoTypeName')
            if 'final' in data:
                result['final'] = data.get('final', False)
            if 'cancel' in data:
                result['cancel'] = data.get('cancel', False)
        
        # CEA-PR特殊字段
        if source_type == 'cea-pr' and 'province' in data:
            result['province'] = data.get('province')
        
        # CWA-EEW特殊字段
        if source_type == 'cwa-eew' and 'locationDesc' in data:
            result['location_desc'] = data.get('locationDesc')
        
        # KMA-EEW特殊字段
        if source_type == 'kma-eew' and 'affectedAreas' in data:
            result['affected_areas'] = data.get('affectedAreas')
        
        # Sichuan特殊字段
        if source_type == 'sichuan':
            if 'infoTypeName' in data:
                result['info_type'] = data.get('infoTypeName')
            if 'producer' in data:
                result['producer'] = data.get('producer')
        
        return result
    
    def _parse_weather(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """解析气象预警数据"""
        # 获取机构名称：如果适配器类型是 'all'，使用实际的 source_type
        if self.data_source_type == 'all':
            organization = self._get_organization_name_by_type('weatheralarm')
        else:
            organization = self.get_organization_name()
        
        # 获取event_id（气象预警可能使用id字段）
        event_id = data.get('id', data.get('eventId', ''))
        # 如果没有id，使用title + effective作为唯一标识
        if not event_id:
            title = data.get('title', data.get('headline', ''))
            effective = data.get('effective', '')
            if title and effective:
                event_id = f"{title}_{effective}"
        
        return {
            'type': 'weather',
            'magnitude': 0,
            'latitude': self._safe_float(data.get('latitude', 0)),
            'longitude': self._safe_float(data.get('longitude', 0)),
            'depth': 0,
            'place_name': data.get('headline', data.get('title', '')),
            'shock_time': data.get('effective', ''),
            'organization': organization,
            'title': data.get('title', data.get('headline', '')),
            'description': data.get('description', ''),
            'warning_type': data.get('type', ''),
            'event_id': event_id,  # 添加event_id用于去重
            'source_type': 'weatheralarm',  # 添加数据源类型
            'raw_data': data,
        }
    
    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """安全转换为浮点数"""
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def _parse_generic_earthquake(self, data: Dict[str, Any], source_type: str) -> Dict[str, Any]:
        """解析通用地震数据"""
        return self._parse_earthquake_report(data, source_type)
    
    def _get_organization_name_by_type(self, source_type: str) -> str:
        """
        根据数据源类型获取机构名称
        
        Args:
            source_type: 数据源类型（如 'cenc', 'ningxia' 等）
            
        Returns:
            机构名称
        """
        try:
            from config import Config
            config = Config()
            return config.get_organization_name(source_type)
        except Exception as e:
            logger.debug(f"获取机构名称失败: {e}，返回source_type: {source_type}")
            return source_type
    
    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型"""
        return data.get('type', 'report')
