#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wolfx WebSocket 适配器（ws-api.wolfx.jp/all_eew、cwa_eew）。

除 CWA 走独立 cwa_eew 外，其余 EEW / 列表速报均经 all_eew 收发。
字段约定见 https://api.wolfx.jp/ 各 JSON 表。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .base_adapter import BaseAdapter

from config import Config, WOLFX_CENC_EQLIST_URL, WOLFX_JMA_EQLIST_URL
from utils.logger import get_logger
from utils import timezone_utils
from utils.jma_eew_special import classify_jma_eew_special, intensity_valid

logger = get_logger()

# Wolfx 顶层 JSON type（小写） -> 本程序 source_type
WOLFX_TYPE_MAP: Dict[str, str] = {
    "jma_eew": "wolfx_jma_eew",
    "sc_eew": "wolfx_sc_eew",
    "fj_eew": "wolfx_fj_eew",
    "cenc_eew": "wolfx_cenc_eew",
    "cq_eew": "wolfx_cq_eew",
    "cwa_eew": "wolfx_cwa_eew",
    "cenc_eqlist": "wolfx_cenc",
    "jma_eqlist": "wolfx_jma_eqlist",
}

WOLFX_REPORT_TYPES = frozenset({"wolfx_cenc", "wolfx_jma_eqlist"})

# source_type -> 消息配置解析开关字段名（与设置页 Wolfx 区块一致）
# wolfx_cwa_eew 由 WOLFX_CWA_EEW_URL 连接开关控制，不复用 Fan Studio 的 fanstudio_parse_*
WOLFX_PARSE_FLAG: Dict[str, str] = {
    "wolfx_jma_eew": "ali_all_parse_nied",
    "wolfx_sc_eew": "ali_all_parse_early_est",
    "wolfx_fj_eew": "ali_all_parse_jma_volcano",
    "wolfx_cenc_eew": "ali_all_parse_bmkg",
    "wolfx_cq_eew": "ali_all_parse_cq_eew",
}

ORG_BY_SOURCE: Dict[str, str] = {
    # 各 Wolfx 子源对应的机构显示名称
    "wolfx_jma_eew": "日本气象厅（Wolfx）",
    "wolfx_sc_eew": "四川省地震局（Wolfx）",
    "wolfx_fj_eew": "福建省地震局（Wolfx）",
    "wolfx_cenc_eew": "中国地震台网（Wolfx）",
    "wolfx_cq_eew": "重庆市地震局（Wolfx）",
    "wolfx_cwa_eew": "台湾中央气象署（Wolfx）",
    "wolfx_cenc": "中国地震台网中心（Wolfx）",
    "wolfx_jma_eqlist": "日本气象厅地震情报（Wolfx）",
}


def _to_float(value: Any, default: float = 0.0) -> float:
    """安全转换为浮点数。"""
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


def _infer_jma_warn_area_type(data: Dict[str, Any]) -> str:
    """
    Wolfx jma_eew：区域发报类型「予報」「警報」。
    优先取 WarnArea[].Type；列表为空时从 Title（緊急地震速報（予報））或 isWarn 推断。
    """
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
    if data.get("isWarn") is True:
        return "警報"
    if data.get("isWarn") is False:
        return "予報"
    return ""


