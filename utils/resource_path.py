#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源路径工具
获取资源文件路径，兼容 PyInstaller 打包后的情况
"""

import sys
from pathlib import Path


def get_resource_path(relative_path: str) -> Path:
    """
    获取资源文件路径，兼容PyInstaller打包后的情况

    Args:
        relative_path: 相对于项目根目录的资源路径

    Returns:
        资源文件的绝对路径
    """
    try:
        # PyInstaller打包后会设置sys._MEIPASS
        base_path = Path(sys._MEIPASS)  # type: ignore
    except (AttributeError, TypeError):
        # 开发环境，使用项目根目录
        try:
            base_path = Path(__file__).parent.parent
        except Exception:
            # 如果都失败，使用当前工作目录
            base_path = Path.cwd()

    return base_path / relative_path
