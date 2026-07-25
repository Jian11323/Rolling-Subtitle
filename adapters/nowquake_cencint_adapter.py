#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Nowquake CENC 烈度速报 WebSocket / HTTP 适配器。

文档：https://doc.nowquake.cn/?url=./docs/cencint.json
WS：wss://api-cencint-public.nowquake.cn/websocket
HTTP：https://api-cencint-public.nowquake.cn （首连建议 GET 一次详情，后续靠 WS 推送）
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, Optional

import requests

from .base_adapter import BaseAdapter
from utils import timezone_utils
from utils.logger import get_logger

logger = get_logger()

NOWQUAKE_CENCINT_HTTP_BASE = "https://api-cencint-public.nowquake.cn"
NOWQUAKE_CENCINT_ORG = "中国地震台网中心地震烈度速报"


class NowquakeCencintAdapter(BaseAdapter):
    """解析 Nowquake CENC 烈度速报（heartbeat / data）。"""

    def __init__(self, source_name: str, source_url: str):
        """初始化并准备事件去重状态。"""
        super().__init__(source_name, source_url)
        self._last_event_key = ""

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 WebSocket JSON（忽略 heartbeat，处理 data）。"""
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError, ValueError):
                return None
        if not isinstance(raw_data, dict):
            return None

        msg_type = str(raw_data.get("type") or "").strip().lower()
        if msg_type == "heartbeat":
            return None
        # WS 推送带 type=data；HTTP 详情无 type，按 eq_id 识别
        if msg_type and msg_type != "data":
            return None
        if not raw_data.get("eq_id") and not raw_data.get("hypocenter"):
            return None
        return self._parse_event(raw_data)

    def fetch_latest_event(self, timeout: float = 12.0) -> Optional[Dict[str, Any]]:
        """首连 HTTP 拉取最新事件详情（仅一次，不做持续轮询）。"""
        try:
            last = requests.get(
                f"{NOWQUAKE_CENCINT_HTTP_BASE}/lastid",
                timeout=timeout,
            )
            last.raise_for_status()
            last_body = last.json()
            eq_id = ""
            if isinstance(last_body, dict):
                eq_id = str(last_body.get("eq_id") or "").strip()
            if not eq_id:
                logger.debug("[cenc-ir/nowquake] /lastid 无有效 eq_id")
                return None
            detail = requests.get(
                f"{NOWQUAKE_CENCINT_HTTP_BASE}/event/{eq_id}",
                timeout=timeout,
            )
            detail.raise_for_status()
            body = detail.json()
            if not isinstance(body, dict):
                return None
            # 与 WS data 包对齐，便于同一套解析
            if "type" not in body:
                body = dict(body)
                body["type"] = "data"
            return self.parse(body)
        except Exception as e:
            logger.warning(f"[cenc-ir/nowquake] 首连拉取最新烈度速报失败: {e}")
            return None

    def _parse_event(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """将 EventDetail / WsData 转为内部 cenc-ir 标准结构。"""
        place_name = str(data.get("hypocenter") or "").strip()
        shock_raw = data.get("happen_time")
        if not place_name and not shock_raw:
            return None

        shock_time = ""
        if shock_raw is not None and shock_raw != "":
            try:
                if isinstance(shock_raw, (int, float)):
                    shock_time = timezone_utils.ms_timestamp_utc_to_display(float(shock_raw))
                else:
                    # 文档：时间均为 UTC+8
                    shock_time = timezone_utils.cst_to_display(str(shock_raw))
            except Exception:
                shock_time = str(shock_raw)

        mag = self._safe_float(data.get("magnitude"), 0.0)
        lat = self._safe_float(data.get("latitude"), 0.0)
        lon = self._safe_float(data.get("longitude"), 0.0)
        depth = self._safe_float(data.get("depth"), 0.0)
        event_id = str(data.get("eq_id") or "").strip()
        update_time = str(data.get("update_time") or "").strip()
        if not event_id:
            event_id = f"nowquake_{shock_time}_{lat}_{lon}"

        # 同事件无实质变化则跳过（update_time / 最大烈度 / 台站数）
        stations_raw = data.get("stations") if isinstance(data.get("stations"), list) else []
        max_int = self._safe_float(data.get("maxintensity"), 0.0)
        dedup_key = f"{event_id}|{update_time}|{mag}|{max_int}|{len(stations_raw)}"
        if self._last_event_key == dedup_key:
            return None
        self._last_event_key = dedup_key

        stations = [self._normalize_station(s) for s in stations_raw if isinstance(s, dict)]
        info_text = str(data.get("info") or "").strip()
        contour = self._decode_forecast_geojson(data.get("forecast"))

        result: Dict[str, Any] = {
            "type": "report",
            "source_type": "cenc-ir",
            "place_name": place_name or "未知地区",
            "shock_time": shock_time,
            "magnitude": mag,
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "organization": NOWQUAKE_CENCINT_ORG,
            "event_id": event_id,
            "max_intensity": max_int if max_int > 0 else None,
            "maxIntensity": max_int if max_int > 0 else None,
            "raw_data": data,
        }
        if info_text:
            result["cenc_ir_intensity_info_text"] = info_text
        if stations:
            result["cenc_ir_instrument_intensity_json"] = stations
        if isinstance(contour, dict):
            result["cenc_ir_contour_geojson"] = contour

        logger.info(
            "[cenc-ir/nowquake] 解析: eq_id=%s place=%s M%s stations=%s contour=%s",
            event_id,
            place_name,
            mag,
            len(stations),
            "yes" if "cenc_ir_contour_geojson" in result else "no",
        )
        return result

    def _normalize_station(self, s: Dict[str, Any]) -> Dict[str, Any]:
        """将 Nowquake 台站字段归一为现有烈度图/文案所用键名。"""
        out = dict(s)
        lon = self._safe_float(s.get("longitude"), 0.0)
        lat = self._safe_float(s.get("latitude"), 0.0)
        intensity = self._safe_float(s.get("int"), 0.0)
        pga = self._safe_float(s.get("pga"), 0.0)
        pgv = self._safe_float(s.get("pgv"), 0.0)

        out.setdefault("stlo", lon)
        out.setdefault("stla", lat)
        out.setdefault("longitude", lon)
        out.setdefault("latitude", lat)
        out.setdefault("INT", intensity)
        out.setdefault("estimateInt", intensity)
        out.setdefault("PGA", pga)
        out.setdefault("PGV", pgv)

        loc = s.get("location_name")
        if isinstance(loc, dict):
            out.setdefault("Province", str(loc.get("province") or "").strip())
            out.setdefault("City", str(loc.get("city") or "").strip())
            out.setdefault("County", str(loc.get("county") or "").strip())
            out.setdefault("Town", str(loc.get("town") or "").strip())
            placename = str(loc.get("placename") or "").strip()
            if placename:
                out.setdefault("placeName", placename)
        return out

    @staticmethod
    def _decode_forecast_geojson(forecast: Any) -> Optional[Dict[str, Any]]:
        """解压 forecast（Base64 + Zstandard）为 GeoJSON FeatureCollection。"""
        if forecast is None or forecast == "":
            return None
        try:
            s = forecast
            if isinstance(s, (bytes, bytearray)):
                s = s.decode("utf-8", errors="ignore")
            if not isinstance(s, str):
                return None
            s = s.strip()
            # 示例形如 "\"KLUv/...\""（JSON 字符串再包一层）
            if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                try:
                    s = json.loads(s)
                except (json.JSONDecodeError, TypeError, ValueError):
                    s = s[1:-1]
            if not isinstance(s, str) or not s:
                return None
            raw = base64.b64decode(s)
            try:
                import zstandard  # type: ignore
            except ImportError:
                logger.warning("[cenc-ir/nowquake] 未安装 zstandard，跳过等震线解压")
                return None
            text = zstandard.ZstdDecompressor().decompress(raw)
            obj = json.loads(text)
            if isinstance(obj, list):
                return {"type": "FeatureCollection", "features": obj}
            if isinstance(obj, dict):
                return obj
        except Exception as e:
            logger.debug(f"[cenc-ir/nowquake] forecast 解压失败: {e}")
        return None

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """安全转换为浮点数。"""
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（烈度速报按 report）。"""
        return data.get("type", "report")

    def get_organization_name(self) -> str:
        """机构显示名。"""
        return NOWQUAKE_CENCINT_ORG
