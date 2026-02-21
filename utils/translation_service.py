#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译服务模块（公开版占位）
公开版已移除百度翻译，此类仅保留接口兼容，translate 直接返回原文。
"""

from typing import Optional


class TranslationService:
    """翻译服务（占位实现，直接返回原文）"""
    
    def __init__(self, config):
        self.config = config
    
    def translate(self, text: str, force_lang: Optional[str] = None, quick_mode: bool = False, skip_cache: bool = False) -> str:
        """直接返回原文，不进行翻译"""
        return text
