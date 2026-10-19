#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FSSN WebSocket 适配器（wss://fssn-api.fanstudio.tech）。

文档：https://fssn-api.fanstudio.tech/
地址：wss://fssn-api.fanstudio.tech/[all|fssn|fssn-cmt]
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .base_adapter import BaseAdapter
from utils.logger import get_logger
from utils import timezone_utils

logger = get_logger()


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_event_id(
    data: Dict[str, Any],
    source_type: str,
    place_name: str,
    shock_time: str,
    latitude: float,
    longitude: float,
) -> str:
    for key in ("id", "eventId", "event_id"):
        v = data.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return f"{source_type}:{shock_time}:{place_name}:{latitude:.3f}:{longitude:.3f}"


def _get_organization_name(source_type: str) -> str:
    try:
        from config import Config

        return Config().get_organization_name(source_type)
    except Exception:
        return "FSSN" if source_type == "fssn" else "FSSN 矩心矩张量解"


class FssnAdapter(BaseAdapter):
    """解析 FSSN / FSSN-CMT 推送与 list 响应。"""

    def __init__(self, source_name: str, source_url: str):
        super().__init__(source_name, source_url)
        path = (source_url or "").rstrip("/").split("/")[-1].split("?")[0].lower()
        self.channel = path if path in ("all", "fssn", "fssn-cmt") else "all"

    def on_open_commands(self) -> List[str]:
        """建连后拉取历史列表。"""
        if self.channel == "fssn-cmt":
            return ["cmtlist"]
        if self.channel == "fssn":
            return ["fssnlist"]
        return ["fssnlist", "cmtlist"]

    def _enabled_sources(self) -> set:
        try:
            from config import Config

            mc = Config().message_config
            out = set()
            if getattr(mc, "fssn_parse_fssn", True):
                out.add("fssn")
            if getattr(mc, "fssn_parse_fssn_cmt", True):
                out.add("fssn-cmt")
            return out
        except Exception:
            return {"fssn", "fssn-cmt"}

    def _parse_fssn_report(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(data, dict):
            return None
        place_name = str(
            data.get("placeName_zh") or data.get("placeName") or data.get("title") or ""
        ).strip()
        shock_time = str(data.get("shockTime") or data.get("createTime") or "").strip()
        if not place_name and not shock_time:
            return None
        magnitude = _safe_float(data.get("magnitude", 0))
        latitude = _safe_float(data.get("latitude", 0))
        longitude = _safe_float(data.get("longitude", 0))
        depth = _safe_float(data.get("depth", 0))
        if shock_time:
            shock_time = timezone_utils.cst_to_display(shock_time)
        event_id = _resolve_event_id(
            data, "fssn", place_name, shock_time, latitude, longitude
        )
        info_type = str(data.get("infoTypeName") or "").strip()
        result: Dict[str, Any] = {
            "type": "report",
            "magnitude": magnitude,
            "latitude": latitude,
            "longitude": longitude,
            "depth": depth,
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": _get_organization_name("fssn"),
            "event_id": event_id,
            "source_type": "fssn",
            "raw_data": data,
            "fssn": True,
        }
        if info_type:
            result["info_type"] = info_type
        return result

    def _parse_fssn_cmt(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(data, dict):
            return None
        place_name = str(data.get("placeName") or "").strip()
        shock_time = str(data.get("shockTime") or "").strip()
        if not place_name and not shock_time:
            return None
        latitude = _safe_float(data.get("latitude", 0))
        longitude = _safe_float(data.get("longitude", 0))
        depth_str = data.get("depth", "")
        if isinstance(depth_str, str):
            match = re.match(r"^([\d.]+)", depth_str.strip())
            depth = _safe_float(match.group(1), 10.0) if match else 10.0
        else:
            depth = _safe_float(depth_str, 10.0)
        all_mag = data.get("allMagnitudes") or {}
        magnitude = _safe_float(
            all_mag.get("Mww")
            or all_mag.get("M")
            or all_mag.get("mB")
            or all_mag.get("mb")
            or all_mag.get("Mwp")
            or 0
        )
        if shock_time:
            shock_time = timezone_utils.cst_to_display(shock_time)
        event_id = _resolve_event_id(
            data, "fssn-cmt", place_name, shock_time, latitude, longitude
        )
        result: Dict[str, Any] = {
            "type": "report",
            "source_type": "fssn-cmt",
            "place_name": place_name,
            "shock_time": shock_time,
            "magnitude": magnitude,
            "latitude": latitude,
            "longitude": longitude,
            "depth": depth,
            "organization": _get_organization_name("fssn-cmt"),
            "event_id": event_id,
            "raw_data": data,
            "fssn": True,
        }
        for key in ("nodalPlane1", "nodalPlane2"):
            val = data.get(key)
            if val:
                result["nodal_plane_1" if key.endswith("1") else "nodal_plane_2"] = val
        for key in ("mnn", "mee", "mdd", "mne", "mnd", "med"):
            val = data.get(key)
            if val is not None and str(val).strip() != "":
                result[key] = val
        return result

    def _parse_payload(
        self, source_type: str, data: Any
    ) -> Optional[Dict[str, Any]]:
        enabled = self._enabled_sources()
        if source_type not in enabled:
            return None
        if source_type == "fssn-cmt":
            return self._parse_fssn_cmt(data if isinstance(data, dict) else {})
        if source_type == "fssn":
            return self._parse_fssn_report(data if isinstance(data, dict) else {})
        return None

    def _parse_one_frame(self, frame: Dict[str, Any]) -> Optional[Any]:
        msg_type = str(frame.get("type") or "").strip().lower()
        if msg_type in ("heartbeat", "pong", "error", "auth_ok", "auth_fail"):
            if msg_type == "error":
                logger.warning(f"[FSSN] 错误: {frame.get('message')}")
            return None

        if msg_type == "initial_all":
            results: List[Dict[str, Any]] = []
            for key in ("fssn", "fssn-cmt"):
                block = frame.get(key)
                if not isinstance(block, dict):
                    continue
                data = block.get("Data") or block.get("data")
                parsed = self._parse_payload(key, data)
                if parsed:
                    results.append(parsed)
            return results or None

        if msg_type in ("fssnlist_response", "cmtlist_response"):
            source_type = "fssn" if msg_type.startswith("fssn") else "fssn-cmt"
            items = frame.get("Data") or frame.get("data") or []
            if not isinstance(items, list):
                return None
            results = []
            for item in items:
                parsed = self._parse_payload(source_type, item)
                if parsed:
                    results.append(parsed)
            return results or None

        # 业务帧 type = 机构 ID（fssn / fssn-cmt）
        if msg_type in ("fssn", "fssn-cmt"):
            data = frame.get("Data") or frame.get("data")
            return self._parse_payload(
                msg_type, data if isinstance(data, dict) else {}
            )

        if msg_type in ("initial", "update", "query_response"):
            source = str(frame.get("source") or "").strip().lower()
            if not source:
                if self.channel in ("fssn", "fssn-cmt"):
                    source = self.channel
                else:
                    # /all 上缺 source 时无法区分，丢弃以免误解析 CMT
                    logger.debug("[FSSN] %s 帧缺少 source，跳过", msg_type)
                    return None
            data = frame.get("Data") or frame.get("data")
            return self._parse_payload(
                source, data if isinstance(data, dict) else {}
            )

        # 无 type、仅有 Data：按 source / 当前频道解析
        data = frame.get("Data") or frame.get("data")
        if isinstance(data, dict):
            source = str(frame.get("source") or "").strip().lower()
            if not source:
                source = self.channel if self.channel in ("fssn", "fssn-cmt") else ""
            if source == "all" or not source:
                logger.debug("[FSSN] 无 type 帧无法确定 source，跳过")
                return None
            return self._parse_payload(source, data)
        return None

    def parse(self, raw_data: Any) -> Optional[Any]:
        if isinstance(raw_data, str):
            text = raw_data.strip()
            if not text or text in ("ping", "pong"):
                return None
            try:
                raw_data = json.loads(text)
            except (json.JSONDecodeError, TypeError, ValueError):
                logger.debug("[FSSN] 非 JSON，跳过")
                return None
        if isinstance(raw_data, list):
            out: List[Dict[str, Any]] = []
            for item in raw_data:
                if not isinstance(item, dict):
                    continue
                parsed = self._parse_one_frame(item)
                if isinstance(parsed, list):
                    out.extend(parsed)
                elif isinstance(parsed, dict):
                    out.append(parsed)
            return out or None
        if isinstance(raw_data, dict):
            return self._parse_one_frame(raw_data)
        return None

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """FSSN 均为速报/CMT。"""
        return str((data or {}).get("type") or "report")

