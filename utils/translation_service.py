#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译服务模块
参考 fused_eew_api_v2.py 的翻译模块实现
支持日语、韩语、英语到中文的翻译，使用百度翻译API
"""

import json
import os
import re
import random
import hashlib
import threading
import requests
from typing import Dict, Optional
from pathlib import Path

from utils.logger import get_logger

logger = get_logger()


class TranslationService:
    """翻译服务"""
    
    def __init__(self, config):
        """
        初始化翻译服务
        
        Args:
            config: 配置对象，包含BAIDU_APP_ID和BAIDU_SECRET_KEY
        """
        self.config = config
        self.cache: Dict[str, str] = {}
        
        # 翻译缓存文件与settings.json、日志文件保持同一位置：C:\Users\账户名\AppData\Roaming\subtitl\translation_cache.json
        # 日志文件也在同一目录：C:\Users\账户名\AppData\Roaming\subtitl\log.txt（或log_YYYYMMDD.txt）
        try:
            config_dir = Path.home() / 'AppData' / 'Roaming' / 'subtitl'
            config_dir.mkdir(parents=True, exist_ok=True)
            self.cache_file = config_dir / "translation_cache.json"
        except Exception as e:
            logger.error(f"创建翻译缓存目录失败: {e}")
            # 使用当前目录作为后备
            self.cache_file = Path("translation_cache.json")
        
        self.lock = threading.Lock()
        self._load_cache()
    
    def _normalize_key(self, text: str) -> str:
        """规范化缓存键（去除多余空格、统一处理）"""
        if not text:
            return text
        # 去除首尾空格，将多个连续空格替换为单个空格
        normalized = ' '.join(text.split())
        return normalized
    
    def _load_cache(self):
        """加载翻译缓存（自动去重）"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    raw_cache = json.load(f)
                
                # 规范化并去重：使用规范化后的键，如果有重复则保留最后一个
                normalized_cache = {}
                duplicates_removed = 0
                
                for key, value in raw_cache.items():
                    normalized_key = self._normalize_key(key)
                    if normalized_key in normalized_cache:
                        duplicates_removed += 1
                    normalized_cache[normalized_key] = value
                
                self.cache = normalized_cache
                
                if duplicates_removed > 0:
                    logger.info(f"加载翻译缓存时发现并移除了 {duplicates_removed} 个重复项")
                    # 立即保存去重后的缓存
                    self._async_save_cache()
                
                logger.debug(f"已加载 {len(self.cache)} 条翻译缓存")
            except Exception as e:
                logger.error(f"加载翻译缓存失败: {e}")
    
    def save_cache(self):
        """保存翻译缓存（自动去重）"""
        try:
            with self.lock:
                # 确保缓存键都已规范化（去重处理）
                normalized_cache = {}
                for key, value in self.cache.items():
                    normalized_key = self._normalize_key(key)
                    normalized_cache[normalized_key] = value
                
                # 更新缓存为去重后的版本
                self.cache = normalized_cache
                
                # 保存到文件
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存翻译缓存失败: {e}")
    
    def _async_save_cache(self):
        """异步保存翻译缓存到文件（无阻塞，自动去重）"""
        def _save():
            try:
                with self.lock:
                    # 确保缓存键都已规范化（去重处理）
                    normalized_cache = {}
                    for key, value in self.cache.items():
                        normalized_key = self._normalize_key(key)
                        normalized_cache[normalized_key] = value
                    
                    # 更新缓存为去重后的版本
                    self.cache = normalized_cache
                    cache_copy = self.cache.copy()  # 复制缓存，减少锁持有时间
                
                # 在锁外进行文件写入
                with open(self.cache_file, 'w', encoding='utf-8') as f:
                    json.dump(cache_copy, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"异步保存翻译缓存失败: {e}")
        
        threading.Thread(target=_save, daemon=True, name="SaveTranslationCache").start()
    
    def translate(self, text: str, force_lang: Optional[str] = None, quick_mode: bool = False, skip_cache: bool = False) -> str:
        """
        翻译文本（支持日语、韩语、英语到中文）
        
        Args:
            text: 要翻译的文本
            force_lang: 强制指定源语言（'kor', 'jp', 'auto'等）
            quick_mode: 快速模式，缓存未命中直接返回原文
            skip_cache: 跳过缓存，直接调用API
            
        Returns:
            翻译后的文本，如果翻译失败则返回原文
        """
        if not text or text == '未知地点':
            return text
        
        # 检查是否配置了翻译API（每次调用时都从config读取最新配置，支持配置热更新）
        app_id = self.config.translation_config.baidu_app_id
        secret_key = self.config.translation_config.baidu_secret_key
        
        if not app_id or not secret_key:
            logger.debug("百度翻译API未配置，跳过翻译")
            return text
        
        # 验证API密钥格式（基本检查）
        if len(app_id) < 10 or len(secret_key) < 10:
            logger.warning(f"百度翻译API密钥格式可能不正确（App ID长度: {len(app_id)}, Secret Key长度: {len(secret_key)}）")
            # 仍然尝试调用，让API返回具体错误信息
        
        # 规范化缓存键（去除多余空格，确保不重复）
        normalized_text = self._normalize_key(text)
        
        # 跳过缓存模式：直接调用API，不检查缓存（加快翻译速度，降低推送延迟）
        if not skip_cache:
            # 检查缓存（使用规范化后的键）
            if normalized_text in self.cache:
                return self.cache[normalized_text]
            
            # 快速模式：缓存未命中直接返回
            if quick_mode:
                return text
        
        # 检测语言
        has_korean = bool(re.search(r'[가-힣]', text))
        has_japanese = bool(re.search(r'[ひらがなカタカナ一-龯]', text))
        has_english = bool(re.search(r'[a-zA-Z]', text))
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text))
        
        if has_chinese and not (has_korean or has_japanese or has_english):
            return text
        
        if force_lang:
            from_lang = force_lang
        elif has_korean:
            from_lang = 'kor'
        elif has_japanese:
            from_lang = 'jp'
        elif has_english:
            from_lang = 'auto'
        else:
            return text
        
        # 调用百度翻译API（使用更短的超时时间以加快响应）
        try:
            api_url = 'http://api.fanyi.baidu.com/api/trans/vip/translate'
            salt = str(random.randint(32768, 65536))
            # 使用最新的配置值（支持配置热更新）
            app_id = self.config.translation_config.baidu_app_id
            secret_key = self.config.translation_config.baidu_secret_key
            sign_str = app_id + text + salt + secret_key
            sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest()
            
            params = {
                'q': text,
                'from': from_lang,
                'to': 'zh',
                'appid': app_id,
                'salt': salt,
                'sign': sign
            }
            
            # 使用更短的超时时间（2秒）以降低推送延迟
            response = requests.get(api_url, params=params, timeout=2)
            response.raise_for_status()
            result = response.json()
            
            # 检查API返回的错误码
            if 'error_code' in result:
                error_code = result.get('error_code')
                error_msg = result.get('error_msg', '未知错误')
                logger.error(f"翻译API返回错误: error_code={error_code}, error_msg={error_msg}")
                # 常见错误码处理
                if error_code == '54003':  # 访问频率受限
                    logger.warning("翻译API访问频率受限，请稍后再试")
                elif error_code == '54004':  # 账户余额不足
                    logger.warning("翻译API账户余额不足")
                elif error_code == '54005':  # 长query请求频繁
                    logger.warning("翻译API请求过于频繁")
                elif error_code in ['52001', '52002', '52003']:  # 系统错误
                    logger.warning(f"翻译API系统错误: {error_msg}")
                return text
            
            if 'trans_result' in result and result['trans_result']:
                translated = result['trans_result'][0]['dst']
                # 保存到内存缓存（使用规范化后的键，确保不重复）
                with self.lock:
                    self.cache[normalized_text] = translated
                # 立即异步保存到文件（确保缓存持久化，无上限）
                self._async_save_cache()
                logger.info(f"翻译成功: '{text}' -> '{translated}'")
                return translated
            else:
                logger.error(f"翻译API返回格式异常: {result}")
                return text
        except requests.Timeout:
            # 超时情况：返回原文，避免阻塞
            logger.warning(f"翻译超时: '{text}'，返回原文")
            return text
        except Exception as e:
            logger.error(f"翻译异常: {e}")
            return text
    
    def translate_async(self, text: str, force_lang: Optional[str] = None):
        """异步翻译（后台任务）"""
        def _translate():
            try:
                normalized_text = self._normalize_key(text)
                if normalized_text not in self.cache:
                    self.translate(text, force_lang=force_lang, quick_mode=False)
            except Exception as e:
                logger.debug(f"异步翻译失败: {text}, {e}")
        
        threading.Thread(target=_translate, daemon=True, name="AsyncTranslate").start()
