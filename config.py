#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块 - 优化版
负责加载和管理应用程序配置，支持动态重载和验证
"""

import json
import os
import threading
from typing import Dict, List, Any, Optional, Callable, Tuple
from dataclasses import dataclass
from pathlib import Path

from utils.logger import get_logger

logger = get_logger()

# Fan Studio 域名
FANSTUDIO_DOMAIN = "fanstudio.tech"


def fanstudio_ws_url(path: str) -> str:
    """构建 Fan Studio WebSocket URL。"""
    return f"wss://ws.{FANSTUDIO_DOMAIN}/{path}"


def fanstudio_http_url(path: str) -> str:
    """构建 Fan Studio HTTP API URL。"""
    return f"https://api.{FANSTUDIO_DOMAIN}/{path.lstrip('/')}"


def fanstudio_http_canonical_key(url: str) -> str:
    """返回 Fan Studio HTTP URL 查找键。"""
    return url or ""


FANSTUDIO_ALL_URL = fanstudio_ws_url("all")
FANSTUDIO_ALL_URLS = (FANSTUDIO_ALL_URL,)

# WeJet（WHEWS）：默认 api.beecld.com；国内站 api.2v8.cn（含 CEA，需 App 鉴权）
WHEWS_HOST_PRIMARY = "api.beecld.com"
WHEWS_HOST_BACKUP = "api.2v8.cn"
WHEWS_HOSTS = (WHEWS_HOST_PRIMARY, WHEWS_HOST_BACKUP)
WHEWS_DOMAIN = WHEWS_HOST_PRIMARY  # 兼容旧引用：默认主机域名
WHEWS_CEA_APPLY_URL = "https://api.2v8.cn/apply"  # CEA App 申请页
DATA_PROVIDER_FANSTUDIO = "fanstudio"
DATA_PROVIDER_WHEWS = "whews"
DATA_PROVIDER_JIAN = "jian"
DATA_PROVIDER_OFFICIAL = "official"
DATA_PROVIDERS = (
    DATA_PROVIDER_FANSTUDIO,
    DATA_PROVIDER_WHEWS,
    DATA_PROVIDER_JIAN,
)
WHEWS_MASTER_KEY = "whews://all"  # 稳定持久化键（勿用带 token 的完整 URL）


def normalize_whews_host(value: Any) -> str:
    """规范化无界科技主机名（主站 / 备用）。"""
    v = str(value or "").strip().lower()
    if v in WHEWS_HOSTS:
        return v
    for host in WHEWS_HOSTS:
        if host in v:
            return host
    return WHEWS_HOST_PRIMARY


def whews_ws_url(path: str, host: Any = None, token: str = "") -> str:
    """构建无界科技 WebSocket URL；beecld 可在 URL 携带 token，亦支持建连后首帧鉴权。"""
    import urllib.parse

    h = normalize_whews_host(host)
    base = f"wss://{h}/ws/{path.lstrip('/')}"
    tok = (token or "").strip()
    if tok:
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}token={urllib.parse.quote(tok, safe='')}"
    return base


def is_whews_url(url: str) -> bool:
    """判断是否为无界科技 WebSocket URL（主站或备用）。"""
    low = (url or "").lower()
    return any(h in low for h in WHEWS_HOSTS)


def all_whews_ws_urls() -> List[str]:
    """主站+备用全部已知端点（含 cenc/cea 专用线，便于强制启停）。"""
    urls: List[str] = []
    for host in WHEWS_HOSTS:
        urls.append(whews_ws_url("all", host))
        urls.append(whews_ws_url("cenc", host))
        urls.append(whews_ws_url("cea", host))
        urls.append(whews_ws_url("cea-pr", host))
        urls.append(whews_ws_url("cea_all", host))
    return urls


def _whews_url_path(url: str) -> str:
    """去掉 query/fragment 后的 WHEWS URL 路径（小写、无尾斜杠）。"""
    return (url or "").lower().split("#", 1)[0].split("?", 1)[0].rstrip("/")


def is_whews_all_url(url: str) -> bool:
    """判断是否为无界科技 /ws/all 聚合通道（兼容 URL 携带 token 查询参数）。"""
    path = _whews_url_path(url)
    return is_whews_url(path) and path.endswith("/ws/all")


def is_whews_dedicated_endpoint(url: str) -> bool:
    """已废弃的专用线（仅强制关闭 cenc；cea/cea-pr/cea_all 由 App 鉴权路径单独管理）。"""
    path = _whews_url_path(url)
    if not is_whews_url(path):
        return False
    return path.endswith("/ws/cenc")


def is_whews_cea_endpoint(url: str) -> bool:
    """是否为 WeJet CEA 专用端点（/ws/cea、/ws/cea-pr、/ws/cea_all）。"""
    path = _whews_url_path(url)
    if not is_whews_url(path):
        return False
    return (
        path.endswith("/ws/cea")
        or path.endswith("/ws/cea-pr")
        or path.endswith("/ws/cea_pr")
        or path.endswith("/ws/cea_all")
    )


def is_whews_cea_all_endpoint(url: str) -> bool:
    """是否为 CEA 合并通道 /ws/cea_all（一次鉴权覆盖 CEA + CEA-PR）。"""
    path = _whews_url_path(url)
    return is_whews_url(path) and path.endswith("/ws/cea_all")


def is_whews_cea_split_endpoint(url: str) -> bool:
    """是否为拆分专用线 /ws/cea 或 /ws/cea-pr（公开版强制关闭，改走 cea_all）。"""
    path = _whews_url_path(url)
    if not is_whews_url(path):
        return False
    if path.endswith("/ws/cea_all"):
        return False
    return (
        path.endswith("/ws/cea")
        or path.endswith("/ws/cea-pr")
        or path.endswith("/ws/cea_pr")
    )


def whews_cea_app_configured(ws_config: Any = None) -> bool:
    """是否已具备 CEA App 凭证（内置或配置；公开版始终注入内置）。"""
    try:
        from utils.whews_cea_builtin import apply_builtin_whews_cea_credentials

        cfg = ws_config
        if cfg is None:
            cfg = Config().ws_config
        apply_builtin_whews_cea_credentials(cfg)
        app_id = (getattr(cfg, "whews_cea_app_id", "") or "").strip()
        app_secret = (getattr(cfg, "whews_cea_app_secret", "") or "").strip()
        return bool(app_id and app_secret)
    except Exception:
        return False


def normalize_data_provider(value: Any) -> str:
    """规范化数据源提供者取值。"""
    v = str(value or "").strip().lower()
    if v == DATA_PROVIDER_OFFICIAL:
        return DATA_PROVIDER_FANSTUDIO
    if v in ("jianproject", "jian_project", "sismotide"):
        return DATA_PROVIDER_JIAN
    if v in DATA_PROVIDERS:
        return v
    return DATA_PROVIDER_FANSTUDIO


def is_whews_all_enabled(enabled_sources: Dict[str, Any]) -> bool:
    """WeJet /ws/all 是否启用（兼容旧版以完整 URL 为键的配置）。"""
    if not isinstance(enabled_sources, dict):
        return False
    if enabled_sources.get(WHEWS_MASTER_KEY, False):
        return True
    for key, val in enabled_sources.items():
        if val and isinstance(key, str) and is_whews_all_url(key):
            return True
    return False


# 兼容旧代码：默认指向主站
WHEWS_ALL_URL = whews_ws_url("all", WHEWS_HOST_PRIMARY)
WHEWS_CEA_ALL_URL = whews_ws_url("cea_all", WHEWS_HOST_BACKUP)
WHEWS_CENC_URL = whews_ws_url("cenc", WHEWS_HOST_PRIMARY)
WHEWS_WS_URLS: List[str] = all_whews_ws_urls()

# 非 Fan Studio 的 WebSocket 数据源固定顺序（与轮播优先级一致，确保顺序不变）
# Wolfx 聚合源 wss://ws-api.wolfx.jp/all_eew
P2PQUAKE_WSS_URL = "wss://api.p2pquake.net/v2/ws"  # P2PQuake 地震情报 WSS 总开关
P2PQUAKE_HISTORY_AGGREGATE_URL = (
    "https://api.p2pquake.net/v2/history?codes=551&codes=552&codes=556&limit=10"
)
WOLFX_ALL_EEW_URL = "wss://ws-api.wolfx.jp/all_eew"  # Wolfx 聚合（EEW + 列表速报；不含 CWA）
WOLFX_CWA_EEW_URL = "wss://ws-api.wolfx.jp/cwa_eew"  # Wolfx CWA 单独通道
# 以下为设置项逻辑键（非独立建连）：勾选后经 all_eew 查询/解析对应列表速报
WOLFX_CENC_EQLIST_URL = "wss://ws-api.wolfx.jp/cenc_eqlist"  # Wolfx 中国地震台网地震信息（经 all_eew）
WOLFX_JMA_EQLIST_URL = "wss://ws-api.wolfx.jp/jma_eqlist"  # Wolfx JMA 地震情報（经 all_eew）
WOLFX_VIRTUAL_SOURCE_KEYS: Tuple[str, ...] = (
    WOLFX_CENC_EQLIST_URL,
    WOLFX_JMA_EQLIST_URL,
)
WOLFX_MASTER_KEY = "wolfx://master"  # Wolfx 总开关逻辑键（全局辅助源，参考 EQSC）
AUX_SOURCES_MASTER_KEY = "aux://master"  # 辅助数据源总开关（Wolfx / EQSC / P2PQuake / OpenQuakeAPI）
NOWQUAKE_CENCINT_WSS_URL = "wss://api-cencint-public.nowquake.cn/websocket"  # Nowquake CENC 烈度速报

# OpenQuakeAPI（api.aloys23.link）全局辅助 WebSocket：默认连 /ws/all 聚合
# 文档: https://docs.aloys23.link/docs/openquake/overview
OPENQUAKE_WS_BASE = "wss://api.aloys23.link"
OPENQUAKE_WS_ALL_URL = f"{OPENQUAKE_WS_BASE}/ws/all"

# 气象预警源互斥：同一时刻仅允许一个解析开关为 True
WEATHER_SOURCE_FLAGS: Dict[str, str] = {
    "fanstudio": "fanstudio_parse_weatheralarm",
    "whews": "whews_parse_weatheralarm",
    "openquake": "openquake_parse_cma",
}


def enforce_weather_source_mutex(message_config: Any) -> str:
    """确保最多一个气象预警源开启；若旧配置多项为真，保留优先级最高者。"""
    enabled = [
        key
        for key, flag in WEATHER_SOURCE_FLAGS.items()
        if bool(getattr(message_config, flag, False))
    ]
    if len(enabled) <= 1:
        return enabled[0] if enabled else ""
    keep = enabled[0]
    for key in enabled[1:]:
        flag = WEATHER_SOURCE_FLAGS[key]
        if hasattr(message_config, flag):
            setattr(message_config, flag, False)
    return keep


# 主数据源 JMA 地震情报（不含 EEW）与 P2PQuake 551 互斥
MAIN_JMA_REPORT_PARSE_FLAGS: Tuple[str, ...] = (
    "jian_parse_jma",   # Jian Project /jma → jma_eq
    "whews_parse_jma",  # WeJet /ws/jma → jma_eq
)
P2P_JMA_REPORT_PARSE_FLAG = "p2pquake_parse_551"


def main_jma_report_enabled(message_config: Any) -> bool:
    """主数据源是否启用了 JMA 地震情报解析。"""
    return any(
        bool(getattr(message_config, flag, False))
        for flag in MAIN_JMA_REPORT_PARSE_FLAGS
    )


def p2p_jma_report_enabled(message_config: Any) -> bool:
    """P2PQuake 是否启用了 551 地震情报解析。"""
    return bool(getattr(message_config, P2P_JMA_REPORT_PARSE_FLAG, False))


def enforce_jma_report_mutex(
    message_config: Any,
    *,
    prefer: str = "main",
) -> str:
    """
    P2PQuake 551 与主源 JMA 情报互斥。
    冲突时 prefer='main' 保留主源并关闭 P2P 551；prefer='p2p' 则相反。
    返回当前保留侧：'main' / 'p2p' / ''。
    """
    p2p_on = p2p_jma_report_enabled(message_config)
    main_on = main_jma_report_enabled(message_config)
    if not p2p_on and not main_on:
        return ""
    if p2p_on and not main_on:
        return "p2p"
    if main_on and not p2p_on:
        return "main"
    # 双边皆开：按 prefer 收敛
    keep = "p2p" if prefer == "p2p" else "main"
    if keep == "main":
        if hasattr(message_config, P2P_JMA_REPORT_PARSE_FLAG):
            setattr(message_config, P2P_JMA_REPORT_PARSE_FLAG, False)
    else:
        for flag in MAIN_JMA_REPORT_PARSE_FLAGS:
            if hasattr(message_config, flag):
                setattr(message_config, flag, False)
    return keep


def active_weather_source(message_config: Any) -> str:
    """返回当前启用的气象预警源键（fanstudio / whews / openquake），无则空串。"""
    for key, flag in WEATHER_SOURCE_FLAGS.items():
        if bool(getattr(message_config, flag, False)):
            return key
    return ""


def weather_provider_for_parsed(parsed_data: Dict[str, Any]) -> Optional[str]:
    """根据解析结果判断气象预警归属（用于互斥门控）。"""
    if not isinstance(parsed_data, dict):
        return None
    msg_type = str(parsed_data.get("type") or "").strip().lower()
    st = str(parsed_data.get("source_type") or "").strip().lower()
    if st == "openquake_cma" or (
        msg_type == "weather" and parsed_data.get("openquake")
    ):
        return "openquake"
    if st == "weatheralarm" or msg_type == "weather":
        if parsed_data.get("whews"):
            return "whews"
        if parsed_data.get("fanstudio"):
            return "fanstudio"
        org = str(parsed_data.get("organization") or "")
        if "中国气象局" in org and parsed_data.get("openquake"):
            return "openquake"
        if st == "weatheralarm":
            return "fanstudio"
    return None


def _normalize_source_url(url: str) -> str:
    """规范化数据源 URL 比较键（去空白、去尾斜杠）。"""
    return (url or "").strip().rstrip("/")


def is_custom_data_source_url(url: str, config: Optional["Config"] = None) -> bool:
    """判断 URL 是否为当前配置的自定义数据源。"""
    cfg = config or Config()
    custom = _normalize_source_url(getattr(cfg, "custom_data_source_url", "") or "")
    return bool(custom and _normalize_source_url(url) == custom)


def is_ws_url_enabled(config: "Config", url: str) -> bool:
    """WebSocket 是否应处理业务消息（自定义源看 custom_data_source_url）。"""
    if is_custom_data_source_url(url, config):
        return bool(_normalize_source_url(config.custom_data_source_url or ""))
    # 兼容尾斜杠差异
    if config.enabled_sources.get(url, None) is not None:
        return bool(config.enabled_sources.get(url))
    norm = _normalize_source_url(url)
    for key, val in config.enabled_sources.items():
        if _normalize_source_url(key) == norm:
            return bool(val)
    return True

# EQSC（equake.top）全局辅助数据源：以 HTTP 轮询为主（官方称 WS 不稳定）
# 登录密钥在 https://equake.top/auth 申请；软件内自动换取 AccessToken
EQSC_HTTP_BASE = "https://equake.top"
EQSC_HTTP_MASTER = "https://equake.top/"  # 总开关逻辑键（不直接轮询）
EQSC_WS_URL = "wss://equake.top:50023/"  # 保留常量；默认强制关闭，不建连
EQSC_JMA_EEW_HTTP = f"{EQSC_HTTP_BASE}/jma_eew.json"
EQSC_JMA_REPORT_HTTP = f"{EQSC_HTTP_BASE}/jma_report.json"
EQSC_JMA_TSUNAMI_HTTP = f"{EQSC_HTTP_BASE}/jma_tsunami.json"
EQSC_CENC_HTTP = f"{EQSC_HTTP_BASE}/eqlistCENC.json?limit=2"
EQSC_CENC_IR_HTTP = f"{EQSC_HTTP_BASE}/listIntensityReportCENC.json?limit=2"
EQSC_CWA_HTTP = f"{EQSC_HTTP_BASE}/eqlistCWA.json?limit=2"
EQSC_HKO_HTTP = f"{EQSC_HTTP_BASE}/eqlistHKO.json?limit=2"
EQSC_USGS_HTTP = f"{EQSC_HTTP_BASE}/eqlistUSGS4.json?limit=2"  # level4：M≥4.5
EQSC_EMSC_HTTP = f"{EQSC_HTTP_BASE}/eqlistEMSC4.json?limit=2"
EQSC_TYPHOON_HTTP = f"{EQSC_HTTP_BASE}/typhoonNMC.json"
EQSC_VOLCANO_HTTP = f"{EQSC_HTTP_BASE}/volcanoJMA.json"
EQSC_HTTP_SOURCE_KEYS: List[str] = [
    EQSC_JMA_EEW_HTTP,
    EQSC_JMA_REPORT_HTTP,
    EQSC_JMA_TSUNAMI_HTTP,
    EQSC_CENC_HTTP,
    EQSC_CENC_IR_HTTP,
    EQSC_CWA_HTTP,
    EQSC_HKO_HTTP,
    EQSC_USGS_HTTP,
    EQSC_EMSC_HTTP,
    EQSC_TYPHOON_HTTP,
    EQSC_VOLCANO_HTTP,
]
# HTTP URL -> API scope（供适配器识别）
EQSC_HTTP_URL_TO_SCOPE: Dict[str, str] = {
    EQSC_JMA_EEW_HTTP: "jma_eew",
    EQSC_JMA_REPORT_HTTP: "jma_report",
    EQSC_JMA_TSUNAMI_HTTP: "jma_tsunami",
    EQSC_CENC_HTTP: "eqlistCENC",
    EQSC_CENC_IR_HTTP: "listIntensityReportCENC",
    EQSC_CWA_HTTP: "eqlistCWA",
    EQSC_HKO_HTTP: "eqlistHKO",
    EQSC_USGS_HTTP: "eqlistUSGS",
    EQSC_EMSC_HTTP: "eqlistEMSC",
    EQSC_TYPHOON_HTTP: "typhoonNMC",
    EQSC_VOLCANO_HTTP: "volcanoJMA",
}
# MessageConfig 解析开关 -> HTTP URL
EQSC_PARSE_FLAG_TO_URL: Dict[str, str] = {
    "eqsc_parse_jma_eew": EQSC_JMA_EEW_HTTP,
    "eqsc_parse_jma_report": EQSC_JMA_REPORT_HTTP,
    "eqsc_parse_jma_tsunami": EQSC_JMA_TSUNAMI_HTTP,
    "eqsc_parse_cenc": EQSC_CENC_HTTP,
    "eqsc_parse_cenc_ir": EQSC_CENC_IR_HTTP,
    "eqsc_parse_cwa": EQSC_CWA_HTTP,
    "eqsc_parse_hko": EQSC_HKO_HTTP,
    "eqsc_parse_usgs": EQSC_USGS_HTTP,
    "eqsc_parse_emsc": EQSC_EMSC_HTTP,
    "eqsc_parse_typhoon": EQSC_TYPHOON_HTTP,
    "eqsc_parse_volcano": EQSC_VOLCANO_HTTP,
}

# Jian Project（主数据源之一，WebSocket 聚合 api.sismotide.top/all）
JIAN_PROJECT_DOMAIN = "api.sismotide.top"
JIAN_PROJECT_ALL_URL = f"wss://{JIAN_PROJECT_DOMAIN}/all"
JIAN_LOGICAL_PREFIX = "jian://"
JIAN_MASTER_KEY = f"{JIAN_LOGICAL_PREFIX}master"

# (短名, 展示用标签) — 对应 message_config.jian_parse_* 解析开关
JIAN_SUB_SOURCE_SPECS: List[Tuple[str, str]] = [
    ("cea", "中国地震预警网"),
    ("cwa-eew", "台湾中央气象署地震预警"),
    ("jma-eew", "日本气象厅紧急地震速报"),
    ("sa", "美国 ShakeAlert 地震预警"),
    ("kma-eew", "韩国气象厅地震预警"),
    ("early-est", "INGV Early-est 快速定位"),
    ("cenc", "CENC 中国地震台网中心"),
    ("cwa", "CWA 台湾中央气象署速报"),
    ("jma", "日本气象厅地震情报"),
    ("hko", "HKO 香港天文台"),
    ("tmd", "TMD 泰国气象局"),
    ("mmd", "MMD 马来西亚气象局"),
    ("bmkg", "BMKG 印尼气象气候地球物理局"),
    ("geonet", "GeoNet 新西兰地质灾害监测网"),
    ("usgs", "USGS 美国地质调查局"),
    ("emsc", "EMSC 欧洲地中海地震中心"),
    ("gfz", "GFZ 德国地学研究中心"),
    ("bcsf", "BCSF 法国中央地震局"),
    ("ingv", "INGV 意大利国家地球物理与火山学研究所"),
    ("usp", "USP 巴西圣保罗大学"),
    ("nrcan", "NRCan 加拿大自然资源部"),
    ("afad", "AFAD 土耳其灾害应急管理局"),
    ("kma", "KMA 韩国气象厅速报"),
]


def jian_logical_key(short: str) -> str:
    """Jian 子源逻辑开关键。"""
    return f"{JIAN_LOGICAL_PREFIX}{str(short or '').strip().lower()}"


def jian_short_to_internal(short: str) -> str:
    """Jian 短名 → 内部 source_type（与适配器一致：jma-eew→jma，jma→jma_eq）。"""
    s = str(short or "").strip().lower()
    if s == "early-est":
        return "early_est"
    if s == "jma-eew":
        return "jma"
    if s == "jma":
        return "jma_eq"
    return s.replace("_", "-")


JIAN_LOGICAL_TO_INTERNAL: Dict[str, str] = {
    jian_logical_key(short): jian_short_to_internal(short)
    for short, _ in JIAN_SUB_SOURCE_SPECS
}
JIAN_INTERNAL_TO_LOGICAL_KEY: Dict[str, str] = {
    internal: key for key, internal in JIAN_LOGICAL_TO_INTERNAL.items()
}
JIAN_SUB_SOURCE_KEYS: List[str] = list(JIAN_LOGICAL_TO_INTERNAL.keys())

JIAN_WARNING_INTERNALS = frozenset({"cea", "cwa-eew", "jma", "sa", "kma-eew", "early_est"})

# Jian 短名 → message_config.jian_parse_* 字段名
JIAN_SHORT_TO_PARSE_FLAG: Dict[str, str] = {
    "cea": "jian_parse_cea",
    "cwa-eew": "jian_parse_cwa_eew",
    "jma-eew": "jian_parse_jma_eew",
    "sa": "jian_parse_sa",
    "kma-eew": "jian_parse_kma_eew",
    "early-est": "jian_parse_early_est",
    "cenc": "jian_parse_cenc",
    "cwa": "jian_parse_cwa",
    "jma": "jian_parse_jma",
    "hko": "jian_parse_hko",
    "tmd": "jian_parse_tmd",
    "mmd": "jian_parse_mmd",
    "bmkg": "jian_parse_bmkg",
    "geonet": "jian_parse_geonet",
    "usgs": "jian_parse_usgs",
    "emsc": "jian_parse_emsc",
    "gfz": "jian_parse_gfz",
    "bcsf": "jian_parse_bcsf",
    "ingv": "jian_parse_ingv",
    "usp": "jian_parse_usp",
    "nrcan": "jian_parse_nrcan",
    "afad": "jian_parse_afad",
    "kma": "jian_parse_kma",
}

JIAN_INTERNAL_TO_PARSE_FLAG: Dict[str, str] = {
    jian_short_to_internal(short): flag
    for short, flag in JIAN_SHORT_TO_PARSE_FLAG.items()
}

# 适配器内部 source_type → jian_parse_*（兜底；主映射见 JIAN_INTERNAL_TO_PARSE_FLAG）
JIAN_ADAPTER_INTERNAL_ALIASES: Dict[str, str] = {
    "jma": "jian_parse_jma_eew",
    "jma_eq": "jian_parse_jma",
}


def jian_parse_flag_for_internal(internal: str) -> Optional[str]:
    """将适配器/报文 source_type 映射到 jian_parse_* 配置字段名。"""
    key = str(internal or "").strip()
    if not key:
        return None
    return JIAN_INTERNAL_TO_PARSE_FLAG.get(key) or JIAN_ADAPTER_INTERNAL_ALIASES.get(key)

P2PQUAKE_HTTP_SOURCE_KEYS: List[str] = [
    P2PQUAKE_HISTORY_AGGREGATE_URL,
]

FANSTUDIO_HTTP_SOURCE_KEYS: List[str] = [
    fanstudio_http_url("we/typhoon.php"),
]
FANSTUDIO_TYPHOON_HTTP = FANSTUDIO_HTTP_SOURCE_KEYS[0]


def is_jian_project_url(url: str) -> bool:
    """是否为 Jian Project WebSocket URL。"""
    low = (url or "").lower().rstrip("/")
    return "sismotide.top" in low and low.startswith(("ws://", "wss://"))


def is_jian_logical_key(key: str) -> bool:
    """是否为 Jian 子源逻辑开关键。"""
    return str(key or "").startswith(JIAN_LOGICAL_PREFIX)


def wolfx_master_enabled(enabled_sources: Dict[str, Any]) -> bool:
    """Wolfx 总开关（全局辅助源）。"""
    if not isinstance(enabled_sources, dict):
        return False
    return bool(
        enabled_sources.get(WOLFX_MASTER_KEY, False)
        or enabled_sources.get(WOLFX_ALL_EEW_URL, False)
    )


def openquake_master_enabled(enabled_sources: Dict[str, Any]) -> bool:
    """OpenQuakeAPI 总开关是否开启（依赖辅助总开关）。"""
    if not aux_sources_enabled(enabled_sources):
        return False
    return bool(enabled_sources.get(OPENQUAKE_WS_ALL_URL, False))


def aux_sources_enabled(enabled_sources: Dict[str, Any]) -> bool:
    """辅助数据源总开关（Wolfx / EQSC / P2PQuake / OpenQuakeAPI）；缺省视为开启以兼容旧配置。"""
    if not isinstance(enabled_sources, dict):
        return True
    if AUX_SOURCES_MASTER_KEY not in enabled_sources:
        return True
    return bool(enabled_sources.get(AUX_SOURCES_MASTER_KEY, True))


def _any_jian_parse_flag_enabled(config: "Config") -> bool:
    """任一 Jian 子源解析开关启用。"""
    mc = config.message_config
    for flag in JIAN_SHORT_TO_PARSE_FLAG.values():
        if bool(getattr(mc, flag, True)):
            return True
    return False


def jian_internal_enabled(config: "Config", internal: str) -> bool:
    """判断 Jian 子源是否启用（须为主提供者且总开关打开）。"""
    if config.get_active_data_provider() != DATA_PROVIDER_JIAN:
        return False
    if not config.enabled_sources.get(JIAN_MASTER_KEY, False):
        return False
    flag = jian_parse_flag_for_internal(internal)
    if flag:
        return bool(getattr(config.message_config, flag, True))
    return False


def any_jian_source_enabled(config: "Config") -> bool:
    """Jian Project 主源是否应建连（主提供者 + 总开关 + 至少一项子源）。"""
    if config.get_active_data_provider() != DATA_PROVIDER_JIAN:
        return False
    if not config.enabled_sources.get(JIAN_MASTER_KEY, False):
        return False
    return _any_jian_parse_flag_enabled(config)

# 各 HTTP 数据源默认轮询间隔（秒，仅保留台风 / P2P 补拉 / EQSC）
DEFAULT_HTTP_POLL_INTERVALS: Dict[str, int] = {
    P2PQUAKE_HISTORY_AGGREGATE_URL: 2,
    # EQSC：预警 1s；速报按品类（海啸稍密，台风/火山较疏）
    EQSC_JMA_EEW_HTTP: 1,
    EQSC_JMA_REPORT_HTTP: 30,
    EQSC_JMA_TSUNAMI_HTTP: 15,
    EQSC_CENC_HTTP: 30,
    EQSC_CENC_IR_HTTP: 30,
    EQSC_CWA_HTTP: 30,
    EQSC_HKO_HTTP: 60,
    EQSC_USGS_HTTP: 60,
    EQSC_EMSC_HTTP: 60,
    EQSC_TYPHOON_HTTP: 300,
    EQSC_VOLCANO_HTTP: 300,
}

ALL_KNOWN_HTTP_SOURCE_KEYS: List[str] = (
    P2PQUAKE_HTTP_SOURCE_KEYS
    + FANSTUDIO_HTTP_SOURCE_KEYS
    + [EQSC_HTTP_MASTER]
    + EQSC_HTTP_SOURCE_KEYS
)


def p2pquake_master_enabled(enabled_sources: Dict[str, Any]) -> bool:
    """
    P2PQuake 总开关：与设置页「P2PQuake（HTTP + WebSocket）」一致。
    以 WSS 项为唯一真值；配置加载时会将两条 HTTP 项同步为与此相同。
    """
    if not isinstance(enabled_sources, dict):
        return False
    return bool(enabled_sources.get(P2PQUAKE_WSS_URL, False))

# 应用版本号（用于更新说明弹窗“仅展示一次”及关于页）
APP_VERSION = "2.8.4"  # 当前程序版本

# 自动更新清单默认 URL（可在设置-关于中修改）
AUTO_UPDATE_MANIFEST_URL_DEFAULT = "https://sismotide.top/rolling-update/manifest.json"  # 默认更新清单地址

# 更新说明（关于页/首次启动弹窗展示，当前版本仅展示一次）
# 每次修改 APP_VERSION 时，请同步修改下方 CHANGELOG_TEXT 的版本标题与更新条目。
CHANGELOG_TEXT = """版本 2.8.4

