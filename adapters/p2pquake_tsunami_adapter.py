#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2PQuake 海啸预报数据源适配器
API: https://api.p2pquake.net/v2/jma/tsunami?limit=1
只取第一条；cancelled 为 True 时不展示。
"""

import json
from typing import Dict, Any, Optional
from .base_adapter import BaseAdapter
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger
from utils import timezone_utils

logger = get_logger()


class P2PQuakeTsunamiAdapter(BaseAdapter):
    """P2PQuake 海啸预报适配器（日本气象厅）"""

    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """
        解析海啸 API 返回的数组，只取第一条；cancelled 时返回 None。
        """
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if not isinstance(data, list) or len(data) == 0:
                return None
            item = data[0]
            if not isinstance(item, dict):
                return None
            if item.get('cancelled') is True:
                return None
            issue = item.get('issue') or {}
            issue_time = issue.get('time') or item.get('time') or ''
            issue_type = issue.get('type') or '海啸情报'
            source = issue.get('source') or '気象庁'
            shock_time = timezone_utils.jst_to_display(issue_time) if issue_time else ''
            areas = item.get('areas') or []
            place_name = self._build_tsunami_detail(areas, issue_type)
            organization = self.get_organization_name()
            return {
                'type': 'report',
                'source_type': 'p2pquake_tsunami',
                'organization': organization,
                'place_name': place_name,
                'magnitude': 0,
                'depth': 0,
                'latitude': 0,
                'longitude': 0,
                'shock_time': shock_time,
                'is_tsunami': True,
                'event_id': item.get('id') or '',
                'raw_data': item,
            }
        except Exception as e:
            logger.debug(f"[P2PQuake海啸] 解析跳过: {e}")
            return None

    def _build_tsunami_detail(self, areas: list, fallback: str) -> str:
        """
        拼接海啸详细说明：等级、预计浪高、各区域及预计到达时间（或“立即”）。
        示例：注意报 预计浪高约１ｍ。北海道太平洋沿岸中部(11:10)、青森県太平洋沿岸(立即)、岩手県(立即)、宮城県(11:30)
        """
        if not areas or not isinstance(areas, list):
            return fallback
        grade_map = {'Watch': '注意报', 'Warning': '警报', 'MajorWarning': '大津波警报'}
        first_grade = ''
        max_height_desc = None
        for a in areas:
            if not isinstance(a, dict):
                continue
            if not first_grade and a.get('grade'):
                first_grade = grade_map.get(a.get('grade'), a.get('grade'))
            mh = a.get('maxHeight') if isinstance(a.get('maxHeight'), dict) else None
            if mh and (mh.get('description') or mh.get('value') is not None):
                max_height_desc = mh.get('description') or f"{mh.get('value')}m"
                break
        parts = []
        if first_grade:
            parts.append(first_grade + ' ')
        if max_height_desc:
            parts.append(f"预计浪高约{max_height_desc}。")
        region_bits = []
        for a in areas[:6]:
            if not isinstance(a, dict):
                continue
            name = a.get('name') or a.get('name_en') or ''
            if not name:
                continue
            immediate = a.get('immediate') is True
            arrival = ''
            fh = a.get('firstHeight') if isinstance(a.get('firstHeight'), dict) else None
            if immediate:
                arrival = '立即'
            elif fh and fh.get('arrivalTime'):
                at_str = fh.get('arrivalTime', '')
                if at_str:
                    try:
                        dt_str = timezone_utils.jst_to_display(at_str)
                        if ' ' in dt_str:
                            arrival = dt_str.split(' ')[1][:5]
                        else:
                            arrival = at_str[-8:-3] if len(at_str) >= 8 else at_str
                    except Exception:
                        arrival = at_str[-8:-3] if len(at_str) >= 8 else ''
            if arrival:
                region_bits.append(f"{name}({arrival})")
            else:
                region_bits.append(name)
        if region_bits:
            parts.append('、'.join(region_bits))
        return ''.join(parts).strip() or fallback

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get('type', 'report')
