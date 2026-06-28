#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PTWC 太平洋海啸预警中心 CAP XML 适配器。"""

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils

CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}  # CAP 1.2 XML 命名空间


class PtwcAdapter(BaseAdapter):
    """解析 NOAA/PTWC CAP 1.2 XML 海啸预警。"""

    response_format = "xml"

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 PTWC CAP 1.2 XML 原始数据，返回标准化事件字典。"""
        if raw_data is None:
            return None
        if isinstance(raw_data, bytes):
            text = raw_data.decode("utf-8", errors="replace")
        elif isinstance(raw_data, str):
            text = raw_data
        else:
            return None
        text = text.strip()
        if not text:
            return None
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return None
        alert = root if root.tag.endswith("alert") else root.find(".//cap:alert", CAP_NS)
        if alert is None:
            for el in root.iter():
                if el.tag.endswith("alert"):
                    alert = el
                    break
        if alert is None:
            return None
        return self._parse_alert(alert)

    def _cap_text(self, parent: ET.Element, tag: str) -> str:
        """从 CAP 元素中提取指定标签的文本（兼容命名空间）。"""
        for el in parent.iter():
            if el.tag.endswith(tag):
                return (el.text or "").strip()
        node = parent.find(f"cap:{tag}", CAP_NS)
        if node is not None and node.text:
            return node.text.strip()
        return ""

    def _cap_info_list(self, alert: ET.Element) -> List[ET.Element]:
        """获取 alert 下所有 info 节点。"""
        infos = alert.findall("cap:info", CAP_NS)
        if not infos:
            infos = [el for el in alert if el.tag.endswith("info")]
        return infos

    def _cap_parameters(self, info: ET.Element) -> Dict[str, str]:
        """提取 info 内 parameter 键值对（如震级、深度、坐标）。"""
        params: Dict[str, str] = {}
        for el in info.iter():
            if not el.tag.endswith("parameter"):
                continue
            name = self._cap_text(el, "valueName")
            val = self._cap_text(el, "value")
            if name:
                params[name] = val
        return params

    def _apply_cap_parameters(
        self,
        params: Dict[str, str],
        *,
        place_name: str,
        magnitude: float,
        depth: float,
        lat: float,
        lon: float,
        mag_type: str,
    ) -> tuple:
        """从 CAP parameter 字段填充地点、震级、深度与坐标。"""
        if params.get("EventLocationName"):
            place_name = params["EventLocationName"]
        if params.get("EventPreliminaryMagnitude"):
            magnitude = self._safe_float(params["EventPreliminaryMagnitude"])
        if params.get("EventPreliminaryMagnitudeType"):
            mag_type = params["EventPreliminaryMagnitudeType"]
        if params.get("EventDepth"):
            d = re.search(r"([\d.]+)", params["EventDepth"])
            if d:
                depth = self._safe_float(d.group(1))
        latlon = params.get("EventLatLon", "")
        if latlon:
            m = re.match(r"([-\d.]+)\s*,\s*([-\d.]+)", latlon)
            if m:
                lat = self._safe_float(m.group(1))
                lon = self._safe_float(m.group(2))
        return place_name, magnitude, depth, lat, lon, mag_type

    def _apply_legacy_area_parameters(
        self,
        info: ET.Element,
        *,
        place_name: str,
        magnitude: float,
        depth: float,
        lat: float,
        lon: float,
        mag_type: str,
    ) -> tuple:
        """从 area/parameter 旧式结构补充震情字段。"""
        for area in info:
            if not area.tag.endswith("area"):
                continue
            desc = self._cap_text(area, "areaDesc")
            if desc and not place_name:
                place_name = desc
            for param in area:
                if not param.tag.endswith("parameter"):
                    continue
                name = self._cap_text(param, "valueName").lower()
                val = self._cap_text(param, "value")
                if "magnitude" in name and val and not magnitude:
                    m = re.search(r"([\d.]+)", val)
                    if m:
                        magnitude = self._safe_float(m.group(1))
                    if "type" in name and not mag_type:
                        mag_type = val
                if "depth" in name and val and not depth:
                    d = re.search(r"([\d.]+)", val)
                    if d:
                        depth = self._safe_float(d.group(1))
                if name in ("latitude", "lat") and val and not lat:
                    lat = self._safe_float(val)
                if name in ("longitude", "lon") and val and not lon:
                    lon = self._safe_float(val)
        return place_name, magnitude, depth, lat, lon, mag_type

    def _fallback_from_description(
        self,
        description: str,
        *,
        magnitude: float,
        lat: float,
        lon: float,
        mag_type: str,
    ) -> tuple:
        """从 description 文本正则回退提取震级与坐标。"""
        if not description:
            return magnitude, lat, lon, mag_type
        if not magnitude:
            m = re.search(r"magnitude\s+([\d.]+)", description, re.I)
            if m:
                magnitude = self._safe_float(m.group(1))
        if not mag_type:
            mt = re.search(r"\(([A-Za-z]+)\)", description)
            if mt:
                mag_type = mt.group(1)
        if not lat or not lon:
            ll = re.search(r"Lat:\s*([-\d.]+),\s*Lon:\s*([-\d.]+)", description, re.I)
            if ll:
                lat = self._safe_float(ll.group(1))
                lon = self._safe_float(ll.group(2))
        return magnitude, lat, lon, mag_type

    def _parse_alert(self, alert: ET.Element) -> Optional[Dict[str, Any]]:
        """将 CAP alert 节点解析为标准化海啸/地震事件字典。"""
        infos = self._cap_info_list(alert)
        if not infos:
            return None
        info = infos[0]
        headline = self._cap_text(info, "headline")
        event = self._cap_text(info, "event")
        description = self._cap_text(info, "description")
        severity = self._cap_text(info, "severity")
        certainty = self._cap_text(info, "certainty")
        urgency = self._cap_text(info, "urgency")
        onset = self._cap_text(info, "onset")
        expires = self._cap_text(info, "expires")
        sender_name = self._cap_text(alert, "senderName") or self._cap_text(info, "senderName")
        web = self._cap_text(info, "web") or self._cap_text(alert, "web")

        place_name = ""
        magnitude = 0.0
        depth = 0.0
        lat = lon = 0.0
        mag_type = ""

        cap_params = self._cap_parameters(info)
        place_name, magnitude, depth, lat, lon, mag_type = self._apply_cap_parameters(
            cap_params,
            place_name=place_name,
            magnitude=magnitude,
            depth=depth,
            lat=lat,
            lon=lon,
            mag_type=mag_type,
        )
        place_name, magnitude, depth, lat, lon, mag_type = self._apply_legacy_area_parameters(
            info,
            place_name=place_name,
            magnitude=magnitude,
            depth=depth,
            lat=lat,
            lon=lon,
            mag_type=mag_type,
        )
        magnitude, lat, lon, mag_type = self._fallback_from_description(
            description,
            magnitude=magnitude,
            lat=lat,
            lon=lon,
            mag_type=mag_type,
        )

        if not place_name:
            for area in info:
                if area.tag.endswith("area"):
                    desc = self._cap_text(area, "areaDesc")
                    if desc:
                        place_name = desc
                        break
        if not place_name:
            place_name = event or headline or "太平洋海啸预警"
        if not place_name:
            return None

        origin_time = cap_params.get("EventOriginTime", "")
        shock_time = ""
        if origin_time:
            shock_time = timezone_utils.utc_to_display(origin_time) if "T" in origin_time else origin_time
        elif onset:
            shock_time = timezone_utils.utc_to_display(onset) if "T" in onset else onset

        identifier = self._cap_text(alert, "identifier") or headline[:80]
        return {
            "type": "report",
            "source_type": "ptwc",
            "place_name": place_name,
            "shock_time": shock_time,
            "magnitude": round(magnitude, 1) if magnitude else 0.0,
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "organization": self.get_organization_name(),
            "event_id": identifier,
            "headline": headline,
            "event": event,
            "severity": severity,
            "description": description,
            "certainty": certainty,
            "urgency": urgency,
            "onset": onset,
            "expires": expires,
            "web": web,
            "senderName": sender_name,
            "magnitudeType": mag_type,
            "raw_data": {"headline": headline, "identifier": identifier},
        }

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """安全转换为浮点数，失败时返回默认值。"""
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（PTWC 默认为速报）。"""
        return data.get("type", "report")

    def get_organization_name(self) -> str:
        """返回 PTWC 机构显示名称。"""
        return "太平洋海啸预警中心 (PTWC)"
