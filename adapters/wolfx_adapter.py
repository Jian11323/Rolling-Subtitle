#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wolfx 数据源适配器
支持 HTTP GET 与 WebSocket：sc_eew, jma_eew, fj_eew, cenc_eew, cwa_eew, cenc_eqlist, jma_eqlist
文档：数据源文档/Wolfx WebSocket API 调用说明.txt
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

# EEW 类型（预警）
WOLFX_EEW_TYPES = {'sc_eew', 'jma_eew', 'fj_eew', 'cenc_eew', 'cwa_eew'}
# 速报类型
WOLFX_EQLIST_TYPES = {'cenc_eqlist', 'jma_eqlist'}


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


class WolfxAdapter(BaseAdapter):
    """Wolfx API 适配器（HTTP 单条 / WebSocket 单条）"""

    def __init__(self, source_type: str, source_url: str):
        """
        source_type: 如 sc_eew, jma_eew, fj_eew, cenc_eew, cwa_eew, cenc_eqlist, jma_eqlist 或 all_eew
        """
        super().__init__(source_type, source_url)
        self.data_source_type = source_type

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if not isinstance(data, dict):
                return None
            msg_type = data.get('type')
            if msg_type in ('heartbeat', 'pong'):
                return None
            # HTTP 单接口返回无 type 时用当前 source 类型（如 cwa_eew 文档未写 type）
            if not msg_type and self.data_source_type in WOLFX_EEW_TYPES:
                msg_type = self.data_source_type
            if not msg_type and self.data_source_type in WOLFX_EQLIST_TYPES:
                msg_type = self.data_source_type
            if msg_type in WOLFX_EEW_TYPES or msg_type == 'cwa_eew':
                return self._parse_eew(data, msg_type or self.data_source_type)
            if msg_type in WOLFX_EQLIST_TYPES:
                return self._parse_eqlist(data, msg_type)
            # all_eew WebSocket 推送带 type
            if msg_type and msg_type in WOLFX_EEW_TYPES:
                return self._parse_eew(data, msg_type)
            if msg_type and msg_type in WOLFX_EQLIST_TYPES:
                return self._parse_eqlist(data, msg_type)
            return None
        except Exception as e:
            logger.debug(f"[Wolfx] 解析跳过: {e}")
            return None

    def _parse_eew(self, data: Dict, api_type: str) -> Optional[Dict[str, Any]]:
        """解析预警类：sc_eew, jma_eew, fj_eew, cenc_eew, cwa_eew"""
        # 四川 / CENC / 福建：HypoCenter, ReportTime/OriginTime UTC+8, Magunitude/Magnitude
        place = data.get('HypoCenter') or data.get('Hypocenter') or ''
        lat = _safe_float(data.get('Latitude'))
        lon = _safe_float(data.get('Longitude'))
        mag = _safe_float(data.get('Magunitude') or data.get('Magnitude'))
        depth = _safe_float(data.get('Depth'))
        origin_time = data.get('OriginTime') or ''
        report_time = data.get('ReportTime') or ''
        event_id = data.get('EventID') or data.get('ID') or ''
        max_int = data.get('MaxIntensity') or ''

        # 时间：JMA 为 UTC+9，其余为 UTC+8
        if api_type == 'jma_eew' and origin_time:
            shock_time = timezone_utils.jst_to_display(origin_time)
        elif origin_time:
            shock_time = timezone_utils.cst_to_display(origin_time)
        else:
            shock_time = timezone_utils.cst_to_display(report_time) if report_time else ''

        # 取消报
        is_cancel = data.get('isCancel') is True
        if is_cancel:
            return None

        try:
            from config import Config
            organization = Config().get_organization_name(f'wolfx_{api_type}')
        except Exception:
            organization = self.get_organization_name()
        result = {
            'type': 'warning',
            'source_type': f'wolfx_{api_type}',
            'organization': organization,
            'place_name': place or '未知',
            'magnitude': mag,
            'latitude': lat,
            'longitude': lon,
            'depth': depth,
            'shock_time': shock_time,
            'event_id': str(event_id),
            'raw_data': data,
        }
        if max_int is not None and max_int != '':
            result['max_intensity'] = str(max_int)
        return result

    def _parse_eqlist(self, data: Dict, api_type: str) -> Optional[Dict[str, Any]]:
        """解析速报：cenc_eqlist / jma_eqlist 只选取第一条（No1），忽略 No2～No50 及 md5 等。"""
        # 仅解析 No1（最新一条），API 返回格式为 { "No1": {...}, "No2": {...}, ..., "md5": "..." }
        item = data.get('No1')
        if item is None or not isinstance(item, dict):
            # 兼容无 No1 包装的单条事件
            if isinstance(data.get('time'), str) or isinstance(data.get('location'), str):
                item = data
            else:
                return None
        place = item.get('placeName') or item.get('location') or ''
        # JMA 速报优先用 time_full（带秒），否则用 time
        time_str = (item.get('time_full') or item.get('time')) if api_type == 'jma_eqlist' else (item.get('time') or '')
        if api_type == 'jma_eqlist' and time_str:
            shock_time = timezone_utils.jst_to_display(time_str)
        elif time_str:
            shock_time = timezone_utils.cst_to_display(time_str)
        else:
            shock_time = ''
        mag = _safe_float(item.get('magnitude'))
        depth_raw = item.get('depth')
        try:
            depth = _safe_float(str(depth_raw).replace('km', '').strip()) if depth_raw is not None else 0.0
        except Exception:
            depth = 0.0
        lat = _safe_float(item.get('latitude'))
        lon = _safe_float(item.get('longitude'))
        try:
            from config import Config
            organization = Config().get_organization_name(f'wolfx_{api_type}')
        except Exception:
            organization = self.get_organization_name()
        return {
            'type': 'report',
            'source_type': f'wolfx_{api_type}',
            'organization': organization,
            'place_name': place or '未知',
            'magnitude': mag,
            'latitude': lat,
            'longitude': lon,
            'depth': depth,
            'shock_time': shock_time,
            'raw_data': data,
        }

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get('type', 'report')
