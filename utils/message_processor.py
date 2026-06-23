#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息处理和格式化模块
负责将解析后的数据格式化为显示消息
"""

from typing import Dict, Any, Optional
import re

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from utils.logger import get_logger
from utils import timezone_utils
from utils.place_name_utils import should_apply_place_name_fix, should_translate_place_name
from utils.translation_service import TranslationService

_place_name_fixer = None


def _get_place_name_fixer():
    global _place_name_fixer
    if _place_name_fixer is None:
        try:
            from utils.place_name_fixer import PlaceNameFixer
            _place_name_fixer = PlaceNameFixer()
        except Exception as e:
            logger.debug(f"初始化地名修正器失败: {e}")
            _place_name_fixer = None
    return _place_name_fixer


def warning_shock_validity_max_seconds(source_type: str, msg_cfg: Any) -> float:
    """与入口校验一致：按 source_type 取发震时间有效期窗口（秒）。"""
    st = (source_type or "").strip()
    if st == "wolfx_jma_eew":
        return float(
            getattr(
                msg_cfg,
                "warning_shock_validity_seconds_nied",
                msg_cfg.warning_shock_validity_seconds,
            )
        )
    if st in ("wolfx_sc_eew", "early_est"):
        return float(
            getattr(
                msg_cfg,
                "warning_shock_validity_seconds_early_est",
                msg_cfg.warning_shock_validity_seconds,
            )
        )
    return float(msg_cfg.warning_shock_validity_seconds)


def warning_shock_validity_remaining_seconds(
    data: Dict[str, Any],
    msg_cfg: Any,
) -> Optional[float]:
    """
    发震时间有效期剩余秒数：max_seconds - (now - shock_time)。

    - ``None``：无发震时间或无法解析（与入口「默认有效」语义一致，由调用方决定兜底时长）。
    - ``float('inf')``：``disable_warning_expiry_for_test`` 开启。
    - 否则为剩余秒数，可能 ≤0 表示已过期。
    """
    if getattr(msg_cfg, "disable_warning_expiry_for_test", False):
        return float("inf")
    shock_time_str = (data or {}).get("shock_time", "") or ""
    if not shock_time_str:
        return None
    shock_time = timezone_utils.parse_display_time(shock_time_str)
    if shock_time is None:
        return None
    time_diff = (timezone_utils.now_in_display_tz() - shock_time).total_seconds()
    source_type = (data or {}).get("source_type", "") or ""
    max_seconds = warning_shock_validity_max_seconds(source_type, msg_cfg)
    return max_seconds - time_diff
from utils.epi_intensity_estimate import (
    SOURCE_NO_CHINA_EPI_ESTIMATE,
    estimate_epi_intensity,
    parsed_declares_epi_intensity,
)

logger = get_logger()

# 中国气象局预警图标基础 URL，可根据 type 编码查询预警图标
NMC_ALARM_IMAGE_BASE = "https://image.nmc.cn/assets/img/alarm"


class MessageProcessor:
    """消息处理器"""
    
    def __init__(self):
        self.config = Config()
        try:
            self.translator = TranslationService(self.config)
            logger.info("翻译服务已初始化")
        except Exception as e:
            logger.error(f"初始化翻译服务失败: {e}")
            self.translator = None

    def _apply_coord_place_name_fix(
        self,
        place_name: str,
        source_type: str,
        lat: Optional[float],
        lon: Optional[float],
    ) -> str:
        """按经纬度修正地名（fe_fix 区域库）。"""
        if lat is None or lon is None:
            return place_name
        fixer = _get_place_name_fixer()
        if not fixer or not fixer.is_supported(source_type):
            return place_name
        try:
            fixed = fixer.fix_place_name(place_name, lat, lon, source_type)
            if fixed and fixed != place_name:
                logger.debug(f"地名修正: {place_name} -> {fixed} ({source_type})")
                return fixed
        except Exception as e:
            logger.debug(f"地名修正失败: {e}")
        return place_name

    def _localize_place_name(
        self,
        place_name: str,
        source_type: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> str:
        """地名修正或百度翻译：非中文数据源二选一；翻译失败时回退经纬度修正。"""
        if not place_name:
            return place_name

        lat = self._safe_float(latitude, 0.0) if latitude is not None else None
        lon = self._safe_float(longitude, 0.0) if longitude is not None else None
        if lat is not None and lon is not None and lat == 0.0 and lon == 0.0:
            lat = lon = None

        if should_apply_place_name_fix(self.config):
            place_name = self._apply_coord_place_name_fix(
                place_name, source_type, lat, lon
            )
            return place_name

        if not getattr(self.config.translation_config, "enabled", False):
            return place_name
        if not should_translate_place_name(source_type, place_name):
            return place_name
        if not self.translator:
            return place_name
        original = place_name
        try:
            translated = self.translator.translate(place_name, quick_mode=False)
            if translated and translated != place_name:
                logger.info(f"地名翻译: {place_name} -> {translated} ({source_type})")
                return translated
        except Exception as e:
            logger.warning(f"翻译地名失败，保持原文: {place_name}, 错误: {e}")
        # 百度翻译未生效时，仍尝试经纬度修正（如 BMKG / GeoNet / INGV 等）
        return self._apply_coord_place_name_fix(original, source_type, lat, lon)

    def _translate_text_if_needed(self, text: str) -> str:
        """百度翻译模式下，翻译含非中文的文本（如火山情报字段）。"""
        if not text or not getattr(self.config.translation_config, "enabled", False):
            return text
        if not self.translator:
            return text
        has_non_chinese = bool(re.search(r"[^\u4e00-\u9fff\s]", text))
        if not has_non_chinese:
            return text
        try:
            translated = self.translator.translate(text, quick_mode=False)
            if translated and translated.strip():
                return translated.strip()
        except Exception as e:
            logger.debug(f"文本翻译失败，保持原文: {e}")
        return text
    
    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        """
        安全转换为浮点数（参考fused_eew_api_v2.py的Utils类）
        
        Args:
            value: 要转换的值
            default: 转换失败时的默认值
            
        Returns:
            转换后的浮点数
        """
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def format_message(
        self,
        parsed_data: Dict[str, Any],
        *,
        ignore_warning_expiry: bool = False,
    ) -> Optional[str]:
        """
        格式化消息
        
        Args:
            parsed_data: 解析后的数据字典
            
        Returns:
            格式化后的消息字符串，如果无法格式化则返回None
        """
        try:
            message_type = parsed_data.get('type', 'report')
            # 对于预警消息，检查有效时间（见 _is_warning_valid：发震时间在配置窗口内有效）
            # 无论是initial_all还是update类型的消息，都需要检查有效性
            # 避免显示明显过期的历史预警数据
            if message_type == 'warning':
                # JMA数据特殊处理：检查cancel字段，如果为true，应撤销该事件的预警
                source_type = parsed_data.get('source_type', '')
                if source_type == 'jma':
                    is_cancel = parsed_data.get('cancel', False)
                    if is_cancel:
                        event_id = parsed_data.get('event_id', '')
                        logger.info(f"JMA预警消息被取消（cancel=true），忽略: event_id={event_id}")
                        return None
                
                # 检查有效性（发震时间在配置的有效期内）
                # 对 Wolfx 的 JMA / 四川预警使用单独有效期窗口：
                # - wolfx_jma_eew: warning_shock_validity_seconds_nied（默认 5 分钟）
                # - wolfx_sc_eew: warning_shock_validity_seconds_early_est（默认 10 分钟）
                is_valid = self._is_warning_valid(parsed_data)
                if not is_valid and not ignore_warning_expiry:
                    shock_time = parsed_data.get('shock_time', '')
                    event_id = parsed_data.get('event_id', '')
                    logger.debug(f"预警消息已过期（format_message 阶段），忽略: event_id={event_id}, shock_time={shock_time}, source_type={source_type}")
                    return None
                if not is_valid and ignore_warning_expiry:
                    logger.debug(
                        "预警已过期，但 ignore_warning_expiry=True，仍格式化供历史/TTS 测试: "
                        f"event_id={parsed_data.get('event_id')}, source_type={source_type}"
                    )
                
                # 格式化预警消息
                try:
                    logger.debug(f"开始格式化预警消息，数据: organization={parsed_data.get('organization')}, place_name={parsed_data.get('place_name')}, magnitude={parsed_data.get('magnitude')}, source_type={parsed_data.get('source_type')}")
                    result = self._format_warning_message(parsed_data)
                    if not result or result.strip() == "":
                        logger.warning(f"预警消息格式化结果为空，数据: {parsed_data}")
                        return None
                    logger.debug(f"预警消息格式化成功: {result}")
                    return result
                except Exception as e:
                    logger.error(f"格式化预警消息时发生异常: {e}, 数据: {parsed_data}", exc_info=True)
                    return None
            elif message_type == 'report':
                if parsed_data.get('source_type') == 'fanstudio_typhoon':
                    return self._format_fanstudio_typhoon_message(parsed_data)
                if parsed_data.get('source_type') == 'fanstudio_aqi':
                    return self._format_fanstudio_aqi_message(parsed_data)
                if parsed_data.get('source_type') == 'fssn-cmt':
                    return self._format_fssn_cmt_message(parsed_data)
                if parsed_data.get('source_type') == 'cenc-ir':
                    return self._format_cenc_ir_message(parsed_data)
                return self._format_report_message(parsed_data)
            elif message_type == 'weather':
                return self._format_weather_message(parsed_data)
            elif message_type == 'volcano':
                return self._format_volcano_message(parsed_data)
            else:
                return self._format_generic_message(parsed_data)
        except Exception as e:
            logger.error(f"【消息处理器】 格式化消息时出错: {e}, 数据: {parsed_data}", exc_info=True)
            return None
    
    def _is_warning_valid(self, data: Dict[str, Any]) -> bool:
        """
        检查预警消息是否有效（入口侧：按发震时间窗口）。
        超过发震时间有效期的预警在入队时丢弃，不进入缓冲区、不展示。
        发震时间在 warning_shock_validity_seconds（默认 5 分钟）内有效。

        Args:
            data: 解析后的数据字典
            
        Returns:
            True表示有效，False表示已过期
        """
        try:
            msg_cfg = self.config.message_config
            rem = warning_shock_validity_remaining_seconds(data, msg_cfg)
            if rem is None:
                return True
            if rem == float("inf") or rem > 1e200:
                return True

            source_type = (data or {}).get("source_type", "") or ""
            event_id = (data or {}).get("event_id", "")
            shock_time_str = (data or {}).get("shock_time", "") or ""
            max_seconds = warning_shock_validity_max_seconds(source_type, msg_cfg)
            time_diff = max_seconds - rem
            is_valid = rem > 0
            if not is_valid:
                minutes_diff = time_diff / 60
                logger.info(
                    f"预警消息已过期(入口判定): source_type={source_type}, event_id={event_id}, "
                    f"shock_time={shock_time_str}, time_diff={int(time_diff)}秒({minutes_diff:.1f}分钟), "
                    f"max_seconds={int(max_seconds)}"
                )
            else:
                logger.debug(
                    f"预警消息仍在有效期内: source_type={source_type}, event_id={event_id}, "
                    f"shock_time={shock_time_str}, remained={int(rem)}秒"
                )
            return is_valid
        except Exception as e:
            logger.error(f"【消息处理器】 检查预警有效性时出错: {e}")
            # 出错时默认有效，避免误过滤
            return True

    @staticmethod
    def _raw_or_data_has_epi_intensity_key(data: Dict[str, Any]) -> bool:
        """是否存在报文自带的强度字段（日台/Wolfx 常见 MaxIntensity，解析后多为 epiIntensity）。"""
        keys = ("epiIntensity", "epi_intensity", "MaxIntensity", "maxIntensity")
        raw = data.get("raw_data")
        if isinstance(raw, dict) and any(k in raw for k in keys):
            return True
        return any(k in data for k in keys)

    @staticmethod
    def _resolve_epi_intensity_value(data: Dict[str, Any]) -> Any:
        raw = data.get("raw_data")
        for k in ("epi_intensity", "epiIntensity", "MaxIntensity", "maxIntensity"):
            v = data.get(k)
            if v is not None:
                return v
        if isinstance(raw, dict):
            for k in ("epiIntensity", "epi_intensity", "MaxIntensity", "maxIntensity"):
                rv = raw.get(k)
                if rv is not None:
                    return rv
        return None

    def _maybe_inject_estimated_epi_intensity(
        self, data: Dict[str, Any], source_type_lower: str
    ) -> None:
        """无震中烈度字段时对非日台源写入经验估算值（台湾、日本源不估算）。"""
        if source_type_lower in SOURCE_NO_CHINA_EPI_ESTIMATE:
            return
        if parsed_declares_epi_intensity(data):
            return
        mag = self._safe_float(data.get("magnitude"), 0.0)
        if mag <= 0:
            return
        depth_raw = data.get("depth")
        h = None
        if depth_raw is not None:
            d = self._safe_float(depth_raw, 0.0)
            if d > 0:
                h = d
        est = estimate_epi_intensity(mag, h)
        if est is not None and est > 0:
            data["epi_intensity"] = round(est, 1)

    def _append_epi_intensity_after_depth(
        self,
        message_parts: list,
        data: Dict[str, Any],
        source_type: str,
    ) -> None:
        """
        深度之后：
        - 日本气象厅、台湾气象署及 Wolfx 的 JMA/CWA 等（SOURCE_NO_CHINA_EPI_ESTIMATE）：
          仅当报文含强度字段时追加「预估最大震度」（Wolfx 的 MaxIntensity 在适配层映射为 epiIntensity）。
        - 其它预警/速报：有报文震中烈度则用报文值；否则对非日台源用浅源经验式估算后追加「预估最大烈度」。
        """
        st = (source_type or "").strip().lower()
        self._maybe_inject_estimated_epi_intensity(data, st)
        epi_intensity = self._resolve_epi_intensity_value(data)
        if epi_intensity is not None:
            es = str(epi_intensity).strip()
            if (
                es
                and ("弱" in es or "強" in es)
                and st in SOURCE_NO_CHINA_EPI_ESTIMATE
                and self._raw_or_data_has_epi_intensity_key(data)
            ):
                message_parts.append(f"，预估最大震度{es}")
                return
        try:
            intensity_val = self._safe_float(epi_intensity, 0) if epi_intensity is not None else 0.0
        except (ValueError, TypeError):
            intensity_val = 0.0
        if intensity_val <= 0:
            return
        if st in SOURCE_NO_CHINA_EPI_ESTIMATE:
            if not self._raw_or_data_has_epi_intensity_key(data):
                return
            message_parts.append(f"，预估最大震度{intensity_val:.1f}")
        else:
            message_parts.append(f"，预估最大烈度{intensity_val:.1f}")

    @staticmethod
    def _append_wolfx_jma_accuracy_line(
        message_parts: list,
        data: Dict[str, Any],
        source_type: str,
    ) -> None:
        """Wolfx JMA EEW：Accuracy 震中/深度/震级精度说明（新 JSON 格式）。"""
        if (source_type or "").strip().lower() != "wolfx_jma_eew":
            return
        ae = (data.get("wolfx_jma_accuracy_epicenter") or "").strip()
        ad = (data.get("wolfx_jma_accuracy_depth") or "").strip()
        am = (data.get("wolfx_jma_accuracy_magnitude") or "").strip()
        chunks: list[str] = []
        if ae:
            chunks.append(f"震中精度：{ae}")
        if ad:
            chunks.append(f"深度精度：{ad}")
        if am:
            chunks.append(f"震级精度：{am}")
        if not chunks:
            return
        message_parts.append("。" + "，".join(chunks) + "，")

    @staticmethod
    def _strip_fanstudio_brackets(s: Any) -> str:
        """去掉测定标识符等外层方括号，如 [自动测定] / 【正式测定】 → 正式测定。"""
        if s is None:
            return ""
        t = str(s).strip()
        while len(t) >= 2 and t.startswith("[") and t.endswith("]"):
            t = t[1:-1].strip()
        while len(t) >= 2 and t.startswith("【") and t.endswith("】"):
            t = t[1:-1].strip()
        return t

    def _fanstudio_cea_pr_warning_header(self, province: str) -> str:
        """省级预警标头：【省/市/自治区全称地震局地震预警】，尽量与 API province 自动匹配。"""
        p = (province or "").strip()
        if not p:
            return "【省级地震局地震预警】"
        if p.endswith("地震局地震预警"):
            return f"【{p}】"
        for suffix in ("省", "市", "壮族自治区", "回族自治区", "维吾尔自治区", "自治区"):
            if p.endswith(suffix):
                return f"【{p}地震局地震预警】"
        municipalities_short = ("北京", "上海", "天津", "重庆")
        if p in municipalities_short:
            return f"【{p}市地震局地震预警】"
        municipalities_full = ("北京市", "上海市", "天津市", "重庆市")
        if p in municipalities_full:
            return f"【{p}地震局地震预警】"
        autonomous_short = {
            "内蒙古": "内蒙古自治区",
            "广西": "广西壮族自治区",
            "西藏": "西藏自治区",
            "宁夏": "宁夏回族自治区",
            "新疆": "新疆维吾尔自治区",
        }
        if p in autonomous_short:
            return f"【{autonomous_short[p]}地震局地震预警】"
        return f"【{p}省地震局地震预警】"

    def _fanstudio_warning_header(self, data: Dict[str, Any]) -> str:
        """Fan Studio 预警类统一标头（与 Wolfx 等区分）。"""
        st = data.get("source_type") or ""
        province = (data.get("province") or "").strip()
        it = (data.get("info_type") or "").strip()
        if st == "cea":
            return "【中国地震预警网地震预警】"
        if st == "cea-pr":
            return self._fanstudio_cea_pr_warning_header(province)
        if st == "cwa-eew":
            return "【台湾省气象署地震预警】"
        if st == "sa":
            return "【美国ShakeAlert地震预警】"
        if st == "jma":
            if it:
                return f"【日本气象厅  緊急地震速報  {it}】"
            return "【日本气象厅  緊急地震速報】"
        if st == "kma-eew":
            return "【韩国气象厅地震预警】"
        org = (data.get("organization") or "").strip()
        if org:
            if "地震预警" in org or "地震情报" in org:
                return f"【{org}】"
            return f"【{org}地震预警】"
        return "【地震预警】"

    def _fanstudio_report_header(self, data: Dict[str, Any]) -> str:
        """Fan Studio 速报/气象/海啸等统一标头。"""
        st = data.get("source_type") or ""
        raw = data.get("raw_data") or {}
        if not isinstance(raw, dict):
            raw = {}
        info_type = (data.get("info_type") or "").strip()
        if st == "weatheralarm":
            return "【中国气象局气象预警】"
        if st == "tsunami":
            details = raw.get("details") if isinstance(raw.get("details"), dict) else {}
            batch_raw = details.get("batch", "")
            batch = str(batch_raw).strip() if batch_raw is not None else ""
            title = (data.get("tsunami_warning_title") or "").strip()
            if batch and title:
                return f"【自然资源部海啸预警中心 第{batch}报 {title}】"
            if batch:
                return f"【自然资源部海啸预警中心 第{batch}报】"
            if title:
                return f"【自然资源部海啸预警中心 {title}】"
            return "【自然资源部海啸预警中心】"
        if st == "cenc":
            raw_it = raw.get("infoTypeName") or info_type
            clean = self._strip_fanstudio_brackets(raw_it)
            raw_s = str(raw_it or "")
            if "烈度速报" in clean or "烈度速报" in raw_s:
                return "【中国地震台网中心地震烈度速报】"
            if clean:
                return f"【中国地震台网中心地震信息 {clean}】"
            return "【中国地震台网中心地震信息】"
        fixed = {
            "cenc-ir": "【中国地震台网中心地震烈度速报】",
            "ningxia": "【宁夏回族自治区地震局地震信息】",
            "guangxi": "【广西壮族自治区地震局地震信息】",
            "shanxi": "【山西省地震局地震信息】",
            "beijing": "【北京市地震局地震信息】",
            "yunnan": "【云南省地震局地震信息】",
            "cwa": "【台湾省气象署地震报告】",
            "hko": "【香港天文台地震信息】",
            "usgs": "【美国地质调查局地震信息】",
            "emsc": "【欧洲地中海地震中心地震信息】",
            "bcsf": "【法国中央地震研究所地震信息】",
            "gfz": "【德国地学研究中心地震信息】",
            "usp": "【巴西圣保罗大学地震信息】",
            "kma": "【韩国气象厅地震信息】",
            "fssn": "【FSSN 地震信息】",
        }
        if st in fixed:
            return fixed[st]
        org = (data.get("organization") or "").strip()
        if org:
            return f"【{org}】"
        return "【地震信息】"
    
    def _format_warning_message(self, data: Dict[str, Any]) -> str:
        """
        格式化预警消息
        格式：【中国地震预警网预警】第1报，shocktime地点发生X级地震，震源深度X公里
        省级预警格式：【province地震局地震预警】第1报，shocktime地点发生X.X级地震，震源深度X公里
        日本气象厅格式：【日本气象厅 紧急地震速报 infoTypeName】 第1报，shocktime地点发生X.X级地震，震源深度X公里
        日本气象厅最终报格式：【日本气象厅 紧急地震速报 infoTypeName】 最终报，shocktime地点发生X.X级地震，震源深度X公里
        
        注意：
        - cancel字段为true时，消息会被忽略（不显示）
        - final字段为true时，显示"最终报"而不是"第x报"
        - 预警地名：百度翻译模式下对非中文数据源翻译；地名修正模式下保持适配器处理结果
        """
        try:
            organization = data.get('organization', '')
            source_type = data.get('source_type', '')  # 获取数据源类型
            province = data.get('province', '')  # 获取省份（用于省级预警）
            info_type = data.get('info_type', '')  # 获取infoTypeName字段（用于日本气象厅，保持日语原文）
            magnitude = self._safe_float(data.get('magnitude', 0), 0.0)
            place_name = data.get('place_name', '')
        except Exception as e:
            logger.error(f"【消息处理器】获取预警消息字段时出错: {e}")
            organization = ''
            source_type = ''
            province = ''
            info_type = ''
            magnitude = self._safe_float(data.get('magnitude', 0), 0.0)
            place_name = data.get('place_name', '')

        place_name = self._localize_place_name(
            place_name,
            source_type,
            data.get('latitude'),
            data.get('longitude'),
        )
        
        # 获取updates、shock_time、depth等字段并构建消息
        updates = data.get('updates')
        # 确保updates是整数
        if updates is not None:
            try:
                updates = int(updates)
                if updates <= 0:
                    updates = None
            except (ValueError, TypeError):
                updates = None
        # SA（ShakeAlert）预警如果没有updates，按第1报处理
        if updates is None and source_type == 'sa':
            updates = 1
        shock_time = data.get('shock_time', '')  # 获取发震时间
        # 获取深度，如果为null或None，默认为10公里
        depth_value = data.get('depth')
        if depth_value is None:
            depth = 10.0
        else:
            depth = self._safe_float(depth_value, 10.0)
            # 如果转换后为0，也使用默认值10（因为真实深度很少为0）
            if depth == 0:
                depth = 10.0
        
        try:
            # 构建消息
            message_parts = []
            
            # 机构名称处理
            if data.get("fanstudio"):
                message_parts.append(self._fanstudio_warning_header(data))
            # 对于日本气象厅，特殊处理格式
            elif source_type == 'wolfx_jma_eew':
                warn_area_type = (data.get('warn_area_type') or '').strip()
                if warn_area_type:
                    message_parts.append(f"【Wolfx 緊急地震速報 {warn_area_type}】")
                else:
                    message_parts.append("【Wolfx 緊急地震速報】")
            elif source_type == 'wolfx_sc_eew':
                message_parts.append("【Wolfx四川省地震局】")
            elif source_type == 'wolfx_fj_eew':
                message_parts.append("【Wolfx福建省地震局】")
            elif source_type == 'wolfx_cenc_eew':
                message_parts.append("【Wolfx中国地震台网】")
            elif source_type == 'wolfx_cq_eew':
                message_parts.append("【Wolfx重庆市地震局】")
            elif source_type == 'wolfx_cwa_eew':
                message_parts.append("【Wolfx 台湾中央气象署】")
            elif source_type == 'early_est':
                message_parts.append("【Early-est预警】")
            elif source_type == 'jma':
                # 日本气象厅格式：【日本气象厅 紧急地震速报 infoTypeName】
                if info_type:
                    message_parts.append(f"【日本气象厅 紧急地震速报 {info_type}】")
                else:
                    message_parts.append(f"【日本气象厅 紧急地震速报】")
            # 对于省级预警（cea-pr），使用省份名称
            # 仅保留province地震局地震预警格式，如果没有省份信息则使用默认机构名称
            elif source_type == 'cea-pr' and province:
                message_parts.append(f"【{province}地震局地震预警】")
            elif organization:
                # 对于其他预警，处理机构名称
                # 如果机构名称已经包含"地震预警"或"地震情报"，直接使用，不再添加后缀
                if "地震预警" in organization or "地震情报" in organization:
                    message_parts.append(f"【{organization}】")
                elif organization.endswith("地震预警网"):
                    message_parts.append(f"【{organization}预警】")
                elif organization.endswith("预警"):
                    # 已有「预警」结尾（如美国ShakeAlert预警），不再追加，避免「预警预警」
                    message_parts.append(f"【{organization}】")
                else:
                    message_parts.append(f"【{organization}预警】")
            else:
                # 如果没有机构名称，根据source_type生成默认名称
                source_name_map = {
                    'cea': '中国地震预警网',
                    'cea-pr': '省级地震局',
                    'cwa-eew': '台湾中央气象局',
                    'jma': '日本气象厅',
                    'sa': '美国ShakeAlert',
                    'kma-eew': '韩国气象厅',
                    'wolfx_jma_eew': '緊急地震速報',
                    'wolfx_sc_eew': '四川省地震局',
                    'wolfx_fj_eew': '福建省地震局',
                    'wolfx_cenc_eew': '中国地震台网地震预警',
                }
                default_org = source_name_map.get(source_type, '地震预警')
                message_parts.append(f"【{default_org}预警】")

            # 报数（放在机构名称后面）
            # 只有存在updates字段且大于0时才显示报数
            # 某些数据源（如sa）可能没有updates字段
            # JMA数据的final为true时，显示"最终报"而不是"第x报"
            if updates and updates > 0:
                # JMA / Wolfx-JMA / Wolfx-福建：final 为真时显示「最终报」（与 Wolfx jma_eew、fj_eew 字段 isFinal 一致）
                is_final = data.get('final', False)
                if is_final and source_type in ('jma', 'wolfx_jma_eew', 'wolfx_fj_eew'):
                    message_parts.append("最终报")
                else:
                    message_parts.append(f"第{updates}报")
            
            # 发震时间（放在报数后面，如果报数不存在，时间前也需要逗号）
            # 格式要求：【机构】第N报，shocktime，地点发生X级地震，震源深度X公里
            if shock_time:
                # 如果前面有报数，时间前加逗号；如果没有报数，时间前也加逗号（紧跟在机构名称后）
                # 时间后面也需要加逗号
                message_parts.append(f"，{shock_time}，")
            
            # 地点和震级（震级保留一位小数）
            if place_name and magnitude > 0:
                message_parts.append(f"{place_name}发生{magnitude:.1f}级地震")
            elif place_name:
                message_parts.append(f"{place_name}发生地震")
            elif magnitude > 0:
                message_parts.append(f"发生{magnitude:.1f}级地震")
            # 如果既没有地点也没有震级，至少添加一个基本描述
            elif not place_name and magnitude == 0:
                message_parts.append("发生地震")
            
            # 添加深度信息（深度保留整数，所有预警都显示）
            depth_int = int(round(depth, 0))
            message_parts.append(f"，震源深度{depth_int}公里")
            self._append_epi_intensity_after_depth(message_parts, data, source_type)
            self._append_wolfx_jma_accuracy_line(message_parts, data, source_type)

            result = "".join(message_parts)
            # 如果结果为空或只包含机构名称和标点，返回默认消息
            if not result or result.strip() == "" or (len(message_parts) <= 2 and "【" in result and "】" in result):
                logger.warning(f"预警消息格式化结果为空或不完整，数据: {data}")
                # 尝试构建一个基本的预警消息
                org_name = data.get('organization', '')
                source_type = data.get('source_type', '')
                if org_name:
                    result = f"【{org_name}预警】数据更新"
                elif source_type:
                    # 根据source_type生成默认机构名称
                    source_name_map = {
                        'cea': '中国地震预警网',
                        'cea-pr': '省级地震局',
                        'cwa-eew': '台湾中央气象局',
                        'jma': '日本气象厅',
                        'sa': '美国ShakeAlert',
                        'kma-eew': '韩国气象厅',
                        'wolfx_jma_eew': '緊急地震速報',
                        'wolfx_sc_eew': '四川省地震局',
                        'wolfx_fj_eew': '福建省地震局',
                        'wolfx_cenc_eew': '中国地震台网地震预警',
                    }
                    default_org = source_name_map.get(source_type, '地震预警')
                    result = f"【{default_org}预警】数据更新"
                else:
                    result = "【地震预警】数据更新"
            return result
        except Exception as e:
            logger.error(f"格式化预警消息时出错: {e}, 数据: {data}", exc_info=True)
            # 返回一个基本的预警消息，避免完全失败
            try:
                org_name = data.get('organization', '')
                if org_name:
                    return f"【{org_name}预警】数据更新"
            except Exception:
                pass
            return "【地震预警】数据更新"

    @staticmethod
    def _shock_time_to_cmt_display(shock_time: str) -> str:
        """将 shock_time（YYYY-MM-DD HH:mm:ss）转为 CMT 展示格式：YYYY年M月D日HH:mm:ss。"""
        if not shock_time or not shock_time.strip():
            return shock_time or ""
        dt = timezone_utils.parse_display_time(shock_time.strip())
        if dt is None:
            return shock_time
        return dt.strftime("%Y年%-m月%-d日%H:%M:%S") if sys.platform != "win32" else f"{dt.year}年{dt.month}月{dt.day}日{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"

    @staticmethod
    def _parse_depth_with_error(depth_str: str) -> tuple:
        """解析 depth 字符串如 '612(+/- 8)'，返回 (主值km, 误差km或None)。"""
        if not depth_str:
            return (10.0, None)
        s = depth_str.strip()
        main_match = re.match(r'^([\d.]+)', s)
        main_km = float(main_match.group(1)) if main_match else 10.0
        err_match = re.search(r'[+＋]\s*/\s*-\s*([\d.]+)', s)
        err_km = float(err_match.group(1)) if err_match else None
        return (main_km, err_km)

    def _format_fssn_cmt_message(self, data: Dict[str, Any]) -> str:
        """
        格式化 FSSN 矩心矩张量解 (CMT) 消息。
        """
        raw = data.get('raw_data') or {}
        shock_time = data.get('shock_time', '')
        time_display = self._shock_time_to_cmt_display(shock_time) if shock_time else timezone_utils.now_display_str()
        place_name = data.get('place_name', '') or raw.get('placeName', '')
        all_mag = raw.get('allMagnitudes') or {}
        mww = self._safe_float(all_mag.get('Mww') or all_mag.get('M') or data.get('magnitude', 0), 0)
        depth_str = raw.get('depth', '')
        depth_km, depth_err = self._parse_depth_with_error(depth_str)
        centroid_str = raw.get('centroidDepth', '')
        try:
            centroid_km = int(round(float(centroid_str))) if centroid_str else int(round(depth_km))
        except (ValueError, TypeError):
            centroid_km = int(round(depth_km))
        np1 = data.get('nodal_plane_1') or raw.get('nodalPlane1', '')
        np2 = data.get('nodal_plane_2') or raw.get('nodalPlane2', '')
        parts = ["【FSSN 矩心矩张量解】", time_display]
        if place_name:
            parts.append(f"，{place_name}")
        parts.append(f"发生Mw {mww:.1f}级地震")
        if depth_err is not None:
            parts.append(f"，震源深度{int(round(depth_km))} km（±{int(round(depth_err))} km）")
        else:
            parts.append(f"，震源深度{int(round(depth_km))} km")
        parts.append(f"，矩心深度{centroid_km} km")
        parts.append("，震源机制解：")
        if np1 and '/' in np1:
            p1 = np1.strip().split('/')
            if len(p1) == 3:
                parts.append(f"节面1走向{p1[0]}°、倾角{p1[1]}°、滑动角{p1[2]}°")
        if np2 and '/' in np2:
            p2 = np2.strip().split('/')
            if len(p2) == 3:
                parts.append("，节面2走向{}°、倾角{}°、滑动角{}°".format(p2[0], p2[1], p2[2]))
        parts.append("。")
        return "".join(parts)

    def _format_cenc_ir_message(self, data: Dict[str, Any]) -> str:
        """
        CENC 烈度速报（cenc-ir）：对齐 PySide6 版显示文案。
        格式：标头 + 时间地点震级 + 烈度文本摘要 + 最大PGA/PGV。
        """
        org = (data.get('organization') or '中国地震台网中心烈度速报').strip()
        t = (data.get('shock_time') or '').strip()
        place = (data.get('place_name') or '').strip()
        mag = self._safe_float(data.get('magnitude', 0), 0.0)
        raw_text = (data.get('cenc_ir_intensity_info_text') or '').strip()
        if not raw_text and data.get('raw_data'):
            raw = data.get('raw_data') or {}
            if isinstance(raw, dict):
                raw_text = (raw.get('intensity_info_text') or '').strip()

        # 清理常见脏字符与换行；与 PySide6 版保持一致
        body = raw_text.replace('\ufeff', '').replace('\r', '').replace('\n', '')
        body = re.sub(r'\s+', ' ', body).strip()
        body = re.sub(r"基于\s*'([^']+)'", r"基于《\1》", body, count=1)
        if "《" not in body[:24]:
            body = re.sub(r"基于\s*\u2018([^\u2019]+)\u2019", r"基于《\1》", body, count=1)
        body = body.replace(",", "，")
        body = re.sub(r"(\d度)\.(\d)", r"\1。\2", body)
        body = re.sub(r"(平方千米)\.", r"\1。", body)

        instruments = data.get('cenc_ir_instrument_intensity_json')
        if instruments is None and data.get('raw_data'):
            raw = data.get('raw_data') or {}
            if isinstance(raw, dict):
                instruments = raw.get('instrument_intensity_json')
        max_pga = None
        max_pgv = None
        max_estimate_int = None
        max_estimate_place = ""
        station_count = 0
        if isinstance(instruments, list):
            for row in instruments:
                if not isinstance(row, dict):
                    continue
                station_count += 1
                try:
                    pga = float(row.get('PGA', 0) or 0)
                    pgv = float(row.get('PGV', 0) or 0)
                except (TypeError, ValueError):
                    continue
                max_pga = pga if max_pga is None or pga > max_pga else max_pga
                max_pgv = pgv if max_pgv is None or pgv > max_pgv else max_pgv
                try:
                    est_i = float(row.get('estimateInt', row.get('INT', 0)) or 0)
                except (TypeError, ValueError):
                    est_i = None
                if est_i is not None and (max_estimate_int is None or est_i > max_estimate_int):
                    max_estimate_int = est_i
                    province = str(row.get('Province') or '').strip()
                    city = str(row.get('City') or '').strip()
                    county = str(row.get('County') or '').strip()
                    town = str(row.get('Town') or '').strip()
                    name_parts = [x for x in (province, city, county, town) if x]
                    max_estimate_place = "".join(name_parts) if name_parts else ""

        mag_str = f"{mag:.1f}".rstrip('0').rstrip('.') if mag else "0"
        parts = [f"【{org}】"]
        if t:
            parts.append(t)
        parts.append(" ，" if t else "，")
        if place:
            parts.append(place)
        parts.append(f"发生{mag_str}级地震")
        if not body:
            # 当数据源未给 intensity_info_text 时，基于台站烈度自动补全摘要
            auto_bits = []
            if station_count > 0:
                auto_bits.append(f"共接入{station_count}个台站烈度样本")
            if max_estimate_int is not None:
                auto_bits.append(f"最大估计烈度{max_estimate_int:.1f}")
            if max_estimate_place:
                auto_bits.append(f"代表区域{max_estimate_place}")
            if auto_bits:
                body = "，".join(auto_bits)
            else:
                body = "台站烈度数据已接收"

        if body:
            parts.append("，")
            parts.append(body)
        tail_bits = []
        if max_pga is not None:
            tail_bits.append(f"最大PGA {max_pga:g}")
        if max_pgv is not None:
            tail_bits.append(f"最大PGV {max_pgv:g}")
        if tail_bits:
            if parts and not str(parts[-1]).endswith(('。', '！', '？')):
                parts.append("。")
            parts.append(" ".join(tail_bits))
        out = "".join(parts)
        if not out.endswith(('。', '！', '？')):
            out += "。"
        return out

    def _format_fanstudio_typhoon_message(self, data: Dict[str, Any]) -> str:
        """格式化 Fan Studio 台风数据"""
        organization = (data.get('organization') or '台风实时与历史数据').strip()
        time_point = (data.get('Time') or data.get('shock_time') or '').strip()
        name = (data.get('Name') or data.get('place_name') or '').strip()
        enname = (data.get('Enname') or data.get('enname') or '').strip()
        ckposition = (data.get('Ckposition') or data.get('ckposition') or '').strip()
        power = (data.get('Power') or data.get('power') or '').strip()
        speed = (data.get('Speed') or data.get('speed') or '').strip()
        strong = (data.get('Strong') or data.get('strong') or '').strip()
        pressure = (data.get('Pressure') or data.get('pressure') or '').strip()
        movespeed = (data.get('Movespeed') or data.get('movespeed') or '').strip()
        movedirection = (data.get('Movedirection') or data.get('movedirection') or '').strip()
        jl = (data.get('Jl') or data.get('jl') or '').strip()

        header = f"【{organization}】"
        message_body = (
            f"{time_point}，台风“{name}”（{enname}）的中心位于{ckposition}，"
            f"中心附近最大风力{power}级（{speed}米/秒），强度为{strong}，中心气压{pressure} hPa，"
            f"将以{movespeed}公里/小时的速度向{movedirection}移动，{jl}。"
        )
        message = f"{header}{message_body}"
        return message

    def _format_fanstudio_aqi_message(self, data: Dict[str, Any]) -> str:
        """格式化 Fan Studio AQI 数据"""
        time_point = (data.get('shock_time') or '').strip()
        area = (data.get('place_name') or '').strip()
        aqi = (data.get('AQI') or '').strip()
        quality = (data.get('Quality') or '').strip()
        co_level = (data.get('COLevel') or '').strip()
        no2_level = (data.get('NO2Level') or '').strip()
        o3_level = (data.get('O3Level') or '').strip()
        so2_level = (data.get('SO2Level') or '').strip()
        pm10_level = (data.get('PM10Level') or '').strip()
        pm25_level = (data.get('PM2_5Level') or '').strip()
        primary = (data.get('PrimaryPollutant') or '').strip()
        unhealthful = (data.get('Unheathful') or '').strip()
        measure = (data.get('Measure') or '').strip()

        header = "【城市空气质量指数】"
        message = header + f"{time_point}，{area}空气质量指数{aqi}，等级{quality}，一氧化碳指数{co_level}，二氧化氮指数{no2_level}，臭氧指数{o3_level}，二氧化硫指数{so2_level}，PM10指数{pm10_level}，PM2.5指数{pm25_level}，首要污染物：{primary}。{unhealthful}，{measure}。"
        # 保证单行显示与末尾标点
        message = message.replace('\n', ' ').strip()
        if not message.endswith(('。', '！', '？')):
            message += '。'
        return message

    def _format_report_message(self, data: Dict[str, Any]) -> str:
        """
        格式化速报消息
        格式：【机构名称地震信息】时间，地点发生X.X级地震，震源深度X公里
        特殊处理：
        - CENC根据infoTypeName显示为【中国地震台网中心自动测定】或【中国地震台网中心正式测定】
        """
        organization = data.get('organization', '')
        magnitude = data.get('magnitude', 0)
        place_name = data.get('place_name', '')
        shock_time = data.get('shock_time', '')
        depth = self._safe_float(data.get('depth', 0), 10.0)  # 无深度时默认为10km
        info_type = data.get('info_type', '')  # 获取infoTypeName字段（用于CENC）
        
        place_name = self._localize_place_name(
            place_name,
            data.get('source_type', ''),
            data.get('latitude'),
            data.get('longitude'),
        )
        
        # 格式化时间
        if not shock_time:
            shock_time = timezone_utils.now_display_str()
        
        # 构建消息
        # 格式：【机构名称地震信息】时间，地点发生X.X级地震，震源深度X公里
        # 特殊处理：CENC 等（FSSN/HKO/USGS 不再根据 infoTypeName、verify 区分标头）
        message_parts = []
        
        # 机构名称
        if data.get("fanstudio"):
            message_parts.append(self._fanstudio_report_header(data))
        elif organization:
            if organization == "FSSN":
                message_parts.append("【FSSN 地震信息】")
            elif organization == "香港天文台":
                message_parts.append("【香港天文台地震信息】")
            elif organization == "美国地质调查局":
                message_parts.append("【美国地质调查局地震信息】")
            # CENC特殊处理：根据infoTypeName动态显示
            elif organization == "中国地震台网中心自动测定/正式测定":
                det = ""
                raw = data.get("raw_data")
                if isinstance(raw, dict):
                    raw_it = raw.get("infoTypeName") or info_type
                else:
                    raw_it = info_type
                clean = str(raw_it or "").strip("[]")
                if "正式测定" in clean:
                    det = "正式测定"
                elif "自动测定" in clean:
                    det = "自动测定"
                if det:
                    message_parts.append(f"【中国地震台网中心{det}】")
                else:
                    message_parts.append("【中国地震台网中心地震信息】")
            # 如果机构名称已经包含"地震信息"或"地震情报"，直接使用，不再添加
            elif "地震信息" in organization or "地震情报" in organization or "海啸" in organization:
                message_parts.append(f"【{organization}】")
            else:
                message_parts.append(f"【{organization}地震信息】")
        else:
            message_parts.append("【地震信息】")
        
        # 时间
        message_parts.append(shock_time)
        
        # 海啸预报：若有 htmlUrl 解析的备注全文则优先展示，否则展示 place_name
        if data.get('is_tsunami'):
            remarks = (data.get('tsunami_remarks') or '').strip()
            if remarks:
                # 去掉备注开头重复的机构名，避免与【机构】时间，后的正文重复显示
                org = data.get('organization', '')
                base_org = "自然资源部海啸预警中心"
                while True:
                    stripped = False
                    if org and remarks.startswith(org):
                        remarks = remarks[len(org):].strip()
                        stripped = True
                    if base_org and remarks.startswith(base_org):
                        remarks = remarks[len(base_org):].strip()
                        stripped = True
                    if not stripped:
                        break
                # 去掉开头重复的「海啸信息」（标题已有「海啸信息通报」）
                while remarks == "海啸信息" or remarks.startswith("海啸信息 ") or remarks.startswith("海啸信息　"):
                    if remarks == "海啸信息":
                        remarks = ""
                        break
                    for prefix in ("海啸信息 ", "海啸信息　"):
                        if remarks.startswith(prefix):
                            remarks = remarks[len(prefix):].strip()
                            break
                # 正文中「签发： 海啸信息 据…」里的重复「海啸信息」去掉一处
                if "签发： 海啸信息 " in remarks:
                    remarks = remarks.replace("签发： 海啸信息 ", " ", 1)
                # 海啸预警去掉「签发」二字（含「签发：」「签发： 」等）
                remarks = remarks.replace("签发： ", " ").replace("签发：", "")
                # 避免时间接时间：正文已有 shock_time，去掉「编号：」前整段「时间：…」
                if remarks.startswith("时间：") and "编号：" in remarks:
                    remarks = remarks[remarks.find("编号："):].strip()
                # 删除「地图如下」类句子（整句去掉，不保留）
                for phrase in (
                    "地震位置图如下: ", "地震位置图如下：", "地震位置图如下: ", "地震位置图如下： ",
                    "地图如下所示：", "地图如下所示: ", "地震位置图如下:", "地图如下所示： ",
                ):
                    remarks = remarks.replace(phrase, "").strip()
                # 去掉结尾可能残留的「如下」类短句
                for suffix in ("地震位置图如下:", "地震位置图如下：", "地图如下所示：", "地图如下所示:"):
                    s = suffix.strip()
                    if remarks.endswith(s):
                        remarks = remarks[:-len(s)].strip()
                    elif remarks.endswith(s + " "):
                        remarks = remarks[: -(len(s) + 1)].strip()
                # 去掉后置水位监测表格与说明，保留前面的通报正文
                for marker in (
                    "水位监测信息如下：",
                    "水位监测信息如下:",
                    "水位监测信息如下",
                    "潮位监测信息如下：",
                    "潮位监测信息如下:",
                    "潮位监测信息如下",
                ):
                    idx = remarks.find(marker)
                    if idx >= 0:
                        remarks = remarks[:idx].strip()
                        break
                if remarks:
                    message_parts.append(f"，{remarks}")
            if not remarks and place_name:
                message_parts.append(f"，{place_name}")
            return "".join(message_parts)

        # PTWC（太平洋海啸预警中心）海啸/信息：按字段顺序展示（与 CAP 类字段一致）
        if data.get('source_type') == 'ptwc':
            headline = (data.get('headline') or '').strip()
            event = (data.get('event') or '').strip()
            severity = (data.get('severity') or '').strip()
            description = (data.get('description') or '').strip()
            certainty = (data.get('certainty') or '').strip()
            urgency = (data.get('urgency') or '').strip()
            onset = (data.get('onset') or '').strip()
            expires = (data.get('expires') or '').strip()
            web = (data.get('web') or '').strip()
            sender_name = (data.get('senderName') or '').strip()
            mag_type = (data.get('magnitudeType') or '').strip()

            if headline:
                message_parts.append(f"，{headline}")
            if event and event != headline:
                message_parts.append(f"，{event}")

            if place_name and magnitude > 0:
                message_parts.append(f" - {place_name} M{magnitude:.1f}")
            elif place_name:
                message_parts.append(f" - {place_name}")
            elif magnitude > 0:
                message_parts.append(f" - M{magnitude:.1f}")

            depth_int = int(round(depth, 0))
            message_parts.append(f" 深度{depth_int}公里")

            if severity:
                message_parts.append(f" ({severity})")
            if mag_type:
                message_parts.append(f" 震级类型 {mag_type}")

            meta_bits = []
            if certainty:
                meta_bits.append(f"确定性 {certainty}")
            if urgency:
                meta_bits.append(f"紧急度 {urgency}")
            if onset:
                meta_bits.append(f"生效 {onset}")
            if expires:
                meta_bits.append(f"失效 {expires}")
            if sender_name:
                meta_bits.append(f"发送方 {sender_name}")
            if meta_bits:
                message_parts.append("，" + "，".join(meta_bits))

            if description:
                desc = re.sub(r'\s+', ' ', description).strip()
                message_parts.append(f"。{desc}")

            if web:
                message_parts.append(f" {web}")

            out = "".join(message_parts)
            max_len = getattr(self.config.message_config, 'max_message_length', 0) or 0
            if max_len > 0 and len(out) > max_len:
                out = out[:max_len].rstrip() + "..."
            return out

        # 地点和震级
        if place_name and magnitude > 0:
            message_parts.append(f"，{place_name}发生{magnitude:.1f}级地震")
        elif place_name:
            message_parts.append(f"，{place_name}发生地震")
        elif magnitude > 0:
            message_parts.append(f"，发生{magnitude:.1f}级地震")
        
        # 震源深度（深度保留整数，无深度时默认为10km）
        depth_int = int(round(depth, 0))
        message_parts.append(f"，震源深度{depth_int}公里")
        st_rep = data.get("source_type") or ""
        self._append_epi_intensity_after_depth(message_parts, data, st_rep)
        
        return "".join(message_parts)
    
    def _match_weather_image(self, weather_data: Dict[str, Any]) -> Optional[str]:
        """
        气象预警图标仅使用中国气象局在线资源（需 raw_data 中含 NMC type 编码，如 p0005003）。
        不再使用本地「气象预警信号图片」目录。
        """
        try:
            alarm_type = weather_data.get('type')
            if alarm_type and isinstance(alarm_type, str) and alarm_type.strip():
                type_str = alarm_type.strip()
                if re.match(r'^p[a-zA-Z0-9]+$', type_str):
                    url = f"{NMC_ALARM_IMAGE_BASE}/{type_str}.png"
                    logger.info(f"使用 type 字段获取气象预警图片: {url}")
                    return url
                logger.warning(f"气象预警 type 非 NMC 图标编码，无法使用在线图标: {type_str!r}")
                return None
            headline = weather_data.get('headline', '') or weather_data.get('title', '')
            if headline:
                logger.warning(
                    "气象预警缺少 NMC type 编码，无法显示在线图标（数据源需提供 type；已不使用本地图片）"
                )
            else:
                logger.warning("气象预警数据中无 type 且无 headline/title")
            return None
        except Exception as e:
            logger.error(f"匹配气象预警图片时出错: {e}", exc_info=True)
            return None
    
    def _format_weather_message(self, data: Dict[str, Any]) -> str:
        """
        格式化气象预警消息
        格式：图片 【气象预警】 标题。时间，描述
        """
        title = data.get('title', data.get('headline', ''))
        effective = data.get('shock_time', '')
        description = data.get('description', '')
        
        # 构建消息文本（图片会在显示时单独处理）
        prefix = "【中国气象局气象预警】" if data.get("fanstudio") else "【气象预警】"
        parts = [prefix, title]
        
        if effective:
            # 格式化时间，将 2026/02/04 21:25 转换为 2026/02/04 21:25
            parts.append(f"。{effective}")
        
        if description:
            parts.append(f"，{description}")
        
        return "".join(parts)
    
    def get_weather_image_path(self, parsed_data: Dict[str, Any]) -> Optional[str]:
        """
        获取气象预警图标 URL（仅中国气象局 NMC 在线图标，依赖 raw_data.type 编码）。

        Args:
            parsed_data: 解析后的数据字典

        Returns:
            图片 URL 字符串，如果未找到则返回 None
        """
        if parsed_data.get('type') != 'weather':
            return None
        raw_data = parsed_data.get('raw_data', {})
        return self._match_weather_image(raw_data)
    
    def _format_volcano_message(self, data: Dict[str, Any]) -> str:
        """
        格式化 JMA 火山情报消息
        格式：【日本气象厅火山情报  title】volcano：description，name time发布
        """
        title = (data.get('title') or '').strip()
        volcano = (data.get('volcano') or '').strip()
        description = (data.get('description') or '').strip()
        name = (data.get('name') or '').strip()
        shock_time = (data.get('shock_time') or '').strip()
        title = self._translate_text_if_needed(title)
        volcano = self._translate_text_if_needed(volcano)
        description = self._translate_text_if_needed(description)
        name = self._translate_text_if_needed(name)
        if getattr(self.config.message_config, 'force_single_line', True):
            title = (title or '').replace('\n', ' ')
            volcano = (volcano or '').replace('\n', ' ')
            description = (description or '').replace('\n', ' ')
            name = (name or '').replace('\n', ' ')
        head = f"【日本气象厅火山情报  {title}】" if title else "【日本气象厅火山情报】"
        volcano_part = f"{volcano}：" if volcano else ""
        tail = f"，{name} {shock_time}发布".strip() if (name or shock_time) else "发布"
        return f"{head}{volcano_part}{description}{tail}"

    def _format_generic_message(self, data: Dict[str, Any]) -> str:
        """格式化通用消息"""
        organization = data.get('organization', '')
        place_name = self._localize_place_name(
            data.get('place_name', ''),
            data.get('source_type', ''),
            data.get('latitude'),
            data.get('longitude'),
        )
        shock_time = data.get('shock_time', '')
        
        parts = [f"【{organization}】"]
        if place_name:
            parts.append(place_name)
        if shock_time:
            parts.append(shock_time)
        
        return " ".join(parts) if len(parts) > 1 else f"【{organization}】 数据更新"
    
    def get_message_color(self, message_type: str, parsed_data: Optional[Dict[str, Any]] = None) -> str:
        """
        获取消息颜色
        
        Args:
            message_type: 消息类型
            parsed_data: 解析后的数据字典（用于气象预警提取颜色信息）
            
        Returns:
            颜色代码
        """
        # 对于气象预警，根据预警类型返回对应颜色
        if message_type == 'weather' and parsed_data:
            return self._get_weather_warning_color(parsed_data)
        
        # 从配置中读取颜色
        if message_type == 'warning':
            # 预警颜色：从配置中读取（默认红色 #FF0000）
            color = self.config.message_config.warning_color
            logger.debug(f"MessageProcessor.get_message_color: 预警颜色从配置读取: {color}")
            return color
        elif message_type == 'report':
            # 海啸预警中心：按 warningInfo.level 自动着色（信息维持默认速报色）
            if parsed_data and parsed_data.get('is_tsunami'):
                level_color = self._get_tsunami_level_color(parsed_data)
                if level_color:
                    logger.info(f"海啸预警颜色: level={parsed_data.get('tsunami_warning_level')} -> {level_color}")
                    return level_color
            # 速报颜色：从配置中读取（默认青色 #00FFFF）
            color = self.config.message_config.report_color
            logger.debug(f"MessageProcessor.get_message_color: 速报颜色从配置读取: {color}")
            return color
        elif message_type == 'weather':
            # 气象预警默认颜色（如果无法提取预警颜色时使用）
            return '#FFF500'
        elif message_type == 'volcano':
            # 火山情报：与速报同一颜色
            return self.config.message_config.report_color
        else:
            # 默认颜色：绿色
            return '#01FF00'

    def _get_tsunami_level_color(self, parsed_data: Dict[str, Any]) -> Optional[str]:
        """自然资源部海啸：按 warningInfo.level 返回颜色；信息/未知返回 None（沿用速报色）。"""
        raw_level = (parsed_data.get('tsunami_warning_level') or '').strip()
        if not raw_level:
            return None
        if "红" in raw_level:
            return "#FF0000"
        if "橙" in raw_level:
            return "#FF8C00"
        if "黄" in raw_level:
            return "#FFFF00"
        if "蓝" in raw_level:
            return "#00BFFF"
        if "信息" in raw_level:
            return None
        return None
    
    def _get_weather_warning_color(self, parsed_data: Dict[str, Any]) -> str:
        """
        根据气象预警类型获取对应的字体颜色
        自动根据预警颜色（红色/橙色/黄色/蓝色/白色）返回对应的字体颜色
        
        Args:
            parsed_data: 解析后的数据字典
            
        Returns:
            颜色代码
        """
        # 默认颜色（当无法提取预警颜色时使用）
        DEFAULT_WEATHER_COLOR = '#FFF500'  # 黄色
        
        try:
            # 从raw_data中提取headline或title
            raw_data = parsed_data.get('raw_data', {})
            headline = raw_data.get('headline', '') or raw_data.get('title', '')
            
            if not headline:
                # 如果无法获取headline，使用默认颜色
                logger.debug("无法获取headline，使用默认气象预警颜色")
                return DEFAULT_WEATHER_COLOR
            
            # 提取预警颜色
            # 例如："广东省阳江市发布暴雨橙色预警信号" -> "橙色"
            pattern = r'发布(.+?)(红色|橙色|黄色|蓝色|白色)预警'
            match = re.search(pattern, headline)
            
            if match:
                warning_color = match.group(2)  # 预警颜色，如"橙色"
                
                # 根据预警颜色返回对应的字体颜色
                color_map = {
                    '红色': '#FF0000',  # 红色
                    '橙色': '#FF8C00',  # 橙色（深橙色）
                    '黄色': '#FFFF00',  # 黄色
                    '蓝色': '#00BFFF',  # 蓝色（深蓝色）
                    '白色': '#FFFFFF',  # 白色
                }
                
                color = color_map.get(warning_color)
                if color:
                    logger.info(f"气象预警颜色: {warning_color} -> {color}")
                    return color
            
            # 如果无法匹配，尝试从description中提取
            description = raw_data.get('description', '')
            if description:
                # 尝试从description中匹配预警颜色
                desc_pattern = r'([^，。：:；;]+?)(红色|橙色|黄色|蓝色|白色)预警'
                desc_match = re.search(desc_pattern, description)
                if desc_match:
                    warning_color = desc_match.group(2)
                    color_map = {
                        '红色': '#FF0000',
                        '橙色': '#FF8C00',
                        '黄色': '#FFFF00',
                        '蓝色': '#00BFFF',
                        '白色': '#FFFFFF',
                    }
                    color = color_map.get(warning_color)
                    if color:
                        logger.info(f"从description提取气象预警颜色: {warning_color} -> {color}")
                        return color
            
            # 如果无法匹配，使用默认颜色
            logger.debug(f"无法从headline或description提取预警颜色: {headline}，使用默认颜色")
            return DEFAULT_WEATHER_COLOR
            
        except Exception as e:
            logger.error(f"获取气象预警颜色失败: {e}")
            return DEFAULT_WEATHER_COLOR