1、优化占用：精简预警/气象缓冲；优化内存占用；启动与关闭设置窗后压缩工作集
2、适配副屏：主窗/设置窗按所在屏定位；启用 High DPI；按当前屏刷新率同步滚动定时器
3、主数据源三选一控制连接：去掉 Fan Studio / WeJet / Jian 单独连接开关；保存后按所选主源启用
4、Jian Project：修复 JMA 预警时间解析；适配 KMA 韩国气象厅预警；默认主数据源改为 Jian Project
5、P2PQuake 地震情报与主数据源 JMA 情报互斥，避免重复
6、WeJet：恢复 CEA/CEA-PR（国内站 /ws/cea_all + 内置 App 鉴权）；WAuth 令牌首帧鉴权"""

# 应用声明（更新说明弹窗与设置-关于页共用；修改时请两处效果一致）
APP_DECLARATION_TEXT = (
    "本软件依托第三方接口获取数据，内容时效性、准确性不作保证\n"
    "所有参考内容仅作娱乐查阅使用，官方公告为最终标准！\n"
    "严禁盗用、转载及各类商业化牟利使用！\n"
    "本软件为免费开源软件，严禁任何形式的收费行为！"
)

@dataclass
class GUIConfig:
    """GUI配置类"""
    font_size: int = 40
    font_family: str = "SimSun"
    font_bold: bool = False
    font_italic: bool = False
    text_speed: float = 4.0
    bg_color: str = 'black'
    info_color: str = '#01FF00'
    opacity: float = 1.0
    window_width: int = 1000
    window_height: int = 100
    # 主窗口位置：均为 -1 表示从未保存，启动时居中；否则为上次关闭时的坐标（支持多屏负坐标）
    window_x: int = -1
    window_y: int = -1
    resizable: bool = True
    vsync_enabled: bool = True  # 垂直同步开关
    target_fps: int = 30  # 目标帧率（字幕足够流畅；过高会持续拉高 CPU/电源占用）
    timezone: str = "Asia/Shanghai"  # 显示时区（IANA 名称），默认北京时间
    last_seen_changelog_version: str = ""  # 上次已读的更新说明版本，用于弹窗仅展示一次
    use_gpu_rendering: bool = False  # True=GPU 渲染，False=CPU(软件) 渲染，与 render_backend 同步
    render_backend: str = "cpu"  # "cpu" | "opengl"，默认 cpu
    always_on_top: bool = False  # 窗口置顶
    borderless: bool = False  # 无边框模式（FramelessWindowHint）
    # 自定义背景图：存 AppData/subtitl/backgrounds/ 下文件名或绝对路径；空=纯色 bg_color
    background_image_path: str = ""
    background_blur_radius: int = 12  # 毛玻璃模糊半径，0=关闭
    background_overlay_opacity: float = 0.35  # 背景半透明遮罩（保证字幕可读）
    watermark_text: str = ""  # 背景水印文字，空则不显示
    watermark_angle: str = "horizontal"  # 水印方向："horizontal" 横向，"45" 斜向45度
    watermark_font_family: str = ""  # 水印字体族名，空表示跟随主字体
    watermark_font_size: int = 0  # 水印字体大小，0 表示自动（按主字体比例）
    watermark_position: str = "diagonal"  # 水印位置: diagonal | top_left | top_right | bottom_left | bottom_right
    # 自动更新（仅 PyInstaller 打包 exe 生效；启动时拉取清单比对 APP_VERSION）
    auto_update_check_on_startup: bool = True
    auto_update_upgrade_only: bool = True  # True：仅当服务器版本高于本地时更新；False：版本不一致即更新（含降级）
    auto_update_manifest_url: str = AUTO_UPDATE_MANIFEST_URL_DEFAULT
    auto_update_timeout_seconds: int = 15
    auto_update_package_kind: str = "installer"  # installer | zip（zip 为便携目录结构，与一键打包 onedir 一致）
    # 启动时「发现新版本」弹窗用户点否后记录的服务器版本，避免同版本每次启动反复询问
    last_dismissed_update_offer_version: str = ""
    minimize_to_tray: bool = False
    toast_notifications_enabled: bool = False
    performance_mode: str = "medium"  # low | medium | high | extreme | custom
    image_cache_max: int = 16  # 图片纹理缓存上限（气象/沙滩球等）
    text_texture_cache_max: int = 10  # 文本纹理缓存上限
    opengl_msaa_samples: int = 0  # OpenGL 多重采样（0/2/4）；0 更省显存/内存
    auto_save_settings: bool = False  # Auto-save settings window changes to disk

    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            assert 10 <= self.font_size <= 100, "字体大小必须在10-100之间"
            assert 0.1 <= self.text_speed <= 20.0, "滚动速度必须在0.1-20.0之间"
            assert 0.1 <= self.opacity <= 1.0, "不透明度必须在0.1-1.0之间"
            # 窗口尺寸不受系统分辨率限制，允许超出屏幕；仅做合理范围校验
            assert 800 <= self.window_width <= 20000, "窗口宽度必须在800-20000之间"
            assert 100 <= self.window_height <= 5000, "窗口高度必须在100-5000之间"
            wx = getattr(self, "window_x", -1)
            wy = getattr(self, "window_y", -1)
            for name, v in (("window_x", wx), ("window_y", wy)):
                if v != -1 and not (-32768 <= v <= 32767):
                    logger.warning(f"{name}={v} 超出范围，重置为 -1")
                    setattr(self, name, -1)
            if (getattr(self, "window_x", -1) == -1) != (getattr(self, "window_y", -1) == -1):
                self.window_x, self.window_y = -1, -1
            assert 1 <= self.target_fps <= 240, "目标帧率必须在1-240之间"
            assert self.render_backend in ("cpu", "opengl"), "render_backend 必须为 cpu 或 opengl"
            from utils.performance_presets import normalize_performance_mode

            pm = normalize_performance_mode(getattr(self, "performance_mode", "medium"))
            self.performance_mode = pm
            self.borderless = bool(getattr(self, "borderless", False))
            try:
                br = int(getattr(self, "background_blur_radius", 12) or 0)
                self.background_blur_radius = max(0, min(40, br))
            except (TypeError, ValueError):
                self.background_blur_radius = 12
            try:
                msaa = int(getattr(self, "opengl_msaa_samples", 0) or 0)
                if msaa not in (0, 2, 4, 8):
                    msaa = 0
                self.opengl_msaa_samples = msaa
            except (TypeError, ValueError):
                self.opengl_msaa_samples = 0
            try:
                ic = int(getattr(self, "image_cache_max", 16) or 16)
                self.image_cache_max = max(4, min(32, ic))
            except (TypeError, ValueError):
                self.image_cache_max = 16
            try:
                tc = int(getattr(self, "text_texture_cache_max", 10) or 10)
                self.text_texture_cache_max = max(4, min(24, tc))
            except (TypeError, ValueError):
                self.text_texture_cache_max = 10
            try:
                ov = float(getattr(self, "background_overlay_opacity", 0.35) or 0.0)
                self.background_overlay_opacity = max(0.0, min(0.9, ov))
            except (TypeError, ValueError):
                self.background_overlay_opacity = 0.35
            self.background_image_path = str(getattr(self, "background_image_path", "") or "").strip()
            if getattr(self, 'watermark_angle', 'horizontal') not in ("horizontal", "45"):
                self.watermark_angle = "horizontal"
            try:
                if getattr(self, 'watermark_font_size', 0) < 0:
                    self.watermark_font_size = 0
            except Exception:
                self.watermark_font_size = 0
            allowed_positions = {"diagonal", "top_left", "top_right", "bottom_left", "bottom_right"}
            if getattr(self, 'watermark_position', 'diagonal') not in allowed_positions:
                self.watermark_position = "diagonal"
            if getattr(self, 'auto_update_package_kind', 'installer') not in ('installer', 'zip'):
                self.auto_update_package_kind = 'installer'
            try:
                tout = int(getattr(self, 'auto_update_timeout_seconds', 15))
                if tout < 5 or tout > 120:
                    self.auto_update_timeout_seconds = 15
            except (TypeError, ValueError):
                self.auto_update_timeout_seconds = 15
            mu = (getattr(self, 'auto_update_manifest_url', '') or '').strip()
            if not mu:
                self.auto_update_manifest_url = AUTO_UPDATE_MANIFEST_URL_DEFAULT
            elif len(mu) > 2048:
                self.auto_update_manifest_url = mu[:2048]
            else:
                self.auto_update_manifest_url = mu
            return True
        except AssertionError as e:
            logger.error(f"GUI配置验证失败: {e}")
            return False


@dataclass
class MessageConfig:
    """消息处理配置"""
    max_message_length: int = 0
    display_duration: int = 0
    # 预警无活动时长（秒）：自最后一次收到该事件更新报起，超过此时长且无更新则视为过期（默认 10 分钟）
    max_warning_inactivity_time: int = 600
    # 预警按发震时间的有效期（秒）：超过此时长的预警入队时丢弃、展示时移除，默认 5 分钟
    warning_shock_validity_seconds: int = 300
    # Wolfx JMA 预警的发震时间有效期（秒），默认 5 分钟
    warning_shock_validity_seconds_nied: int = 300
    # Wolfx 四川地震局预警的发震时间有效期（秒），默认 10 分钟
    warning_shock_validity_seconds_early_est: int = 600
    # 预警最少展示时长（秒）：一旦展示则在此时间内不因发震时间过期被移除，默认 5 分钟
    warning_min_display_seconds: int = 300
    # 测试用：为 True 时跳过发震时间窗口与「展示满最少时长即移除」等过期判定（勿在生产长期开启）
    disable_warning_expiry_for_test: bool = False
    max_report_inactivity_time: int = 300
    max_other_inactivity_time: int = 300
    # 主线程消息队列与展示缓冲区容量（字幕场景无需过大缓冲）
    message_queue_maxsize: int = 100
    message_buffer_max_size: int = 40
    no_activity_message: str = '系统运行中，等待最新地震信息...'
    custom_text: str = '系统运行中，等待最新地震信息...'
    use_custom_text: bool = False  # True=自定义文本模式(与地震速报二选一)，False=地震速报模式
    # Fan Studio All 数据源：勾选则解析对应类型，不勾选则不解析（不写单项 URL）
    fanstudio_parse_warning: bool = True  # 勾选则解析所有预警数据源
    fanstudio_parse_report: bool = True   # 勾选则解析所有速报数据源（含气象预警）
    # Wolfx 聚合源 (ws-api.wolfx.jp/all_eew)：勾选则解析对应子源，不勾选则不解析
    ali_all_parse_nied: bool = True         # 解析 JMA 緊急地震速報
    ali_all_parse_early_est: bool = True    # 解析 四川省地震局预警
    ali_all_parse_jma_volcano: bool = True  # 解析 福建省地震局预警
    ali_all_parse_bmkg: bool = True         # 解析 中国地震台网地震预警
    ali_all_parse_cq_eew: bool = True       # 解析 重庆市地震局预警
    # EQSC（equake.top）全局辅助源：勾选则解析对应类型
    eqsc_parse_jma_eew: bool = True
    eqsc_parse_jma_report: bool = True
    eqsc_parse_jma_tsunami: bool = True
    eqsc_parse_cenc: bool = True
    eqsc_parse_cenc_ir: bool = True
    eqsc_parse_cwa: bool = True
    eqsc_parse_hko: bool = True
    eqsc_parse_usgs: bool = True
    eqsc_parse_emsc: bool = True
    eqsc_parse_typhoon: bool = True
    eqsc_parse_volcano: bool = False  # 数据量大，默认关闭
    warning_color: str = '#FF0000'  # 红色
    report_color: str = '#00FFFF'  # 青色
    custom_text_color: str = '#01FF00'  # 自定义文本颜色（绿色，与默认颜色一致）
    default_color: str = '#01FF00'
    weather_warning_color: str = '#FFF500'
    # 收到预警更新报立即切换：开启则同事件更新报立即打断并替换，否则仅后台替换；默认关闭
    show_one_alert_per_received: bool = False
    # 强制单行：将数据源中的换行符替换为空格，保证滚动字幕单行显示；默认开启
    force_single_line: bool = True
    # 预警后限时显示速报再回自定义：仅在「自定义文本」模式下生效；速报连续显示 custom_text_return_seconds 秒后自动恢复为仅显示自定义文本
    custom_text_return_after_warning: bool = False
    custom_text_return_seconds: int = 300  # 限时秒数，默认 5 分钟；仅当 custom_text_return_after_warning 为 True 时生效
    # 中国经验烈度与有感/强有感红屏流程
    enable_china_intensity: bool = False  # 是否启用中国预估烈度算法
    enable_felt_alert_flow: bool = False  # 有感地震是否启用红屏提示
    enable_strong_felt_alert_flow: bool = True  # 强有感地震是否启用红屏提示
    felt_alert_stage1_ms: int = 1500  # 有感阶段一时长
    felt_alert_stage2_ms: int = 2500  # 有感阶段二时长
    strong_felt_stage1_ms: int = 1500  # 强有感阶段一时长
    strong_felt_stage2_ms: int = 2500  # 强有感阶段二时长
    alert_flash_interval_ms: int = 400  # 红色背景闪烁间隔
    # Fan Studio 单项数据源解析开关（基于 All 通道按子源细分）
    # 预警类
    fanstudio_parse_cea: bool = True
    fanstudio_parse_cea_pr: bool = True
    fanstudio_parse_cwa_eew: bool = True
    fanstudio_parse_jma: bool = True
    fanstudio_parse_sa: bool = True
    fanstudio_parse_kma_eew: bool = True
    # 速报 / 其他类
    fanstudio_parse_cenc: bool = True
    fanstudio_parse_ningxia: bool = True
    fanstudio_parse_guangxi: bool = True
    fanstudio_parse_shanxi: bool = True
    fanstudio_parse_beijing: bool = True
    fanstudio_parse_yunnan: bool = True
    fanstudio_parse_cwa: bool = True
    fanstudio_parse_hko: bool = True
    fanstudio_parse_usgs: bool = True
    fanstudio_parse_emsc: bool = True
    fanstudio_parse_bcsf: bool = True
    fanstudio_parse_gfz: bool = True
    fanstudio_parse_usp: bool = True
    fanstudio_parse_kma: bool = True
    fanstudio_parse_fssn: bool = True
    fanstudio_parse_fssn_cmt: bool = True
    fanstudio_parse_weatheralarm: bool = True
    fanstudio_parse_tsunami: bool = True
    # 无界科技（WHEWS）子源解析开关
    whews_parse_jma_eew: bool = True
    whews_parse_jma: bool = True  # WeJet /ws/jma 地震情报（与紧急地震速报分开）
    whews_parse_cwa_eew: bool = True
    whews_parse_sa_eew: bool = True
    whews_parse_cea: bool = True  # WeJet CEA 国家级预警（需 App 鉴权）
    whews_parse_cea_pr: bool = True  # WeJet CEA 省级预警（需 App 鉴权）
    whews_parse_cenc: bool = True
    whews_parse_cwa: bool = True
    whews_parse_hko: bool = True
    whews_parse_usgs: bool = True
    whews_parse_emsc: bool = True
    whews_parse_bcsf: bool = True
    whews_parse_gfz: bool = True
    whews_parse_usp: bool = True
    whews_parse_kma: bool = True
    whews_parse_bmkg: bool = True
    whews_parse_geonet: bool = True
    whews_parse_tmd: bool = True
    whews_parse_ingv: bool = True
    whews_parse_nrcan: bool = True
    whews_parse_mmd: bool = True
    whews_parse_kma_eew: bool = True
    whews_parse_beijing: bool = True
    whews_parse_yunnan: bool = True
    whews_parse_ningxia: bool = True
    whews_parse_jma_volcano: bool = True  # 无界科技 source=va 火山情报
    whews_parse_tsunami: bool = True
    whews_parse_weatheralarm: bool = True
    whews_parse_phivolcs: bool = True
    whews_parse_sgc: bool = True
    whews_parse_ga: bool = True
    whews_parse_cenais: bool = True
    whews_parse_ntwc: bool = True
    whews_parse_ptwc: bool = True
    whews_parse_incois: bool = True
    whews_parse_jma_tsunami: bool = True
    whews_parse_gsras: bool = True
    whews_parse_bgs: bool = True
    whews_parse_ipma: bool = True
    whews_parse_ssn: bool = True
    whews_parse_afad: bool = True
    whews_parse_sed: bool = True
    whews_parse_noa: bool = True
    whews_parse_scsn: bool = True
    whews_parse_iag: bool = True
    whews_parse_igp: bool = True
    whews_parse_nepal: bool = True
    whews_parse_typhoon: bool = False
    # Jian Project 子源解析开关（主提供者 api.sismotide.top/all）
    jian_parse_cea: bool = True
    jian_parse_cwa_eew: bool = True
    jian_parse_jma_eew: bool = True
    jian_parse_sa: bool = True
    jian_parse_kma_eew: bool = True
    jian_parse_early_est: bool = True
    jian_parse_cenc: bool = True
    jian_parse_cwa: bool = True
    jian_parse_jma: bool = True  # Jian /jma 地震情报（与 jma-eew 分开）
    jian_parse_hko: bool = True
    jian_parse_tmd: bool = True
    jian_parse_mmd: bool = True
    jian_parse_bmkg: bool = True
    jian_parse_geonet: bool = True
    jian_parse_usgs: bool = True
    jian_parse_emsc: bool = True
    jian_parse_gfz: bool = True
    jian_parse_bcsf: bool = True
    jian_parse_ingv: bool = True
    jian_parse_usp: bool = True
    jian_parse_nrcan: bool = True
    jian_parse_afad: bool = True
    jian_parse_kma: bool = True
    # P2PQuake WSS：同一连接下按 code 分别控制是否解析（551 地震情報 / 552 津波予報 / 556 緊急地震速報）
    p2pquake_parse_551: bool = False  # 与主源 JMA 情报互斥；默认关，优先主源
    p2pquake_parse_552: bool = True
    p2pquake_parse_556: bool = True
    # OpenQuakeAPI（/ws/all）：按子源分别控制是否解析
    openquake_parse_gq: bool = True
    openquake_parse_nmefc: bool = True
    openquake_parse_nmefc_wave: bool = True
    openquake_parse_nmefc_surge: bool = True
    openquake_parse_cma: bool = True
    # GlobalQuake 专用震级阈值（0 表示不限制；与全局 min_report_magnitude 独立）
    openquake_gq_min_magnitude: float = 4.5
    # 速报震级过滤（0 表示不限制）
    min_report_magnitude: float = 0.0
    # 关注区域过滤（以经纬度为圆心、半径 km 内才显示）
    geo_filter_enabled: bool = False
    geo_filter_latitude: float = 39.9042
    geo_filter_longitude: float = 116.4074
    geo_filter_radius_km: float = 1000.0
    # 气象预警过滤：地区（市/县/区，逗号分隔）与等级档位
    weather_region_filter_enabled: bool = False
    weather_region_filter: str = ""
    # none=不过滤 / yellow_up=黄及以上 / orange_up=橙及以上 / red=仅红色
    weather_level_filter: str = "none"

    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            assert self.max_message_length >= 0, "消息最大长度不能为负数"
            assert self.display_duration >= 0, "显示持续时间不能为负数"
            assert self.max_warning_inactivity_time > 0, "预警无活动时长必须大于0"
            assert self.warning_shock_validity_seconds > 0, "预警发震时间有效期必须大于0"
            if getattr(self, 'warning_shock_validity_seconds_nied', 0) <= 0:
                self.warning_shock_validity_seconds_nied = self.warning_shock_validity_seconds
            if getattr(self, 'warning_shock_validity_seconds_early_est', 0) <= 0:
                self.warning_shock_validity_seconds_early_est = max(
                    self.warning_shock_validity_seconds,
                    self.warning_shock_validity_seconds_nied,
                )
            assert self.warning_min_display_seconds > 0, "预警最少展示时长必须大于0"
            assert self.max_report_inactivity_time > 0, "速报无活动时长必须大于0"
            assert self.max_other_inactivity_time > 0, "其他消息无活动时长必须大于0"
            assert 1 <= self.custom_text_return_seconds <= 3600, "custom_text_return_seconds 必须在 1–3600 之间"
            self.disable_warning_expiry_for_test = bool(
                getattr(self, "disable_warning_expiry_for_test", False)
            )
            # 气象预警等级档位：不过滤 / 黄及以上 / 橙及以上 / 仅红
            _wl = (getattr(self, "weather_level_filter", "none") or "none").strip().lower()
            if _wl not in ("none", "yellow_up", "orange_up", "red"):
                _wl = "none"
            self.weather_level_filter = _wl
            return True
        except AssertionError as e:
            logger.error(f"消息配置验证失败: {e}")
            return False


@dataclass
class AlertConfig:
    """
    预警告警闪烁与有感/强有感提示配置。

    单位约定：
    - ``flash_interval_ms``：左侧「地震预警」条明灭间隔。
    - 提示期兜底时长由报文发震时间与 ``MessageConfig.warning_shock_validity_seconds*`` 决定，不再单独配置。
    """
    enabled: bool = False
    min_magnitude: float = 3.0
    flash_interval_ms: int = 400
    flash_scope: str = "scrolling_only"
    flash_target_screen: int = -1
    flash_color: str = "#FF0000"
    flash_max_alpha: int = 180
    sound_enabled: bool = False
    sound_path: str = ""
    sound_volume: int = 100
    sound_warnings_only: bool = True
    felt_sound_enabled: bool = False
    felt_sound_path: str = ""
    felt_sound_repeat: int = 1
    critical_sound_enabled: bool = False
    critical_sound_path: str = ""
    critical_sound_repeat: int = 1
    # 已废弃：速报不再使用预设 WAV，保留字段仅为兼容旧配置
    ciev_sound_enabled: bool = False
    ciev_sound_path: str = ""
    ciev_sound_repeat: int = 1
    nhk_news_bell_enabled: bool = False
    nhk_news_bell_path: str = ""
    nhk_news_bell_repeat: int = 1
    jma_eew_alert_sound_enabled: bool = True
    jma_eew_alert_sound_path: str = ""
    jma_eew_alert_sound_repeat: int = 2
    alert_feedback_mode: str = "sound"
    felt_tts_enabled: bool = False
    critical_tts_enabled: bool = False
    felt_tts_repeat: int = 1
    critical_tts_repeat: int = 1
    report_tts_enabled: bool = True
    report_tts_repeat: int = 1
    weather_tts_enabled: bool = True
    weather_tts_repeat: int = 1
    tsunami_tts_enabled: bool = True
    tsunami_tts_repeat: int = 1
    tts_playback_mode: str = "supplement"
    tts_rate: int = 150
    tts_voice: str = ""
    tts_include_safety_hint: bool = True
    tts_repeat_policy: str = "smart"
    tts_cooldown_seconds: int = 60
    # 预警主反馈去重：first_received=本程序首条视为内部第1报仅播一次；smart=更新报/震级变化可再播
    warning_feedback_policy: str = "first_received"

    def validate(self) -> bool:
        try:
            if self.min_magnitude < 0:
                self.min_magnitude = 0.0
            if self.flash_interval_ms < 50:
                self.flash_interval_ms = 50
            if self.flash_interval_ms > 2000:
                self.flash_interval_ms = 2000
            # 仅保留字幕条左侧「地震预警」标识闪烁，不再使用主窗口四边叠加
            self.flash_scope = "scrolling_only"
            try:
                self.flash_target_screen = int(self.flash_target_screen)
            except (TypeError, ValueError):
                self.flash_target_screen = -1
            if not isinstance(self.flash_color, str) or not self.flash_color.strip():
                self.flash_color = "#FF0000"
            if self.flash_max_alpha < 30:
                self.flash_max_alpha = 30
            if self.flash_max_alpha > 255:
                self.flash_max_alpha = 255
            self.felt_sound_path = (self.felt_sound_path or "").strip()
            self.critical_sound_path = (self.critical_sound_path or "").strip()
            self.ciev_sound_path = (self.ciev_sound_path or "").strip()
            self.nhk_news_bell_path = (self.nhk_news_bell_path or "").strip()
            self.jma_eew_alert_sound_path = (self.jma_eew_alert_sound_path or "").strip()
            try:
                self.felt_sound_repeat = int(self.felt_sound_repeat)
            except (TypeError, ValueError):
                self.felt_sound_repeat = 1
            try:
                self.critical_sound_repeat = int(self.critical_sound_repeat)
            except (TypeError, ValueError):
                self.critical_sound_repeat = 1
            try:
                self.ciev_sound_repeat = int(self.ciev_sound_repeat)
            except (TypeError, ValueError):
                self.ciev_sound_repeat = 1
            try:
                self.nhk_news_bell_repeat = int(self.nhk_news_bell_repeat)
            except (TypeError, ValueError):
                self.nhk_news_bell_repeat = 1
            try:
                self.jma_eew_alert_sound_repeat = int(self.jma_eew_alert_sound_repeat)
            except (TypeError, ValueError):
                self.jma_eew_alert_sound_repeat = 2
            self.felt_sound_repeat = max(1, min(10, self.felt_sound_repeat))
            self.critical_sound_repeat = max(1, min(10, self.critical_sound_repeat))
            self.ciev_sound_repeat = max(1, min(10, self.ciev_sound_repeat))
            self.nhk_news_bell_repeat = max(1, min(10, self.nhk_news_bell_repeat))
            self.jma_eew_alert_sound_repeat = max(1, min(10, self.jma_eew_alert_sound_repeat))
            self.alert_feedback_mode = (self.alert_feedback_mode or "sound").strip().lower()
            if self.alert_feedback_mode not in ("sound", "tts"):
                self.alert_feedback_mode = "sound"
            try:
                self.felt_tts_repeat = int(self.felt_tts_repeat)
            except (TypeError, ValueError):
                self.felt_tts_repeat = 1
            try:
                self.critical_tts_repeat = int(self.critical_tts_repeat)
            except (TypeError, ValueError):
                self.critical_tts_repeat = 1
            try:
                self.report_tts_repeat = int(self.report_tts_repeat)
            except (TypeError, ValueError):
                self.report_tts_repeat = 1
            try:
                self.weather_tts_repeat = int(self.weather_tts_repeat)
            except (TypeError, ValueError):
                self.weather_tts_repeat = 1
            try:
                self.tsunami_tts_repeat = int(self.tsunami_tts_repeat)
            except (TypeError, ValueError):
                self.tsunami_tts_repeat = 1
            self.felt_tts_repeat = max(1, min(10, self.felt_tts_repeat))
            self.critical_tts_repeat = max(1, min(10, self.critical_tts_repeat))
            self.report_tts_repeat = max(1, min(10, self.report_tts_repeat))
            self.weather_tts_repeat = max(1, min(10, self.weather_tts_repeat))
            self.tsunami_tts_repeat = max(1, min(10, self.tsunami_tts_repeat))
            self.tts_playback_mode = (self.tts_playback_mode or "supplement").strip().lower()
            if self.tts_playback_mode not in ("supplement", "replace"):
                self.tts_playback_mode = "supplement"
            self.tts_voice = (self.tts_voice or "").strip()
            self.tts_repeat_policy = (self.tts_repeat_policy or "smart").strip().lower()
            if self.tts_repeat_policy not in ("smart", "first_only", "always"):
                self.tts_repeat_policy = "smart"
            self.warning_feedback_policy = (
                self.warning_feedback_policy or "first_received"
            ).strip().lower()
            if self.warning_feedback_policy in ("first_report_only", "first_only"):
                self.warning_feedback_policy = "first_received"
            if self.warning_feedback_policy not in ("smart", "first_received"):
                self.warning_feedback_policy = "first_received"
            try:
                self.tts_rate = int(self.tts_rate)
            except (TypeError, ValueError):
                self.tts_rate = 150
            self.tts_rate = max(80, min(300, self.tts_rate))
            try:
                self.tts_cooldown_seconds = int(self.tts_cooldown_seconds)
            except (TypeError, ValueError):
                self.tts_cooldown_seconds = 60
            self.tts_cooldown_seconds = max(0, min(600, self.tts_cooldown_seconds))
            return True
        except Exception as e:
            logger.error(f"告警配置验证失败: {e}")
            return False


@dataclass
class WebSocketConfig:
    """WebSocket配置类"""
    reconnect_interval: int = 5
    max_reconnect_attempts: int = -1
    ping_interval: int = 30
    ping_timeout: int = 10
    close_timeout: int = 5
    connection_timeout: int = 10
    # 启动时相邻两路 WebSocket 建连任务之间的间隔（秒），0 表示不间隔（与旧版同时发起）
    startup_stagger_seconds: float = 1.5
    # Fan Studio /all 用户 API Key（sk-…）；未填写时仍可连上，但仅收到公开精简数据流
    fanstudio_api_key: str = ""
    # 无界科技 WAuth 令牌（wat_…）；建连后以纯文本首帧发送，须在 5 秒内
    whews_token: str = ""
    # CEA App 凭证由内置模块注入（公开版不对外暴露设置项；连接 /ws/cea_all）
    whews_cea_app_id: str = ""
    whews_cea_app_secret: str = ""
    # EQSC 登录密钥（https://equake.top/auth）；软件内自动换取 Refresh/Access Token
    eqsc_login_token: str = ""
    # WeJet 主机：api.beecld.com（默认）/ api.2v8.cn（国内，CEA）
    whews_host: str = WHEWS_HOST_PRIMARY

    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            assert self.reconnect_interval > 0, "重连间隔必须大于0"
            assert self.max_reconnect_attempts >= -1, "最大重连次数必须≥-1"
            assert self.ping_interval > 0, "心跳间隔必须大于0"
            assert self.ping_timeout > 0, "心跳超时必须大于0"
            assert self.close_timeout > 0, "关闭超时必须大于0"
            assert self.connection_timeout > 0, "连接超时必须大于0"
            assert self.startup_stagger_seconds >= 0, "启动建连间隔不能为负"
            self.whews_host = normalize_whews_host(getattr(self, "whews_host", WHEWS_HOST_PRIMARY))
            return True
        except AssertionError as e:
            logger.error(f"WebSocket配置验证失败: {e}")
            return False


@dataclass
class TranslationConfig:
    """地名处理配置：地名修正与百度翻译二选一。"""
    use_place_name_fix: bool = True  # 国外数据源优先 FE 地名修正（与百度翻译互斥）；CENC/CWA/JMA/HKO/P2P 保留原文
    enabled: bool = False  # 非中文数据源使用百度翻译（与地名修正互斥）
    baidu_app_id: str = ""  # 百度翻译开放平台 AppID
    baidu_secret: str = ""  # 百度翻译开放平台密钥
    # 兼容旧版配置（仅加载时使用，不再持久化）
    use_volcano_translation: bool = False

    def validate(self) -> bool:
        """验证配置有效性，并强制地名修正与百度翻译互斥。"""
        if self.enabled and self.use_place_name_fix:
            self.use_place_name_fix = False
        if self.enabled and not self.baidu_app_id.strip():
            logger.warning("百度翻译已启用但未配置 AppID，翻译功能将不可用")
        if self.enabled and not self.baidu_secret.strip():
            logger.warning("百度翻译已启用但未配置密钥，翻译功能将不可用")
        return True


@dataclass
class LogConfig:
    """日志配置类"""
    output_to_file: bool = True  # 是否输出日志到文件（默认开启）
    clear_log_on_startup: bool = True  # 每次程序启动前是否清空日志（默认开启）
    split_by_date: bool = False  # 是否按日期分割日志（默认关闭）
    max_log_size: int = 10  # 日志文件最大大小（MB，默认10MB）
    
    def validate(self) -> bool:
        """验证配置有效性"""
        try:
            assert self.max_log_size > 0, "日志大小必须大于0"
            assert self.max_log_size <= 1000, "日志大小不能超过1000MB"
            return True
        except AssertionError as e:
            logger.error(f"日志配置验证失败: {e}")
            return False


class Config:
    """配置管理类 - 单例模式，支持动态重载"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Config, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        # 配置实例
        self.gui_config = GUIConfig()  # GUI 相关配置
        self.message_config = MessageConfig()
        self.alert_config = AlertConfig()
        self.ws_config = WebSocketConfig()
        self.translation_config = TranslationConfig()
        self.log_config = LogConfig()

        # 数据源配置
        # 当前选用的数据源提供者：fanstudio / whews（二选一，设置页顶部切换）
        self.data_provider: str = DATA_PROVIDER_JIAN
        self.enabled_sources: Dict[str, bool] = {}
        self.ws_urls: List[str] = []
        self.custom_data_source_url: str = ""  # 自定义数据源 URL（http/https/ws/wss），空为关闭
        self.custom_data_source_insecure_ssl: bool = False  # 自定义 HTTP 源跳过 SSL 证书校验
        self.http_poll_intervals: Dict[str, int] = dict(DEFAULT_HTTP_POLL_INTERVALS)
        
        # 配置变更回调
        self._config_callbacks: List[Callable] = []
        
        # 配置文件路径：C:\Users\账户名\AppData\Roaming\subtitl\settings.json
        # 日志文件：C:\Users\账户名\AppData\Roaming\subtitl\log.txt（或log_YYYYMMDD.txt）
        # 翻译缓存：C:\Users\账户名\AppData\Roaming\subtitl\translation_cache.json
        # 注意：日志文件和翻译缓存都在同一个文件夹（subtitl目录）中
        try:
            config_dir = Path.home() / 'AppData' / 'Roaming' / 'subtitl'
            
            # 如果目录不存在，自动创建（使用try-except避免阻塞）
            if not config_dir.exists():
                try:
                    config_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"已创建配置目录: {config_dir}")
                except (OSError, PermissionError) as e:
                    logger.warning(f"无法创建配置目录 {config_dir}: {e}，使用默认配置")
            else:
                logger.debug(f"配置目录已存在: {config_dir}")
            
            self.config_file = config_dir / 'settings.json'
        except Exception as e:
            logger.error(f"配置目录初始化失败: {e}，使用默认配置")
            self.config_file = None
        
        # 加载配置（使用try-except避免阻塞）
        try:
            self.load_config()
        except Exception as e:
            logger.error(f"配置加载失败: {e}，使用默认配置")
            self._apply_default_config()
            self._maybe_auto_match_performance_mode(had_saved_performance_mode=False)
        
        self._initialized = True
        logger.debug("配置管理器初始化完成")
    
    def add_config_callback(self, callback: Callable):
        """添加配置变更回调"""
        self._config_callbacks.append(callback)
    
    def remove_config_callback(self, callback: Callable):
        """移除配置变更回调"""
        if callback in self._config_callbacks:
            self._config_callbacks.remove(callback)
    
    def _notify_config_changed(self):
        """通知配置变更"""
        for callback in self._config_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"配置变更回调执行失败: {e}")
    
    def _get_full_config_dict(self) -> Dict[str, Any]:
        """根据当前内存中的各 config 对象生成完整配置 dict（与 save 结构一致）"""
        try:
            from utils.whews_cea_builtin import apply_builtin_whews_cea_credentials

            apply_builtin_whews_cea_credentials(self.ws_config)
        except Exception:
            pass
        return {
            'config_version': APP_VERSION,
            'GUI_CONFIG': {
                'font_size': self.gui_config.font_size,
                'font_family': self.gui_config.font_family,
                'font_bold': self.gui_config.font_bold,
                'font_italic': self.gui_config.font_italic,
                'text_speed': self.gui_config.text_speed,
                'bg_color': self.gui_config.bg_color,
                'info_color': self.gui_config.info_color,
                'opacity': self.gui_config.opacity,
                'window_width': self.gui_config.window_width,
                'window_height': self.gui_config.window_height,
                'window_x': getattr(self.gui_config, 'window_x', -1),
                'window_y': getattr(self.gui_config, 'window_y', -1),
                'resizable': self.gui_config.resizable,
                'vsync_enabled': self.gui_config.vsync_enabled,
                'target_fps': self.gui_config.target_fps,
                'timezone': self.gui_config.timezone,
                'last_seen_changelog_version': self.gui_config.last_seen_changelog_version,
                'use_gpu_rendering': self.gui_config.use_gpu_rendering,
                'render_backend': self.gui_config.render_backend,
                'always_on_top': self.gui_config.always_on_top,
                'borderless': getattr(self.gui_config, 'borderless', False),
                'background_image_path': getattr(self.gui_config, 'background_image_path', "") or "",
                'background_blur_radius': int(getattr(self.gui_config, 'background_blur_radius', 12) or 0),
                'background_overlay_opacity': float(
                    getattr(self.gui_config, 'background_overlay_opacity', 0.35) or 0.0
                ),
                'watermark_text': self.gui_config.watermark_text,
                'watermark_angle': self.gui_config.watermark_angle,
                'watermark_font_family': getattr(self.gui_config, 'watermark_font_family', ""),
                'watermark_font_size': getattr(self.gui_config, 'watermark_font_size', 0),
                'watermark_position': getattr(self.gui_config, 'watermark_position', "diagonal"),
                'auto_update_check_on_startup': getattr(self.gui_config, 'auto_update_check_on_startup', True),
                'auto_update_upgrade_only': getattr(self.gui_config, 'auto_update_upgrade_only', True),
                'auto_update_manifest_url': getattr(self.gui_config, 'auto_update_manifest_url', "") or AUTO_UPDATE_MANIFEST_URL_DEFAULT,
                'auto_update_timeout_seconds': getattr(self.gui_config, 'auto_update_timeout_seconds', 15),
                'auto_update_package_kind': getattr(self.gui_config, 'auto_update_package_kind', "installer"),
                'last_dismissed_update_offer_version': getattr(
                    self.gui_config, 'last_dismissed_update_offer_version', ""
                ),
                'minimize_to_tray': getattr(self.gui_config, 'minimize_to_tray', False),
                'toast_notifications_enabled': getattr(
                    self.gui_config, 'toast_notifications_enabled', False
                ),
                'performance_mode': getattr(self.gui_config, 'performance_mode', 'medium'),
                'image_cache_max': getattr(self.gui_config, 'image_cache_max', 16),
                'text_texture_cache_max': getattr(self.gui_config, 'text_texture_cache_max', 10),
                'opengl_msaa_samples': getattr(self.gui_config, 'opengl_msaa_samples', 0),
                'auto_save_settings': getattr(self.gui_config, 'auto_save_settings', False),
            },
            'MESSAGE_CONFIG': {
                'max_message_length': self.message_config.max_message_length,
                'display_duration': self.message_config.display_duration,
                'max_warning_inactivity_time': self.message_config.max_warning_inactivity_time,
                'warning_shock_validity_seconds': self.message_config.warning_shock_validity_seconds,
                'warning_shock_validity_seconds_nied': getattr(
                    self.message_config,
                    'warning_shock_validity_seconds_nied',
                    self.message_config.warning_shock_validity_seconds,
                ),
                'warning_shock_validity_seconds_early_est': getattr(
                    self.message_config,
                    'warning_shock_validity_seconds_early_est',
                    max(
                        self.message_config.warning_shock_validity_seconds,
                        getattr(
                            self.message_config,
                            'warning_shock_validity_seconds_nied',
                            self.message_config.warning_shock_validity_seconds,
                        ),
                    ),
                ),
                'warning_min_display_seconds': self.message_config.warning_min_display_seconds,
                'disable_warning_expiry_for_test': getattr(
                    self.message_config, "disable_warning_expiry_for_test", False
                ),
                'max_report_inactivity_time': self.message_config.max_report_inactivity_time,
                'max_other_inactivity_time': self.message_config.max_other_inactivity_time,
                'message_queue_maxsize': getattr(self.message_config, 'message_queue_maxsize', 100),
                'message_buffer_max_size': getattr(self.message_config, 'message_buffer_max_size', 40),
                'no_activity_message': self.message_config.no_activity_message,
                'custom_text': self.message_config.custom_text,
                'use_custom_text': self.message_config.use_custom_text,
                'fanstudio_parse_warning': self.message_config.fanstudio_parse_warning,
                'fanstudio_parse_report': self.message_config.fanstudio_parse_report,
                'ali_all_parse_nied': getattr(self.message_config, 'ali_all_parse_nied', True),
                'ali_all_parse_early_est': getattr(self.message_config, 'ali_all_parse_early_est', True),
                'ali_all_parse_jma_volcano': getattr(self.message_config, 'ali_all_parse_jma_volcano', True),
                'ali_all_parse_bmkg': getattr(self.message_config, 'ali_all_parse_bmkg', True),
                'ali_all_parse_cq_eew': getattr(self.message_config, 'ali_all_parse_cq_eew', True),
                'eqsc_parse_jma_eew': getattr(self.message_config, 'eqsc_parse_jma_eew', True),
                'eqsc_parse_jma_report': getattr(self.message_config, 'eqsc_parse_jma_report', True),
                'eqsc_parse_jma_tsunami': getattr(self.message_config, 'eqsc_parse_jma_tsunami', True),
                'eqsc_parse_cenc': getattr(self.message_config, 'eqsc_parse_cenc', True),
                'eqsc_parse_cenc_ir': getattr(self.message_config, 'eqsc_parse_cenc_ir', True),
                'eqsc_parse_cwa': getattr(self.message_config, 'eqsc_parse_cwa', True),
                'eqsc_parse_hko': getattr(self.message_config, 'eqsc_parse_hko', True),
                'eqsc_parse_usgs': getattr(self.message_config, 'eqsc_parse_usgs', True),
                'eqsc_parse_emsc': getattr(self.message_config, 'eqsc_parse_emsc', True),
                'eqsc_parse_typhoon': getattr(self.message_config, 'eqsc_parse_typhoon', True),
                'eqsc_parse_volcano': getattr(self.message_config, 'eqsc_parse_volcano', False),
                'p2pquake_parse_551': getattr(self.message_config, 'p2pquake_parse_551', True),
                'p2pquake_parse_552': getattr(self.message_config, 'p2pquake_parse_552', True),
                'p2pquake_parse_556': getattr(self.message_config, 'p2pquake_parse_556', True),
                'openquake_parse_gq': getattr(self.message_config, 'openquake_parse_gq', True),
                'openquake_parse_nmefc': getattr(self.message_config, 'openquake_parse_nmefc', True),
                'openquake_parse_nmefc_wave': getattr(
                    self.message_config, 'openquake_parse_nmefc_wave', True
                ),
                'openquake_parse_nmefc_surge': getattr(
                    self.message_config, 'openquake_parse_nmefc_surge', True
                ),
                'openquake_parse_cma': getattr(self.message_config, 'openquake_parse_cma', True),
                'openquake_gq_min_magnitude': float(
                    getattr(self.message_config, 'openquake_gq_min_magnitude', 4.5) or 0.0
                ),
                'warning_color': self.message_config.warning_color,
                'report_color': self.message_config.report_color,
                'custom_text_color': self.message_config.custom_text_color,
                'default_color': self.message_config.default_color,
                'weather_warning_color': self.message_config.weather_warning_color,
                'show_one_alert_per_received': self.message_config.show_one_alert_per_received,
                'force_single_line': getattr(self.message_config, 'force_single_line', True),
                'custom_text_return_after_warning': getattr(self.message_config, 'custom_text_return_after_warning', False),
                'custom_text_return_seconds': getattr(self.message_config, 'custom_text_return_seconds', 300),
                'enable_china_intensity': getattr(self.message_config, 'enable_china_intensity', False),
                'enable_felt_alert_flow': getattr(self.message_config, 'enable_felt_alert_flow', False),
                'enable_strong_felt_alert_flow': getattr(self.message_config, 'enable_strong_felt_alert_flow', True),
                'felt_alert_stage1_ms': getattr(self.message_config, 'felt_alert_stage1_ms', 1500),
                'felt_alert_stage2_ms': getattr(self.message_config, 'felt_alert_stage2_ms', 2500),
                'strong_felt_stage1_ms': getattr(self.message_config, 'strong_felt_stage1_ms', 1500),
                'strong_felt_stage2_ms': getattr(self.message_config, 'strong_felt_stage2_ms', 2500),
                'alert_flash_interval_ms': getattr(self.message_config, 'alert_flash_interval_ms', 400),
                # Fan Studio 子源细粒度开关
                'fanstudio_parse_cea': getattr(self.message_config, 'fanstudio_parse_cea', True),
                'fanstudio_parse_cea_pr': getattr(self.message_config, 'fanstudio_parse_cea_pr', True),
                'fanstudio_parse_cwa_eew': getattr(self.message_config, 'fanstudio_parse_cwa_eew', True),
                'fanstudio_parse_jma': getattr(self.message_config, 'fanstudio_parse_jma', True),
                'fanstudio_parse_sa': getattr(self.message_config, 'fanstudio_parse_sa', True),
                'fanstudio_parse_kma_eew': getattr(self.message_config, 'fanstudio_parse_kma_eew', True),
                'fanstudio_parse_cenc': getattr(self.message_config, 'fanstudio_parse_cenc', True),
                'fanstudio_parse_ningxia': getattr(self.message_config, 'fanstudio_parse_ningxia', True),
                'fanstudio_parse_guangxi': getattr(self.message_config, 'fanstudio_parse_guangxi', True),
                'fanstudio_parse_shanxi': getattr(self.message_config, 'fanstudio_parse_shanxi', True),
                'fanstudio_parse_beijing': getattr(self.message_config, 'fanstudio_parse_beijing', True),
                'fanstudio_parse_yunnan': getattr(self.message_config, 'fanstudio_parse_yunnan', True),
                'fanstudio_parse_cwa': getattr(self.message_config, 'fanstudio_parse_cwa', True),
                'fanstudio_parse_hko': getattr(self.message_config, 'fanstudio_parse_hko', True),
                'fanstudio_parse_usgs': getattr(self.message_config, 'fanstudio_parse_usgs', True),
                'fanstudio_parse_emsc': getattr(self.message_config, 'fanstudio_parse_emsc', True),
                'fanstudio_parse_bcsf': getattr(self.message_config, 'fanstudio_parse_bcsf', True),
                'fanstudio_parse_gfz': getattr(self.message_config, 'fanstudio_parse_gfz', True),
                'fanstudio_parse_usp': getattr(self.message_config, 'fanstudio_parse_usp', True),
                'fanstudio_parse_kma': getattr(self.message_config, 'fanstudio_parse_kma', True),
                'fanstudio_parse_fssn': getattr(self.message_config, 'fanstudio_parse_fssn', True),
                'fanstudio_parse_fssn_cmt': getattr(self.message_config, 'fanstudio_parse_fssn_cmt', True),
                'fanstudio_parse_weatheralarm': getattr(self.message_config, 'fanstudio_parse_weatheralarm', True),
                'fanstudio_parse_tsunami': getattr(self.message_config, 'fanstudio_parse_tsunami', True),
                'whews_parse_jma_eew': getattr(self.message_config, 'whews_parse_jma_eew', True),
                'whews_parse_jma': getattr(self.message_config, 'whews_parse_jma', True),
                'whews_parse_cwa_eew': getattr(self.message_config, 'whews_parse_cwa_eew', True),
                'whews_parse_sa_eew': getattr(self.message_config, 'whews_parse_sa_eew', True),
                'whews_parse_cea': getattr(self.message_config, 'whews_parse_cea', True),
                'whews_parse_cea_pr': getattr(self.message_config, 'whews_parse_cea_pr', True),
                'whews_parse_cenc': getattr(self.message_config, 'whews_parse_cenc', True),
                'whews_parse_cwa': getattr(self.message_config, 'whews_parse_cwa', True),
                'whews_parse_hko': getattr(self.message_config, 'whews_parse_hko', True),
                'whews_parse_usgs': getattr(self.message_config, 'whews_parse_usgs', True),
                'whews_parse_emsc': getattr(self.message_config, 'whews_parse_emsc', True),
                'whews_parse_bcsf': getattr(self.message_config, 'whews_parse_bcsf', True),
                'whews_parse_gfz': getattr(self.message_config, 'whews_parse_gfz', True),
                'whews_parse_usp': getattr(self.message_config, 'whews_parse_usp', True),
                'whews_parse_kma': getattr(self.message_config, 'whews_parse_kma', True),
                'whews_parse_bmkg': getattr(self.message_config, 'whews_parse_bmkg', True),
                'whews_parse_geonet': getattr(self.message_config, 'whews_parse_geonet', True),
                'whews_parse_tmd': getattr(self.message_config, 'whews_parse_tmd', True),
                'whews_parse_ingv': getattr(self.message_config, 'whews_parse_ingv', True),
                'whews_parse_nrcan': getattr(self.message_config, 'whews_parse_nrcan', True),
                'whews_parse_mmd': getattr(self.message_config, 'whews_parse_mmd', True),
                'whews_parse_kma_eew': getattr(self.message_config, 'whews_parse_kma_eew', True),
                'whews_parse_beijing': getattr(self.message_config, 'whews_parse_beijing', True),
                'whews_parse_yunnan': getattr(self.message_config, 'whews_parse_yunnan', True),
                'whews_parse_ningxia': getattr(self.message_config, 'whews_parse_ningxia', True),
                'whews_parse_jma_volcano': getattr(self.message_config, 'whews_parse_jma_volcano', True),
                'whews_parse_tsunami': getattr(self.message_config, 'whews_parse_tsunami', True),
                'whews_parse_weatheralarm': getattr(self.message_config, 'whews_parse_weatheralarm', True),
                'whews_parse_phivolcs': getattr(self.message_config, 'whews_parse_phivolcs', True),
                'whews_parse_sgc': getattr(self.message_config, 'whews_parse_sgc', True),
                'whews_parse_ga': getattr(self.message_config, 'whews_parse_ga', True),
                'whews_parse_cenais': getattr(self.message_config, 'whews_parse_cenais', True),
                'whews_parse_ntwc': getattr(self.message_config, 'whews_parse_ntwc', True),
                'whews_parse_ptwc': getattr(self.message_config, 'whews_parse_ptwc', True),
                'whews_parse_incois': getattr(self.message_config, 'whews_parse_incois', True),
                'whews_parse_jma_tsunami': getattr(self.message_config, 'whews_parse_jma_tsunami', True),
                'whews_parse_gsras': getattr(self.message_config, 'whews_parse_gsras', True),
                'whews_parse_bgs': getattr(self.message_config, 'whews_parse_bgs', True),
                'whews_parse_ipma': getattr(self.message_config, 'whews_parse_ipma', True),
                'whews_parse_ssn': getattr(self.message_config, 'whews_parse_ssn', True),
                'whews_parse_afad': getattr(self.message_config, 'whews_parse_afad', True),
                'whews_parse_sed': getattr(self.message_config, 'whews_parse_sed', True),
                'whews_parse_noa': getattr(self.message_config, 'whews_parse_noa', True),
                'whews_parse_scsn': getattr(self.message_config, 'whews_parse_scsn', True),
                'whews_parse_iag': getattr(self.message_config, 'whews_parse_iag', True),
                'whews_parse_igp': getattr(self.message_config, 'whews_parse_igp', True),
                'whews_parse_nepal': getattr(self.message_config, 'whews_parse_nepal', True),
                'whews_parse_typhoon': getattr(self.message_config, 'whews_parse_typhoon', False),
                'jian_parse_cea': getattr(self.message_config, 'jian_parse_cea', True),
                'jian_parse_cwa_eew': getattr(self.message_config, 'jian_parse_cwa_eew', True),
                'jian_parse_jma_eew': getattr(self.message_config, 'jian_parse_jma_eew', True),
                'jian_parse_sa': getattr(self.message_config, 'jian_parse_sa', True),
                'jian_parse_kma_eew': getattr(self.message_config, 'jian_parse_kma_eew', True),
                'jian_parse_early_est': getattr(self.message_config, 'jian_parse_early_est', True),
                'jian_parse_cenc': getattr(self.message_config, 'jian_parse_cenc', True),
                'jian_parse_cwa': getattr(self.message_config, 'jian_parse_cwa', True),
                'jian_parse_jma': getattr(self.message_config, 'jian_parse_jma', True),
                'jian_parse_hko': getattr(self.message_config, 'jian_parse_hko', True),
                'jian_parse_tmd': getattr(self.message_config, 'jian_parse_tmd', True),
                'jian_parse_mmd': getattr(self.message_config, 'jian_parse_mmd', True),
                'jian_parse_bmkg': getattr(self.message_config, 'jian_parse_bmkg', True),
                'jian_parse_geonet': getattr(self.message_config, 'jian_parse_geonet', True),
                'jian_parse_usgs': getattr(self.message_config, 'jian_parse_usgs', True),
                'jian_parse_emsc': getattr(self.message_config, 'jian_parse_emsc', True),
                'jian_parse_gfz': getattr(self.message_config, 'jian_parse_gfz', True),
                'jian_parse_bcsf': getattr(self.message_config, 'jian_parse_bcsf', True),
                'jian_parse_ingv': getattr(self.message_config, 'jian_parse_ingv', True),
                'jian_parse_usp': getattr(self.message_config, 'jian_parse_usp', True),
                'jian_parse_nrcan': getattr(self.message_config, 'jian_parse_nrcan', True),
                'jian_parse_afad': getattr(self.message_config, 'jian_parse_afad', True),
                'jian_parse_kma': getattr(self.message_config, 'jian_parse_kma', True),
                'min_report_magnitude': getattr(self.message_config, 'min_report_magnitude', 0.0),
                'geo_filter_enabled': getattr(self.message_config, 'geo_filter_enabled', False),
                'geo_filter_latitude': getattr(self.message_config, 'geo_filter_latitude', 39.9042),
                'geo_filter_longitude': getattr(self.message_config, 'geo_filter_longitude', 116.4074),
                'geo_filter_radius_km': getattr(self.message_config, 'geo_filter_radius_km', 1000.0),
                'weather_region_filter_enabled': getattr(
                    self.message_config, 'weather_region_filter_enabled', False
                ),
                'weather_region_filter': getattr(self.message_config, 'weather_region_filter', '') or '',
                'weather_level_filter': getattr(self.message_config, 'weather_level_filter', 'none') or 'none',
            },
            'ALERT_CONFIG': {
                'enabled': self.alert_config.enabled,
                'min_magnitude': self.alert_config.min_magnitude,
                'flash_interval_ms': self.alert_config.flash_interval_ms,
                'flash_scope': self.alert_config.flash_scope,
                'flash_target_screen': self.alert_config.flash_target_screen,
                'flash_color': self.alert_config.flash_color,
                'flash_max_alpha': self.alert_config.flash_max_alpha,
                'sound_enabled': getattr(self.alert_config, 'sound_enabled', False),
                'sound_path': getattr(self.alert_config, 'sound_path', ''),
                'sound_volume': getattr(self.alert_config, 'sound_volume', 100),
                'sound_warnings_only': getattr(self.alert_config, 'sound_warnings_only', True),
                'felt_sound_enabled': getattr(self.alert_config, 'felt_sound_enabled', False),
                'felt_sound_path': getattr(self.alert_config, 'felt_sound_path', ''),
                'felt_sound_repeat': getattr(self.alert_config, 'felt_sound_repeat', 1),
                'critical_sound_enabled': getattr(self.alert_config, 'critical_sound_enabled', False),
                'critical_sound_path': getattr(self.alert_config, 'critical_sound_path', ''),
                'critical_sound_repeat': getattr(self.alert_config, 'critical_sound_repeat', 1),
                'ciev_sound_enabled': getattr(self.alert_config, 'ciev_sound_enabled', False),
                'ciev_sound_path': getattr(self.alert_config, 'ciev_sound_path', ''),
                'ciev_sound_repeat': getattr(self.alert_config, 'ciev_sound_repeat', 1),
                'nhk_news_bell_enabled': getattr(self.alert_config, 'nhk_news_bell_enabled', False),
                'nhk_news_bell_path': getattr(self.alert_config, 'nhk_news_bell_path', ''),
                'nhk_news_bell_repeat': getattr(self.alert_config, 'nhk_news_bell_repeat', 1),
                'jma_eew_alert_sound_enabled': getattr(self.alert_config, 'jma_eew_alert_sound_enabled', True),
                'jma_eew_alert_sound_path': getattr(self.alert_config, 'jma_eew_alert_sound_path', ''),
                'jma_eew_alert_sound_repeat': getattr(self.alert_config, 'jma_eew_alert_sound_repeat', 2),
                'alert_feedback_mode': getattr(self.alert_config, 'alert_feedback_mode', 'sound'),
                'felt_tts_enabled': getattr(self.alert_config, 'felt_tts_enabled', False),
                'critical_tts_enabled': getattr(self.alert_config, 'critical_tts_enabled', False),
                'felt_tts_repeat': getattr(self.alert_config, 'felt_tts_repeat', 1),
                'critical_tts_repeat': getattr(self.alert_config, 'critical_tts_repeat', 1),
                'report_tts_enabled': getattr(self.alert_config, 'report_tts_enabled', True),
                'report_tts_repeat': getattr(self.alert_config, 'report_tts_repeat', 1),
                'weather_tts_enabled': getattr(self.alert_config, 'weather_tts_enabled', True),
                'weather_tts_repeat': getattr(self.alert_config, 'weather_tts_repeat', 1),
                'tsunami_tts_enabled': getattr(self.alert_config, 'tsunami_tts_enabled', True),
                'tsunami_tts_repeat': getattr(self.alert_config, 'tsunami_tts_repeat', 1),
                'tts_playback_mode': getattr(self.alert_config, 'tts_playback_mode', 'supplement'),
                'tts_rate': getattr(self.alert_config, 'tts_rate', 150),
                'tts_voice': getattr(self.alert_config, 'tts_voice', ''),
                'tts_include_safety_hint': getattr(self.alert_config, 'tts_include_safety_hint', True),
                'tts_repeat_policy': getattr(self.alert_config, 'tts_repeat_policy', 'smart'),
                'tts_cooldown_seconds': getattr(self.alert_config, 'tts_cooldown_seconds', 60),
                'warning_feedback_policy': getattr(
                    self.alert_config, 'warning_feedback_policy', 'first_received'
                ),
            },
            'WS_CONFIG': {
                'reconnect_interval': self.ws_config.reconnect_interval,
                'max_reconnect_attempts': self.ws_config.max_reconnect_attempts,
                'ping_interval': self.ws_config.ping_interval,
                'ping_timeout': self.ws_config.ping_timeout,
                'close_timeout': self.ws_config.close_timeout,
                'connection_timeout': self.ws_config.connection_timeout,
                'startup_stagger_seconds': self.ws_config.startup_stagger_seconds,
                'fanstudio_api_key': getattr(self.ws_config, 'fanstudio_api_key', '') or '',
                'whews_token': getattr(self.ws_config, 'whews_token', '') or '',
                'whews_cea_app_id': getattr(self.ws_config, 'whews_cea_app_id', '') or '',
                'whews_cea_app_secret': getattr(self.ws_config, 'whews_cea_app_secret', '') or '',
                'eqsc_login_token': getattr(self.ws_config, 'eqsc_login_token', '') or '',
                'whews_host': normalize_whews_host(
                    getattr(self.ws_config, 'whews_host', WHEWS_HOST_PRIMARY)
                ),
            },
            'TRANSLATION_CONFIG': {
                'use_place_name_fix': self.translation_config.use_place_name_fix,
                'enabled': self.translation_config.enabled,
                'baidu_app_id': getattr(self.translation_config, 'baidu_app_id', ''),
                'baidu_secret': getattr(self.translation_config, 'baidu_secret', ''),
            },
            'LOG_CONFIG': {
                'output_to_file': self.log_config.output_to_file,
                'clear_log_on_startup': self.log_config.clear_log_on_startup,
                'split_by_date': self.log_config.split_by_date,
                'max_log_size': self.log_config.max_log_size,
            },
            'DATA_PROVIDER': normalize_data_provider(getattr(self, 'data_provider', DATA_PROVIDER_FANSTUDIO)),
            'ENABLED_SOURCES': self._get_persisted_enabled_sources(),
            'CUSTOM_DATA_SOURCE_URL': self.custom_data_source_url,
            'CUSTOM_DATA_SOURCE_INSECURE_SSL': bool(
                getattr(self, 'custom_data_source_insecure_ssl', False)
            ),
            'HTTP_POLL_INTERVALS': dict(self.http_poll_intervals),
        }
    
    def _is_fanstudio_individual_url(self, url: str) -> bool:
        """是否为应剔除持久化的 Fan Studio 单项 URL（历史遗留：除 all 外的 path 源）。"""
        if not url or not isinstance(url, str):
            return False
        if "fanstudio.tech" not in url:
            return False
        # Fan Studio HTTP 源（如 typhoon.php）不应被视为“历史遗留的单项 URL”，
        # 它们需要持久化开关状态，否则用户关闭后重启会被恢复为默认启用。
        if url.startswith("http://") or url.startswith("https://"):
            return False
        nu = url.rstrip("/").lower()
        if nu == FANSTUDIO_ALL_URL.rstrip("/").lower():
            return False
        return True

    def _is_websocket_url(self, url: str) -> bool:
        """判断 URL 是否为 WebSocket 协议。"""
        return isinstance(url, str) and url.startswith(("ws://", "wss://"))

    def _sync_p2pquake_http_with_wss(self) -> None:
        """P2PQuake 以 WSS 为实时通道；HTTP 键强制关闭，避免 HTTPPollingManager 持续轮询。
        启动补拉由 WebSocketManager._fetch_p2p_initial_http 单独完成。
        """
        self._migrate_p2pquake_http_keys()
        for u in P2PQUAKE_HTTP_SOURCE_KEYS:
            self.enabled_sources[u] = False

    def _migrate_p2pquake_http_keys(self) -> None:
        """将旧版 P2PQuake HTTP 键迁移为聚合 history URL，并清理废弃键。"""
        legacy_keys = [
            "https://api.p2pquake.net/v2/history?codes=551&limit=3",
            "https://api.p2pquake.net/v2/jma/tsunami?limit=1",
        ]
        for key in legacy_keys:
            self.enabled_sources.pop(key, None)
            self.http_poll_intervals.pop(key, None)
        agg = P2PQUAKE_HISTORY_AGGREGATE_URL
        if agg not in self.enabled_sources:
            self.enabled_sources[agg] = False
        if agg not in self.http_poll_intervals:
            self.http_poll_intervals[agg] = DEFAULT_HTTP_POLL_INTERVALS.get(agg, 2)

    def _disable_eqsc_ws(self) -> None:
        """EQSC 官方称 WebSocket 不稳定，强制关闭 WS 建连，仅用 HTTP。"""
        if EQSC_WS_URL in self.enabled_sources and self.enabled_sources.get(EQSC_WS_URL):
            logger.info("已关闭 EQSC WebSocket（改用 HTTP 轮询）")
        self.enabled_sources[EQSC_WS_URL] = False

    def _ensure_eqsc_http_defaults(self) -> None:
        """补全 EQSC HTTP 总开关与子源缺项；同步解析开关→启用状态；强制关 WS。"""
        # 旧配置若曾打开 WS，迁移为 HTTP 总开关
        if self.enabled_sources.pop(EQSC_WS_URL, False):
            if not self.enabled_sources.get(EQSC_HTTP_MASTER, False):
                self.enabled_sources[EQSC_HTTP_MASTER] = True
                logger.info("已将 EQSC WebSocket 开关迁移为 HTTP 总开关")
        self._disable_eqsc_ws()
        if EQSC_HTTP_MASTER not in self.enabled_sources:
            self.enabled_sources[EQSC_HTTP_MASTER] = False
        for url in EQSC_HTTP_SOURCE_KEYS:
            if url not in self.enabled_sources:
                self.enabled_sources[url] = False
        self._sync_eqsc_http_from_parse_flags()

    def _sync_eqsc_http_from_parse_flags(self) -> None:
        """按辅助总开关 + EQSC 总开关 + eqsc_parse_* 同步各 HTTP 子源。"""
        master = bool(
            aux_sources_enabled(self.enabled_sources)
            and self.enabled_sources.get(EQSC_HTTP_MASTER, False)
        )
        mc = self.message_config
        for flag, url in EQSC_PARSE_FLAG_TO_URL.items():
            parse_on = bool(getattr(mc, flag, flag != "eqsc_parse_volcano"))
            self.enabled_sources[url] = bool(master and parse_on)
        self._disable_eqsc_ws()

    def _allowed_logical_source_keys(self) -> set:
        """允许持久化的逻辑开关键（非 ws/http URL）。"""
        return {
            JIAN_MASTER_KEY,
            WHEWS_MASTER_KEY,
            WOLFX_MASTER_KEY,
            AUX_SOURCES_MASTER_KEY,
            *JIAN_SUB_SOURCE_KEYS,
            *WOLFX_VIRTUAL_SOURCE_KEYS,
        }

    def _is_persisted_source_key(self, key: str) -> bool:
        """判断 enabled_sources 键是否应写入配置文件。"""
        if not isinstance(key, str) or not key:
            return False
        if key in self._allowed_logical_source_keys() or is_jian_logical_key(key):
            return True
        all_url = FANSTUDIO_ALL_URL
        allowed_ws = self._allowed_public_ws_urls()
        allowed_http = set(ALL_KNOWN_HTTP_SOURCE_KEYS)
        if key == all_url or not self._is_fanstudio_individual_url(key):
            if self._is_websocket_url(key):
                return key in allowed_ws
            return key in allowed_http
        return False

    def _allowed_public_ws_urls(self) -> set:
        """公开版允许持久化/连接的 WebSocket URL 集合。"""
        return {
            FANSTUDIO_ALL_URL,
            JIAN_PROJECT_ALL_URL,
            P2PQUAKE_WSS_URL,
            NOWQUAKE_CENCINT_WSS_URL,
            WOLFX_ALL_EEW_URL,
            WOLFX_CWA_EEW_URL,
            OPENQUAKE_WS_ALL_URL,
            *WOLFX_VIRTUAL_SOURCE_KEYS,
            *all_whews_ws_urls(),
        }

    def _enforce_public_ws_sources(self) -> List[str]:
        """
        公开版连接策略：仅保留 Fan Studio /all、无界科技、Wolfx/P2P 等公开 WebSocket，
        并仅保留已知 HTTP 拉取配置项。
        Returns:
            被移除的 URL 列表
        """
        allowed_ws = self._allowed_public_ws_urls()
        allowed_http = set(ALL_KNOWN_HTTP_SOURCE_KEYS)
        allowed_logical = self._allowed_logical_source_keys()
        removed: List[str] = []
        for url in list(self.enabled_sources.keys()):
            if url in allowed_logical or is_jian_logical_key(url):
                continue
            if self._is_websocket_url(url):
                # WeJet URL 常带 ?token=，与无 query 的白名单做路径级匹配
                if url in allowed_ws:
                    continue
                if is_whews_all_url(url) or is_whews_cea_all_endpoint(url):
                    continue
                if is_whews_url(url) and (
                    is_whews_dedicated_endpoint(url) or is_whews_cea_split_endpoint(url)
                ):
                    # 废弃/拆分线：删除键
                    removed.append(url)
                    del self.enabled_sources[url]
                    continue
                if is_whews_url(url):
                    continue
                removed.append(url)
                del self.enabled_sources[url]
                continue
            if url not in allowed_http:
                removed.append(url)
                del self.enabled_sources[url]
        return removed

    def _get_persisted_enabled_sources(self) -> Dict[str, bool]:
        """供保存到配置文件的 enabled_sources。"""
        return {
            k: v
            for k, v in self.enabled_sources.items()
            if self._is_persisted_source_key(k)
        }

    def _ensure_whews_source_defaults(self) -> None:
        """补全无界科技 WebSocket 开关缺项；迁移 URL 键 → WHEWS_MASTER_KEY。"""
        self._migrate_whews_url_keys_to_master()
        if WHEWS_MASTER_KEY not in self.enabled_sources:
            self.enabled_sources[WHEWS_MASTER_KEY] = False
        for url in all_whews_ws_urls():
            if url not in self.enabled_sources:
                self.enabled_sources[url] = False
        self._disable_whews_dedicated_endpoints()

    def _migrate_whews_url_keys_to_master(self) -> None:
        """将以 /ws/all URL（含 token 查询参数）为键的开关迁移为 WHEWS_MASTER_KEY。"""
        enabled = False
        for key, val in list(self.enabled_sources.items()):
            if not isinstance(key, str):
                continue
            if is_whews_all_url(key) and val:
                enabled = True
        if enabled:
            self.enabled_sources[WHEWS_MASTER_KEY] = True
        for key in list(self.enabled_sources.keys()):
            if isinstance(key, str) and is_whews_all_url(key):
                del self.enabled_sources[key]

    def _disable_whews_dedicated_endpoints(self) -> None:
        """强制关闭 cenc 与拆分 CEA 线；公开版仅允许 /ws/cea_all。"""
        for url in list(self.enabled_sources.keys()):
            if is_whews_dedicated_endpoint(url) or is_whews_cea_split_endpoint(url):
                if self.enabled_sources.get(url):
                    logger.info(f"已关闭 WeJet 专用端点（改走聚合通道）: {url}")
                self.enabled_sources[url] = False
        for url in all_whews_ws_urls():
            if is_whews_dedicated_endpoint(url) or is_whews_cea_split_endpoint(url):
                self.enabled_sources[url] = False
        # 注入内置 CEA 凭证；失败时关闭全部 cea_all
        if not whews_cea_app_configured(self.ws_config):
            for url in list(self.enabled_sources.keys()):
                if is_whews_cea_endpoint(url):
                    self.enabled_sources[url] = False
            for host in WHEWS_HOSTS:
                self.enabled_sources[whews_ws_url("cea_all", host)] = False
        else:
            # CEA 固定国内站：关掉主站上的 cea_all，避免双连
            primary_cea = whews_ws_url("cea_all", WHEWS_HOST_PRIMARY)
            self.enabled_sources[primary_cea] = False
            for url in list(self.enabled_sources.keys()):
                if is_whews_cea_all_endpoint(url) and WHEWS_HOST_BACKUP not in (url or "").lower():
                    self.enabled_sources[url] = False

    def get_whews_host(self) -> str:
        """返回当前无界科技主机。"""
        return normalize_whews_host(getattr(self.ws_config, "whews_host", WHEWS_HOST_PRIMARY))

    def get_whews_endpoint_urls(self, host: Any = None) -> Dict[str, str]:
        """WeJet 端点：/ws/all 跟所选主机；/ws/cea_all 始终走国内站。"""
        h = normalize_whews_host(host if host is not None else self.get_whews_host())
        token = (getattr(self.ws_config, "whews_token", "") or "").strip()
        urls = {"all": whews_ws_url("all", h, token=token)}
        if whews_cea_app_configured(self.ws_config):
            # CEA 仅国内站提供；与主站/国内站选择无关
            urls["cea_all"] = whews_ws_url("cea_all", WHEWS_HOST_BACKUP, token=token)
        return urls

    def get_active_data_provider(self) -> str:
        """返回当前规范化后的数据源提供者。"""
        return normalize_data_provider(getattr(self, "data_provider", DATA_PROVIDER_FANSTUDIO))

    def is_url_active_for_provider(self, url: str, provider: Optional[str] = None) -> bool:
        """判断 URL 是否属于当前（或指定）数据源提供者。P2PQuake / Nowquake / 台风 HTTP 始终可用。"""
        provider = normalize_data_provider(provider if provider is not None else self.get_active_data_provider())
        u = (url or "").strip()
        if not u:
            return False
        low = u.lower()
        # 辅助数据源（Wolfx / EQSC / P2PQuake / OpenQuakeAPI）：总开关关闭时不可用
        if u == P2PQUAKE_WSS_URL or "api.p2pquake.net" in low:
            return aux_sources_enabled(self.enabled_sources)
        if "equake.top" in low:
            return aux_sources_enabled(self.enabled_sources)
        if (
            "wolfx.jp" in low
            or u in WOLFX_VIRTUAL_SOURCE_KEYS
            or u == WOLFX_MASTER_KEY
        ):
            return aux_sources_enabled(self.enabled_sources)
        if u == OPENQUAKE_WS_ALL_URL or "api.aloys23.link" in low:
            return aux_sources_enabled(self.enabled_sources)
        # 自定义数据源：与主提供者无关，始终可用
        if is_custom_data_source_url(u, self):
            return True
        # CENC 烈度速报（Nowquake）：任意提供者下均可连接（不计入辅助三源）
        if u == NOWQUAKE_CENCINT_WSS_URL or "nowquake.cn" in low:
            return True
        # 台风 HTTP：任意提供者下均可轮询（全局，与主提供者/辅助三源解耦）
        if (
            u == FANSTUDIO_TYPHOON_HTTP
            or FANSTUDIO_TYPHOON_HTTP in u
            or "typhoon.php" in low
        ):
            return True
        if provider == DATA_PROVIDER_FANSTUDIO:
            return u == FANSTUDIO_ALL_URL or "fanstudio" in low
        if provider == DATA_PROVIDER_WHEWS:
            # /ws/all 跟所选主机；/ws/cea_all 固定国内站，二者均属 WeJet
            return (
                u == WHEWS_MASTER_KEY
                or is_whews_all_url(u)
                or is_whews_cea_all_endpoint(u)
            )
        if provider == DATA_PROVIDER_JIAN:
            return u == JIAN_MASTER_KEY or u == JIAN_PROJECT_ALL_URL or is_jian_project_url(u)
        if "fanstudio" in low or is_whews_url(u) or is_jian_project_url(u):
            return False
        return False

    def get_http_poll_interval(self, url: str) -> int:
        """获取指定 HTTP 数据源的轮询间隔（秒），最低 1 秒。"""
        if self.custom_data_source_url and url == self.custom_data_source_url:
            custom_key = "__custom_http__"
            if custom_key in self.http_poll_intervals:
                return max(1, int(self.http_poll_intervals[custom_key]))
            return 1
        lookup_url = fanstudio_http_canonical_key(url) if "api.fanstudio" in (url or "") else url
        try:
            val = self.http_poll_intervals.get(
                lookup_url, DEFAULT_HTTP_POLL_INTERVALS.get(lookup_url, 2)
            )
            return max(1, int(val))
        except (TypeError, ValueError):
            return max(1, DEFAULT_HTTP_POLL_INTERVALS.get(lookup_url, 2))

    def _ensure_http_poll_interval_defaults(self) -> None:
        """补全已知 HTTP 源的默认轮询间隔（不覆盖用户已设值）。"""
        for url, default_sec in DEFAULT_HTTP_POLL_INTERVALS.items():
            if url not in self.http_poll_intervals:
                self.http_poll_intervals[url] = default_sec
        if "__custom_http__" not in self.http_poll_intervals:
            self.http_poll_intervals["__custom_http__"] = 1

    def _ensure_jian_source_defaults(self) -> None:
        """补全 Jian Project 总开关缺项；迁移旧逻辑键到 jian_parse_*。"""
        self._remove_legacy_fanstudio_aqi()
        self._migrate_legacy_http_to_jian_logical_keys()
        self._migrate_jian_logical_keys_to_parse_flags()
        self._purge_obsolete_intl_http_config()
        if JIAN_MASTER_KEY not in self.enabled_sources:
            self.enabled_sources[JIAN_MASTER_KEY] = False
        if JIAN_PROJECT_ALL_URL in self.enabled_sources:
            if self.enabled_sources.pop(JIAN_PROJECT_ALL_URL, False):
                self.enabled_sources[JIAN_MASTER_KEY] = True
        for key in JIAN_SUB_SOURCE_KEYS:
            self.enabled_sources.pop(key, None)

    def _migrate_jian_logical_keys_to_parse_flags(self) -> bool:
        """将 jian://短名 连接开关迁移为 jian_parse_* 解析开关。"""
        migrated = False
        mc = self.message_config
        for short, flag in JIAN_SHORT_TO_PARSE_FLAG.items():
            logical = jian_logical_key(short)
            if self.enabled_sources.pop(logical, False):
                if hasattr(mc, flag):
                    setattr(mc, flag, True)
                    migrated = True
        if self.enabled_sources.pop(JIAN_MASTER_KEY, False):
            self.enabled_sources[JIAN_MASTER_KEY] = True
            if self.data_provider not in DATA_PROVIDERS or self.data_provider == DATA_PROVIDER_FANSTUDIO:
                self.data_provider = DATA_PROVIDER_JIAN
            migrated = True
        return migrated

    @staticmethod
    def _legacy_http_to_jian_logical_map() -> Dict[str, str]:
        """旧版国际 HTTP 开关键 → Jian 逻辑键（仅迁移用）。"""
        pairs = [
            ("bmkg", "data.bmkg.go.id"),
            ("geonet", "api.geonet.org.nz"),
            ("ingv", "terraquakeapi.com"),
            ("early-est", "early-est.rm.ingv.it"),
            ("usgs", "earthquake.usgs.gov"),
            ("hko", "weather.gov.hk"),
            ("gfz", "geofon.gfz.de"),
            ("usp", "moho.iag.usp.br"),
            ("cwa", "api.core.exptech.dev"),
            ("emsc", "seismicportal.eu"),
            ("tmd", "eq.tmd.go.th"),
            ("bcsf", "franceseisme.fr"),
            ("mmd", "mygempa.met.gov.my"),
            ("nrcan", "earthquakescanada.nrcan.gc.ca"),
            ("cenc", "dizhensubao.igexin.com"),
        ]
        out: Dict[str, str] = {}
        for short, marker in pairs:
            out[marker] = jian_logical_key(short)
        return out

    def _migrate_legacy_http_to_jian_logical_keys(self) -> None:
        """将遗留国际 HTTP 开关键迁移为 Jian 逻辑键。"""
        migrated = False
        marker_map = self._legacy_http_to_jian_logical_map()
        for key in list(self.enabled_sources.keys()):
            if not isinstance(key, str):
                continue
            low = key.lower()
            if not low.startswith(("http://", "https://")):
                continue
            logical = None
            for marker, lk in marker_map.items():
                if marker in low:
                    logical = lk
                    break
            if logical and self.enabled_sources.pop(key, False):
                self.enabled_sources[logical] = True
                migrated = True
        if migrated:
            logger.info("已将遗留国际 HTTP 开关键迁移为 Jian Project 解析开关")
        if self.data_provider == DATA_PROVIDER_OFFICIAL:
            self.data_provider = DATA_PROVIDER_FANSTUDIO
            logger.info(
                "已将主数据源「官方+Wolfx」迁移为 Fan Studio；"
                "国际速报请选用 Jian Project 主源，Wolfx 仅作辅助源"
            )

    def _purge_obsolete_intl_http_config(self) -> None:
        """移除已下线的国际 HTTP 配置残留（非 P2P / 台风 / EQSC / 自定义）。"""
        keep_markers = (
            "api.p2pquake.net",
            "api.fanstudio",
            "equake.top",
            "tsunami.gov",
            "kma.go.kr",
            "jma.go.jp/developer/xml/feed/eqvol",
        )
        removed = False
        for key in list(self.enabled_sources.keys()):
            if not isinstance(key, str):
                continue
            low = key.lower()
            if not low.startswith(("http://", "https://")):
                continue
            if any(m in low for m in keep_markers[:3]):
                continue
            if any(m in low for m in keep_markers[3:]):
                del self.enabled_sources[key]
                removed = True
                continue
            if any(m in low for m in (
                "bmkg.go.id", "geonet.org.nz", "terraquakeapi.com", "early-est.rm.ingv.it",
                "earthquake.usgs.gov", "weather.gov.hk", "geofon.gfz.de", "moho.iag.usp.br",
                "api.core.exptech.dev", "seismicportal.eu", "eq.tmd.go.th", "franceseisme.fr",
                "mygempa.met.gov.my", "earthquakescanada.nrcan.gc.ca", "dizhensubao.igexin.com",
            )):
                del self.enabled_sources[key]
                removed = True
        for key in list(self.http_poll_intervals.keys()):
            if not isinstance(key, str):
                continue
            low = key.lower()
            if low.startswith(("http://", "https://")) and not any(
                m in low for m in ("api.p2pquake.net", "api.fanstudio", "equake.top")
            ):
                del self.http_poll_intervals[key]
                removed = True
        if removed:
            logger.info("已清理遗留国际 HTTP 数据源配置项")

    def _ensure_wolfx_source_defaults(self) -> None:
        """补全 Wolfx 全局辅助源开关键；总开关与 all_eew 连接项保持一致。"""
        if WOLFX_MASTER_KEY not in self.enabled_sources:
            self.enabled_sources[WOLFX_MASTER_KEY] = bool(
                self.enabled_sources.get(WOLFX_ALL_EEW_URL, False)
            )
        list_needs_all = (
            self.enabled_sources.get(WOLFX_CENC_EQLIST_URL, False)
            or self.enabled_sources.get(WOLFX_JMA_EQLIST_URL, False)
        )
        master_on = bool(self.enabled_sources.get(WOLFX_MASTER_KEY, False))
        if list_needs_all:
            master_on = True
            self.enabled_sources[WOLFX_MASTER_KEY] = True
        self.enabled_sources[WOLFX_ALL_EEW_URL] = master_on
        for url in (WOLFX_CWA_EEW_URL, WOLFX_CENC_EQLIST_URL, WOLFX_JMA_EQLIST_URL):
            if url not in self.enabled_sources:
                self.enabled_sources[url] = False

    def _remove_legacy_fanstudio_aqi(self) -> None:
        """移除已下线的 Fan Studio 空气质量 HTTP 源配置残留。"""
        aqi_marker = "aqi.php"
        removed = False
        for key in list(self.enabled_sources.keys()):
            if isinstance(key, str) and aqi_marker in key.lower():
                del self.enabled_sources[key]
                removed = True
        for key in list(self.http_poll_intervals.keys()):
            if isinstance(key, str) and aqi_marker in key.lower():
                del self.http_poll_intervals[key]
                removed = True
        if removed:
            logger.info("已移除遗留的 Fan Studio 空气质量（aqi.php）HTTP 数据源配置")

    def _merge_config_file(self, existing: Dict[str, Any], full: Dict[str, Any]) -> Dict[str, Any]:
        """仅对 existing 做缺项补全：只补 full 中有而 existing 中没有的键，不删除 existing 中任何键。"""
        import copy
        merged = copy.deepcopy(existing)
        for key, full_value in full.items():
            if key not in merged:
                merged[key] = copy.deepcopy(full_value)
            elif isinstance(full_value, dict) and isinstance(merged.get(key), dict):
                # 嵌套 dict：只补全缺失的子键
                for subkey, subval in full_value.items():
                    if subkey not in merged[key]:
                        merged[key][subkey] = copy.deepcopy(subval)
        return merged
    
    def _has_missing_keys(self, existing: Dict[str, Any], full: Dict[str, Any]) -> bool:
        """检查 existing 是否缺少 full 中的键（用于决定是否写回补全后的配置）。"""
        for key in full:
            if key not in existing:
                return True
            if isinstance(full[key], dict) and isinstance(existing.get(key), dict):
                for subkey in full[key]:
                    if subkey not in existing[key]:
                        return True
        return False

    def _remove_legacy_jian_project_settings(self, config_data: Dict[str, Any]) -> bool:
        """
        清理 settings.json 中遗留的 Jian Project 配置项。
        返回值:
            True: 本次有清理动作
            False: 无需清理
        """
        changed = False
        try:
            # 1) 删除历史顶层块（若存在）
            for top_key in ("JIAN_PROJECT_CONFIG", "JIANPROJECT_CONFIG", "ALI_ALL_CONFIG"):
                if top_key in config_data:
                    del config_data[top_key]
                    changed = True
            if "INTEGRATION_CONFIG" in config_data:
                del config_data["INTEGRATION_CONFIG"]
                changed = True

            # 2) 删除 MESSAGE_CONFIG 中已废弃的 Jian 子源开关
            msg_cfg = config_data.get("MESSAGE_CONFIG")
            if isinstance(msg_cfg, dict):
                deprecated_msg_keys = (
                    "ali_all_parse_geonet",
                    "ali_all_parse_ptwc",
                )
                for key in deprecated_msg_keys:
                    if key in msg_cfg:
                        del msg_cfg[key]
                        changed = True

            # 3) 迁移 ENABLED_SOURCES 中遗留的 sismotide URL → 新 Jian /all
            enabled = config_data.get("ENABLED_SOURCES")
            if isinstance(enabled, dict):
                for k, v in list(enabled.items()):
                    if "sismotide.top" in (k or "").lower():
                        if v:
                            enabled[JIAN_MASTER_KEY] = True
                        del enabled[k]
                        changed = True
        except Exception as e:
            logger.debug(f"清理遗留 Jian Project 配置失败(可忽略): {e}")
        return changed
    
    def _write_config_dict(self, config_data: Dict[str, Any]) -> bool:
        """将配置 dict 原子写入配置文件（敏感字段 DPAPI 加密后落盘）。"""
        if not self.config_file:
            return False
        import shutil
        try:
            from utils.secret_store import protect_secrets_in_config_dict

            config_data = protect_secrets_in_config_dict(config_data)
        except Exception as e:
            logger.warning(f"敏感配置加密失败，将按明文写入: {e}")
        temp_file = self.config_file.with_suffix('.tmp')
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            shutil.move(str(temp_file), str(self.config_file))
            return True
        except Exception as e:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            logger.warning(f"写回配置文件失败: {e}")
            return False
    
    def load_config(self) -> bool:
        """加载配置文件"""
        try:
            if self.config_file is None or not self.config_file.exists():
                logger.warning(f"配置文件不存在，使用默认配置")
                self._apply_default_config()
                self._maybe_auto_match_performance_mode(had_saved_performance_mode=False)
                return True
            
            # 使用try-except包裹文件读取，避免阻塞
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except (OSError, PermissionError, json.JSONDecodeError) as e:
                logger.warning(f"读取配置文件失败: {e}，使用默认配置")
                self._apply_default_config()
                self._maybe_auto_match_performance_mode(had_saved_performance_mode=False)
                return False

            # 敏感字段：磁盘可能为 DPAPI 密文，加载时还原为明文供内存使用
            try:
                from utils.secret_store import reveal_secrets_in_config_dict

                reveal_secrets_in_config_dict(config_data)
            except Exception as e:
                logger.warning(f"敏感配置解密失败(可忽略): {e}")
            
            # 版本不一致或缺少版本时，仅备份并继续按 section 合并加载（缺项补全，保留用户自定义）
            saved_version = config_data.get('config_version') or config_data.get('app_version') or ''
            version_changed = (saved_version != APP_VERSION)
            legacy_jian_settings_removed = self._remove_legacy_jian_project_settings(config_data)
            if version_changed:
                logger.info(f"配置版本({saved_version or '无'})与当前程序版本({APP_VERSION})不一致，将合并加载并补全缺失项，保留用户设置")
                try:
                    if self.config_file and self.config_file.exists():
                        bak = self.config_file.with_suffix('.json.bak')
                        import shutil
                        shutil.copy2(str(self.config_file), str(bak))
                        logger.debug(f"已备份旧配置到 {bak}")
                except Exception as e:
                    logger.debug(f"备份旧配置失败(可忽略): {e}")
            
            # 加载各模块配置（缺失的键保持 dataclass 默认值）
            success = True
            
            if 'GUI_CONFIG' in config_data:
                gui_section = config_data['GUI_CONFIG']
                had_saved_performance_mode = 'performance_mode' in gui_section
                gui_data = {k: v for k, v in gui_section.items() if hasattr(self.gui_config, k)}
                # 只更新配置文件中存在的字段，对于不存在的字段保留当前值
                for key, value in gui_data.items():
                    if hasattr(self.gui_config, key):
                        setattr(self.gui_config, key, value)
                # 兼容旧配置：无 render_backend 时根据 use_gpu_rendering 推导
                if 'render_backend' not in config_data.get('GUI_CONFIG', {}):
                    self.gui_config.render_backend = "opengl" if self.gui_config.use_gpu_rendering else "cpu"
                # 规范化并迁移：统一为小写，不支持的取值改为 opengl
                backend = (self.gui_config.render_backend or "").strip().lower()
                if backend in ("cpu", "opengl"):
                    self.gui_config.render_backend = backend
                else:
                    # 非法取值回退 CPU，避免配置损坏后静默切到 GPU
                    self.gui_config.render_backend = "cpu"
                # 根据 render_backend 同步 use_gpu_rendering，保证一致
                self.gui_config.use_gpu_rendering = (self.gui_config.render_backend == "opengl")
                if not self.gui_config.validate():
                    success = False
            else:
                had_saved_performance_mode = False
            
            if 'MESSAGE_CONFIG' in config_data:
                msg_data = {k: v for k, v in config_data['MESSAGE_CONFIG'].items() if hasattr(self.message_config, k)}
                # 只更新配置文件中存在的字段，对于不存在的字段保留当前值
                for key, value in msg_data.items():
                    if hasattr(self.message_config, key):
                        setattr(self.message_config, key, value)
                if not self.message_config.validate():
                    success = False
                enforce_weather_source_mutex(self.message_config)
                enforce_jma_report_mutex(self.message_config, prefer="main")
                # 迁移逻辑：当老配置仅有 fanstudio_parse_warning / fanstudio_parse_report 时，
                # 按这两个总开关初始化各 Fan Studio 子源细粒度开关，避免升级后行为变化。
                try:
                    parse_warning_flag = getattr(self.message_config, 'fanstudio_parse_warning', True)
                    parse_report_flag = getattr(self.message_config, 'fanstudio_parse_report', True)
                    # 预警类子源字段名
                    warning_fields = [
                        'fanstudio_parse_cea',
                        'fanstudio_parse_cea_pr',
                        'fanstudio_parse_cwa_eew',
                        'fanstudio_parse_jma',
                        'fanstudio_parse_sa',
                        'fanstudio_parse_kma_eew',
                    ]
                    # 速报/其他类子源字段名
                    report_fields = [
                        'fanstudio_parse_cenc',
                        'fanstudio_parse_ningxia',
                        'fanstudio_parse_guangxi',
                        'fanstudio_parse_shanxi',
                        'fanstudio_parse_beijing',
                        'fanstudio_parse_yunnan',
                        'fanstudio_parse_cwa',
                        'fanstudio_parse_hko',
                        'fanstudio_parse_usgs',
                        'fanstudio_parse_emsc',
                        'fanstudio_parse_bcsf',
                        'fanstudio_parse_gfz',
                        'fanstudio_parse_usp',
                        'fanstudio_parse_kma',
                        'fanstudio_parse_fssn',
                        'fanstudio_parse_fssn_cmt',
                        'fanstudio_parse_weatheralarm',
                        'fanstudio_parse_tsunami',
                    ]
                    # 如果配置文件中没有对应键，则根据总开关初始化，已有键则保留用户设置
                    msg_cfg_section = config_data.get('MESSAGE_CONFIG', {})
                    for field in warning_fields:
                        if field not in msg_cfg_section:
                            setattr(self.message_config, field, bool(parse_warning_flag))
                    for field in report_fields:
                        if field not in msg_cfg_section:
                            setattr(self.message_config, field, bool(parse_report_flag))
                except Exception as e:
                    logger.debug(f"迁移 Fan Studio 子源解析开关失败(可忽略): {e}")
            
            # 加载 ALERT_CONFIG（若不存在，则触发一次旧字段迁移）
            if 'ALERT_CONFIG' in config_data:
                alert_section = config_data.get('ALERT_CONFIG') or {}
                alert_data = {
                    k: v for k, v in alert_section.items()
                    if hasattr(self.alert_config, k)
                }
                for key, value in alert_data.items():
                    setattr(self.alert_config, key, value)
                self._migrate_tiered_sound_fields(alert_section)
                self._migrate_alert_feedback_mode(alert_section)
            else:
                self._migrate_legacy_alert_fields(config_data)
            if not self.alert_config.validate():
                success = False

            if 'WS_CONFIG' in config_data:
                ws_data = {k: v for k, v in config_data['WS_CONFIG'].items() if hasattr(self.ws_config, k)}
                # 只更新配置文件中存在的字段，对于不存在的字段保留当前值
                for key, value in ws_data.items():
                    if hasattr(self.ws_config, key):
                        setattr(self.ws_config, key, value)
                if not self.ws_config.validate():
                    success = False
            # 公开版：CEA App 凭证始终用内置值（不对外开放设置）
            try:
                from utils.whews_cea_builtin import apply_builtin_whews_cea_credentials

                apply_builtin_whews_cea_credentials(self.ws_config)
            except Exception as e:
                logger.debug(f"注入内置 CEA 凭证失败(可忽略): {e}")
            
            if 'TRANSLATION_CONFIG' in config_data:
                raw_trans = config_data['TRANSLATION_CONFIG']
                # 兼容旧版：use_volcano_translation → enabled
                if 'enabled' not in raw_trans and raw_trans.get('use_volcano_translation'):
                    raw_trans = dict(raw_trans)
                    raw_trans['enabled'] = True
                    raw_trans['use_place_name_fix'] = False
                # 兼容 PySide6 版密钥字段名
                if 'baidu_secret_key' in raw_trans and 'baidu_secret' not in raw_trans:
                    raw_trans = dict(raw_trans)
                    raw_trans['baidu_secret'] = raw_trans.pop('baidu_secret_key')
                trans_data = {k: v for k, v in raw_trans.items() if hasattr(self.translation_config, k)}
                for key, value in trans_data.items():
                    if hasattr(self.translation_config, key):
                        setattr(self.translation_config, key, value)
                if not self.translation_config.validate():
                    success = False
            
            if 'LOG_CONFIG' in config_data:
                log_data = {k: v for k, v in config_data['LOG_CONFIG'].items() if hasattr(self.log_config, k)}
                # 只更新配置文件中存在的字段，对于不存在的字段保留当前值
                for key, value in log_data.items():
                    if hasattr(self.log_config, key):
                        setattr(self.log_config, key, value)
                if not self.log_config.validate():
                    success = False

            self.data_provider = normalize_data_provider(
                config_data.get('DATA_PROVIDER', getattr(self, 'data_provider', DATA_PROVIDER_FANSTUDIO))
            )

            # 加载数据源配置（仅持久化 all 与非 Fan Studio 数据源，Fan Studio 单项已移除）
            raw_sources = config_data.get('ENABLED_SOURCES', {})
            all_url = FANSTUDIO_ALL_URL
            self.enabled_sources = {
                k: v for k, v in raw_sources.items()
                if k == all_url or not self._is_fanstudio_individual_url(k)
            }
            # 确保内存中不保留任何 Fan Studio 单项 URL
            for k in list(self.enabled_sources.keys()):
                if self._is_fanstudio_individual_url(k):
                    del self.enabled_sources[k]
            removed_ws = self._enforce_public_ws_sources()
            if removed_ws:
                logger.info(f"已清理非公开 WebSocket 数据源: {removed_ws}")
            self.custom_data_source_url = (config_data.get('CUSTOM_DATA_SOURCE_URL') or "").strip()
            self.custom_data_source_insecure_ssl = bool(
                config_data.get('CUSTOM_DATA_SOURCE_INSECURE_SSL', False)
            )

            raw_poll = config_data.get('HTTP_POLL_INTERVALS', {})
            if isinstance(raw_poll, dict) and raw_poll:
                try:
                    self.http_poll_intervals = {
                        k: max(1, int(v)) for k, v in raw_poll.items()
                    }
                except (TypeError, ValueError):
                    self.http_poll_intervals = dict(DEFAULT_HTTP_POLL_INTERVALS)
            else:
                self.http_poll_intervals = dict(DEFAULT_HTTP_POLL_INTERVALS)
            self._ensure_http_poll_interval_defaults()

            # 如果配置文件中没有数据源配置，使用默认配置（仅 all + 非 Fan Studio）
            if not self.enabled_sources:
                self.enabled_sources = {all_url: True}
                # P2PQuake 仅 WSS + 启动时 HTTP 拉取，不启用 HTTP 轮询
                self.enabled_sources[P2PQUAKE_HISTORY_AGGREGATE_URL] = False
                self.enabled_sources[FANSTUDIO_TYPHOON_HTTP] = True
                self.enabled_sources[WOLFX_MASTER_KEY] = False
                self.enabled_sources[WOLFX_ALL_EEW_URL] = False
                self.enabled_sources[WOLFX_CWA_EEW_URL] = False
                self.enabled_sources[WOLFX_CENC_EQLIST_URL] = False
                self.enabled_sources[WOLFX_JMA_EQLIST_URL] = False
                self.enabled_sources[NOWQUAKE_CENCINT_WSS_URL] = False
                self.enabled_sources["wss://api.p2pquake.net/v2/ws"] = False
                self.enabled_sources[OPENQUAKE_WS_ALL_URL] = False
                logger.info("配置文件中没有数据源配置，使用默认配置（all + 非 Fan Studio）")
            else:
                if all_url not in self.enabled_sources:
                    self.enabled_sources[all_url] = True
                # 若配置中已有 all_url，尊重用户关闭聚合连接的设置，不再强制为 True
                # 仅补全非 Fan Studio 数据源缺失项；P2PQuake HTTP 不用于轮询，仅启动时拉取
                if P2PQUAKE_HISTORY_AGGREGATE_URL not in self.enabled_sources:
                    self.enabled_sources[P2PQUAKE_HISTORY_AGGREGATE_URL] = False
                if FANSTUDIO_TYPHOON_HTTP not in self.enabled_sources:
                    self.enabled_sources[FANSTUDIO_TYPHOON_HTTP] = True
                other_wss_urls = [
                    WOLFX_ALL_EEW_URL,
                    WOLFX_CWA_EEW_URL,
                    WOLFX_CENC_EQLIST_URL,
                    WOLFX_JMA_EQLIST_URL,
                    NOWQUAKE_CENCINT_WSS_URL,
                    "wss://api.p2pquake.net/v2/ws",
                    OPENQUAKE_WS_ALL_URL,
                ]
                for wss_url in other_wss_urls:
                    if wss_url not in self.enabled_sources:
                        self.enabled_sources[wss_url] = False

            # P2PQuake：一个总开关，两条 HTTP 拉取与 WSS 项保持一致
            self._sync_p2pquake_http_with_wss()
            self._ensure_jian_source_defaults()
            self._ensure_wolfx_source_defaults()
            self._ensure_whews_source_defaults()
            self._ensure_eqsc_http_defaults()

            # 根据服务器选择更新URL
            self._cleanup_invalid_fanstudio_ws_sources()
            removed_ws = self._enforce_public_ws_sources()
            if removed_ws:
                logger.info(f"URL 规范化后再次清理非公开 WebSocket 数据源: {removed_ws}")
            
            # 按固定顺序构建 ws_urls，确保轮播数据源顺序不变
            self.ws_urls = self._build_ws_urls_ordered()
            for u in self.ws_urls:
                logger.debug(f"已添加数据源到ws_urls: {u}")
            logger.info(f"配置加载成功，启用 {len(self.ws_urls)} 个WebSocket数据源")
            self._maybe_auto_match_performance_mode(had_saved_performance_mode=had_saved_performance_mode)
            self._notify_config_changed()
            # 缺项补全：仅添加缺失的键并写回，不覆盖用户已有设置；ENABLED_SOURCES 使用过滤后的值
            full = self._get_full_config_dict()
            merged = self._merge_config_file(config_data, full)
            merged['ENABLED_SOURCES'] = full['ENABLED_SOURCES']
            if version_changed:
                merged['config_version'] = APP_VERSION
            if version_changed or self._has_missing_keys(config_data, full) or legacy_jian_settings_removed:
                try:
                    if self._write_config_dict(merged):
                        if legacy_jian_settings_removed:
                            logger.info("已清理 settings.json 中遗留的 Jian Project 配置并写回")
                        else:
                            logger.info("已补全缺失配置项并写回，保留用户自定义设置")
                    else:
                        logger.warning("补全配置写回失败(可忽略)")
                except Exception as e:
                    logger.warning(f"写回补全配置失败(可忽略): {e}")
            return success
            
        except json.JSONDecodeError as e:
            logger.error(f"配置文件格式错误: {e}")
            self._apply_default_config()
            self._maybe_auto_match_performance_mode(had_saved_performance_mode=False)
            return False
        except Exception as e:
            logger.error(f"配置加载失败: {e}")
            self._apply_default_config()
            self._maybe_auto_match_performance_mode(had_saved_performance_mode=False)
            return False
    
    def save_config(self) -> bool:
        """保存当前配置到文件（合并写入：程序已知键用内存值更新，文件中多出的键保留）"""
        import threading
        import shutil
        
        if not hasattr(self, '_save_lock'):
            self._save_lock = threading.Lock()
        
        if not self._save_lock.acquire(timeout=5):
            logger.error("配置保存失败: 无法获取文件锁，可能正在被其他线程使用")
            return False
        
        try:
            our_config = self._get_full_config_dict()
            # 若配置文件存在，先读取再合并，保留用户自定义键
            if self.config_file and self.config_file.exists():
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                except (OSError, json.JSONDecodeError):
                    existing = {}
                # 逐 section 合并：existing 中多出的键保留，程序已知键用内存值覆盖
                merged = dict(existing)
                for key, our_value in our_config.items():
                    if key == 'ENABLED_SOURCES':
                        # 写入过滤后的数据源，避免历史敏感 WS URL 被保留
                        merged[key] = dict(our_value)
                    elif isinstance(our_value, dict):
                        merged[key] = {**existing.get(key, {}), **our_value}
                    else:
                        merged[key] = our_value
                config_data = merged
            else:
                config_data = our_config

            if self.config_file:
                if self._write_config_dict(config_data):
                    logger.info("配置保存成功")
                    return True
                raise RuntimeError("_write_config_dict 返回 False")
            logger.error("配置保存失败: 配置文件路径未设置")
            return False
        except Exception as e:
            logger.error(f"配置保存失败: {e}", exc_info=True)
            return False
        finally:
            self._save_lock.release()
    
    def _migrate_tiered_sound_fields(self, alert_section: Dict[str, Any]) -> None:
        """从旧版单层 sound_enabled/sound_path 迁移到分级预警声音字段。"""
        if not isinstance(alert_section, dict):
            return
        has_new = (
            'felt_sound_enabled' in alert_section
            or 'critical_sound_enabled' in alert_section
        )
        if has_new:
            return
        old_enabled = bool(alert_section.get('sound_enabled', False))
        old_path = (alert_section.get('sound_path') or '').strip()
        self.alert_config.felt_sound_enabled = old_enabled
        self.alert_config.critical_sound_enabled = old_enabled
        if old_path:
            self.alert_config.felt_sound_path = old_path

    def _migrate_alert_feedback_mode(self, alert_section: Dict[str, Any]) -> None:
        """从旧版 tts_playback_mode / TTS 开关迁移到 alert_feedback_mode。"""
        if not isinstance(alert_section, dict):
            return
        if "alert_feedback_mode" in alert_section:
            return
        legacy = str(alert_section.get("tts_playback_mode") or "").strip().lower()
        tts_on = bool(
            alert_section.get("felt_tts_enabled")
            or alert_section.get("critical_tts_enabled")
        )
        if legacy == "replace" or tts_on:
            self.alert_config.alert_feedback_mode = "tts"
        else:
            self.alert_config.alert_feedback_mode = "sound"

    def _migrate_legacy_alert_fields(self, config_data: Dict[str, Any]) -> None:
        """
        从旧版 GUI_CONFIG / MESSAGE_CONFIG 中迁移告警相关字段到新的 ``AlertConfig``。

        触发条件：``ALERT_CONFIG`` 节缺失（首次升级）。
        旧字段保留在原 section 中以保证降级兼容；下个版本会清理。
        """
        try:
            msg_section = config_data.get('MESSAGE_CONFIG', {}) or {}

            enable_china = bool(msg_section.get('enable_china_intensity', False))
            self.alert_config.enabled = enable_china

            self.alert_config.flash_interval_ms = int(
                msg_section.get('alert_flash_interval_ms', 400) or 400
            )
            self.alert_config.flash_scope = "scrolling_only"
            logger.info("已从旧版字段迁移 AlertConfig（首次升级）")
        except Exception as e:
            logger.warning(f"迁移旧版告警配置失败（使用默认值）: {e}")

    def _apply_default_config(self):
        """应用默认配置"""
        self.gui_config = GUIConfig()
        self.message_config = MessageConfig()
        self.alert_config = AlertConfig()
        self.ws_config = WebSocketConfig()
        self.translation_config = TranslationConfig()
        self.log_config = LogConfig()
        # 默认数据源：仅聚合/独立源，不加入 Fan Studio 单项 wss URL（实际只连 /all）
        all_url = FANSTUDIO_ALL_URL

        self.enabled_sources = {all_url: False}
        # P2PQuake 仅 WSS + 启动时 HTTP 拉取，不启用 HTTP 轮询
        self.enabled_sources[P2PQUAKE_HISTORY_AGGREGATE_URL] = False
        self.enabled_sources[FANSTUDIO_TYPHOON_HTTP] = True
        self.enabled_sources[WOLFX_MASTER_KEY] = False
        self.enabled_sources[WOLFX_ALL_EEW_URL] = False
        self.enabled_sources[WOLFX_CWA_EEW_URL] = False
        self.enabled_sources[WOLFX_CENC_EQLIST_URL] = False
        self.enabled_sources[WOLFX_JMA_EQLIST_URL] = False
        self.enabled_sources[NOWQUAKE_CENCINT_WSS_URL] = False
        self.enabled_sources["wss://api.p2pquake.net/v2/ws"] = False
        self.enabled_sources[OPENQUAKE_WS_ALL_URL] = False
        self.enabled_sources[AUX_SOURCES_MASTER_KEY] = True
        self.enabled_sources[JIAN_MASTER_KEY] = True
        self.enabled_sources[WHEWS_MASTER_KEY] = False
        self.data_provider = DATA_PROVIDER_JIAN
        self._ensure_jian_source_defaults()
        self._ensure_wolfx_source_defaults()
        self._ensure_whews_source_defaults()
        self._ensure_eqsc_http_defaults()
        self._ensure_http_poll_interval_defaults()
        self._enforce_public_ws_sources()

        self.ws_urls = self._build_ws_urls_ordered()
        self.custom_data_source_url = ""
        self.custom_data_source_insecure_ssl = False
        logger.info(f"已应用默认配置（仅聚合/独立源，无 Fan Studio 单项）: {self.ws_urls}")
    
    def _build_ws_urls_ordered(self) -> List[str]:
        """按主提供者构建 ws_urls；Wolfx / P2P / Nowquake 为全局辅助源。"""
        self._cleanup_invalid_fanstudio_ws_sources()
        self._enforce_public_ws_sources()
        self._disable_whews_dedicated_endpoints()
        self._migrate_whews_url_keys_to_master()
        provider = self.get_active_data_provider()
        ws_urls: List[str] = []
        if provider == DATA_PROVIDER_FANSTUDIO:
            if self.enabled_sources.get(FANSTUDIO_ALL_URL, False):
                ws_urls.append(FANSTUDIO_ALL_URL)
        elif provider == DATA_PROVIDER_WHEWS:
            if is_whews_all_enabled(self.enabled_sources):
                all_url = self.get_whews_endpoint_urls().get("all")
                if all_url:
                    ws_urls.append(all_url)
                cea_all = self.get_whews_endpoint_urls().get("cea_all")
                if cea_all:
                    # CEA App 鉴权专用合并通道（与 /ws/all 并存）
                    self.enabled_sources[cea_all] = True
                    if cea_all not in ws_urls:
                        ws_urls.append(cea_all)
        elif provider == DATA_PROVIDER_JIAN:
            if any_jian_source_enabled(self):
                ws_urls.append(JIAN_PROJECT_ALL_URL)
        # Wolfx / P2PQuake / OpenQuakeAPI（辅助源；受 aux://master 门控）
        if aux_sources_enabled(self.enabled_sources):
            if wolfx_master_enabled(self.enabled_sources):
                if WOLFX_ALL_EEW_URL not in ws_urls:
                    ws_urls.append(WOLFX_ALL_EEW_URL)
            if self.enabled_sources.get(WOLFX_CWA_EEW_URL, False):
                if WOLFX_CWA_EEW_URL not in ws_urls:
                    ws_urls.append(WOLFX_CWA_EEW_URL)
            if self.enabled_sources.get(P2PQUAKE_WSS_URL, False):
                if P2PQUAKE_WSS_URL not in ws_urls:
                    ws_urls.append(P2PQUAKE_WSS_URL)
            if self.enabled_sources.get(OPENQUAKE_WS_ALL_URL, False):
                if OPENQUAKE_WS_ALL_URL not in ws_urls:
                    ws_urls.append(OPENQUAKE_WS_ALL_URL)
        # Nowquake（独立全局源，不受辅助总开关影响）
        if self.enabled_sources.get(NOWQUAKE_CENCINT_WSS_URL, False):
            if NOWQUAKE_CENCINT_WSS_URL not in ws_urls:
                ws_urls.append(NOWQUAKE_CENCINT_WSS_URL)
        filtered: List[str] = []
        for u in ws_urls:
            if is_whews_dedicated_endpoint(u):
                continue
            if not self.is_url_active_for_provider(u, provider):
                continue
            filtered.append(u)
        return filtered

    def update_enabled_sources(self, sources: Dict[str, bool]):
        """更新启用的数据源"""
        self.enabled_sources.update(sources)
        self._cleanup_invalid_fanstudio_ws_sources()
        removed_ws = self._enforce_public_ws_sources()
        if removed_ws:
            logger.info(f"更新数据源时已清理非公开 WebSocket 数据源: {removed_ws}")
        self.ws_urls = self._build_ws_urls_ordered()
        logger.info(f"更新数据源配置，当前启用 {len(self.ws_urls)} 个WebSocket数据源: {self.ws_urls}")
        self._notify_config_changed()

    def _maybe_auto_match_performance_mode(self, had_saved_performance_mode: bool) -> None:
        """首次初始化时按系统资源自动匹配性能模式；已有用户选择或自定义时不覆盖。"""
        if had_saved_performance_mode:
            from utils.performance_presets import normalize_performance_mode

            self.gui_config.performance_mode = normalize_performance_mode(
                getattr(self.gui_config, "performance_mode", "medium")
            )
            return
        from utils.performance_presets import (
            apply_performance_preset,
            detect_auto_performance_mode,
            PERFORMANCE_MODE_LABELS,
            _get_system_total_memory_mb,
        )

        mode = detect_auto_performance_mode()
        apply_performance_preset(self, mode)
        label = PERFORMANCE_MODE_LABELS.get(mode, mode)
        logger.info(
            "已根据本机配置自动匹配性能模式: %s（物理内存约 %dMB，CPU 核心 %d）",
            label,
            _get_system_total_memory_mb(),
            os.cpu_count() or 2,
        )

    def apply_performance_preset(self, mode: str) -> Dict[str, Any]:
        """应用低/中/高/极致性能预设，返回变更信息（均已支持热重载）。"""
        from utils.performance_presets import apply_performance_preset

        result = apply_performance_preset(self, mode)
        self._notify_config_changed()
        logger.info(
            "已应用性能模式 %s（render_changed=%s, sources_changed=%s）",
            mode,
            result.get("render_backend_changed"),
            result.get("sources_changed"),
        )
        return result
    
    def _cleanup_invalid_fanstudio_ws_sources(self) -> None:
        """仅保留 Fan Studio /all；剔除其余 Fan Studio WebSocket 配置项。"""
        if not hasattr(self, "enabled_sources"):
            return
        all_norm = FANSTUDIO_ALL_URL.rstrip("/").lower()
        for url in list(self.enabled_sources.keys()):
            if not isinstance(url, str):
                continue
            low = url.lower()
            if "fanstudio" in low and low.startswith(("ws://", "wss://")):
                if url.rstrip("/").lower() != all_norm:
                    del self.enabled_sources[url]
                    logger.debug(f"已移除无效 Fan Studio WebSocket 配置: {url}")
    
    def get_source_name(self, url: str) -> str:
        """获取数据源名称。Fan Studio 子源用 path 代号映射（不写完整 wss URL），其余用完整 URL 映射。"""
        if self.custom_data_source_url and url == self.custom_data_source_url:
            return "custom"
        normalized_url = (url or "").rstrip("/")
        http_url_to_name = {
            FANSTUDIO_TYPHOON_HTTP: "fanstudio_typhoon",
            P2PQUAKE_HISTORY_AGGREGATE_URL: "p2pquake",
            "https://api.p2pquake.net/v2/history?codes=551&limit=3": "p2pquake",
            "https://api.p2pquake.net/v2/jma/tsunami?limit=1": "p2pquake_tsunami",
            EQSC_HTTP_MASTER: "eqsc",
            EQSC_JMA_EEW_HTTP: "eqsc_jma_eew",
            EQSC_JMA_REPORT_HTTP: "eqsc_jma_report",
            EQSC_JMA_TSUNAMI_HTTP: "eqsc_jma_tsunami",
            EQSC_CENC_HTTP: "eqsc_cenc",
            EQSC_CENC_IR_HTTP: "eqsc_cenc_ir",
            EQSC_CWA_HTTP: "eqsc_cwa",
            EQSC_HKO_HTTP: "eqsc_hko",
            EQSC_USGS_HTTP: "eqsc_usgs",
            EQSC_EMSC_HTTP: "eqsc_emsc",
            EQSC_TYPHOON_HTTP: "eqsc_typhoon",
            EQSC_VOLCANO_HTTP: "eqsc_volcano",
        }
        if normalized_url in http_url_to_name:
            return http_url_to_name[normalized_url]
        if is_jian_logical_key(normalized_url):
            internal = JIAN_LOGICAL_TO_INTERNAL.get(normalized_url)
            if internal:
                return internal
        if normalized_url == JIAN_MASTER_KEY:
            return "jian"
        if normalized_url == WOLFX_MASTER_KEY:
            return "wolfx"
        # 无界科技（主站或备用）
        if is_whews_url(normalized_url) and normalized_url.startswith(("wss://", "ws://")):
            path = normalized_url.rstrip("/").split("?")[0].split("/")[-1] or "all"
            whews_path_to_name = {
                "all": "whews",
                "cea_all": "whews_cea",
                "cenc": "cenc",
            }
            return whews_path_to_name.get(path, "whews")
        # Fan Studio wss：从 URL 抽 path，用代号查表，避免在代码中写单项 API 链接
        if "fanstudio.tech" in normalized_url and normalized_url.startswith(("wss://", "ws://")):
            try:
                path = normalized_url.rstrip("/").split("/")[-1] or "all"
                fanstudio_path_to_name = {
                    "all": "fanstudio",
                    "weatheralarm": "weatheralarm",
                    "tsunami": "海啸信息",
                    "cenc": "cenc", "cea": "cea", "cea-pr": "cea-pr",
                    "ningxia": "ningxia", "guangxi": "guangxi",
                    "shanxi": "shanxi", "beijing": "beijing", "yunnan": "yunnan",
                    "cwa": "cwa", "cwa-eew": "cwa-eew", "jma": "jma", "hko": "hko",
                    "usgs": "usgs", "sa": "sa", "emsc": "emsc", "bcsf": "bcsf",
                    "gfz": "gfz", "usp": "usp", "kma": "kma", "kma-eew": "kma-eew", "fssn": "fssn",
                    "fssn-cmt": "fssn-cmt",
                }
                if path in fanstudio_path_to_name:
                    return fanstudio_path_to_name[path]
            except Exception:
                pass
        # 非 Fan Studio：仅保留需完整 URL 的数据源（P2PQuake WSS、Wolfx All 等）
        url_to_name = {
            WOLFX_MASTER_KEY: "wolfx",
            WOLFX_ALL_EEW_URL: "wolfx_all_eew",
            WOLFX_CWA_EEW_URL: "wolfx_cwa_eew",
            WOLFX_CENC_EQLIST_URL: "wolfx_cenc",
            WOLFX_JMA_EQLIST_URL: "wolfx_jma_eqlist",
            NOWQUAKE_CENCINT_WSS_URL: "cenc-ir",
            "wss://api.p2pquake.net/v2/ws": "p2pquake_ws",
            OPENQUAKE_WS_ALL_URL: "openquake",
            JIAN_PROJECT_ALL_URL: "jian",
        }
        return url_to_name.get(normalized_url, url)
    
    def get_organization_name(self, source_name: str) -> str:
        """获取机构名称"""
        organization_name_mapping = {
            "custom": "自定义数据源",
            "fanstudio": "Fan Studio数据源",
            "whews": "WeJet",
            "whews_cea": "中国地震预警网",
            "weatheralarm": "气象预警",
            "cenc": "中国地震台网中心自动测定/正式测定",
            "cenc-ir": "中国地震台网中心地震烈度速报",
            "cea": "中国地震预警网",
            "cea-pr": "中国地震预警网-省级预警",
            "ningxia": "宁夏地震局",
            "guangxi": "广西地震局",
            "shanxi": "山西地震局",
            "beijing": "北京地震局",
            "yunnan": "云南地震局",
            "fujian": "福建地震局",
            "sichuan": "四川地震局",
            "shaanxi": "陕西地震局",
            "hubei": "湖北地震局",
            "nrcan": "加拿大自然资源部",
            "mmd": "马来西亚气象局",
            "tsunami": "自然资源部海啸预警中心",
            "海啸信息": "自然资源部海啸预警中心",
            "cwa": "台湾中央气象署",
            "cwa-eew": "台湾中央气象署地震预警",
            "jma": "日本气象厅地震预警",
            "jma_eq": "日本气象厅地震情报",
            "p2pquake": "日本气象厅地震情报",
            "p2pquake_tsunami": "日本气象厅海啸预报",
            "p2pquake_eew": "日本气象厅紧急地震速报",
            "openquake": "OpenQuakeAPI",
            "openquake_gq": "GlobalQuake地震预警",
            "openquake_nmefc": "国家海洋环境预报中心海啸预警",
            "openquake_nmefc_wave": "国家海洋环境预报中心海浪警报",
            "openquake_nmefc_surge": "国家海洋环境预报中心风暴潮警报",
            "openquake_cma": "中国气象局气象预警",
            "hko": "香港天文台",
            "fanstudio_typhoon": "台风实时与历史数据",
            "usgs": "美国地质调查局",
            "sa": "美国ShakeAlert地震预警",
            "emsc": "欧洲地中海地震中心",
            "bcsf": "法国中央地震研究所",
            "gfz": "德国地学研究中心",
            "usp": "巴西圣保罗大学",
            "kma": "韩国气象厅",
            "kma-eew": "韩国气象厅地震预警",
            "fssn": "FSSN",
            "fssn-cmt": "FSSN 矩心矩张量解",
            "p2pquake_ws": "日本气象厅地震/海啸 (P2PQuake WSS)",
            "wolfx_jma_eew": "緊急地震速報",
            "wolfx_sc_eew": "四川省地震局",
            "wolfx_fj_eew": "福建省地震局",
            "wolfx_cenc_eew": "中国地震台网",
            "wolfx_cq_eew": "重庆市地震局",
            "wolfx_cwa_eew": "台湾中央气象署",
            "wolfx_cenc": "中国地震台网中心",
            "wolfx_jma_eqlist": "日本气象厅地震情报",
            "bmkg": "印尼气象气候和地球物理局",
            "geonet": "新西兰 GeoNet",
            "ingv": "意大利国家地球物理与火山学研究所",
            "tmd": "泰国地震局",
            "early_est": "Early-est",
            "jma_volcano": "日本气象厅火山情报",
            "eqsc": "EQSC",
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
            "ptwc": "太平洋海啸预警中心 (PTWC)",
            "ntwc": "美国国家海啸预警中心 (NTWC)",
            "incois": "印度海啸早期预警中心 (INCOIS)",
            "jma_tsunami": "日本气象厅海啸预警",
            "phivolcs": "菲律宾火山地震研究所",
            "sgc": "哥伦比亚地质服务局",
            "ga": "澳大利亚地球科学局",
            "cenais": "古巴国家地震研究中心",
            "gsras": "希腊地震研究与监测中心",
            "bgs": "英国地质调查局",
            "ipma": "葡萄牙海洋与大气研究所",
            "ssn": "墨西哥国家地震局",
            "afad": "土耳其灾害和应急管理总局",
            "sed": "瑞士地震局",
            "noa": "挪威地震阵列",
            "scsn": "南加州地震网络",
            "iag": "阿根廷国家地震研究所",
            "igp": "秘鲁地质矿产与金属研究所",
            "nepal": "尼泊尔地震局",
            "typhoon": "台风实况",
        }
        
        return organization_name_mapping.get(source_name, source_name)