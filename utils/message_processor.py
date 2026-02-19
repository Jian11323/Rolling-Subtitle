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
from utils.resource_path import get_resource_path
from utils import timezone_utils

logger = get_logger()


class MessageProcessor:
    """消息处理器"""
    
    def __init__(self):
        self.config = Config()
        # 气象预警图片目录（兼容打包后的路径）
        self.weather_images_dir = get_resource_path("气象预警信号图片")
        
        # 初始化翻译服务
        try:
            from utils.translation_service import TranslationService
            self.translator = TranslationService(self.config)
            logger.info("翻译服务已初始化")
        except Exception as e:
            logger.error(f"初始化翻译服务失败: {e}")
            self.translator = None
    
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
    
    def format_message(self, parsed_data: Dict[str, Any]) -> Optional[str]:
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
                is_valid = self._is_warning_valid(parsed_data)
                if not is_valid:
                    shock_time = parsed_data.get('shock_time', '')
                    event_id = parsed_data.get('event_id', '')
                    logger.debug(f"预警消息已过期，忽略: event_id={event_id}, shock_time={shock_time}")
                    return None
                
                # 格式化预警消息
                try:
                    logger.debug(f"开始格式化预警消息，数据: organization={parsed_data.get('organization')}, place_name={parsed_data.get('place_name')}, magnitude={parsed_data.get('magnitude')}, source_type={parsed_data.get('source_type')}")
                    result = self._format_warning_message(parsed_data)
                    if not result or result.strip() == "":
                        logger.warning(f"预警消息格式化结果为空，数据: {parsed_data}")
                        return None
                    logger.debug(f"预警消息格式化成功: {result[:100]}...")
                    return result
                except Exception as e:
                    logger.error(f"格式化预警消息时发生异常: {e}, 数据: {parsed_data}", exc_info=True)
                    return None
            elif message_type == 'report':
                return self._format_report_message(parsed_data)
            elif message_type == 'weather':
                return self._format_weather_message(parsed_data)
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
            shock_time_str = data.get('shock_time', '')
            if not shock_time_str:
                # 如果没有发震时间，默认有效
                return True
            
            # 解析发震时间（显示时区下的时间）
            shock_time = timezone_utils.parse_display_time(shock_time_str)
            if shock_time is None:
                return True
            
            # 计算时间差（秒），与显示时区当前时间比较
            time_diff = (timezone_utils.now_in_display_tz() - shock_time).total_seconds()
            
            msg_cfg = Config().message_config
            max_seconds = msg_cfg.warning_shock_validity_seconds
            is_valid = time_diff <= max_seconds
            if not is_valid:
                minutes_diff = time_diff / 60
                logger.info(f"预警消息已过期: {shock_time_str}, 时间差: {int(time_diff)}秒 ({minutes_diff:.1f}分钟)")
            return is_valid
        except Exception as e:
            logger.error(f"【消息处理器】 检查预警有效性时出错: {e}")
            # 出错时默认有效，避免误过滤
            return True
    
    def _format_warning_message(self, data: Dict[str, Any]) -> str:
        """
        格式化预警消息
        格式：【中国地震预警网预警】第1报，shocktime地点发生X级地震，震源深度X公里
        省级预警格式：【province地震局地震预警】第1报，shocktime地点发生X.X级地震，震源深度X公里
        日本气象厅格式：【日本气象厅 紧急地震速报 infoTypeName】 第1报，shocktime地点发生X.X级地震，震源深度X公里
        日本气象厅最终报格式：【日本气象厅 紧急地震速报 infoTypeName】 最终报，shocktime地点发生X.X级地震，震源深度X公里
        
        注意：
        - JMA数据的placeName和infoTypeName为日语原文
        - infoTypeName：保持日语原文（予報、警報），不进行翻译
        - placeName：地震预警使用百度翻译（如果启用了翻译且地名不包含中文）
        - cancel字段为true时，消息会被忽略（不显示）
        - final字段为true时，显示"最终报"而不是"第x报"
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
            
        # 预警地名翻译（仅对特定数据源进行翻译）
        try:
            if place_name:
                import re
                has_chinese = bool(re.search(r'[\u4e00-\u9fff]', place_name))
                
                # CEA、CEA-PR、SICHUAN、CWA-EEW、Wolfx 部分为中文地名，无需翻译
                chinese_sources = {'cea', 'cea-pr', 'sichuan', 'cwa-eew', 'wolfx_sc_eew', 'wolfx_fj_eew', 'wolfx_cenc_eew', 'wolfx_cenc_eqlist'}
                
                # JMA、Wolfx JMA、NIED 保持原始地名（日文等）
                if source_type == 'jma':
                    logger.debug(f"JMA预警地名保持原文: {place_name}")
                elif source_type == 'nied' or (source_type and str(source_type).startswith('wolfx_jma')):
                    logger.debug(f"{source_type} 预警地名保持原文: {place_name}")
                # USGS有专门的地名修正逻辑（保持原文，后续修正）
                elif source_type == 'usgs':
                    logger.debug(f"USGS预警地名保持原文以便后续修正: {place_name}")
                # 特定中文数据源无需翻译
                elif source_type in chinese_sources:
                    logger.debug(f"{source_type} 地名默认为中文，无需翻译: {place_name}")
                else:
                    # 其他数据源如需翻译可在此扩展
                    if False and not has_chinese:
                        if self.translator and self.config.translation_config.enabled:
                            try:
                                original_name = place_name
                                translated = self.translator.translate(
                                    place_name,
                                    quick_mode=False
                                )
                                if translated and translated != place_name:
                                    place_name = translated
                                    logger.info(f"预警地名翻译成功: {original_name} -> {translated}")
                                else:
                                    logger.debug(f"预警地名翻译未改变: {original_name} (可能API未配置或翻译失败)")
                            except Exception as e:
                                logger.warning(f"翻译预警地名时发生异常，保持原文: {place_name}, 错误: {e}")
                        else:
                            if not self.translator:
                                logger.debug(f"翻译服务未初始化，预警地名保持原文: {place_name}")
                            elif not self.config.translation_config.enabled:
                                logger.debug(f"预警翻译未启用，地名保持原文: {place_name}")
                    else:
                        logger.debug(f"预警地名无需翻译: {place_name}")
        except Exception as e:
            # 如果整个翻译逻辑发生异常，记录错误但继续处理，确保消息能正常显示
            logger.error(f"预警地名翻译逻辑发生异常，保持原文继续处理: {e}", exc_info=True)
        
        # 获取updates、shock_time、depth等字段并构建消息（无论翻译成功与否都执行）
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
            # 对于日本气象厅，特殊处理格式
            if source_type == 'jma':
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
                    'sichuan': '四川地震局',
                    'cwa-eew': '台湾中央气象局',
                    'jma': '日本气象厅',
                    'sa': '美国ShakeAlert',
                    'kma-eew': '韩国气象厅',
                    'nied': '日本防災科研所预警',
                }
                default_org = source_name_map.get(source_type, '地震预警')
                if default_org == '地震预警' and source_type and str(source_type).startswith('wolfx_'):
                    default_org = 'Wolfx 预警'
                message_parts.append(f"【{default_org}预警】")

            # 报数（放在机构名称后面）
            # 只有存在updates字段且大于0时才显示报数
            # 某些数据源（如sa）可能没有updates字段
            # JMA数据的final为true时，显示"最终报"而不是"第x报"
            if updates and updates > 0:
                # 检查是否为JMA数据源且final为true
                is_final = data.get('final', False)
                if source_type == 'jma' and is_final:
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
            
            # 当数据包含 epiIntensity 时添加：预估最大烈度x.x度
            epi_intensity = data.get('epi_intensity') or data.get('epiIntensity')
            if epi_intensity is not None:
                try:
                    intensity_val = self._safe_float(epi_intensity, 0)
                    if intensity_val > 0:
                        message_parts.append(f"，预估最大烈度{intensity_val:.1f}度")
                except (ValueError, TypeError):
                    pass
            
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
                        'sichuan': '四川地震局',
                        'cwa-eew': '台湾中央气象局',
                        'jma': '日本气象厅',
                        'sa': '美国ShakeAlert',
                        'kma-eew': '韩国气象厅',
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
    
    def _format_report_message(self, data: Dict[str, Any]) -> str:
        """
        格式化速报消息
        格式：【机构名称地震信息】时间，地点发生X.X级地震，震源深度X公里
        特殊处理：
        - FSSN显示为【FSSN地震信息】
        - CENC根据infoTypeName显示为【中国地震台网中心自动测定】或【中国地震台网中心正式测定】
        """
        organization = data.get('organization', '')
        magnitude = data.get('magnitude', 0)
        place_name = data.get('place_name', '')
        shock_time = data.get('shock_time', '')
        depth = self._safe_float(data.get('depth', 0), 10.0)  # 无深度时默认为10km
        info_type = data.get('info_type', '')  # 获取infoTypeName字段（用于CENC）
        
        # 速报消息使用地名修正（已在适配器中完成，这里不再进行翻译）
        # 地名修正逻辑在adapters/fanstudio_adapter.py的_parse_earthquake_report方法中处理
        
        # 格式化时间
        if not shock_time:
            shock_time = timezone_utils.now_display_str()
        
        # 构建消息
        # 格式：【机构名称地震信息】时间，地点发生X.X级地震，震源深度X公里
        # 特殊处理：FSSN和CENC
        message_parts = []
        
        # 机构名称
        if organization:
            # FSSN特殊处理：显示为【FSSN地震信息】
            if organization == "FSSN":
                message_parts.append(f"【{organization}地震信息】")
            # CENC特殊处理：根据infoTypeName动态显示
            elif organization == "中国地震台网中心自动测定/正式测定":
                # 从infoTypeName中提取测定类型（去掉方括号）
                # infoTypeName格式可能是 "[正式测定]" 或 "[自动测定]"
                determination_type = "自动测定/正式测定"  # 默认值
                if info_type:
                    # 去掉方括号
                    info_type_clean = info_type.strip('[]')
                    if "正式测定" in info_type_clean:
                        determination_type = "正式测定"
                    elif "自动测定" in info_type_clean:
                        determination_type = "自动测定"
                
                message_parts.append(f"【中国地震台网中心{determination_type}】")
            # 如果机构名称已经包含"地震信息"或"地震情报"，直接使用，不再添加
            elif "地震信息" in organization or "地震情报" in organization or "海啸" in organization:
                message_parts.append(f"【{organization}】")
            else:
                message_parts.append(f"【{organization}地震信息】")
        else:
            message_parts.append("【地震信息】")
        
        # 时间
        message_parts.append(shock_time)
        
        # 海啸预报：仅显示类型/区域，不显示震级与震源深度
        if data.get('is_tsunami'):
            if place_name:
                message_parts.append(f"，{place_name}")
            return "".join(message_parts)
        
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
        
        # 当数据包含 epiIntensity 时添加：预估最大烈度x.x度
        epi_intensity = data.get('epi_intensity') or data.get('epiIntensity')
        if epi_intensity is not None:
            try:
                intensity_val = self._safe_float(epi_intensity, 0)
                if intensity_val > 0:
                    message_parts.append(f"，预估最大烈度{intensity_val:.1f}度")
            except (ValueError, TypeError):
                pass
        
        return "".join(message_parts)
    
    def _match_weather_image(self, weather_data: Dict[str, Any]) -> Optional[str]:
        """
        根据气象预警数据匹配图片文件路径（快速匹配，不阻塞）
        优先从headline中匹配，如果未匹配到图片，则从description中匹配
        
        Args:
            weather_data: 气象预警数据字典，包含 'headline', 'title', 'description' 等字段
            
        Returns:
            匹配的图片文件路径（字符串），如果未找到则返回None
        """
        try:
            # 从headline或title中提取预警信息
            headline = weather_data.get('headline', '') or weather_data.get('title', '')
            if not headline:
                logger.warning("气象预警数据中没有headline或title字段")
                logger.debug(f"weather_data keys: {list(weather_data.keys())}")
                return None
            
            logger.info(f"尝试匹配气象预警图片，headline: {headline}")
            
            # 检查图片目录是否存在
            if not self.weather_images_dir.exists():
                logger.error(f"气象预警图片目录不存在: {self.weather_images_dir}")
                return None
            
            # 提取预警类型和颜色
            # 例如："广东省阳江市发布暴雨橙色预警信号" -> "暴雨橙色预警"
            # 匹配模式：{类型}{颜色}预警
            pattern = r'发布(.+?)(红色|橙色|黄色|蓝色|白色)预警'
            match = re.search(pattern, headline)
            
            warning_type = None
            warning_color = None
            
            if match:
                warning_type = match.group(1)  # 预警类型，如"暴雨"
                warning_color = match.group(2)  # 预警颜色，如"橙色"
                
                logger.info(f"从headline匹配到预警类型: {warning_type}, 颜色: {warning_color}")
                
                # 构建图片文件名
                image_filename = f"{warning_type}{warning_color}预警.jpg"
                image_path = self.weather_images_dir / image_filename
                
                logger.info(f"查找图片文件: {image_path}")
                
                # 快速检查文件是否存在（使用try-except避免阻塞）
                try:
                    if image_path.exists():
                        logger.info(f"✓ 找到气象预警图片: {image_filename}, 完整路径: {image_path}")
                        return str(image_path)
                    else:
                        logger.warning(f"✗ 气象预警图片文件不存在: {image_path}")
                        # 如果headline中匹配到但文件不存在，继续尝试从description中匹配
                        logger.info("headline中匹配到但图片不存在，尝试从description中匹配")
                except (OSError, PermissionError) as e:
                    # 文件系统错误，忽略
                    logger.error(f"检查图片文件时出错: {e}")
                    pass
            else:
                logger.warning(f"无法从headline匹配图片模式: {headline}")
                logger.debug(f"尝试的正则表达式: {pattern}")
                # 如果headline中未匹配到，尝试从description中匹配
                logger.info("headline中未匹配到，尝试从description中匹配")
            
            # 如果headline中未匹配到图片，尝试从description中匹配
            # 首先需要从headline中提取颜色（如果之前未提取）
            if not warning_color:
                # 尝试从headline中提取颜色
                color_match = re.search(r'(红色|橙色|黄色|蓝色|白色)预警', headline)
                if color_match:
                    warning_color = color_match.group(1)
                    logger.debug(f"从headline中提取到颜色: {warning_color}")
            
            # 从description中提取预警类型和颜色
            description = weather_data.get('description', '')
            if description:
                logger.info(f"尝试从description中匹配预警类型，description: {description[:100]}...")
                
                # 匹配description中的预警类型和颜色
                # 例如："高速公路大雾Ⅳ级预警" -> "大雾"
                # 支持多种格式：大雾预警、大雾Ⅳ级预警、暴雨预警、大雾蓝色预警等
                desc_patterns = [
                    r'([^，。：:；;]+?)(红色|橙色|黄色|蓝色|白色)预警',  # 优先匹配带颜色的，如"大雾蓝色预警"
                    r'([^，。：:；;]+?)(?:Ⅳ级|Ⅴ级|Ⅲ级|Ⅱ级|Ⅰ级)?预警',  # 匹配"大雾Ⅳ级预警"或"大雾预警"
                ]
                
                for desc_pattern in desc_patterns:
                    desc_match = re.search(desc_pattern, description)
                    if desc_match:
                        # 提取预警类型（去除常见的前缀词）
                        potential_type = desc_match.group(1).strip()
                        # 清理前缀词（如"高速公路"、"发布"、"预计"、"根据"等）
                        potential_type = re.sub(r'^(高速公路|发布|预计|根据|上述地区)', '', potential_type)
                        potential_type = potential_type.strip()
                        
                        # 如果匹配到颜色，使用匹配到的颜色（优先使用description中的颜色）
                        if len(desc_match.groups()) > 1 and desc_match.group(2) in ['红色', '橙色', '黄色', '蓝色', '白色']:
                            warning_color = desc_match.group(2)
                            logger.info(f"从description中提取到颜色: {warning_color}")
                        
                        # 如果还没有颜色，尝试从description中单独提取颜色
                        if not warning_color:
                            color_match = re.search(r'(红色|橙色|黄色|蓝色|白色)预警', description)
                            if color_match:
                                warning_color = color_match.group(1)
                                logger.info(f"从description中单独提取到颜色: {warning_color}")
                        
                        if potential_type and len(potential_type) <= 10:  # 限制长度，避免匹配到过长的文本
                            # 如果还没有类型，使用从description中提取的类型
                            # 如果已有类型（从headline中提取），但图片不存在，也尝试使用description中的类型
                            desc_warning_type = potential_type
                            
                            # 如果类型和颜色都有，尝试匹配图片
                            if desc_warning_type and warning_color:
                                logger.info(f"从description匹配到预警类型: {desc_warning_type}, 颜色: {warning_color}")
                                
                                # 构建图片文件名
                                image_filename = f"{desc_warning_type}{warning_color}预警.jpg"
                                image_path = self.weather_images_dir / image_filename
                                
                                logger.info(f"查找图片文件: {image_path}")
                                
                                # 检查文件是否存在
                                try:
                                    if image_path.exists():
                                        logger.info(f"✓ 从description中找到气象预警图片: {image_filename}, 完整路径: {image_path}")
                                        return str(image_path)
                                    else:
                                        logger.warning(f"✗ description中匹配到但图片文件不存在: {image_path}")
                                except (OSError, PermissionError) as e:
                                    logger.error(f"检查图片文件时出错: {e}")
                                    pass
                        break
                else:
                    logger.debug("无法从description中匹配到预警类型")
            else:
                logger.debug("description字段为空，无法从description中匹配")
            
            # 列出目录中的文件以便调试
            try:
                existing_files = list(self.weather_images_dir.glob("*.jpg"))
                logger.debug(f"图片目录中的文件数量: {len(existing_files)}")
                if len(existing_files) <= 10:
                    logger.debug(f"图片目录中的文件: {[f.name for f in existing_files]}")
            except Exception as e:
                logger.debug(f"无法列出图片目录: {e}")
            
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
        parts = ["【气象预警】", title]
        
        if effective:
            # 格式化时间，将 2026/02/04 21:25 转换为 2026/02/04 21:25
            parts.append(f"。{effective}")
        
        if description:
            parts.append(f"，{description}")
        
        return "".join(parts)
    
    def get_weather_image_path(self, parsed_data: Dict[str, Any]) -> Optional[str]:
        """
        获取气象预警图片路径
        
        Args:
            parsed_data: 解析后的数据字典
            
        Returns:
            图片路径字符串，如果未找到则返回None
        """
        if parsed_data.get('type') != 'weather':
            return None
        
        raw_data = parsed_data.get('raw_data', {})
        return self._match_weather_image(raw_data)
    
    def _format_generic_message(self, data: Dict[str, Any]) -> str:
        """格式化通用消息"""
        organization = data.get('organization', '')
        place_name = data.get('place_name', '')
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
            # 速报颜色：从配置中读取（默认青色 #00FFFF）
            color = self.config.message_config.report_color
            logger.debug(f"MessageProcessor.get_message_color: 速报颜色从配置读取: {color}")
            return color
        elif message_type == 'weather':
            # 气象预警默认颜色（如果无法提取预警颜色时使用）
            return '#FFF500'
        else:
            # 默认颜色：绿色
            return '#01FF00'
    
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
            logger.debug(f"无法从headline或description提取预警颜色: {headline[:50]}...，使用默认颜色")
            return DEFAULT_WEATHER_COLOR
            
        except Exception as e:
            logger.error(f"获取气象预警颜色失败: {e}")
            return DEFAULT_WEATHER_COLOR