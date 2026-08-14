#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内置背景图：清单与路径解析。"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from utils.resource_path import get_resource_path

# 配置值形如 builtin:soft_clouds.jpg
BUILTIN_BACKGROUND_PREFIX = "builtin:"

# (文件名, 显示名) — 文件位于 media/backgrounds/
BUILTIN_BACKGROUNDS: List[Tuple[str, str]] = [
    ("city_night_bokeh.jpg", "夜市灯火"),
    ("blue_street_bokeh.jpg", "街灯虚影"),
    ("warm_fairy_lights.jpg", "暖金灯串"),
    ("green_nature_bokeh.jpg", "林间光斑"),
    ("blue_marble.jpg", "蓝白石纹"),
    ("soft_clouds.jpg", "云海远景"),
    ("warm_light_flare.jpg", "胶片暖光"),
]


def is_builtin_background(raw: str) -> bool:
    return str(raw or "").strip().startswith(BUILTIN_BACKGROUND_PREFIX)


def builtin_id_from_path(raw: str) -> str:
    """builtin:xxx.jpg → xxx.jpg；否则空串。"""
    s = str(raw or "").strip()
    if not s.startswith(BUILTIN_BACKGROUND_PREFIX):
        return ""
    return s[len(BUILTIN_BACKGROUND_PREFIX) :].strip()


def make_builtin_path(filename: str) -> str:
    return f"{BUILTIN_BACKGROUND_PREFIX}{filename}"


def resolve_background_image_file(raw: str) -> str:
    """
    解析配置中的背景图为可读本地文件路径。
    支持：空、绝对路径、AppData/subtitl/backgrounds 相对名、builtin: 内置图。
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    if is_builtin_background(s):
        name = builtin_id_from_path(s)
        if not name or ".." in name or "/" in name or "\\" in name:
            return ""
        cand = get_resource_path(f"media/backgrounds/{name}")
        return str(cand) if cand.is_file() else ""
    p = Path(s)
    if p.is_file():
        return str(p)
    bg_dir = Path.home() / "AppData" / "Roaming" / "subtitl" / "backgrounds"
    cand = bg_dir / s
    if cand.is_file():
        return str(cand)
    return ""


def builtin_display_name(raw: str) -> str:
    name = builtin_id_from_path(raw)
    for fname, label in BUILTIN_BACKGROUNDS:
        if fname == name:
            return label
    return name or "内置背景"
