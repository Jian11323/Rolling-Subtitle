#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
翻译服务模块
支持百度翻译开放平台通用翻译 API（多语种→中文）
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger()

_BAIDU_TRANSLATE_URL = "https://api.fanyi.baidu.com/api/trans/vip/translate"
_BAIDU_MAX_QUERY_LEN = 6000
_BAIDU_TIMEOUT = 5


def _get_baidu_credentials(config: Any) -> tuple[str, str]:
    tc = getattr(config, "translation_config", config)
    app_id = (getattr(tc, "baidu_app_id", "") or "").strip()
    secret = (
        (getattr(tc, "baidu_secret", "") or "")
        or (getattr(tc, "baidu_secret_key", "") or "")
    ).strip()
    return app_id, secret


class TranslationService:
    """翻译服务（百度翻译，多语种→中文）。"""

    def __init__(self, config: Any):
        self.config = config
        self.cache: Dict[str, str] = {}
        try:
            config_dir = Path.home() / "AppData" / "Roaming" / "subtitl"
            config_dir.mkdir(parents=True, exist_ok=True)
            self.cache_file = config_dir / "translation_cache.json"
        except Exception as e:
            logger.error(f"创建翻译缓存目录失败: {e}")
            self.cache_file = Path("translation_cache.json")
        self.lock = threading.Lock()
        self._load_cache()

    @staticmethod
    def _normalize_key(text: str) -> str:
        if not text:
            return text
        return " ".join(text.split())

    def _load_cache(self) -> None:
        if not self.cache_file.exists():
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                raw_cache = json.load(f)
            normalized_cache: Dict[str, str] = {}
            duplicates_removed = 0
            for key, value in raw_cache.items():
                normalized_key = self._normalize_key(key)
                if normalized_key in normalized_cache:
                    duplicates_removed += 1
                normalized_cache[normalized_key] = value
            self.cache = normalized_cache
            if duplicates_removed > 0:
                logger.info(f"加载翻译缓存时发现并移除了 {duplicates_removed} 个重复项")
                self._async_save_cache()
            logger.debug(f"已加载 {len(self.cache)} 条翻译缓存")
        except Exception as e:
            logger.error(f"加载翻译缓存失败: {e}")

    def _async_save_cache(self) -> None:
        def _save() -> None:
            try:
                with self.lock:
                    normalized_cache = {}
                    for key, value in self.cache.items():
                        normalized_key = self._normalize_key(key)
                        normalized_cache[normalized_key] = value
                    self.cache = normalized_cache
                    cache_copy = self.cache.copy()
                with open(self.cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache_copy, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"异步保存翻译缓存失败: {e}")

        threading.Thread(target=_save, daemon=True, name="SaveTranslationCache").start()

    def translate(
        self,
        text: str,
        force_lang: Optional[str] = None,
        quick_mode: bool = False,
        skip_cache: bool = False,
    ) -> str:
        """翻译文本为中文。未配置或失败时返回原文。"""
        if not text or text == "未知地点":
            return text
        text = text.strip()
        app_id, secret_key = _get_baidu_credentials(self.config)
        if not app_id or not secret_key:
            logger.debug("百度翻译 API 未配置，跳过翻译")
            return text
        if len(text) > _BAIDU_MAX_QUERY_LEN:
            text = text[:_BAIDU_MAX_QUERY_LEN]
            logger.debug("翻译文本过长，已截断")
        normalized_text = self._normalize_key(text)
        if not skip_cache and normalized_text in self.cache:
            return self.cache[normalized_text]
        if quick_mode:
            return text

        has_korean = bool(re.search(r"[가-힣]", text))
        has_japanese = bool(re.search(r"[ひらがなカタカナ一-龯]", text))
        has_english = bool(re.search(r"[a-zA-Z]", text))
        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", text))
        if has_chinese and not (has_korean or has_japanese or has_english):
            return text

        if force_lang:
            from_lang = force_lang if force_lang != "zh" else "auto"
        elif has_korean:
            from_lang = "kor"
        elif has_japanese:
            from_lang = "jp"
        elif has_english:
            from_lang = "auto"
        else:
            from_lang = "auto"

        try:
            result = self._call_baidu_api(text, app_id, secret_key, from_lang)
            if result and result != text:
                with self.lock:
                    self.cache[normalized_text] = result
                self._async_save_cache()
                logger.info(f"翻译成功: '{text}' -> '{result}'")
                return result
        except Exception as e:
            logger.debug(f"百度翻译失败，退回原文: {e}")
        return text

    def _call_baidu_api(self, text: str, app_id: str, secret_key: str, from_lang: str) -> str:
        salt = str(random.randint(32768, 65536)) + str(int(time.time() * 1000))
        sign_str = app_id + text + salt + secret_key
        sign = hashlib.md5(sign_str.encode("utf-8")).hexdigest()
        data = {
            "q": text,
            "from": from_lang,
            "to": "zh",
            "appid": app_id,
            "salt": salt,
            "sign": sign,
        }
        try:
            import requests

            resp = requests.post(
                _BAIDU_TRANSLATE_URL,
                data=data,
                timeout=_BAIDU_TIMEOUT,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            out = resp.json()
        except ImportError:
            out = self._call_baidu_api_urllib(data)
        if "error_code" in out and out["error_code"]:
            logger.debug(f"百度翻译 API 错误: {out.get('error_msg', out)}")
            return text
        trans = out.get("trans_result") or []
        if not trans:
            return text
        return trans[0].get("dst", text)

    @staticmethod
    def _call_baidu_api_urllib(data: dict) -> dict:
        import urllib.parse
        import urllib.request

        body = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(
            _BAIDU_TRANSLATE_URL,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=_BAIDU_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
