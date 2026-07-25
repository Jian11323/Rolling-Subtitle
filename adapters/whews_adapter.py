#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无界科技（WHEWS：api.2v8.cn / 备用 api.beecld.com）数据源适配器。

帧格式：{"Data": {...}, "md5": "...", "source": "cenc"}
聚合 /ws/all 首连为 JSON 数组，之后为单对象；心跳 type=heartbeat。
JMA 预警（jma_eew）随主服务解析；JMA 情报（jma）不解析，统一走 P2PQuake。
解析复用 FanStudioAdapter 的字段处理逻辑。

注意：上游 API 的 source 字段大小写混杂（如 CENC / cenc / Cenc），
解析时一律规范化为小写后再映射；待上游统一后再可简化。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set

from .base_adapter import BaseAdapter
from .fanstudio_adapter import FanStudioAdapter
from utils.logger import get_logger

logger = get_logger()

# JMA 情报仅使用 P2PQuake；预警由主服务（无界科技）解析
WHEWS_SKIP_SOURCES = frozenset({"jma"})

# WHEWS source 短名 → 内部 source_type（与 Fan Studio / 展示层一致）
# 键一律小写；实际查找走 _WHEWS_SOURCE_LOOKUP（兼容大小写与 -/_）
WHEWS_SOURCE_TO_INTERNAL = {
    "jma_eew": "jma",
    "cwa_eew": "cwa-eew",
    "sa_eew": "sa",
    "cea": "cea",
    "cea-pr": "cea-pr",
    "cenc": "cenc",
    "cwa": "cwa",
    "hko": "hko",
    "usgs": "usgs",
    "emsc": "emsc",
    "bcsf": "bcsf",
    "gfz": "gfz",
    "usp": "usp",
    "kma": "kma",
    "bmkg": "bmkg",
    "geonet": "geonet",
    "tmd": "tmd",
    "ingv": "ingv",
    "tsunami": "tsunami",
    "weatheralarm": "weatheralarm",
    "va": "jma_volcano",
}


def _build_whews_source_lookup() -> Dict[str, str]:
    """构建 source 短名查找表：小写，并同时登记 - / _ 两种写法。"""
    out: Dict[str, str] = {}
    for key, internal in WHEWS_SOURCE_TO_INTERNAL.items():
        kl = str(key).strip().lower()
        if not kl:
            continue
        for alias in (kl, kl.replace("_", "-"), kl.replace("-", "_")):
            out.setdefault(alias, internal)
    return out


_WHEWS_SOURCE_LOOKUP = _build_whews_source_lookup()


def normalize_whews_source(value: Any) -> str:
    """将 API source 规范为小写短名（兼容大小写混杂）。"""
    return str(value or "").strip().lower()


def resolve_whews_internal_source(short: str) -> Optional[str]:
    """将规范化后的 source 短名解析为内部 source_type。"""
    key = normalize_whews_source(short)
    if not key:
        return None
    return _WHEWS_SOURCE_LOOKUP.get(key)


# 内部 source_type → message_config.whews_parse_* 字段名
WHEWS_SOURCE_FLAG_FIELD = {
    "jma": "whews_parse_jma_eew",
    "cwa-eew": "whews_parse_cwa_eew",
    "sa": "whews_parse_sa_eew",
    "cea": "whews_parse_cea",
    "cea-pr": "whews_parse_cea_pr",
    "cenc": "whews_parse_cenc",
    "cwa": "whews_parse_cwa",
    "hko": "whews_parse_hko",
    "usgs": "whews_parse_usgs",
    "emsc": "whews_parse_emsc",
    "bcsf": "whews_parse_bcsf",
    "gfz": "whews_parse_gfz",
    "usp": "whews_parse_usp",
    "kma": "whews_parse_kma",
    "bmkg": "whews_parse_bmkg",
    "geonet": "whews_parse_geonet",
    "tmd": "whews_parse_tmd",
    "ingv": "whews_parse_ingv",
    "tsunami": "whews_parse_tsunami",
    "weatheralarm": "whews_parse_weatheralarm",
    "jma_volcano": "whews_parse_jma_volcano",
}

WHEWS_WARNING_INTERNAL = {"jma", "cwa-eew", "sa", "cea", "cea-pr"}