def _extract_warn_areas(data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """JMA 预报区列表（WarnArea.Chiiki / Shindo1 / Shindo2 / Type / Arrive 等），供 alert_controller 白字提示等使用。"""
    wa = data.get("WarnArea")
    rows: List[Dict[str, Any]] = []

    def _row_from_wa_item(item: Dict[str, Any]) -> Dict[str, Any]:
        """从单个 WarnArea 条目提取预报区字段。"""
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
        rows.append(_row_from_wa_item(wa))
    elif isinstance(wa, list):
        for item in wa:
            if isinstance(item, dict):
                rows.append(_row_from_wa_item(item))
    return rows if rows else None


def _extract_list_entry(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 cenc_eqlist / jma_eqlist 帧中取出最新一条（No1）。"""
    for key in ("No1", "no1", "1"):
        item = data.get(key)
        if isinstance(item, dict):
            return item
    # 兼容 No01 等写法：取编号最小的 NoN
    best: Optional[Tuple[int, Dict[str, Any]]] = None
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        m = re.match(r"^no0*(\d+)$", str(k).strip(), re.IGNORECASE)
        if not m:
            continue
        n = int(m.group(1))
        if best is None or n < best[0]:
            best = (n, v)
    return best[1] if best else None


def _list_fingerprint(data: Dict[str, Any], item: Dict[str, Any]) -> str:
    """列表帧去重指纹：优先顶层/条目 md5，否则用 EventID+时间+震级。"""
    for src in (data, item):
        md5 = str(src.get("md5") or src.get("MD5") or "").strip()
        if md5:
            return md5
    eid = str(item.get("EventID") or item.get("event_id") or "").strip()
    t = str(item.get("time") or item.get("time_full") or "").strip()
    mag = str(item.get("magnitude") or "").strip()
    return f"{eid}|{t}|{mag}"


class WolfxAdapter(BaseAdapter):
    """Wolfx all_eew / cwa_eew 端点解析（列表速报亦经 all_eew）。"""

    def __init__(self, source_name: str, source_url: str):
        """初始化适配器并准备列表速报去重状态。"""
        super().__init__(source_name, source_url)
        self._last_list_fp: Dict[str, str] = {}  # source_type -> fingerprint

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 Wolfx WebSocket JSON 消息，过滤心跳与训练报后返回预警/速报字典。"""
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError, ValueError):
                return None
        if not isinstance(raw_data, dict):
            return None

        wtype = str(raw_data.get("type") or "").strip().lower()
        if wtype in ("heartbeat", "pong", "ping", "initial_all", "update", ""):
            return None  # 心跳与空 type 不解析

        source_type = WOLFX_TYPE_MAP.get(wtype)
        if not source_type:
            logger.debug(f"WolfxAdapter: 未支持的 type={wtype!r}，跳过")
            return None

        mgr = str(getattr(self, "_manager_source_type", "") or "")
        if mgr == "wolfx_cwa_eew":
            if source_type != "wolfx_cwa_eew":
                return None  # CWA 独立连接只收 cwa_eew
        elif mgr == "wolfx_all_eew":
            if source_type == "wolfx_cwa_eew":
                return None  # CWA 仅走独立 cwa_eew，不经 all_eew

        try:
            cfg = Config()
            # 列表速报：沿用设置页勾选（逻辑键仍为原专线 URL，实际走 all_eew）
            if source_type == "wolfx_cenc" and not bool(
                cfg.enabled_sources.get(WOLFX_CENC_EQLIST_URL, False)
            ):
                return None
            if source_type == "wolfx_jma_eqlist" and not bool(
                cfg.enabled_sources.get(WOLFX_JMA_EQLIST_URL, False)
            ):
                return None
            mc = cfg.message_config
            flag = WOLFX_PARSE_FLAG.get(source_type)
            if flag and not bool(getattr(mc, flag, True)):
                return None  # 设置页关闭了该子源解析
        except Exception as e:
            logger.debug(f"WolfxAdapter: 读取解析开关失败，继续解析: {e}")

        if raw_data.get("isTraining") is True or raw_data.get("is_training") is True:
            logger.debug("WolfxAdapter: 训练报 isTraining，跳过")
            return None  # 训练报不展示

        if source_type in WOLFX_REPORT_TYPES:
            return self._build_report_dict(raw_data, source_type)
        return self._build_warning_dict(raw_data, source_type)

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（预警或速报）。"""
        return str(data.get("type") or "warning")

    def _build_report_dict(self, data: Dict[str, Any], source_type: str) -> Optional[Dict[str, Any]]:
        """将 Wolfx 列表速报（No1）映射为标准化 report 字典，并用指纹去重。"""
        item = _extract_list_entry(data)
        if not item:
            logger.debug(f"WolfxAdapter: {source_type} 无 No1 条目，跳过")
            return None

        fp = _list_fingerprint(data, item)
        if self._last_list_fp.get(source_type) == fp:
            logger.debug(f"WolfxAdapter: {source_type} 列表未变化（{fp[:16]}…），跳过")
            return None
        self._last_list_fp[source_type] = fp

        place_name = str(
            item.get("location") or item.get("placeName") or item.get("place_name") or ""
        ).strip()
        mag = _to_float(item.get("magnitude"), 0.0)
        lat = _to_float(item.get("latitude"), 0.0)
        lon = _to_float(item.get("longitude"), 0.0)
        # 上游缺失或不合法时不捏造 10km；0 保留为极浅
        depth_raw = item.get("depth")
        depth: Optional[float] = None
        if depth_raw is not None and str(depth_raw).strip() != "":
            d = _to_float(depth_raw, -1.0)
            if d >= 0:
                depth = d

        shock_raw = str(
            item.get("time_full") or item.get("time") or item.get("ReportTime") or ""
        ).strip()
        if shock_raw:
            if source_type == "wolfx_jma_eqlist":
                shock_time = timezone_utils.jst_to_display(shock_raw)
            else:
                shock_time = timezone_utils.cst_to_display(shock_raw)
        else:
            shock_time = ""

        event_id = str(item.get("EventID") or item.get("event_id") or "").strip()
        if not event_id:
            event_id = fp

        result: Dict[str, Any] = {
            "type": "report",
            "source_type": source_type,
            "magnitude": mag,
            "latitude": lat,
            "longitude": lon,
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": ORG_BY_SOURCE.get(source_type, "地震信息"),
            "event_id": event_id,
            "raw_data": dict(item),
            "fanstudio": False,
            "whews": False,
        }
        if depth is not None:
            result["depth"] = depth

        if source_type == "wolfx_cenc":
            itype = str(item.get("type") or "").strip().lower()
            if itype == "reviewed":
                result["info_type"] = "正式测定"
            elif itype == "automatic":
                result["info_type"] = "自动测定"
            intensity = item.get("intensity")
            if intensity is not None and str(intensity).strip() != "":
                result["intensity"] = intensity
                result["epiIntensity"] = intensity
        elif source_type == "wolfx_jma_eqlist":
            shindo = str(item.get("shindo") or "").strip()
            if shindo:
                result["epiIntensity"] = shindo
                result["intensity"] = shindo
            title = str(item.get("Title") or item.get("title") or "").strip()
            if title:
                result["wolfx_jma_eqlist_title"] = title
            info = str(item.get("info") or "").strip()
            if info:
                result["tsunami_info"] = info

        return result

    def _build_warning_dict(self, data: Dict[str, Any], source_type: str) -> Dict[str, Any]:
        """将 Wolfx 子源原始字段映射为标准化预警字典。"""
        mag = data.get("Magunitude")
        if mag is None:
            mag = data.get("Magnitude") or data.get("magnitude")
        magnitude = _to_float(mag, 0.0)

        place = (
            data.get("HypoCenter")
            or data.get("Hypocenter")
            or data.get("hypocenter")
            or data.get("place_name")
            or ""
        )
        place_name = str(place).strip()
        # JMA：若尚无震央地名，可用预报区 Chiiki 作补充（与 api.wolfx.jp 字段说明一致）
        if not place_name and source_type == "wolfx_jma_eew":
            wa0 = data.get("WarnArea")
            if isinstance(wa0, dict):
                chiiki = wa0.get("Chiiki") or wa0.get("chiiki")
                if chiiki:
                    place_name = str(chiiki).strip()
            elif isinstance(wa0, list) and wa0:
                first = wa0[0]
                if isinstance(first, dict):
                    chiiki = first.get("Chiiki") or first.get("chiiki")
                    if chiiki:
                        place_name = str(chiiki).strip()

        lat = _to_float(data.get("Latitude") or data.get("latitude"), 0.0)
        lon = _to_float(data.get("Longitude") or data.get("longitude"), 0.0)

        depth_raw = data.get("Depth")
        if depth_raw is None:
            depth_raw = data.get("depth")
        depth_f: Optional[float] = None
        if depth_raw is not None and str(depth_raw).strip() != "":
            d = _to_float(depth_raw, -1.0)
            if d >= 0:
                depth_f = d

        # JMA：发震时间 OriginTime（UTC+9）；其余子源为 UTC+8（与 Wolfx API 说明一致）→ 统一为 GUI 显示时区
        shock_time = str(
            data.get("OriginTime") or data.get("origin_time") or data.get("ReportTime") or ""
        ).strip()
        if shock_time:
            if source_type == "wolfx_jma_eew":
                shock_time = timezone_utils.jst_to_display(shock_time)
            else:
                shock_time = timezone_utils.cst_to_display(shock_time)

        event_id = str(data.get("EventID") or data.get("event_id") or data.get("ID") or "").strip()
        if not event_id and shock_time:
            event_id = f"{source_type}_{shock_time}"

        updates_raw = data.get("ReportNum")
        if updates_raw is None:
            updates_raw = data.get("Serial") or data.get("updates")
        updates_i: Optional[int] = None
        if updates_raw is not None:
            try:
                u = int(updates_raw)
                if u > 0:
                    updates_i = u
            except (TypeError, ValueError):
                updates_i = None

        # MaxIntensity：日台报文中的「最大震度」，与其它源的震中烈度标量共用 epiIntensity 键供下游展示
        epi = data.get("MaxIntensity")
        if epi is None:
            epi = data.get("maxIntensity") or data.get("epiIntensity")

        final = bool(data.get("isFinal") or data.get("final"))
        cancel = bool(data.get("isCancel") or data.get("cancel"))

        warn_area_type = ""
        if source_type == "wolfx_jma_eew":
            warn_area_type = _infer_jma_warn_area_type(data)
        else:
            wa = data.get("WarnArea")
            if isinstance(wa, dict):
                warn_area_type = str(wa.get("Type") or wa.get("type") or "").strip()
            elif isinstance(wa, list) and wa:
                w0 = wa[0]
                if isinstance(w0, dict):
                    warn_area_type = str(w0.get("Type") or w0.get("type") or "").strip()

        warn_rows = _extract_warn_areas(data)

        issue_src = ""
        issue_status = ""
        issue = data.get("Issue")
        if isinstance(issue, dict):
            issue_src = str(issue.get("Source") or issue.get("source") or "").strip()
            issue_status = str(issue.get("Status") or issue.get("status") or "").strip()

        # JMA 特殊手法：PLUM / Level / IPF单点 / 深発（无效字段置空，地名前缀）
        jma_method = ""
        jma_omit_depth = False
        if source_type == "wolfx_jma_eew":
            special = classify_jma_eew_special(data)
            jma_method = special["method"]
            if special["is_plum"] or special["is_level"]:
                # PLUM：M1.0/深10km 为假设值；Level：仅有预估震度
                magnitude = 0.0
                jma_omit_depth = True
            elif special["is_ipf1"]:
                # IPF 单点：仅震级可信，深度不可靠
                jma_omit_depth = True
            if special["is_deep"] and not intensity_valid(epi):
                # 深层 150km+：常规法不给预估震度（PLUM 已给出则保留）
                epi = None
            if jma_method and place_name and not place_name.startswith(f"（{jma_method}）"):
                place_name = f"（{jma_method}）{place_name}"
            if jma_omit_depth:
                depth_f = None

        result: Dict[str, Any] = {
            "type": "warning",
            "source_type": source_type,
            "magnitude": magnitude,
            "latitude": lat,
            "longitude": lon,
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": ORG_BY_SOURCE.get(source_type, "地震预警"),
            "event_id": event_id,
            "updates": updates_i,
            "raw_data": dict(data),
            "final": final,
            "cancel": cancel,
            "fanstudio": False,
            "whews": False,
        }
        if depth_f is not None:
            result["depth"] = depth_f
        if jma_method:
            result["jma_method"] = jma_method
        if jma_omit_depth:
            result["jma_omit_depth"] = True
        if epi is not None and intensity_valid(epi):
            result["epiIntensity"] = epi
        if warn_area_type:
            result["warn_area_type"] = warn_area_type
        if warn_rows:
            result["wolfx_warn_areas"] = warn_rows
        if issue_src:
            result["wolfx_issue_source"] = issue_src
        if issue_status:
            result["wolfx_issue_status"] = issue_status

        if source_type == "wolfx_jma_eew":
            ct = str(data.get("CodeType") or data.get("codeType") or "").strip()
            if ct:
                result["wolfx_jma_code_type"] = ct
            title_j = str(data.get("Title") or data.get("title") or "").strip()
            if title_j:
                result["wolfx_jma_title"] = title_j
            acc = data.get("Accuracy")
            if isinstance(acc, dict):
                ae = str(acc.get("Epicenter") or acc.get("epicenter") or "").strip()
                ad = str(acc.get("Depth") or acc.get("depth") or "").strip()
                am = str(acc.get("Magnitude") or acc.get("magnitude") or "").strip()
                if ae:
                    result["wolfx_jma_accuracy_epicenter"] = ae
                if ad:
                    result["wolfx_jma_accuracy_depth"] = ad
                if am:
                    result["wolfx_jma_accuracy_magnitude"] = am
            mic = data.get("MaxIntChange")
            if isinstance(mic, dict):
                m_s = str(mic.get("String") or mic.get("string") or "").strip()
                m_r = str(mic.get("Reason") or mic.get("reason") or "").strip()
                if m_s or m_r:
                    result["wolfx_jma_max_int_change"] = {"string": m_s, "reason": m_r}

        return result
