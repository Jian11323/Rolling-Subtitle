#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EQSC（equake.top）数据源适配器。

WebSocket：wss://equake.top:50023/
HTTP：https://equake.top/<scope>.json（需 AccessToken）
文档：https://equake.top/apidocs

作为全局辅助数据源（非主提供者），可与 Fan Studio / WeJet 及 Jian Project 等并存。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import requests

from .base_adapter import BaseAdapter
from utils import timezone_utils
from utils.eqsc_credentials import EQSC_BASE_URL, eqsc_auth_headers
from utils.logger import get_logger

logger = get_logger()


def _stable_event_id(prefix: str, fingerprint: str) -> str:
    """跨进程稳定的短事件 ID（sha256 前 16 位十六进制）。"""
    digest = hashlib.sha256(
        (fingerprint or "").encode("utf-8", errors="replace")
    ).hexdigest()[:16]
    return f"{prefix}_{digest}"

# WS/API type -> 本程序 source_type
EQSC_TYPE_MAP: Dict[str, str] = {
    "jma_eew": "eqsc_jma_eew",
    "jma_report": "eqsc_jma_report",
    "jma_tsunami": "eqsc_jma_tsunami",
    "eqlistCENC": "eqsc_cenc",
    "listIntensityReportCENC": "eqsc_cenc_ir",
    "intensityReportCENC": "eqsc_cenc_ir",
    "eqlistCWA": "eqsc_cwa",
    "eqlistHKO": "eqsc_hko",
    "eqlistUSGS": "eqsc_usgs",
    "eqlistEMSC": "eqsc_emsc",
    # 带 level 的 HTTP 路径
    "eqlistUSGS1": "eqsc_usgs",
    "eqlistUSGS2": "eqsc_usgs",
    "eqlistUSGS3": "eqsc_usgs",
    "eqlistUSGS4": "eqsc_usgs",
    "eqlistEMSC1": "eqsc_emsc",
    "eqlistEMSC2": "eqsc_emsc",
    "eqlistEMSC3": "eqsc_emsc",
    "eqlistEMSC4": "eqsc_emsc",
    "typhoonNMC": "eqsc_typhoon",
    "volcanoJMA": "eqsc_volcano",
}

EQSC_WARNING_TYPES = frozenset({"eqsc_jma_eew"})
EQSC_DIRECT_SOURCE_TYPES = frozenset(EQSC_TYPE_MAP.values())

# source_type -> MessageConfig 解析开关
EQSC_PARSE_FLAG: Dict[str, str] = {
    "eqsc_jma_eew": "eqsc_parse_jma_eew",
    "eqsc_jma_report": "eqsc_parse_jma_report",
    "eqsc_jma_tsunami": "eqsc_parse_jma_tsunami",
    "eqsc_cenc": "eqsc_parse_cenc",
    "eqsc_cenc_ir": "eqsc_parse_cenc_ir",
    "eqsc_cwa": "eqsc_parse_cwa",
    "eqsc_hko": "eqsc_parse_hko",
    "eqsc_usgs": "eqsc_parse_usgs",
    "eqsc_emsc": "eqsc_parse_emsc",
    "eqsc_typhoon": "eqsc_parse_typhoon",
    "eqsc_volcano": "eqsc_parse_volcano",
}

ORG_BY_SOURCE: Dict[str, str] = {
    "eqsc_jma_eew": "日本气象厅（EQSC）",
    "eqsc_jma_report": "日本气象厅地震情报（EQSC）",
    "eqsc_jma_tsunami": "日本气象厅海啸情报（EQSC）",
    "eqsc_cenc": "中国地震台网中心（EQSC）",
    "eqsc_cenc_ir": "中国地震台网中心烈度速报（EQSC）",
    "eqsc_cwa": "台湾中央气象署（EQSC）",
    "eqsc_hko": "香港天文台（EQSC）",
    "eqsc_usgs": "美国地质调查局（EQSC）",
    "eqsc_emsc": "欧洲地中海地震中心（EQSC）",
    "eqsc_typhoon": "中央气象台台风（EQSC）",
    "eqsc_volcano": "日本气象厅火山（EQSC）",
}

_TSUNAMI_GRADE_MAP = {
    "Minor": "若干的海面变动",
    "Watch": "海啸注意报",
    "Warning": "海啸警报",
    "MajorWarning": "大海啸警报",
}


