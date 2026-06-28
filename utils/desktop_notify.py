#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""桌面系统通知（Windows Toast / 其他平台 fallback）。"""

import sys
import threading
from typing import Any

from utils.logger import get_logger

logger = get_logger()


def show_event_notification(config: Any, title: str, body: str) -> None:
    """异步显示系统通知。"""
    gc = getattr(config, "gui_config", None)
    if gc is None or not getattr(gc, "toast_notifications_enabled", False):
        return  # 未启用系统通知
    title = (title or "地震情报").strip()[:120]
    body = (body or "").strip()[:500]
    if not body:
        return  # 无正文不弹通知

    def _run() -> None:
        try:
            if sys.platform == "win32":
                try:
                    from win10toast import ToastNotifier
                    ToastNotifier().show_toast(title, body, duration=8, threaded=True)
                    return  # win10toast 成功则结束
                except Exception:
                    pass
                try:
                    import subprocess
                    ps = (
                        "[Windows.UI.Notifications.ToastNotificationManager, "
                        "Windows.UI.Notifications, ContentType = WindowsRuntime] "
                        "| Out-Null; "
                        "$template = [Windows.UI.Notifications.ToastNotificationManager]::"
                        "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::"
                        "ToastText02); "
                        "$text = $template.GetElementsByTagName('text'); "
                        f"$text.Item(0).AppendChild($template.CreateTextNode('{title.replace(chr(39), chr(39)+chr(39))}')) | Out-Null; "
                        f"$text.Item(1).AppendChild($template.CreateTextNode('{body.replace(chr(39), chr(39)+chr(39))}')) | Out-Null; "
                        "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
                        "[Windows.UI.Notifications.ToastNotificationManager]::"
                        "CreateToastNotifier('地震情报实况栏').Show($toast)"
                    )
                    kwargs = {"timeout": 10, "capture_output": True}
                    cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if cf:
                        kwargs["creationflags"] = cf
                    subprocess.run(
                        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                        **kwargs,
                    )
                    return
                except Exception as e:
                    logger.debug(f"Windows Toast 失败: {e}")
            try:
                from PyQt5.QtWidgets import QSystemTrayIcon
                from PyQt5.QtGui import QIcon
                # 无托盘实例时跳过（此处仅探测 Qt 是否可用）
                _ = QSystemTrayIcon
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"系统通知失败: {e}")

    threading.Thread(target=_run, daemon=True, name="DesktopNotify").start()  # 异步避免阻塞主线程
