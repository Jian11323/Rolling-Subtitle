#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译服务模块
支持百度翻译开放平台通用翻译 API（日文→中文，用于火山情报等）
"""

import hashlib
import random
import time
from typing import Optional

from utils.logger import get_logger

logger = get_logger()

# 百度翻译 API
_BAIDU_TRANSLATE_URL = "https://api.fanyi.baidu.com/api/trans/vip/translate"
_BAIDU_MAX_QUERY_LEN = 6000  # 单次请求最大字符数
_BAIDU_TIMEOUT = 5


class TranslationService:
    """翻译服务（百度翻译日文→中文）"""

    def __init__(self, config):
        self.config = config
        self._cache: dict = {}  # 简单内存缓存：原文 -> 译文

    def translate(
        self,
        text: str,
        force_lang: Optional[str] = None,
        quick_mode: bool = False,
        skip_cache: bool = False,
    ) -> str:
        """
        翻译文本（日文→中文）。未配置或失败时返回原文。

        Args:
            text: 待翻译文本
            force_lang: 目标语言，'zh' 表示中文
            quick_mode: 未使用，接口兼容
            skip_cache: 为 True 时跳过缓存

        Returns:
            翻译后的文本，失败或未配置时返回原文
        """
        if not text or not text.strip():
            return text
        text = text.strip()
        app_id = getattr(self.config, "baidu_app_id", "") or ""
        secret = getattr(self.config, "baidu_secret", "") or ""
        if not app_id or not secret:
            return text
        if len(text) > _BAIDU_MAX_QUERY_LEN:
            text = text[:_BAIDU_MAX_QUERY_LEN]
            logger.debug("火山翻译文本过长，已截断")
        if not skip_cache and text in self._cache:
            return self._cache[text]
        try:
            result = self._baidu_translate(text, app_id, secret)
            if result and result != text:
                self._cache[text] = result
                return result
        except Exception as e:
            logger.debug(f"百度翻译失败，退回原文: {e}")
        return text

    def _baidu_translate(self, q: str, app_id: str, secret: str) -> str:
        """调用百度翻译 API，日→中。"""
        salt = str(random.randint(32768, 65536)) + str(int(time.time() * 1000))
        sign_str = app_id + q + salt + secret
        sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()
        data = {
            "q": q,
            "from": "jp",
            "to": "zh",
            "appid": app_id,
            "salt": salt,
            "sign": sign,
        }
        try:
            import requests
        except ImportError:
            return self._baidu_translate_urllib(q, app_id, secret, salt, sign, data)
        resp = requests.post(
            _BAIDU_TRANSLATE_URL,
            data=data,
            timeout=_BAIDU_TIMEOUT,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        out = resp.json()
        if "error_code" in out and out["error_code"]:
            logger.debug(f"百度翻译 API 错误: {out.get('error_msg', out)}")
            return q
        trans = out.get("trans_result") or []
        if not trans:
            return q
        return trans[0].get("dst", q)

    def _baidu_translate_urllib(
        self, q: str, app_id: str, secret: str, salt: str, sign: str, data: dict
    ) -> str:
        """无 requests 时用 urllib 调用百度翻译。"""
        import urllib.request
        import urllib.parse

        body = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(
            _BAIDU_TRANSLATE_URL,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=_BAIDU_TIMEOUT) as resp:
            import json as _json

            out = _json.loads(resp.read().decode("utf-8"))
        if "error_code" in out and out["error_code"]:
            logger.debug(f"百度翻译 API 错误: {out.get('error_msg', out)}")
            return q
        trans = out.get("trans_result") or []
        if not trans:
            return q
        return trans[0].get("dst", q)
