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
    if getattr(sys, "frozen", False) and sys.platform == "win32":  # 打包版 Windows 用 Unicode 路径
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
    # 非打包：脚本路径优先；argv[0] 为空或 -c 时回退到 __main__.__file__
    script = sys.argv[0] if sys.argv else None
    if not script or script == "-c":  # 交互模式回退到 __main__ 模块路径
        main_file = getattr(sys.modules.get("__main__"), "__file__", None)
        script = main_file if main_file else sys.executable
    else:
        script = script or sys.executable
    return os.path.abspath(script)


def get_executable_dir() -> str:
    """获取可执行文件所在目录（用于与 exe 同目录的启动日志等）。"""
    return os.path.dirname(get_executable_path())


def get_cmt_weather_cache_root():
    """
    返回 cmt-weather 可写目录（沙滩球、CENC 等震线图等共用）并尽量创建。
    打包时为 exe 同目录下 cmt-weather；开发时为项目根目录下 cmt-weather。
    创建失败时返回 None，调用方可回退到系统临时目录。
    """
    if getattr(sys, "frozen", False):
        root = Path(get_executable_dir()) / "cmt-weather"
    else:
        try:
            root = Path(__file__).resolve().parent.parent / "cmt-weather"
        except Exception:
            root = Path.cwd() / "cmt-weather"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return root


def get_resource_path(relative_path: str) -> Path:
    """
    获取资源文件路径，兼容PyInstaller打包后的情况

    Args:
        relative_path: 相对于项目根目录的资源路径

    Returns:
        资源文件的绝对路径
    """
    try:
        # PyInstaller 打包后会设置 sys._MEIPASS
        base_path = Path(sys._MEIPASS)  # type: ignore
    except (AttributeError, TypeError):
        # 开发环境，使用项目根目录
        try:
            base_path = Path(__file__).parent.parent
        except Exception:
            # 若上述均失败，使用当前工作目录
            base_path = Path.cwd()

    return base_path / relative_path  # 拼接资源相对路径
