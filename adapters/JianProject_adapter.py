#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jian Project 适配器
解析 initial_all 与 update 消息，产出 nied、early_est、jma_volcano 等子源数据。
子源是否解析由配置 ali_all_parse_nied / ali_all_parse_early_est / ali_all_parse_jma_volcano 等开关控制。
"""

import json
from typing import Dict, Any, Optional, List

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .base_adapter import BaseAdapter
from .nied_adapter import NiedAdapter
from .jma_volcano_adapter import JmaVolcanoAdapter
from utils.logger import get_logger
from utils import timezone_utils

logger = get_logger()

ALI_ALL_URL = "wss://sismotide.top/all"

# initial_all 中与子源对应的键；jma-volcano-long / jma-volcano-high 均映射为 jma_volcano
SOURCE_KEYS_NIED = ["nied"]
SOURCE_KEYS_EARLY_EST = ["early-est"]
SOURCE_KEYS_JMA_VOLCANO = ["jma-volcano-long", "jma-volcano-high"]
# 其他速报/海啸信息子源
SOURCE_KEYS_BMKG = ["bmkg"]
SOURCE_KEYS_GEONET = ["geonet"]
SOURCE_KEYS_PTWC = ["ptwc"]


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _get_config():
    from config import Config
    return Config()


def _ali_all_enabled_sub_sources() -> Dict[str, bool]:
    """返回 ali all 各子源是否启用解析。"""
    cfg = _get_config()
    return {
        "nied": getattr(cfg.message_config, "ali_all_parse_nied", False),
        "early_est": getattr(cfg.message_config, "ali_all_parse_early_est", False),
        "jma_volcano": getattr(cfg.message_config, "ali_all_parse_jma_volcano", True),
        "bmkg": getattr(cfg.message_config, "ali_all_parse_bmkg", True),
        "geonet": getattr(cfg.message_config, "ali_all_parse_geonet", True),
        "ptwc": getattr(cfg.message_config, "ali_all_parse_ptwc", True),
    }


_place_name_fixer = None


def _get_place_name_fixer():
    """延迟加载地名修正工具，供 BMKG / GeoNet 使用。"""
    global _place_name_fixer
    if _place_name_fixer is None:
        try:
            from utils.place_name_fixer import PlaceNameFixer
            _place_name_fixer = PlaceNameFixer()
        except Exception as e:
            logger.error(f"初始化地名修正工具失败: {e}")
            _place_name_fixer = None
    return _place_name_fixer


def _parse_nied_from_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 all 源中的 nied Data 构造与 NiedAdapter 兼容的 update，并解析。"""
    if not payload or payload.get("is_cancel") is True:
        return None
    # NiedAdapter.parse 期望 {"type": "update", "data": inner}
    fake = {"type": "update", "data": payload}
    adapter = NiedAdapter("nied", ALI_ALL_URL)
    return adapter.parse(fake)


def _parse_early_est_from_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 all 源中的 early-est Data 解析为统一预警结构。"""
    if not payload or payload.get("isCancel") is True:
        return None
    try:
        place = (payload.get("placeName") or "").strip() or "未知"
        mag = _safe_float(payload.get("magnitude"))
        depth = _safe_float(payload.get("depth"))
        event_id = (payload.get("eventID") or "").strip()
        shock_raw = payload.get("shockTime") or ""
        if shock_raw:
            s = shock_raw.strip().replace("/", "-")
            if " " in s and "T" not in s:
                s = s.replace(" ", "T", 1)
            shock_time = timezone_utils.utc_to_display(s)
        else:
            shock_time = ""
        return {
            "type": "warning",
            "source_type": "early_est",
            "organization": "Early-est",
            "place_name": place,
            "magnitude": mag,
            "latitude": _safe_float(payload.get("latitude")),
            "longitude": _safe_float(payload.get("longitude")),
            "depth": depth,
            "shock_time": shock_time,
            "event_id": event_id,
            "raw_data": {"type": "update", "source": "early-est", "Data": payload},
        }
    except Exception as e:
        logger.debug(f"[AliAll early-est] 解析跳过: {e}")
        return None


def _parse_jma_volcano_from_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 all 源中的 jma-volcano Data 构造与 JmaVolcanoAdapter 兼容的 update，并解析。"""
    if not payload:
        return None
    fake = {"type": "update", "data": {"Data": payload}}
    adapter = JmaVolcanoAdapter("jma_volcano", ALI_ALL_URL)
    return adapter.parse(fake)


