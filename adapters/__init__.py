#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源适配器模块
提供各种数据源的适配器实现（按需懒加载，避免启动时一次性导入全部适配器）。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Dict, Tuple

# 名称 -> (模块路径, 属性名)
_LAZY_ATTRS: Dict[str, Tuple[str, str]] = {
    "BaseAdapter": (".base_adapter", "BaseAdapter"),
    "FanStudioAdapter": (".fanstudio_adapter", "FanStudioAdapter"),
    "FanStudioHttpAdapter": (".fanstudio_http_adapter", "FanStudioHttpAdapter"),
    "P2PQuakeAdapter": (".p2pquake_adapter", "P2PQuakeAdapter"),
    "P2PQuakeTsunamiAdapter": (".p2pquake_tsunami_adapter", "P2PQuakeTsunamiAdapter"),
    "P2PQuakeWebSocketAdapter": (".p2pquake_ws_adapter", "P2PQuakeWebSocketAdapter"),
    "CustomAdapter": (".custom_adapter", "CustomAdapter"),
    "WolfxAdapter": (".wolfx_adapter", "WolfxAdapter"),
    "WhewsAdapter": (".whews_adapter", "WhewsAdapter"),
    "NowquakeCencintAdapter": (".nowquake_cencint_adapter", "NowquakeCencintAdapter"),
    "EqscAdapter": (".eqsc_adapter", "EqscAdapter"),
    "JianProjectAdapter": (".jian_project_adapter", "JianProjectAdapter"),
}

__all__ = list(_LAZY_ATTRS.keys())


def __getattr__(name: str) -> Any:
    """按属性名懒加载对应适配器类。"""
    spec = _LAZY_ATTRS.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr = spec
    mod = import_module(module_path, __name__)
    value = getattr(mod, attr)
    globals()[name] = value
    return value


def __dir__() -> list:
    return sorted(set(globals().keys()) | set(__all__))
