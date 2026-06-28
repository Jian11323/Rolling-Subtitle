#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wolfx WebSocket 适配器（ws-api.wolfx.jp/all_eew 与 …/cwa_eew）。

字段约定见 https://api.wolfx.jp/ 各 JSON 表（jma_eew / sc_eew / fj_eew / cenc_eew / cq_eew / cwa_eew）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .base_adapter import BaseAdapter

from config import Config
from utils.logger import get_logger
from utils import timezone_utils

logger = get_logger()

# Wolfx 顶层 JSON type（小写） -> 本程序 source_type
WOLFX_TYPE_MAP: Dict[str, str] = {
    "jma_eew": "wolfx_jma_eew",
    "sc_eew": "wolfx_sc_eew",
    "fj_eew": "wolfx_fj_eew",
    "cenc_eew": "wolfx_cenc_eew",
    "cq_eew": "wolfx_cq_eew",
    "cwa_eew": "wolfx_cwa_eew",
}

# source_type -> 消息配置解析开关字段名（与设置页 Wolfx 区块一致）
WOLFX_PARSE_FLAG: Dict[str, str] = {
    "wolfx_jma_eew": "ali_all_parse_nied",
    "wolfx_sc_eew": "ali_all_parse_early_est",
    "wolfx_fj_eew": "ali_all_parse_jma_volcano",
    "wolfx_cenc_eew": "ali_all_parse_bmkg",
    "wolfx_cq_eew": "ali_all_parse_cq_eew",
    "wolfx_cwa_eew": "fanstudio_parse_cwa_eew",
}

ORG_BY_SOURCE: Dict[str, str] = {
    # 各 Wolfx 子源对应的机构显示名称
    "wolfx_jma_eew": "日本气象厅（Wolfx）",
    "wolfx_sc_eew": "四川省地震局（Wolfx）",
    "wolfx_fj_eew": "福建省地震局（Wolfx）",
    "wolfx_cenc_eew": "中国地震台网（Wolfx）",
    "wolfx_cq_eew": "重庆市地震局（Wolfx）",
    "wolfx_cwa_eew": "台湾中央气象署（Wolfx）",
}


def _to_float(value: Any, default: float = 0.0) -> float:
    """安全转换为浮点数。"""
    try:
        if value is None or value == "":
            return default
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


class WolfxAdapter(BaseAdapter):
    """Wolfx all_eew / cwa_eew 端点解析。"""

    def parse(self, raw_data: Any) -> Optional[Dict[str, Any]]:
        """解析 Wolfx WebSocket JSON 消息，过滤心跳与训练报后返回预警字典。"""
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
                return None  # all_eew 通道不含 CWA

        try:
            cfg = Config()
            mc = cfg.message_config
            flag = WOLFX_PARSE_FLAG.get(source_type)
            if flag and not bool(getattr(mc, flag, True)):
                return None  # 设置页关闭了该子源解析
        except Exception as e:
            logger.debug(f"WolfxAdapter: 读取解析开关失败，继续解析: {e}")

        if raw_data.get("isTraining") is True or raw_data.get("is_training") is True:
            logger.debug("WolfxAdapter: 训练报 isTraining，跳过")
            return None  # 训练报不展示

        return self._build_warning_dict(raw_data, source_type)

    def get_message_type(self, data: Dict[str, Any]) -> str:
        """获取消息类型（Wolfx 默认为预警）。"""
        return str(data.get("type") or "warning")

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
        depth_f = _to_float(depth_raw, 10.0) if depth_raw is not None else 10.0
        if depth_f <= 0:
            depth_f = 10.0

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

        result: Dict[str, Any] = {
            "type": "warning",
            "source_type": source_type,
            "magnitude": magnitude,
            "latitude": lat,
            "longitude": lon,
            "depth": depth_f,
            "place_name": place_name,
            "shock_time": shock_time,
            "organization": ORG_BY_SOURCE.get(source_type, "地震预警"),
            "event_id": event_id,
            "updates": updates_i,
            "raw_data": dict(data),
            "final": final,
            "cancel": cancel,
            "fanstudio": False,
        }
        if epi is not None and str(epi).strip() != "":
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