def _parse_bmkg_from_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 all 源中的 bmkg Data 解析为统一速报结构。"""
    if not payload:
        return None
    try:
        place = (payload.get("placeName") or "").strip() or "未知地区"
        mag = _safe_float(payload.get("magnitude"))
        depth = _safe_float(payload.get("depth"), 10.0)
        event_id = (payload.get("eventId") or "").strip()
        shock_raw = payload.get("shockTime") or ""
        if shock_raw:
            # BMKG 给出当地时间，约 UTC+7，这里简单视作 CST 再转换到显示时区，避免过度假设
            shock_time = timezone_utils.cst_to_display(shock_raw.replace("T", " "))
        else:
            shock_time = ""
        # 可选：根据配置对 BMKG 地名进行修正
        try:
            cfg = _get_config()
            tcfg = cfg.translation_config
            if getattr(tcfg, "use_place_name_fix", True) and place:
                fixer = _get_place_name_fixer()
                if fixer and fixer.is_supported("bmkg"):
                    place = fixer.fix_place_name(
                        place,
                        _safe_float(payload.get("latitude")),
                        _safe_float(payload.get("longitude")),
                        "bmkg",
                    )
        except Exception as e:
            logger.debug(f"[AliAll bmkg] 地名修正失败，使用原始地名: {e}")
        result: Dict[str, Any] = {
            "type": "report",
            "source_type": "bmkg",
            "organization": _get_config().get_organization_name("bmkg"),
            "place_name": place,
            "magnitude": mag,
            "latitude": _safe_float(payload.get("latitude")),
            "longitude": _safe_float(payload.get("longitude")),
            "depth": depth,
            "shock_time": shock_time,
            "event_id": event_id,
            "raw_data": {"type": "update", "source": "bmkg", "Data": payload},
        }
        potensi = (payload.get("potensi") or "").strip()
        if potensi:
            result["potensi"] = potensi
        return result
    except Exception as e:
        logger.debug(f"[AliAll bmkg] 解析跳过: {e}")
        return None


def _parse_geonet_from_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 all 源中的 geonet Data 解析为统一速报结构。"""
    if not payload:
        return None
    try:
        place = (payload.get("placeName") or "").strip() or "未知地区"
        mag = _safe_float(payload.get("magnitude"))
        depth = _safe_float(payload.get("depth"), 10.0)
        event_id = (payload.get("eventId") or "").strip()
        shock_raw = payload.get("shockTime") or ""
        if shock_raw:
            # GeoNet 提供 UTC 时间
            s = shock_raw.strip().replace(" ", "T") if "T" not in shock_raw else shock_raw.strip()
            shock_time = timezone_utils.utc_to_display(s)
        else:
            shock_time = ""
        # 可选：根据配置对 GeoNet 地名进行修正
        try:
            cfg = _get_config()
            tcfg = cfg.translation_config
            if getattr(tcfg, "use_place_name_fix", True) and place:
                fixer = _get_place_name_fixer()
                if fixer and fixer.is_supported("geonet"):
                    place = fixer.fix_place_name(
                        place,
                        _safe_float(payload.get("latitude")),
                        _safe_float(payload.get("longitude")),
                        "geonet",
                    )
        except Exception as e:
            logger.debug(f"[AliAll geonet] 地名修正失败，使用原始地名: {e}")
        result: Dict[str, Any] = {
            "type": "report",
            "source_type": "geonet",
            "organization": _get_config().get_organization_name("geonet"),
            "place_name": place,
            "magnitude": mag,
            "latitude": _safe_float(payload.get("latitude")),
            "longitude": _safe_float(payload.get("longitude")),
            "depth": depth,
            "shock_time": shock_time,
            "event_id": event_id,
            "raw_data": {"type": "update", "source": "geonet", "Data": payload},
        }
        quality = (payload.get("quality") or "").strip()
        if quality:
            result["quality"] = quality
        if payload.get("mmi") is not None:
            result["mmi"] = payload.get("mmi")
        return result
    except Exception as e:
        logger.debug(f"[AliAll geonet] 解析跳过: {e}")
        return None


