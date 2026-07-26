#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面系统通知（Win10 / Win11 通用，不启动 PowerShell）。

路径优先级：
1. Qt QSystemTrayIcon.showMessage（无额外依赖，双系统均可用）
2. Windows Runtime Toast（winsdk / winrt / windows-toasts，可选）
"""

from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from utils.logger import get_logger

logger = get_logger()

# 解包桌面程序在 Win10/11 上显示系统 Toast 时建议设置显式 AUMID
APP_USER_MODEL_ID = "FanStudio.RollingSubtitle"
_TOAST_APP_NAME = "地震情报实况栏"

# 由主窗口注册：返回已 show 的 QSystemTrayIcon，或 None
_tray_getter: Optional[Callable[[], Any]] = None
_aumid_set = False
# None=未探测；False=不可用；callable=可用的 show 函数
_winrt_show: Any = None


def ensure_windows_app_id() -> None:
    """在创建 QApplication 之前调用，提升 Win10/11 Toast 关联与显示稳定性。"""
    global _aumid_set
    if _aumid_set or sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        _aumid_set = True
    except Exception as e:
        logger.debug(f"设置 AppUserModelID 失败（可忽略）: {e}")


def set_tray_icon_provider(getter: Optional[Callable[[], Any]]) -> None:
    """注册托盘图标提供者，供系统通知使用。"""
    global _tray_getter
    _tray_getter = getter


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _resolve_winrt_show() -> Any:
    """探测可选 WinRT 后端；结果缓存。返回 show(title, body)->None 或 False。"""
    global _winrt_show
    if _winrt_show is not None:
        return _winrt_show

    # winsdk（较新）
    try:
        from winsdk.windows.data.xml.dom import XmlDocument
        from winsdk.windows.ui.notifications import (
            ToastNotification,
            ToastNotificationManager,
        )

        def _show(title: str, body: str) -> None:
            xml = (
                "<toast><visual><binding template='ToastGeneric'>"
                f"<text>{_escape_xml(title)}</text>"
                f"<text>{_escape_xml(body)}</text>"
                "</binding></visual></toast>"
            )
            doc = XmlDocument()
            doc.load_xml(xml)
            notifier = ToastNotificationManager.create_toast_notifier(_TOAST_APP_NAME)
            notifier.show(ToastNotification(doc))

        _winrt_show = _show
        return _winrt_show
    except Exception:
        pass

    # winrt（旧包名）
    try:
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import (
            ToastNotification,
            ToastNotificationManager,
        )

        def _show(title: str, body: str) -> None:
            xml = (
                "<toast><visual><binding template='ToastGeneric'>"
                f"<text>{_escape_xml(title)}</text>"
                f"<text>{_escape_xml(body)}</text>"
                "</binding></visual></toast>"
            )
            doc = XmlDocument()
            doc.load_xml(xml)
            notifier = ToastNotificationManager.create_toast_notifier(_TOAST_APP_NAME)
            notifier.show(ToastNotification(doc))

        _winrt_show = _show
        return _winrt_show
    except Exception:
        pass

    # windows-toasts
    try:
        from windows_toasts import Toast, WindowsToaster

        toaster = WindowsToaster(_TOAST_APP_NAME)

        def _show(title: str, body: str) -> None:
            toast = Toast()
            toast.text_fields = [title, body]
            toaster.show_toast(toast)

        _winrt_show = _show
        return _winrt_show
    except Exception:
        pass

    _winrt_show = False
    return _winrt_show


def _show_winrt_toast(title: str, body: str) -> bool:
    """Win10（16299+）/ Win11 原生 Toast；无可选依赖时返回 False。"""
    show = _resolve_winrt_show()
    if not show:
        return False
    try:
        show(title, body)
        return True
    except Exception as e:
        logger.debug(f"WinRT Toast 失败: {e}")
        return False


def _show_qt_tray_toast(title: str, body: str) -> bool:
    """Win10/Win11 通用：经已注册的系统托盘发通知（Shell_NotifyIcon）。"""
    try:
        from PyQt5.QtWidgets import QSystemTrayIcon

        tray = _tray_getter() if _tray_getter else None
        if tray is None or not isinstance(tray, QSystemTrayIcon):
            return False
        if hasattr(tray, "supportsMessages") and not tray.supportsMessages():
            return False

        icon = tray.icon()
        if icon is not None and not icon.isNull():
            tray.showMessage(title, body, icon, 8000)
        else:
            tray.showMessage(title, body, QSystemTrayIcon.Information, 8000)
        return True
    except Exception as e:
        logger.debug(f"Qt 托盘通知失败: {e}")
        return False


def show_event_notification(config: Any, title: str, body: str) -> None:
    """显示系统通知（建议在 Qt 主线程调用）。兼容 Win10 与 Win11。"""
    gc = getattr(config, "gui_config", None)
    if gc is None or not getattr(gc, "toast_notifications_enabled", False):
        return  # 未启用系统通知
    title = (title or "地震情报").strip()[:120]
    body = (body or "").strip()[:500]
    if not body:
        return  # 无正文不弹通知

    ensure_windows_app_id()

    try:
        # 默认 Qt 托盘：Win10/11 均可用，无需额外依赖，也不触发火绒
        if _show_qt_tray_toast(title, body):
            return
        if sys.platform == "win32" and _show_winrt_toast(title, body):
            return
        logger.debug("系统通知跳过：托盘与 WinRT 均不可用")
    except Exception as e:
        logger.debug(f"系统通知失败: {e}")