def _to_float(value: Any, default: float = 0.0) -> float:
    """安全转浮点。"""
    try:
        if value is None or value == "":
            return default
        s = str(value).strip().lower().replace("km", "").strip()
        m = re.match(r"^([-+]?\d+(?:\.\d+)?)", s)
        if m:
            return float(m.group(1))
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_depth(*candidates: Any) -> Optional[float]:
    """解析深度：上游缺失或不合法则返回 None（勿默认 10km）；0 表示极浅，保留。"""
    for value in candidates:
        if value is None or value == "":
            continue
        d = _to_float(value, -1.0)
        if d >= 0:
            return d
    return None


def _to_bool(value: Any) -> bool:
    """宽松布尔解析。"""
    if isinstance(value, bool):
        return value
    s = str(value or "").strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _extract_list_entry(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 No1 / No_1 / 列表首条提取最新条目。"""
    for key in ("No1", "No_1", "no1"):
        item = data.get(key)
        if isinstance(item, dict):
            return item
    # 按 NoN 数字排序取最小编号
    nos: List[Tuple[int, Dict[str, Any]]] = []
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        m = re.match(r"^No_?(\d+)$", str(k), re.I)
        if m:
            nos.append((int(m.group(1)), v))
    if nos:
        nos.sort(key=lambda x: x[0])
        return nos[0][1]
    if isinstance(data.get("data"), dict):
        return _extract_list_entry(data["data"])
    return None


def _list_fingerprint(item: Dict[str, Any]) -> str:
    """列表条目去重指纹。"""
    parts = [
        str(item.get("eventID") or item.get("eventId") or item.get("id") or ""),
        str(item.get("shockTime") or item.get("magnitude") or ""),
        str(item.get("reportTime") or item.get("updatedTime") or ""),
        str(item.get("placeName") or item.get("place") or item.get("location") or ""),
    ]
    return "|".join(parts)


def _infer_jma_warn_area_type(data: Dict[str, Any]) -> str:
    """JMA EEW 预报/警报类型。"""
    wa = data.get("WarnArea")
    if isinstance(wa, dict):
        t = str(wa.get("Type") or wa.get("type") or "").strip()
        if t:
            return t
    elif isinstance(wa, list):
        for item in wa:
            if isinstance(item, dict):
                t = str(item.get("Type") or item.get("type") or "").strip()
                if t:
                    return t
    title = str(data.get("Title") or "").strip()
    m = re.search(r"[（(](警報|予報)[）)]", title)
    if m:
        return m.group(1)
    if _to_bool(data.get("isWarn")):
        return "警報"
    return "予報" if data.get("isWarn") is False or str(data.get("isWarn")).lower() == "false" else ""


def _extract_warn_areas(data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """提取 JMA 预报区列表。"""
    wa = data.get("WarnArea")
    rows: List[Dict[str, Any]] = []

    def _row(item: Dict[str, Any]) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "chiiki": item.get("Chiiki") or item.get("chiiki"),
            "shindo1": item.get("Shindo1") or item.get("shindo1"),
            "shindo2": item.get("Shindo2") or item.get("shindo2"),
            "time": item.get("Time") or item.get("time"),
            "arrive": item.get("Arrive") if "Arrive" in item else item.get("arrive"),
        }
        wt = item.get("Type") if "Type" in item else item.get("type")
        if wt is not None and str(wt).strip():
            row["warn_type"] = str(wt).strip()
        return row

    if isinstance(wa, dict):
        rows.append(_row(wa))
    elif isinstance(wa, list):
        for item in wa:
            if isinstance(item, dict):
                rows.append(_row(item))
    return rows or None


class EqscAdapter(BaseAdapter):
    """EQSC HTTP（主）/ WebSocket（保留解析）统一适配器。"""

    def __init__(
        self,
        source_name: str = "eqsc",
        source_url: str = "",
        http_scope: Optional[str] = None,
    ):
        """初始化；http_scope 为 HTTP 轮询时对应的 API 类型名。"""
        super().__init__(source_name, source_url or EQSC_BASE_URL)
        self._eqsc_http_scope = (http_scope or "").strip()
        self._last_list_fp: Dict[str, str] = {}
        self._last_event_key: Dict[str, str] = {}
        self.fetch_timeout = 20

    @property
    def fetch_headers(self) -> Dict[str, str]:
        """每次轮询动态附带 AccessToken。"""
        try:
            from config import Config

            login = (getattr(Config().ws_config, "eqsc_login_token", "") or "").strip()
        except Exception:
            login = ""
        if not login:
            return {}
        ok, headers, msg = eqsc_auth_headers(login)
        if not ok:
            logger.debug(f"[EQSC] 获取鉴权头失败: {msg}")
            return {}
        return headers

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 EQSC WebSocket 帧或 HTTP JSON。"""
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError, ValueError):
                return None
        if not isinstance(raw_data, dict):
            return None

        # HTTP 轮询：响应体无 type，用构造时注入的 scope
        if self._eqsc_http_scope and not str(raw_data.get("type") or "").strip():
            return self._parse_scoped_payload(self._eqsc_http_scope, raw_data)

        msg_type = str(raw_data.get("type") or "").strip()
        low = msg_type.lower()

        # 控制类消息由 WebSocketManager 处理
        if low in (
            "heartbeat",
            "request_authentication",
            "respond_authentication",
            "authentication_result",
            "request_data",
            "disconnect_reason",
            "ping",
            "pong",
        ):
            return None

        payload = raw_data
        scope = msg_type
        if low == "respond_data":
            data_field = raw_data.get("data")
            if isinstance(data_field, dict):
                inner_type = str(data_field.get("type") or data_field.get("scope") or "").strip()
                if inner_type and inner_type in EQSC_TYPE_MAP:
                    scope = inner_type
                    payload = data_field.get("data") if isinstance(data_field.get("data"), dict) else data_field
                elif any(
                    k in data_field
                    for k in ("EventID", "Title", "No1", "typhoon", "volcanoes", "areas", "Control")
                ):
                    payload = data_field
                    scope = str(raw_data.get("scope") or msg_type or "").strip()
                else:
                    payload = data_field
            scope = str(scope or raw_data.get("scope") or "").strip()

        if not scope or scope not in EQSC_TYPE_MAP:
            scope = self._infer_scope(payload if isinstance(payload, dict) else raw_data)
        if not scope:
            return None
        if not isinstance(payload, dict):
            return None
        return self._parse_scoped_payload(scope, payload)

    def _parse_scoped_payload(self, scope: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """按 scope 分发到各解析器。"""
        source_type = EQSC_TYPE_MAP.get(scope)
        if not source_type:
            base = re.sub(r"\d+$", "", scope)
            source_type = EQSC_TYPE_MAP.get(base)
        if not source_type:
            logger.debug(f"[EQSC] 未知类型跳过: {scope}")
            return None

        if not self._is_parse_enabled(source_type):
            return None

        if _to_bool(payload.get("isTraining")) or _to_bool(payload.get("is_training")):
            logger.debug("[EQSC] 训练报跳过")
            return None

        if source_type == "eqsc_jma_eew":
            return self._parse_jma_eew(payload, source_type)
        if source_type == "eqsc_jma_report":
            return self._parse_jma_report(payload, source_type)
        if source_type == "eqsc_jma_tsunami":
            return self._parse_jma_tsunami(payload, source_type)
        if source_type == "eqsc_cenc_ir":
            result = self._parse_cenc_ir(payload, source_type, scope)
            # HTTP 列表：必须补拉详情；失败则丢弃薄事件并允许下次重试
            if (
                result
                and result.get("eqsc_need_intensity_detail")
                and result.get("event_id")
            ):
                try:
                    from config import Config

                    login = (getattr(Config().ws_config, "eqsc_login_token", "") or "").strip()
                except Exception:
                    login = ""
                if login:
                    detail = self.fetch_intensity_detail(str(result["event_id"]), login)
                    if detail:
                        return detail
                # 详情失败：清列表指纹以便后续轮询重试，不展示 lat/lon=0 的摘要
                self._last_list_fp.pop(f"{source_type}_list", None)
                logger.debug(
                    f"[EQSC] CENC IR 详情拉取失败，已丢弃列表摘要 event_id={result.get('event_id')}"
                )
                return None
            return result
        if source_type == "eqsc_typhoon":
            return self._parse_typhoon(payload, source_type)
        if source_type == "eqsc_volcano":
            return self._parse_volcano(payload, source_type)
        return self._parse_eqlist(payload, source_type)

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """返回消息类型。"""
        return str(data.get("type") or "report")

    def fetch_intensity_detail(
        self,
        event_id: str,
        login_key: str,
        timeout: float = 12.0,
    ) -> Optional[Dict[str, Any]]:
        """HTTP 拉取 CENC 烈度速报详情。"""
        eid = str(event_id or "").strip()
        if not eid:
            return None
        ok, headers, msg = eqsc_auth_headers(login_key)
        if not ok:
            logger.warning(f"[EQSC] 烈度详情鉴权失败: {msg}")
            return None
        try:
            url = f"{EQSC_BASE_URL}/intensityReportCENC.json"
            resp = requests.get(url, params={"id": eid}, headers=headers, timeout=timeout)
            resp.raise_for_status()
            body = resp.json()
            if not isinstance(body, dict):
                return None
            return self._parse_scoped_payload("intensityReportCENC", body)
        except Exception as e:
            logger.warning(f"[EQSC] 拉取烈度详情失败 id={eid}: {e}")
            return None

    def _is_parse_enabled(self, source_type: str) -> bool:
        """读取 MessageConfig 解析开关。"""
        try:
            from config import Config

            flag = EQSC_PARSE_FLAG.get(source_type)
            if not flag:
                return True
            return bool(getattr(Config().message_config, flag, True))
        except Exception as e:
            logger.debug(f"[EQSC] 读取解析开关失败: {e}")
            return True

    def _infer_scope(self, data: Dict[str, Any]) -> str:
        """根据字段结构推断 scope。"""
        if not isinstance(data, dict):
            return ""
        if "Magunitude" in data or ("MaxIntensity" in data and "EventID" in data and "Hypocenter" in data):
            return "jma_eew"
        if "Control" in data and "Head" in data:
            return "jma_report"
        if isinstance(data.get("areas"), list) and data.get("areas"):
            first = data["areas"][0] if data["areas"] else None
            if isinstance(first, dict) and "grade" in first:
                return "jma_tsunami"
        if "eventInfo" in data and "intensityReport" in data:
            return "intensityReportCENC"
        if "typhoon" in data:
            return "typhoonNMC"
        if "volcanoes" in data:
            return "volcanoJMA"
        item = _extract_list_entry(data)
        if item:
            if "hypoCenterName" in item:
                return "eqlistHKO"
            if "areaIntensity" in item or str(item.get("eventID") or "").startswith("CWA"):
                return "eqlistCWA"
            if "author" in item or str(item.get("eventID") or "").startswith("EMSC"):
                return "eqlistEMSC"
            if "magnitudeType" in item or str(item.get("eventID") or "").startswith("USGS"):
                return "eqlistUSGS"
            if "url" in item and "intensity" in str(item.get("url") or "").lower():
                return "listIntensityReportCENC"
            if "location" in item or "shockTime" in item:
                return "eqlistCENC"
        return ""

    def _base_result(self, source_type: str, **kwargs: Any) -> Dict[str, Any]:
        """构造带 eqsc 标记的标准结果。"""
        result: Dict[str, Any] = {
            "source_type": source_type,
            "organization": ORG_BY_SOURCE.get(source_type, "EQSC"),
            "fanstudio": False,
            "whews": False,
            "eqsc": True,
        }
        result.update(kwargs)
        return result

    def _parse_jma_eew(self, data: Dict[str, Any], source_type: str) -> Optional[Dict[str, Any]]:
        """解析 JMA 紧急地震速报。"""
        if _to_bool(data.get("isCancel")):
            # 取消报仍下发，供下游提示
            pass

        mag = data.get("Magunitude")
        if mag is None:
            mag = data.get("Magnitude") or data.get("magnitude")
        magnitude = _to_float(mag, 0.0)

        place = (
            data.get("Hypocenter")
            or data.get("HypoCenter")
            or data.get("hypocenter")
            or ""
        )
        place_name = str(place).strip()
        if not place_name:
            wa = data.get("WarnArea")
            if isinstance(wa, list) and wa and isinstance(wa[0], dict):
                place_name = str(wa[0].get("Chiiki") or "").strip()

        lat = _to_float(data.get("Latitude") or data.get("latitude"), 0.0)
        lon = _to_float(data.get("Longitude") or data.get("longitude"), 0.0)
        depth = _optional_depth(data.get("Depth"), data.get("depth"))

        shock_raw = str(data.get("OriginTime") or data.get("origin_time") or "").strip()
        shock_time = timezone_utils.jst_to_display(shock_raw) if shock_raw else ""

        event_id = str(data.get("EventID") or data.get("event_id") or "").strip()
        if not event_id and shock_time:
            event_id = f"{source_type}_{shock_time}"

        updates_i = None
        for key in ("Serial", "ReportNum", "updates"):
            if data.get(key) is not None:
                try:
                    u = int(data.get(key))
                    if u > 0:
                        updates_i = u
                        break
                except (TypeError, ValueError):
                    pass

        epi = data.get("MaxIntensity")
        if epi is None:
            epi = data.get("maxIntensity") or data.get("epiIntensity")

        warn_area_type = _infer_jma_warn_area_type(data)
        warn_rows = _extract_warn_areas(data)

        dedup = f"{event_id}|{updates_i}|{magnitude}|{epi}|{data.get('AnnouncedTime')}"
        if self._last_event_key.get(source_type) == dedup:
            return None
        self._last_event_key[source_type] = dedup

        result = self._base_result(
            source_type,
            type="warning",
            magnitude=magnitude,
            latitude=lat,
            longitude=lon,
            place_name=place_name or "未知地区",
            shock_time=shock_time,
            event_id=event_id,
            final=_to_bool(data.get("isFinal")),
            cancel=_to_bool(data.get("isCancel")),
            raw_data=data,
        )
        if depth is not None:
            result["depth"] = depth
        if updates_i is not None:
            result["updates"] = updates_i
        if epi is not None and str(epi).strip() != "":
            result["epiIntensity"] = epi
            result["intensity"] = epi
        if warn_area_type:
            result["warn_area_type"] = warn_area_type
        if warn_rows:
            result["wolfx_warn_areas"] = warn_rows  # 复用白字提示结构
            result["eqsc_warn_areas"] = warn_rows
        # Accuracy
        acc = data.get("Accuracy")
        if isinstance(acc, dict):
            result["accuracy"] = {
                "epicenter": acc.get("Epicenter") or acc.get("epicenter"),
                "depth": acc.get("Depth") or acc.get("depth"),
                "magnitude": acc.get("Magnitude") or acc.get("magnitude"),
            }
        return result

    def _parse_jma_report(self, data: Dict[str, Any], source_type: str) -> Optional[Dict[str, Any]]:
        """解析 JMA 地震情报（Control/Head/Body）。"""
        head = data.get("Head") if isinstance(data.get("Head"), dict) else {}
        body = data.get("Body") if isinstance(data.get("Body"), dict) else {}
        earthquake = body.get("Earthquake") if isinstance(body.get("Earthquake"), dict) else {}
        hypo = earthquake.get("Hypocenter") if isinstance(earthquake.get("Hypocenter"), dict) else {}
        area = hypo.get("Area") if isinstance(hypo.get("Area"), dict) else {}

        place_name = str(
            area.get("Name")
            or hypo.get("Name")
            or head.get("Title")
            or ""
        ).strip()
        # 坐标可能在 Coordinate 字符串中
        lat = _to_float(area.get("Latitude") or hypo.get("Latitude"), 0.0)
        lon = _to_float(area.get("Longitude") or hypo.get("Longitude"), 0.0)
        depth = _optional_depth(
            area.get("Depth"), hypo.get("Depth"), earthquake.get("Depth")
        )
        mag_raw = earthquake.get("Magnitude")
        mag_info = earthquake.get("MagnitudeInfo")
        if mag_raw is None and isinstance(mag_info, dict):
            mag_raw = mag_info.get("Magnitude")
        mag = _to_float(mag_raw, 0.0)

        shock_raw = str(
            earthquake.get("OriginTime")
            or head.get("TargetDateTime")
            or head.get("ReportDateTime")
            or ""
        ).strip()
        shock_time = timezone_utils.jst_to_display(shock_raw) if shock_raw else ""

        event_id = str(head.get("EventID") or data.get("EventID") or "").strip()
        title = str(head.get("Title") or (data.get("Control") or {}).get("Title") or "").strip()

        fp = f"{event_id}|{shock_time}|{mag}|{place_name}|{title}"
        if self._last_list_fp.get(source_type) == fp:
            return None
        self._last_list_fp[source_type] = fp

        # 最大震度
        intensity = ""
        intensity_info = body.get("Intensity") if isinstance(body.get("Intensity"), dict) else {}
        observation = (
            intensity_info.get("Observation")
            if isinstance(intensity_info.get("Observation"), dict)
            else {}
        )
        max_int = observation.get("MaxInt") or observation.get("maxInt")
        if max_int is not None:
            intensity = str(max_int).strip()

        result = self._base_result(
            source_type,
            type="report",
            magnitude=mag,
            latitude=lat,
            longitude=lon,
            place_name=place_name or title or "未知地区",
            shock_time=shock_time,
            event_id=event_id or fp,
            raw_data=data,
        )
        if depth is not None:
            result["depth"] = depth
        if intensity:
            result["epiIntensity"] = intensity
            result["intensity"] = intensity
        if title:
            result["eqsc_jma_report_title"] = title
        return result

    def _parse_jma_tsunami(self, data: Dict[str, Any], source_type: str) -> Optional[Dict[str, Any]]:
        """解析 JMA 海啸情报。"""
        areas = data.get("areas") if isinstance(data.get("areas"), list) else []
        if not areas and isinstance(data.get("data"), dict):
            areas = data["data"].get("areas") if isinstance(data["data"].get("areas"), list) else []

        detail = self._build_tsunami_detail(areas)
        fp = detail[:120]
        if self._last_list_fp.get(source_type) == fp:
            return None
        self._last_list_fp[source_type] = fp

        return self._base_result(
            source_type,
            type="report",
            magnitude=0,
            latitude=0,
            longitude=0,
            depth=0,
            place_name=detail or "海啸情报",
            shock_time="",
            is_tsunami=True,
            event_id=f"{_stable_event_id('eqsc_tsunami', fp)}",
            raw_data=data,
        )

    def _build_tsunami_detail(self, areas: list) -> str:
        """拼接海啸区域说明。"""
        if not areas:
            return "海啸情报"
        first_grade = ""
        max_height_desc = None
        region_bits = []
        for a in areas:
            if not isinstance(a, dict):
                continue
            grade = str(a.get("grade") or "").strip()
            if grade and not first_grade:
                first_grade = _TSUNAMI_GRADE_MAP.get(grade, grade)
            mh = a.get("maxHeight") if isinstance(a.get("maxHeight"), dict) else None
            if mh and max_height_desc is None:
                max_height_desc = mh.get("description") or (
                    f"{mh.get('value')}m" if mh.get("value") is not None else None
                )
            name = str(a.get("name") or "").strip()
            if not name:
                continue
            arrival = ""
            fh = a.get("firstHeight") if isinstance(a.get("firstHeight"), dict) else None
            if fh:
                cond = str(fh.get("condition") or "").strip()
                at = str(fh.get("arrivalTime") or "").strip()
                arrival = cond or at
            if arrival:
                region_bits.append(f"{name}({arrival})")
            else:
                region_bits.append(name)
        parts = []
        if first_grade:
            parts.append(first_grade)
        if max_height_desc:
            parts.append(f"预计浪高约{max_height_desc}")
        if region_bits:
            parts.append("、".join(region_bits[:8]))
        return "。".join(parts) if parts else "海啸情报"

    def _parse_eqlist(self, data: Dict[str, Any], source_type: str) -> Optional[Dict[str, Any]]:
        """解析各类历史地震列表（取最新一条）。"""
        item = _extract_list_entry(data)
        if not item:
            # 可能已是单条
            if any(k in data for k in ("eventID", "magnitude", "shockTime", "place", "location")):
                item = data
            else:
                return None

        fp = _list_fingerprint(item)
        if self._last_list_fp.get(source_type) == fp:
            return None
        self._last_list_fp[source_type] = fp

        place_name = str(
            item.get("location")
            or item.get("placeName")
            or item.get("place")
            or item.get("hypoCenterName")
            or ""
        ).strip()
        mag = _to_float(item.get("magnitude"), 0.0)
        lat = _to_float(item.get("latitude"), 0.0)
        lon = _to_float(item.get("longitude"), 0.0)
        depth = _optional_depth(item.get("depth"))

        shock_raw = str(item.get("shockTime") or item.get("time") or "").strip()
        if shock_raw:
            if source_type in ("eqsc_cwa", "eqsc_hko", "eqsc_cenc"):
                shock_time = timezone_utils.cst_to_display(shock_raw)
            elif source_type in ("eqsc_usgs", "eqsc_emsc"):
                # USGS / EMSC 时间按 UTC（ISO/Z 或无时区朴素串）
                shock_time = timezone_utils.utc_to_display(shock_raw)
            else:
                shock_time = self.format_time(shock_raw.replace("/", "-"))
        else:
            shock_time = ""

        event_id = str(item.get("eventID") or item.get("eventId") or fp).strip()

        result = self._base_result(
            source_type,
            type="report",
            magnitude=mag,
            latitude=lat,
            longitude=lon,
            place_name=place_name or "未知地区",
            shock_time=shock_time,
            event_id=event_id,
            raw_data=item,
        )
        if depth is not None:
            result["depth"] = depth

        if source_type == "eqsc_cenc":
            itype = str(item.get("type") or "").strip().lower()
            if itype == "reviewed":
                result["info_type"] = "正式测定"
            elif itype == "automatic":
                result["info_type"] = "自动测定"
            intensity = item.get("intensity")
            if intensity is not None and str(intensity).strip() != "":
                result["intensity"] = intensity
                result["epiIntensity"] = intensity

        return result

    def _parse_cenc_ir(
        self,
        data: Dict[str, Any],
        source_type: str,
        scope: str,
    ) -> Optional[Dict[str, Any]]:
        """解析 CENC 烈度速报列表或详情。"""
        # 详情
        event_info = data.get("eventInfo") if isinstance(data.get("eventInfo"), dict) else None
        if event_info is None and isinstance(data.get("data"), dict):
            inner = data["data"]
            event_info = inner.get("eventInfo") if isinstance(inner.get("eventInfo"), dict) else None
            if event_info:
                data = inner

        if event_info:
            place_name = str(event_info.get("placeName") or "").strip()
            mag = _to_float(event_info.get("magnitude"), 0.0)
            lat = _to_float(event_info.get("latitude"), 0.0)
            lon = _to_float(event_info.get("longitude"), 0.0)
            depth = _optional_depth(event_info.get("depth"))
            shock_raw = str(event_info.get("shockTime") or "").strip()
            # 示例：20251129 06:53:28
            if re.match(r"^\d{8}\s+\d", shock_raw):
                shock_raw = f"{shock_raw[:4]}/{shock_raw[4:6]}/{shock_raw[6:8]} {shock_raw[9:]}"
            shock_time = timezone_utils.cst_to_display(shock_raw) if shock_raw else ""
            event_id = str(event_info.get("eventID") or "").strip()
            ir = data.get("intensityReport") if isinstance(data.get("intensityReport"), dict) else {}
            info_text = str(ir.get("info") or "").strip()
            max_int = ir.get("maxIntensity") or ir.get("MaxIntensity")
            fp = f"{event_id}|{mag}|{max_int}|{info_text[:40]}"
            if self._last_list_fp.get(source_type) == fp:
                return None
            self._last_list_fp[source_type] = fp
            result = self._base_result(
                source_type,
                type="report",
                magnitude=mag,
                latitude=lat,
                longitude=lon,
                place_name=place_name or "未知地区",
                shock_time=shock_time,
                event_id=event_id or fp,
                raw_data=data,
            )
            if depth is not None:
                result["depth"] = depth
            if max_int is not None and str(max_int).strip() != "":
                result["max_intensity"] = max_int
                result["maxIntensity"] = max_int
                result["epiIntensity"] = max_int
            if info_text:
                result["cenc_ir_intensity_info_text"] = info_text
            return result

        # 列表：取 No1，必要时由管理器再拉详情
        item = _extract_list_entry(data)
        if not item:
            return None
        fp = _list_fingerprint(item)
        if self._last_list_fp.get(f"{source_type}_list") == fp:
            return None
        self._last_list_fp[f"{source_type}_list"] = fp

        place_name = str(item.get("placeName") or "").strip()
        mag = _to_float(item.get("magnitude"), 0.0)
        event_id = str(item.get("eventID") or "").strip()
        # 列表 stub 尚无坐标/深度，等详情补全；勿捏造 10km
        result = self._base_result(
            source_type,
            type="report",
            magnitude=mag,
            latitude=0.0,
            longitude=0.0,
            place_name=place_name or "未知地区",
            shock_time="",
            event_id=event_id or fp,
            raw_data=item,
            eqsc_need_intensity_detail=True,
        )
        return result

    def _parse_typhoon(self, data: Dict[str, Any], source_type: str) -> Optional[Dict[str, Any]]:
        """解析 NMC 台风路径（展示活跃台风摘要）。"""
        typhoons = data.get("typhoon") if isinstance(data.get("typhoon"), list) else []
        if not typhoons and isinstance(data.get("data"), dict):
            typhoons = data["data"].get("typhoon") if isinstance(data["data"].get("typhoon"), list) else []
        if not typhoons:
            return None

        active = [t for t in typhoons if isinstance(t, dict) and t.get("isActive")]
        show_list = active or [t for t in typhoons if isinstance(t, dict)][:3]
        if not show_list:
            return None

        bits = []
        for t in show_list[:5]:
            name = str(t.get("nameCN") or t.get("nameEN") or t.get("id") or "").strip()
            tid = str(t.get("id") or "").strip()
            track = t.get("historyTrack") if isinstance(t.get("historyTrack"), list) else []
            latest = track[-1] if track and isinstance(track[-1], dict) else {}
            ttype = str(latest.get("typeNameCN") or latest.get("type") or "").strip()
            label = name
            if tid:
                label = f"{name}({tid})" if name else tid
            if ttype:
                label = f"{label} {ttype}"
            bits.append(label)

        place_name = "；".join(bits) if bits else "台风情报"
        fp = place_name
        if self._last_list_fp.get(source_type) == fp:
            return None
        self._last_list_fp[source_type] = fp

        first = show_list[0]
        track = first.get("historyTrack") if isinstance(first.get("historyTrack"), list) else []
        latest = track[-1] if track and isinstance(track[-1], dict) else {}
        return self._base_result(
            source_type,
            type="weather",
            magnitude=0,
            latitude=_to_float(latest.get("latitude"), 0.0),
            longitude=_to_float(latest.get("longitude"), 0.0),
            depth=0,
            place_name=place_name,
            shock_time=str(latest.get("time") or ""),
            event_id=str(first.get("id") or fp),
            raw_data={"typhoon": show_list},
            is_typhoon=True,
        )

    def _parse_volcano(self, data: Dict[str, Any], source_type: str) -> Optional[Dict[str, Any]]:
        """解析 JMA 活跃火山（挑有警戒等级变化的条目摘要）。"""
        volcanoes = data.get("volcanoes") if isinstance(data.get("volcanoes"), list) else []
        if not volcanoes and isinstance(data.get("data"), dict):
            volcanoes = data["data"].get("volcanoes") if isinstance(data["data"].get("volcanoes"), list) else []
        if not volcanoes:
            return None

        # 优先展示非“留意其为活火山”的条目
        notable = []
        for v in volcanoes:
            if not isinstance(v, dict):
                continue
            type_code = str(v.get("typeCode") or "").strip()
            type_name = str(v.get("typeName") or "").strip()
            info = v.get("volcanoInfo") if isinstance(v.get("volcanoInfo"), dict) else {}
            name = str(info.get("name") or "").strip()
            if not name:
                continue
            # typeCode 11 = 留意活火山，降权
            if type_code and type_code != "11":
                notable.append((name, type_name or type_code))
        show = notable[:5]
        if not show:
            # 无更高警戒时仍提示数量，避免刷屏：仅当指纹变化
            show = []
            for v in volcanoes[:3]:
                if isinstance(v, dict):
                    info = v.get("volcanoInfo") if isinstance(v.get("volcanoInfo"), dict) else {}
                    name = str(info.get("name") or "").strip()
                    if name:
                        show.append((name, str(v.get("typeName") or "").strip()))

        if not show:
            return None

        bits = [f"{n}（{t}）" if t else n for n, t in show]
        place_name = "；".join(bits)
        fp = f"{len(volcanoes)}|{place_name}"
        if self._last_list_fp.get(source_type) == fp:
            return None
        self._last_list_fp[source_type] = fp

        first = show[0]
        first_v = next(
            (
                v
                for v in volcanoes
                if isinstance(v, dict)
                and str((v.get("volcanoInfo") or {}).get("name") or "") == first[0]
            ),
            {},
        )
        info = first_v.get("volcanoInfo") if isinstance(first_v.get("volcanoInfo"), dict) else {}
        return self._base_result(
            source_type,
            type="report",
            magnitude=0,
            latitude=_to_float(info.get("lat"), 0.0),
            longitude=_to_float(info.get("lng"), 0.0),
            depth=0,
            place_name=place_name,
            shock_time="",
            event_id=f"{_stable_event_id('eqsc_volcano', fp)}",
            raw_data={"count": len(volcanoes), "sample": show},
            is_volcano=True,
        )