def _parse_ptwc_from_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 all 源中的 PTWC Data 解析为海啸信息类速报。"""
    if not payload:
        return None
    try:
        place = (payload.get("placeName") or "").strip() or "OFFSHORE"
        mag = _safe_float(payload.get("magnitude"))
        depth = _safe_float(payload.get("depth"), 10.0)
        event_id = (payload.get("eventId") or "").strip()
        shock_raw = payload.get("shockTime") or ""
        if shock_raw:
            s = shock_raw.strip().replace(" ", "T") if "T" not in shock_raw else shock_raw.strip()
            shock_time = timezone_utils.utc_to_display(s)
        else:
            shock_time = ""
        cfg = _get_config()
        org = cfg.get_organization_name("ptwc")

        # 对 PTWC 关键信息调用百度翻译（若已正确配置）
        headline = (payload.get("headline") or "").strip()
        event = (payload.get("event") or "").strip()
        severity = (payload.get("severity") or "").strip()
        description = (payload.get("description") or "").strip()
        try:
            from utils.translation_service import TranslationService
            app_id = getattr(cfg.translation_config, "baidu_app_id", "") or ""
            secret = getattr(cfg.translation_config, "baidu_secret", "") or ""
            if app_id and secret:
                svc = TranslationService(cfg.translation_config)
                if headline:
                    headline = svc.translate(headline, force_lang="zh", skip_cache=False)
                if event:
                    event = svc.translate(event, force_lang="zh", skip_cache=False)
                if description:
                    description = svc.translate(description, force_lang="zh", skip_cache=False)
                if place and place != "OFFSHORE":
                    place = svc.translate(place, force_lang="zh", skip_cache=False)
        except Exception as e:
            logger.debug(f"[AliAll ptwc] 调用百度翻译失败，使用原文: {e}")

        result: Dict[str, Any] = {
            "type": "report",
            "source_type": "ptwc",
            "organization": org,
            "place_name": place,
            "magnitude": mag,
            "latitude": _safe_float(payload.get("latitude")),
            "longitude": _safe_float(payload.get("longitude")),
            "depth": depth,
            "shock_time": shock_time,
            "event_id": event_id,
            "raw_data": {"type": "update", "source": "ptwc", "Data": payload},
        }
        # 关键信息直接透传，供 message_processor 组合海啸文案
        # 其中 headline / event / description / severity 若已翻译则写入译文
        if headline:
            result["headline"] = headline
        if event:
            result["event"] = event
        if severity:
            result["severity"] = severity
        if description:
            result["description"] = description
        for key in (
            "certainty",
            "urgency",
            "onset",
            "expires",
            "web",
            "senderName",
            "magnitudeType",
        ):
            if payload.get(key) is not None:
                result[key] = payload.get(key)
        return result
    except Exception as e:
        logger.debug(f"[AliAll ptwc] 解析跳过: {e}")
        return None


class JianProjectAdapter(BaseAdapter):
    """Jian Project：解析 initial_all 与 update，按配置产出子源消息。"""

    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)

    def _enabled(self) -> Dict[str, bool]:
        return _ali_all_enabled_sub_sources()

    def parse_all_sources(self, raw_data: Any) -> List[Dict[str, Any]]:
        """解析 initial_all，返回已启用的各子源解析结果列表。"""
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if not isinstance(data, dict) or data.get("type") != "initial_all":
                return []
            enabled = self._enabled()

            results = []

            for key in SOURCE_KEYS_NIED:
                if not enabled.get("nied"):
                    continue
                if key not in data or not isinstance(data[key], dict):
                    continue
                payload = data[key].get("Data")
                if not isinstance(payload, dict):
                    continue
                parsed = _parse_nied_from_payload(payload)
                if parsed:
                    results.append(parsed)

            for key in SOURCE_KEYS_EARLY_EST:
                if not enabled.get("early_est"):
                    continue
                if key not in data or not isinstance(data[key], dict):
                    continue
                payload = data[key].get("Data")
                if not isinstance(payload, dict):
                    continue
                parsed = _parse_early_est_from_payload(payload)
                if parsed:
                    results.append(parsed)

            for key in SOURCE_KEYS_JMA_VOLCANO:
                if not enabled.get("jma_volcano"):
                    continue
                if key not in data or not isinstance(data[key], dict):
                    continue
                payload = data[key].get("Data")
                if not isinstance(payload, dict):
                    continue
                parsed = _parse_jma_volcano_from_payload(payload)
                if parsed:
                    results.append(parsed)

            for key in SOURCE_KEYS_BMKG:
                if not enabled.get("bmkg"):
                    continue
                if key not in data or not isinstance(data[key], dict):
                    continue
                payload = data[key].get("Data")
                if not isinstance(payload, dict):
                    continue
                parsed = _parse_bmkg_from_payload(payload)
                if parsed:
                    results.append(parsed)

            for key in SOURCE_KEYS_GEONET:
                if not enabled.get("geonet"):
                    continue
                if key not in data or not isinstance(data[key], dict):
                    continue
                payload = data[key].get("Data")
                if not isinstance(payload, dict):
                    continue
                parsed = _parse_geonet_from_payload(payload)
                if parsed:
                    results.append(parsed)

            for key in SOURCE_KEYS_PTWC:
                if not enabled.get("ptwc"):
                    continue
                if key not in data or not isinstance(data[key], dict):
                    continue
                payload = data[key].get("Data")
                if not isinstance(payload, dict):
                    continue
                parsed = _parse_ptwc_from_payload(payload)
                if parsed:
                    results.append(parsed)

            if results:
                logger.info(f"[AliAll] initial_all 解析出 {len(results)} 条（nied={enabled['nied']}, early_est={enabled['early_est']}, jma_volcano={enabled['jma_volcano']}）")
            return results
        except Exception as e:
            logger.error(f"[AliAll] 解析 initial_all 失败: {e}", exc_info=True)
            return []

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析单条消息（含 update）。仅处理 type=update，按 source 字段分发并检查子源开关。"""
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if not isinstance(data, dict) or data.get("type") != "update":
                return None
            source_key = (data.get("source") or "").strip()
            payload = data.get("Data") if isinstance(data.get("Data"), dict) else None
            if not payload:
                return None
            enabled = self._enabled()

            if source_key in SOURCE_KEYS_NIED and enabled.get("nied"):
                return _parse_nied_from_payload(payload)
            if source_key in SOURCE_KEYS_EARLY_EST and enabled.get("early_est"):
                return _parse_early_est_from_payload(payload)
            if source_key in SOURCE_KEYS_JMA_VOLCANO and enabled.get("jma_volcano"):
                return _parse_jma_volcano_from_payload(payload)
            if source_key in SOURCE_KEYS_BMKG and enabled.get("bmkg"):
                return _parse_bmkg_from_payload(payload)
            if source_key in SOURCE_KEYS_GEONET and enabled.get("geonet"):
                return _parse_geonet_from_payload(payload)
            if source_key in SOURCE_KEYS_PTWC and enabled.get("ptwc"):
                return _parse_ptwc_from_payload(payload)

            return None
        except Exception as e:
            logger.debug(f"[AliAll] parse 跳过: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "unknown")

