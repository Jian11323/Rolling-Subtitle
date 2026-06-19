#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JMA Atom 火山情报适配器（长周期 eqvol_l.xml）"""

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from .base_adapter import BaseAdapter
from utils import timezone_utils

ATOM_NS = "http://www.w3.org/2005/Atom"
NS = {"atom": ATOM_NS}

VOLCANO_KEYWORDS = (
    "火山", "噴火", "降灰", "噴煙", "火山観測報", "降灰予報", "噴煙流向",
    "火山名", "噴火警戒", "火口",
)


def _extract_volcano_name(content: str) -> str:
    if not content:
        return ""
    m = re.search(r"【火山名　([^　】]+)", content)
    if m:
        return m.group(1).strip()
    m = re.search(r"【火山名\s+([^ 】]+)", content)
    if m:
        return m.group(1).strip()
    m = re.search(r"【([^　】]+)　推定噴煙流向報】", content)
    if m:
        return m.group(1).strip()
    m = re.search(r"火　　山：([^ 日]+)", content)
    if m:
        return m.group(1).strip()
    return ""


def _extract_description(content: str) -> str:
    if not content:
        return ""
    raw = content.strip()
    if "現　　象：" in raw:
        return raw.split("現　　象：", 1)[-1].strip()
    if raw.startswith("【") and "】" in raw:
        idx = raw.index("】")
        return raw[idx + 1 :].lstrip("　").strip()
    return raw


class JmaAtomAdapter(BaseAdapter):
    """解析 JMA eqvol_l.xml Atom feed，取最新火山相关条目。"""

    response_format = "bytes"
    fetch_headers = {"User-Agent": "JMAVolcanoFeed/1.0 (Python; feed client)"}

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        if raw_data is None:
            return None
        xml_bytes = raw_data
        if isinstance(raw_data, str):
            xml_bytes = raw_data.encode("utf-8")
        if not isinstance(xml_bytes, (bytes, bytearray)):
            return None
        try:
            entries = self._parse_entries(xml_bytes)
            volcano_entries = self._filter_volcano_only(entries)
            if not volcano_entries:
                return None
            entry = volcano_entries[0]
            return self._entry_to_parsed(entry)
        except ET.ParseError:
            return None

    def _parse_entries(self, xml_bytes: bytes) -> List[Dict[str, Any]]:
        root = ET.fromstring(xml_bytes)
        entries: List[Dict[str, Any]] = []
        for entry_el in root.findall(".//atom:entry", NS):
            def text(elem, tag: str, default: str = "") -> str:
                if elem is None:
                    return default
                child = elem.find(f"atom:{tag}", NS)
                return (child.text or "").strip() if child is not None else default

            title = text(entry_el, "title")
            id_val = text(entry_el, "id")
            updated = text(entry_el, "updated")
            author_el = entry_el.find("atom:author", NS)
            author = ""
            if author_el is not None:
                name_el = author_el.find("atom:name", NS)
                if name_el is not None and name_el.text:
                    author = name_el.text.strip()
            content_el = entry_el.find("atom:content", NS)
            content = ""
            if content_el is not None and content_el.text:
                content = content_el.text.strip()
            entries.append({
                "title": title,
                "id": id_val,
                "updated": updated,
                "author": author,
                "content": content,
            })
        return entries

    def _filter_volcano_only(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for e in entries:
            combined = (e.get("title") or "") + " " + (e.get("content") or "")
            if any(kw in combined for kw in VOLCANO_KEYWORDS):
                result.append(e)
        return result

    def _entry_to_parsed(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        content = entry.get("content") or ""
        updated = (entry.get("updated") or "").strip()
        shock_time = timezone_utils.utc_to_display(updated) if updated else ""
        volcano = _extract_volcano_name(content)
        description = _extract_description(content)
        return {
            "type": "volcano",
            "source_type": "jma_volcano",
            "title": (entry.get("title") or "").strip(),
            "volcano": volcano,
            "description": description,
            "name": (entry.get("author") or "日本气象厅").strip(),
            "shock_time": shock_time,
            "place_name": volcano or (entry.get("title") or "").strip(),
            "organization": self.get_organization_name(),
            "event_id": (entry.get("id") or "").strip(),
            "raw_data": entry,
        }

    def get_message_type(self, data: Dict[str, Any]) -> str:
        return data.get("type", "volcano")