class WhewsAdapter(BaseAdapter):
    """无界科技 WebSocket 适配器。"""

    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)
        path = (source_url or "").rstrip("/").split("/")[-1].split("?")[0].lower()
        self.endpoint = path or "all"
        self._fs = FanStudioAdapter("all", source_url)
        self._fs.data_source_type = "all"

    def _enabled_internal_sources(self) -> Set[str]:
        """根据配置返回当前允许解析的内部 source_type 集合。"""
        from config import Config, is_whews_url

        config = getattr(self, "_config", None) or Config()
        enabled_sources = getattr(self, "_enabled_sources", None) or config.enabled_sources
        # 任一无界科技通道启用即可解析（子源由 parse 开关控制）
        if not any(bool(v) and is_whews_url(k) for k, v in (enabled_sources or {}).items()):
            return set()
        msg = getattr(config, "message_config", None)
        if msg is None:
            return set()
        # 备用站无 CEA：即使勾选也不解析
        host = ""
        try:
            host = config.get_whews_host()
        except Exception:
            host = ""
        from config import whews_host_supports_cea

        allow_cea = whews_host_supports_cea(host)
        out: Set[str] = set()
        for internal, field in WHEWS_SOURCE_FLAG_FIELD.items():
            if internal in ("cea", "cea-pr") and not allow_cea:
                continue
            if getattr(msg, field, True):
                out.add(internal)
        return out

    @staticmethod
    def _dict_get_ci(d: Any, *keys: str) -> Any:
        """按候选键取值；键名大小写不敏感。"""
        if not isinstance(d, dict) or not keys:
            return None
        wanted = {str(k).lower() for k in keys}
        for k, v in d.items():
            if isinstance(k, str) and k.lower() in wanted:
                return v
        return None

    @classmethod
    def _extract_source_short(cls, frame: Dict[str, Any]) -> str:
        """从帧中提取 WHEWS source 短名（值与键名均兼容大小写）。"""
        src = cls._dict_get_ci(frame, "source")
        if src is not None and str(src).strip():
            return normalize_whews_source(src)
        data = cls._dict_get_ci(frame, "Data", "data")
        if isinstance(data, dict):
            inner = cls._dict_get_ci(data, "source")
            if inner is not None and str(inner).strip():
                return normalize_whews_source(inner)
        return ""

    def _parse_one_frame(self, frame: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析单帧业务数据。"""
        if not isinstance(frame, dict):
            return None
        msg_type = normalize_whews_source(self._dict_get_ci(frame, "type") or "")
        if msg_type in ("heartbeat", "ping", "pong"):
            return None
        data_obj = self._dict_get_ci(frame, "Data", "data")
        if data_obj is None:
            return None

        short = self._extract_source_short(frame)
        if not short and self.endpoint in ("cea_all", "cea", "cea-pr"):
            short = "cea" if self.endpoint != "cea-pr" else "cea-pr"
            if isinstance(data_obj, dict) and self._dict_get_ci(data_obj, "province"):
                short = "cea-pr"
        if not short and self.endpoint == "cenc":
            short = "cenc"
        if not short:
            logger.debug("[WHEWS] 无法识别 source，跳过")
            return None

        if short in WHEWS_SKIP_SOURCES:
            logger.debug(f"[WHEWS] source={short}（JMA 情报）由 P2PQuake 负责，跳过")
            return None

        internal = resolve_whews_internal_source(short)
        if not internal:
            logger.debug(f"[WHEWS] 未支持的 source={short}，跳过")
            return None

        enabled = self._enabled_internal_sources()
        if internal not in enabled:
            logger.debug(f"[WHEWS] source={short}({internal}) 未勾选解析，跳过")
            return None

        if not isinstance(data_obj, dict) or not data_obj:
            return None

        if internal == "tmd":
            parsed = self._fs._parse_earthquake_report(data_obj, "usgs")
            if not parsed:
                return None
            parsed["source_type"] = "tmd"
            parsed["organization"] = "泰国地震局"
            parsed["fanstudio"] = False
            parsed["whews"] = True
            return parsed

        # update_source 使用规范化短名，避免大小写混杂写入 raw_data
        parsed = self._fs._parse_specific_source(data_obj, internal, update_source=short)
        if not parsed:
            return None
        parsed["fanstudio"] = False
        parsed["whews"] = True
        return parsed

    def parse_all_sources(self, raw_data: Any) -> List[Dict[str, Any]]:
        """解析首连补发的数组帧。"""
        try:
            if isinstance(raw_data, str):
                data = json.loads(raw_data)
            else:
                data = raw_data
            if not isinstance(data, list):
                one = self._parse_one_frame(data) if isinstance(data, dict) else None
                return [one] if one else []
            results: List[Dict[str, Any]] = []
            for item in data:
                parsed = self._parse_one_frame(item) if isinstance(item, dict) else None
                if parsed:
                    results.append(parsed)
            if results:
                logger.info(f"[WHEWS] 首连数组解析出 {len(results)} 条")
            return results
        except Exception as e:
            logger.error(f"[WHEWS] parse_all_sources 失败: {e}")
            return []

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析单条消息；若为数组则返回第一条有效数据（完整列表走 parse_all_sources）。"""
        try:
            if isinstance(raw_data, str):
                try:
                    data = json.loads(raw_data)
                except (json.JSONDecodeError, TypeError, ValueError):
                    logger.debug("[WHEWS] 非 JSON 字符串，跳过")
                    return None
            else:
                data = raw_data
            if isinstance(data, list):
                all_parsed = self.parse_all_sources(data)
                return all_parsed[0] if all_parsed else None
            if isinstance(data, dict):
                return self._parse_one_frame(data)
            return None
        except Exception as e:
            logger.error(f"[WHEWS] parse 失败: {e}")
            return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型。"""
        return data.get("type", "report") if isinstance(data, dict) else "report"
