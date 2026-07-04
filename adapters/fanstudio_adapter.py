#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fan Studio数据源适配器
根据Fan Studio数据服务 API文档实现
支持所有数据源：
- 地震速报：cenc, ningxia, guangxi, shanxi, beijing, yunnan, cwa, hko, usgs, emsc, bcsf, gfz, usp, kma, fssn
- 地震预警：cea, cea-pr, cwa-eew, jma, sa, kma-eew
- 气象预警：weatheralarm
- 海啸信息：tsunami
"""

import json
import re
import ssl
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, List
from datetime import datetime
from .base_adapter import BaseAdapter
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import get_logger
from utils import timezone_utils
from config import CENC_IR_URL

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


def _resolve_event_id(
    data: Dict[str, Any],
    source_type: str,
    place_name: str = "",
    shock_time: str = "",
    latitude: float = 0.0,
    longitude: float = 0.0,
) -> str:
    """eventId/id 缺失时用稳定字段合成，避免轮播 event_id 为空。"""
    for key in ("eventId", "uniEventId", "id"):
        val = data.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    parts = [
        source_type or "",
        (place_name or "").strip(),
        (shock_time or "").strip(),
    ]
    if latitude or longitude:
        parts.append(f"{latitude:.4f},{longitude:.4f}")
    joined = ":".join(p for p in parts if p)
    return joined or f"{source_type}:unknown"


class FanStudioAdapter(BaseAdapter):
    """Fan Studio数据源适配器"""
    
    def __init__(self, source_name: str, source_url: str):
        """初始化适配器并从 URL 提取 Fan Studio 子源类型。"""
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

    # Fan Studio All 时按配置决定解析范围
    FANSTUDIO_WARNING_SOURCES = ['cea', 'cea-pr', 'cwa-eew', 'jma', 'sa', 'kma-eew']
    FANSTUDIO_REPORT_SOURCES = ['cenc', 'cenc-ir', 'ningxia', 'guangxi', 'shanxi', 'beijing', 'yunnan', 'cwa', 'hko',
                                'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma', 'fssn', 'fssn-cmt', 'weatheralarm', 'tsunami']

    # 映射 Fan Studio 子源 → Config.message_config 中的细粒度开关字段名
    FANSTUDIO_SOURCE_FLAG_FIELD = {
        # 预警类
        'cea': 'fanstudio_parse_cea',
        'cea-pr': 'fanstudio_parse_cea_pr',
        'cwa-eew': 'fanstudio_parse_cwa_eew',
        'jma': 'fanstudio_parse_jma',
        'sa': 'fanstudio_parse_sa',
        'kma-eew': 'fanstudio_parse_kma_eew',
        # 速报 / 其他
        'cenc': 'fanstudio_parse_cenc',
        'ningxia': 'fanstudio_parse_ningxia',
        'guangxi': 'fanstudio_parse_guangxi',
        'shanxi': 'fanstudio_parse_shanxi',
        'beijing': 'fanstudio_parse_beijing',
        'yunnan': 'fanstudio_parse_yunnan',
        'cwa': 'fanstudio_parse_cwa',
        'hko': 'fanstudio_parse_hko',
        'usgs': 'fanstudio_parse_usgs',
        'emsc': 'fanstudio_parse_emsc',
        'bcsf': 'fanstudio_parse_bcsf',
        'gfz': 'fanstudio_parse_gfz',
        'usp': 'fanstudio_parse_usp',
        'kma': 'fanstudio_parse_kma',
        'fssn': 'fanstudio_parse_fssn',
        'fssn-cmt': 'fanstudio_parse_fssn_cmt',
        'weatheralarm': 'fanstudio_parse_weatheralarm',
        'tsunami': 'fanstudio_parse_tsunami',
    }

    def _get_fanstudio_enabled_source_names_legacy(self, enabled_sources: Dict[str, bool], config: Any, all_url: str) -> set:
        """
        旧逻辑：仅根据 fanstudio_parse_warning / fanstudio_parse_report 决定解析范围。
        供极旧配置向后兼容使用，新配置优先使用细粒度 fanstudio_parse_* 开关。
        """
        out = set()
        if not enabled_sources.get(all_url, False):
            return out
        parse_warning = getattr(config.message_config, 'fanstudio_parse_warning', True)
        parse_report = getattr(config.message_config, 'fanstudio_parse_report', True)
        if parse_warning:
            out.update(self.FANSTUDIO_WARNING_SOURCES)
        if parse_report:
            out.update(self.FANSTUDIO_REPORT_SOURCES)
        return out

    def _get_fanstudio_enabled_source_names(self, enabled_sources: Dict[str, bool], config: Any, all_url: str) -> set:
        """
        新逻辑：基于 Config.message_config 中的 fanstudio_parse_* 细粒度开关，
        返回当前启用的 Fan Studio 子源名称集合。
        若细粒度字段不存在时退回旧逻辑。
        """
        # 若 enabled_sources 中 all_url 未启用，直接返回空集
        if not enabled_sources.get(all_url, False):
            return set()
        msg_cfg = getattr(config, 'message_config', None)
        if msg_cfg is None:
            return set()
        # 检查是否存在任意一个细粒度字段；若都不存在则认为是旧配置，退回 legacy 行为
        has_any_detail_flag = False
        for field in self.FANSTUDIO_SOURCE_FLAG_FIELD.values():
            if hasattr(msg_cfg, field):
                has_any_detail_flag = True
                break
        if not has_any_detail_flag:
            return self._get_fanstudio_enabled_source_names_legacy(enabled_sources, config, all_url)
        enabled_names = set()
        for source, field in self.FANSTUDIO_SOURCE_FLAG_FIELD.items():
            value = getattr(msg_cfg, field, True)
            if value:
                enabled_names.add(source)
        return enabled_names

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
            
            base_domain = "fanstudio.tech"
            all_url = f"wss://ws.{base_domain}/all"
            # 由配置 fanstudio_parse_* 细粒度开关决定解析范围（不合并单项 URL）
            enabled_source_names = self._get_fanstudio_enabled_source_names(enabled_sources, config, all_url)
            logger.info(f"[FanStudio适配器] 启用的数据源名称集合: {sorted(enabled_source_names)}")
            
            results = []
            # 所有数据源（按优先级排序）
            priority_sources = [
                # 地震预警（优先级最高）
                'cea', 'cea-pr', 'cwa-eew', 'jma', 'sa', 'kma-eew',
                # 地震速报
                'cenc', 'ningxia', 'guangxi', 'shanxi', 'beijing', 'yunnan', 'cwa', 'hko',
                'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma', 'fssn', 'fssn-cmt',
                # 气象预警、海啸信息
                'weatheralarm', 'tsunami'
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
                    # 优先级：预警 > 速报 > 气象预警 > 海啸信息
                    priority_sources = [
                        # 地震预警（优先级最高）
                        'cea', 'cea-pr', 'cwa-eew', 'jma', 'sa', 'kma-eew',
                        # 地震速报
                        'cenc', 'ningxia', 'guangxi', 'shanxi', 'beijing', 'yunnan', 'cwa', 'p2pquake', 'hko',
                        'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma', 'fssn', 'fssn-cmt',
                        # 气象预警、海啸信息
                        'weatheralarm', 'tsunami'
                    ]
                    
                    enabled_sources = getattr(self, '_enabled_sources', {})
                    config = getattr(self, '_config', None)
                    if config is None:
                        from config import Config
                        config = Config()
                        enabled_sources = config.enabled_sources
                    base_domain = "fanstudio.tech"
                    all_url = f"wss://ws.{base_domain}/all"
                    enabled_source_names = self._get_fanstudio_enabled_source_names(enabled_sources, config, all_url)
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
                if self.data_source_type == 'cenc-ir' and not source:
                    source = 'cenc-ir'
                if self.data_source_type == 'all':
                    config = getattr(self, '_config', None)
                    if config is None:
                        from config import Config
                        config = Config()
                    # 烈度速报独立 WSS 已关闭时，/all 仍可能推送同源 update，此处与 main_window 入口过滤一致
                    if source == 'cenc-ir' and not config.enabled_sources.get(
                        CENC_IR_URL, False
                    ):
                        logger.debug("[FanStudio] update cenc-ir：独立数据源已关闭，跳过")
                        return None
                    # All 通道转发的 P2PQuake 地震情報：与消息配置开关一致
                    if source == 'p2pquake' and not getattr(
                        config.message_config, 'p2pquake_parse_551', True
                    ):
                        logger.debug("[FanStudio] update p2pquake：地震情報解析已关闭，跳过")
                        return None
                    # 先按总类开关过滤（预警/速报）
                    parse_warning = getattr(config.message_config, 'fanstudio_parse_warning', True)
                    parse_report = getattr(config.message_config, 'fanstudio_parse_report', True)
                    if source in self.FANSTUDIO_WARNING_SOURCES and not parse_warning:
                        logger.debug(f"[FanStudio] update 数据源 {source} 未勾选解析预警，跳过")
                        return None
                    if source in self.FANSTUDIO_REPORT_SOURCES and not parse_report:
                        logger.debug(f"[FanStudio] update 数据源 {source} 未勾选解析速报，跳过")
                        return None
                    # 再按细粒度 fanstudio_parse_* 子源开关过滤
                    flag_field = self.FANSTUDIO_SOURCE_FLAG_FIELD.get(source)
                    if flag_field:
                        detail_enabled = getattr(config.message_config, flag_field, True)
                        if not detail_enabled:
                            logger.debug(f"[FanStudio] update 数据源 {source} 对应细粒度开关 {flag_field}=False，跳过")
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
            elif source_type == 'tsunami':
                result = self._parse_tsunami(data)
            elif source_type == 'fssn-cmt':
                result = self._parse_fssn_cmt(data)
            elif source_type == 'cenc-ir':
                result = self._parse_cenc_ir(data)
            elif source_type in ['cenc', 'ningxia', 'guangxi', 'shanxi', 'beijing', 'yunnan', 'cwa',
                                'hko', 'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma', 'fssn']:
                result = self._parse_earthquake_report(data, source_type)
            elif source_type in ['cea', 'cea-pr', 'cwa-eew', 'jma', 'sa', 'kma-eew']:
                result = self._parse_earthquake_warning(data, source_type)
            else:
                # 默认按速报处理
                result = self._parse_earthquake_report(data, source_type)
            
            # 如果是update类型，确保raw_data包含source字段，以便后续提取source_name
            if result and update_source and 'raw_data' in result:
                if isinstance(result['raw_data'], dict):
                    result['raw_data']['_update_source'] = update_source

            # 供消息格式化层识别 Fan Studio 子源，使用统一标头（与 Wolfx/P2P 等区分）
            if result and isinstance(result, dict):
                result['fanstudio'] = True

            return result
        except Exception as e:
            logger.error(f"【FanStudio适配器】 解析{source_type}数据时出错: {e}")
            return None

    def _parse_cenc_ir(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析 Fan Studio CENC 烈度速报（cenc-ir 独立通道）。"""
        def _normalize_json_obj(v: Any) -> Any:
            """兼容一层/多层字符串化 JSON（例如 "\"{...}\""）。"""
            cur = v
            for _ in range(3):
                if not isinstance(cur, str):
                    break
                s = cur.strip()
                if not s:
                    return cur
                # 去掉外围引号后再尝试（处理 "\"{...}\""）
                if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                    s = s[1:-1].strip()
                if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                    try:
                        nxt = json.loads(s)
                        if nxt is cur:
                            break
                        cur = nxt
                        continue
                    except Exception:
                        break
                break
            return cur

        def _deep_pick(obj: Any, key_candidates: List[str]) -> Any:
            """在嵌套 dict/list 中递归查找第一个匹配键。"""
            if isinstance(obj, dict):
                for k in key_candidates:
                    if k in obj and obj[k] not in (None, "", [], {}):
                        return _normalize_json_obj(obj[k])
                for vv in obj.values():
                    got = _deep_pick(vv, key_candidates)
                    if got not in (None, "", [], {}):
                        return got
            elif isinstance(obj, list):
                for it in obj:
                    got = _deep_pick(it, key_candidates)
                    if got not in (None, "", [], {}):
                        return got
            return None

        # cenc-ir 实际字段与常规速报不同，兼容 initial/update 两种消息体命名
        place_name = data.get('placeName', data.get('locName', data.get('title', data.get('nameByInfo', ''))))
        shock_time = data.get('shockTime', data.get('oriTime', data.get('createTime', data.get('gmtCreate', ''))))
        if not place_name and not shock_time:
            return None
        if shock_time:
            try:
                # 兼容毫秒时间戳（int/float）与字符串时间
                if isinstance(shock_time, (int, float)):
                    shock_time = timezone_utils.ms_timestamp_utc_to_display(float(shock_time))
                else:
                    shock_time = timezone_utils.cst_to_display(str(shock_time))
            except Exception:
                shock_time = str(shock_time)
        if self.data_source_type == 'all':
            organization = self._get_organization_name_by_type('cenc-ir')
        else:
            organization = self.get_organization_name()
        result = {
            'type': 'report',
            'source_type': 'cenc-ir',
            'place_name': place_name,
            'shock_time': shock_time,
            'magnitude': self._safe_float(data.get('magnitude', 0)),
            'latitude': self._safe_float(data.get('latitude', data.get('epiLat', 0))),
            'longitude': self._safe_float(data.get('longitude', data.get('epiLon', 0))),
            'depth': self._safe_float(data.get('depth', data.get('focDepth', 0))),
            'organization': organization,
            'event_id': data.get('eventId', data.get('uniEventId', data.get('id', ''))),
            'raw_data': data,
        }
        info_text = (data.get('intensityInfoText') or data.get('intensity_info_text') or '').strip()
        if info_text:
            result['cenc_ir_intensity_info_text'] = info_text
        contour = _deep_pick(
            data,
            [
                'cenc_ir_contour_geojson',
                'contourGeoJson',
                'contour_geojson',
                'contour',
                'isoseismalGeoJson',
                'isoseismal_geojson',
            ],
        )
        # 部分事件会把核心字段塞在 raw_event_json（字符串）中
        if contour in (None, "", [], {}):
            raw_event = _normalize_json_obj(data.get("raw_event_json"))
            contour = _deep_pick(
                raw_event,
                [
                    'cenc_ir_contour_geojson',
                    'contourGeoJson',
                    'contour_geojson',
                    'contour',
                    'isoseismalGeoJson',
                    'isoseismal_geojson',
                ],
            )
        if isinstance(contour, list):
            # 兼容仅给 features 数组的情况
            contour = {"type": "FeatureCollection", "features": contour}
        if isinstance(contour, dict):
            result['cenc_ir_contour_geojson'] = contour
        instrument_intensity = _deep_pick(
            data,
            [
                'instrumentIntensityJson',
                'instrument_intensity_json',
                'stationIntensityJson',
                'station_intensity_json',
                'stations',
            ],
        )
        if instrument_intensity in (None, "", [], {}):
            raw_event = _normalize_json_obj(data.get("raw_event_json"))
            instrument_intensity = _deep_pick(
                raw_event,
                [
                    'instrumentIntensityJson',
                    'instrument_intensity_json',
                    'stationIntensityJson',
                    'station_intensity_json',
                    'stations',
                ],
            )
        if isinstance(instrument_intensity, list) and instrument_intensity:
            result['cenc_ir_instrument_intensity_json'] = instrument_intensity
        logger.info(
            "[cenc-ir] 解析结果: keys=%s, contour=%s, contour_raw_type=%s, stations=%s",
            list(data.keys())[:20],
            "yes" if 'cenc_ir_contour_geojson' in result else "no",
            type(data.get("contour_geojson")).__name__ if "contour_geojson" in data else "missing",
            len(result.get('cenc_ir_instrument_intensity_json') or []),
        )
        return result
    
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

    def _parse_fssn_cmt(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        解析 FSSN 矩心矩张量解 (CMT) 数据。
        返回与速报一致的结构，并保留 nodal_plane_1 / nodal_plane_2 供沙滩球绘制使用。
        """
        place_name = data.get('placeName', '')
        shock_time = data.get('shockTime', '')
        if not place_name and not shock_time:
            return None
        latitude = self._safe_float(data.get('latitude', 0))
        longitude = self._safe_float(data.get('longitude', 0))
        depth_str = data.get('depth', '')
        if isinstance(depth_str, str):
            match = re.match(r'^([\d.]+)', depth_str.strip())
            depth = self._safe_float(match.group(1), 10.0) if match else 10.0
        else:
            depth = self._safe_float(depth_str, 10.0)
        all_mag = data.get('allMagnitudes') or {}
        magnitude = self._safe_float(
            all_mag.get('Mww') or all_mag.get('M') or all_mag.get('mB') or all_mag.get('mb') or all_mag.get('Mwp') or 0
        )
        nodal_plane_1 = data.get('nodalPlane1', '')
        nodal_plane_2 = data.get('nodalPlane2', '')
        if shock_time:
            shock_time = timezone_utils.cst_to_display(shock_time)
        event_id = _resolve_event_id(
            data, 'fssn-cmt', place_name, shock_time, latitude, longitude
        )
        if self.data_source_type == 'all':
            organization = self._get_organization_name_by_type('fssn-cmt')
        else:
            organization = self.get_organization_name()
        result = {
            'type': 'report',
            'source_type': 'fssn-cmt',
            'place_name': place_name,
            'shock_time': shock_time,
            'magnitude': magnitude,
            'latitude': latitude,
            'longitude': longitude,
            'depth': depth,
            'organization': organization,
            'event_id': event_id,
            'raw_data': data,
        }
        if nodal_plane_1:
            result['nodal_plane_1'] = nodal_plane_1
        if nodal_plane_2:
            result['nodal_plane_2'] = nodal_plane_2
        for key in ('mnn', 'mee', 'mdd', 'mne', 'mnd', 'med'):
            val = data.get(key)
            if val is not None and (val != '' if isinstance(val, str) else True):
                result[key] = val
        return result

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
        raw_mag = data.get('magnitude')
        if raw_mag is None:
            raw_mag = data.get('magnitudel')
        magnitude = self._safe_float(raw_mag, 0)
        latitude = self._safe_float(data.get('latitude', 0))
        longitude = self._safe_float(data.get('longitude', 0))
        depth = self._safe_float(data.get('depth', 0))
        
        # 应用地名修正（针对usgs, emsc, bcsf, gfz, usp, kma数据源）
        # 只有在配置中启用了地名修正时才应用
        if place_name and latitude and longitude:
            try:
                from config import Config
                config = Config()
                from utils.place_name_utils import should_apply_place_name_fix
                if should_apply_place_name_fix(config):
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
        # 格式化时间（FanStudio 速报均为 UTC+8，转为显示时区）
        if shock_time:
            shock_time = timezone_utils.cst_to_display(shock_time)

        event_id = _resolve_event_id(
            data, source_type, place_name, shock_time, latitude, longitude
        )
        # 不向展示层传递 HKO verify、USGS/FSSN infoTypeName 等区分字段（标头与正文均不依赖）
        info_type = data.get('infoTypeName', '') if source_type not in ('hko', 'usgs', 'fssn') else ''
        
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
                from utils.place_name_utils import should_apply_place_name_fix
                if should_apply_place_name_fix(config):
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
                # 非 JMA 数据源为 UTC+8，转为显示时区
                shock_time = timezone_utils.cst_to_display(shock_time)
        
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

        eff_raw = data.get("effective", "")
        eff_display = (
            timezone_utils.flexible_time_to_display(str(eff_raw)) if eff_raw else ""
        )

        return {
            'type': 'weather',
            'magnitude': 0,
            'latitude': self._safe_float(data.get('latitude', 0)),
            'longitude': self._safe_float(data.get('longitude', 0)),
            'depth': 0,
            'place_name': data.get('headline', data.get('title', '')),
            'shock_time': eff_display or str(eff_raw).strip(),
            'organization': organization,
            'title': data.get('title', data.get('headline', '')),
            'description': data.get('description', ''),
            'warning_type': data.get('type', ''),
            'event_id': event_id,  # 添加event_id用于去重
            'source_type': 'weatheralarm',  # 添加数据源类型
            'raw_data': data,
        }

    def _parse_tsunami(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        解析海啸信息数据（自然资源部海啸预警中心）。
        显示格式参考 P2PQuake 海啸：等级 + 震源/海域 + 预计浪高（如有）+ 沿海预报区域及到达时间（如有）。
        """
        if not data or not isinstance(data, dict):
            return None
        warning_info = data.get('warningInfo') or {}
        time_info = data.get('timeInfo') or {}
        shock_info = data.get('shockInfo') or {}
        details = data.get('details') or {}
        forecasts = data.get('forecasts') or []
        water_level_monitoring = data.get('waterLevelMonitoring') or []
        shock_time = shock_info.get('shockTime') or time_info.get('alarmDate') or ''
        if not shock_time:
            return None
        if shock_time:
            shock_time = timezone_utils.cst_to_display(shock_time)
        organization = warning_info.get('orgUnit') or self._get_organization_name_by_type('tsunami')
        # 机构名带 LEVEL：第X报 XXX通报
        batch = (details.get('batch') or '').strip()
        title = (warning_info.get('title') or '海啸信息').strip()
        if batch:
            organization = f"{organization} 第{batch}报 {title}通报".strip()
        else:
            organization = f"{organization} {title}通报".strip() if title else organization
        magnitude = self._safe_float(shock_info.get('magnitude'), 0)
        depth = self._safe_float(shock_info.get('depth'), 0)
        latitude = self._safe_float(shock_info.get('latitude'), 0)
        longitude = self._safe_float(shock_info.get('longitude'), 0)
        event_id = data.get('id') or data.get('code') or ''
        # 按 P2PQuake 海啸格式拼接详细说明：等级 + 震源海域 + 预计浪高 + 沿海区域(到达时间)
        place_name = self._build_tsunami_detail_nmefc(
            warning_info=warning_info,
            shock_info=shock_info,
            details=details,
            forecasts=forecasts,
        )
        logo_url = (details.get('logoUrl') or '').strip()
        # 相对路径时用 htmlUrl 同源拼成绝对 URL，避免前端请求失败
        if logo_url and not logo_url.startswith(('http://', 'https://')):
            html_url_for_base = (details.get('htmlUrl') or '').strip()
            if html_url_for_base:
                logo_url = urllib.parse.urljoin(html_url_for_base, logo_url)
        # 海啸 logo 为 obs.nmefc.cn 时：path 规范化为单次编码，并强制使用 https（该站仅 HTTPS 可访问）
        if logo_url and 'obs.nmefc.cn' in logo_url:
            try:
                parsed_logo = urllib.parse.urlparse(logo_url)
                path_decoded = urllib.parse.unquote(parsed_logo.path, encoding='utf-8')
                path_encoded = urllib.parse.quote(path_decoded, safe='/', encoding='utf-8')
                scheme = 'https' if parsed_logo.scheme == 'http' else parsed_logo.scheme
                logo_url = urllib.parse.urlunparse((scheme, parsed_logo.netloc, path_encoded, parsed_logo.params, parsed_logo.query, parsed_logo.fragment))
            except Exception:
                pass
        result = {
            'type': 'report',
            'is_tsunami': True,
            'source_type': 'tsunami',
            'place_name': place_name,
            'shock_time': shock_time,
            'organization': organization,
            'magnitude': magnitude,
            'depth': depth,
            'latitude': latitude,
            'longitude': longitude,
            'event_id': event_id,
            'tsunami_code': data.get('code', ''),
            'tsunami_warning_level': (warning_info.get('level') or '').strip(),
            'tsunami_warning_title': title,
            'tsunami_warning_subtitle': (warning_info.get('subtitle') or '').strip(),
            'tsunami_update_time': (time_info.get('updateDate') or '').strip(),
            'tsunami_forecasts': forecasts if isinstance(forecasts, list) else [],
            'tsunami_water_level_monitoring': water_level_monitoring if isinstance(water_level_monitoring, list) else [],
            'raw_data': data,
        }
        if logo_url:
            result['logo_url'] = logo_url
        html_url = (details.get('htmlUrl') or '').strip()
        if html_url:
            remarks = self._fetch_tsunami_remarks(html_url)
            if remarks:
                result['tsunami_remarks'] = remarks
        return result

    def _fetch_tsunami_remarks(self, html_url: str) -> str:
        """
        从 details.htmlUrl 拉取 HTML，解析出备注等通报正文。
        优先提取「备注」或「|| 备注」后的内容；否则返回主内容区全文。
        """
        if not html_url or not isinstance(html_url, str):
            return ''
        try:
            req = urllib.request.Request(html_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                raw = resp.read()
            html = raw.decode('utf-8', errors='replace')
        except Exception as e:
            logger.debug(f"[海啸] 拉取 htmlUrl 失败: {html_url[:60]}..., {e}")
            return ''
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.debug("[海啸] 解析 htmlUrl 需要 beautifulsoup4")
            return ''
        try:
            soup = BeautifulSoup(html, 'html.parser')
            full_text = soup.get_text(separator='\n', strip=True)
        except Exception as e:
            logger.debug(f"[海啸] 解析 HTML 失败: {e}")
            return ''
        if not full_text:
            return ''

        def _strip_note_section(s: str) -> str:
            """去掉「注：」及之后的说明段，不展示注的内容。"""
            for note_marker in ['注：', '注:']:
                if note_marker in s:
                    s = s.split(note_marker)[0].strip()
                    break
            return s

        # 优先提取「备注」或「|| 备注」后的内容
        for marker in ['|| 备注:', '备注:', '|| 备注：', '备注：']:
            idx = full_text.find(marker)
            if idx >= 0:
                remarks = full_text[idx + len(marker):].strip()
                remarks = re.sub(r'\n+', '。', remarks)
                remarks = re.sub(r'\s+', ' ', remarks).strip()
                remarks = _strip_note_section(remarks)
                return remarks if remarks else ''
        full_clean = re.sub(r'\n+', '。', re.sub(r'\s+', ' ', full_text).strip())
        return _strip_note_section(full_clean)

    def _build_tsunami_detail_nmefc(
        self,
        warning_info: Dict[str, Any],
        shock_info: Dict[str, Any],
        details: Dict[str, Any],
        forecasts: List[Dict[str, Any]],
    ) -> str:
        """
        拼接自然资源部海啸详细说明，格式参考 P2PQuake：等级 + 震源海域 + 预计浪高 + 沿海省份(到达时间)。
        示例：海啸信息 加里曼丹岛(婆罗洲)海域。预计浪高约50厘米。福建(10:30)、广东(11:00)
        """
        parts = []
        level = (warning_info.get('level') or warning_info.get('title') or '').strip()
        if level:
            parts.append(level + ' ')
        place = (shock_info.get('placeName') or warning_info.get('subtitle') or '').strip()
        if place:
            parts.append(place)
        flist = [x for x in (forecasts or []) if isinstance(x, dict)]
        max_height_str = None
        for f in flist:
            if f.get('maxWaveHeight'):
                max_height_str = f.get('maxWaveHeight')
                break
        # 若值为纯数字或区间（如 90、30-100），按文档补上厘米单位；已有单位则保持原样。
        if isinstance(max_height_str, str):
            mh = max_height_str.strip()
            if mh and not any(u in mh for u in ("厘米", "cm", "CM", "米", "m", "M")):
                max_height_str = f"{mh}厘米"
        region_bits = []
        for f in flist[:8]:
            prov = (f.get('province') or f.get('warningLevel') or '').strip()
            eta = (f.get('estimatedArrivalTime') or '').strip()
            if not prov:
                continue
            if eta:
                region_bits.append(f"{prov}({eta})")
            else:
                region_bits.append(prov)
        if max_height_str or region_bits:
            if parts:
                parts.append('。')
            if max_height_str:
                parts.append(f"预计浪高约{max_height_str}。")
            if region_bits:
                parts.append('、'.join(region_bits))
        return ''.join(parts).strip() or (place or level or '海啸信息')

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
