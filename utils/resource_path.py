#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源路径工具
获取资源文件路径，兼容 PyInstaller 打包后的情况
并提供在 Windows 中文路径下正确的 exe 路径（避免 sys.executable 乱码）
"""

import os
import sys
from pathlib import Path


def get_executable_path() -> str:
    """
    获取当前可执行文件的真实路径。
    Windows 下 PyInstaller 打包时 sys.executable 可能因编码/8.3 短路径乱码，
    此处用 GetModuleFileNameW 获取 Unicode 路径。
    """
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32")  # type: ignore
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if kernel32.GetModuleFileNameW(None, buf, len(buf)):
                return buf.value
        except Exception:
            pass
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0] or getattr(sys, "__file__", sys.executable))


def get_executable_dir() -> str:
    """获取可执行文件所在目录（用于与 exe 同目录的启动日志等）。"""
    return os.path.dirname(get_executable_path())


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
