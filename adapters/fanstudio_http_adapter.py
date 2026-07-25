#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fan Studio HTTP 数据源适配器
支持：台风实时与历史数据
"""

import json
import sys
import os
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from .base_adapter import BaseAdapter
from utils.logger import get_logger

logger = get_logger()


class FanStudioHttpAdapter(BaseAdapter):
    """Fan Studio HTTP 数据源适配器"""

    def __init__(self, source_name: str, source_url: str):
        """根据 URL 识别 HTTP 接口类型。"""
        super().__init__(source_name, source_url)
        lower_url = source_url.lower()
        if 'typhoon.php' in lower_url:
            self.http_type = 'typhoon'
        else:
            self.http_type = source_name

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（HTTP 接口均为速报）。"""
        return 'report'

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 Fan Studio HTTP JSON，按接口类型分发。"""
        try:
            if isinstance(raw_data, str):
                try:
                    data = json.loads(raw_data)
                except (json.JSONDecodeError, TypeError, ValueError):
                    logger.debug("[FanStudio HTTP] 非 JSON 字符串，跳过")
                    return None
            else:
                data = raw_data
            if self.http_type == 'typhoon':
                return self._parse_typhoon(data)
            return None
        except Exception as e:
            logger.error(f"[FanStudio HTTP] 解析数据失败: {e}")
            return None

    @staticmethod
    def _normalize_value(item: Dict[str, Any], keys: list) -> str:
        """按候选键名顺序取第一个非空字符串值。"""
        for key in keys:
            value = item.get(key)
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == '':
                continue
            return str(value).strip()
        return ''

    def _parse_typhoon(self, data: Any) -> Optional[Dict[str, Any]]:
        """解析台风实时数据，优先取活跃台风条目。"""
        if isinstance(data, dict) and data.get('msg') == '当前无台风':
            return None
        if isinstance(data, dict) and 'Data' in data:
            data = data.get('Data')

        item = None
        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict) and str(entry.get('isactive', entry.get('active', ''))).strip().lower() in ('1', 'true', 'yes'):
                    item = entry
                    break
            if item is None and data:
                item = data[0]
        elif isinstance(data, dict):
            item = data

        if not item or not isinstance(item, dict):
            return None

        point = None
        if isinstance(item.get('points'), list) and item.get('points'):
            first_point = item['points'][0]
            if isinstance(first_point, dict):
                point = first_point

        shock_time = self._normalize_value(point or item, ['Time', 'time', 'TimePoint', 'time_point', 'UpdateTime', 'updated_at', 'starttime'])
        name = self._normalize_value(item, ['name', 'Name', 'typhoonName', 'TyphoonName', 'NameCn'])
        enname = self._normalize_value(item, ['Enname', 'enname', 'EngName', 'EnglishName', 'enName'])
        ckposition = self._normalize_value(item, ['ckposition', 'Ckposition', 'centerPosition', 'center_position', 'center', 'centerPositionText'])
        if not ckposition:
            ckposition = self._format_center_position(item)
        power = self._normalize_value(point or item, ['Power', 'power', 'PowerLevel', 'strong'])
        speed = self._normalize_value(point or item, ['Speed', 'speed', 'windSpeed'])
        strong = self._normalize_value(point or item, ['Strong', 'strong', 'intensity'])
        pressure = self._normalize_value(point or item, ['Pressure', 'pressure', 'pressure_hpa'])
        movespeed = self._normalize_value(point or item, ['Movespeed', 'movespeed', 'moveSpeed', 'move_speed'])
        movedirection = self._normalize_value(point or item, ['Movedirection', 'movedirection', 'moveDirection', 'direction'])
        jl = self._normalize_value(point or item, ['Jl', 'jl', 'JlRemark', 'remark', '备注'])

        typhoon_id = self._normalize_value(item, ['tfid', 'id', 'TyphoonID', 'typhoon_id'])
        event_id = f"fanstudio_typhoon:{typhoon_id or name or enname or 'unknown'}:{shock_time or 'unknown'}"
        return {
            'type': 'report',
            'source_type': self.source_name,
            'organization': self.get_organization_name(),
            'place_name': name,
            'shock_time': shock_time,
            'Time': shock_time,
            'Name': name,
            'Enname': enname,
            'raw_data': item,
            'fanstudio': True,
            'event_id': event_id,
            'Ckposition': ckposition,
            'ckposition': ckposition,
            'Power': power,
            'power': power,
            'Speed': speed,
            'speed': speed,
            'Strong': strong,
            'strong': strong,
            'Pressure': pressure,
            'pressure': pressure,
            'Movespeed': movespeed,
            'movespeed': movespeed,
            'Movedirection': movedirection,
            'movedirection': movedirection,
            'Jl': jl,
            'jl': jl,
        }

    def _format_center_position(self, item: Dict[str, Any]) -> str:
        """将经纬度格式化为「北纬/南纬 …，东经/西经 …」文本。"""
        lat = self._normalize_value(item, ['centerlat', 'center_lat', 'centerLat', 'latitude', 'Latitude'])
        lng = self._normalize_value(item, ['centerlng', 'center_lng', 'centerLng', 'longitude', 'Longitude'])
        if not lat or not lng:
            return ''
        try:
            lat_val = float(lat)
            lng_val = float(lng)
            lat_label = '北纬' if lat_val >= 0 else '南纬'
            lng_label = '东经' if lng_val >= 0 else '西经'
            return f"{lat_label}{abs(lat_val):.2f}°，{lng_label}{abs(lng_val):.2f}°"
        except ValueError:
            return f"{lat}，{lng}"
