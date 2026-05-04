# -*- coding: utf-8 -*-
"""打包 exe 单实例（QLocalServer），避免重复启动导致重复的「检查更新」等对话框。"""
from __future__ import annotations

import sys
from typing import Any

_SINGLETON_KEY = "RollingSubtitle_EarthquakeScroller_SingleInstance"


def try_acquire_single_instance(app: Any) -> bool:
    """
    若当前为打包版且已有实例在运行，返回 False。
    调用方应在创建主窗口、执行启动时更新检查之前调用。
    """
    if not getattr(sys, "frozen", False):
        return True
    try:
        from PyQt5.QtNetwork import QLocalServer, QLocalSocket
    except Exception:
        return True

    probe = QLocalSocket()
    probe.connectToServer(_SINGLETON_KEY)
    if probe.waitForConnected(500):
        probe.disconnectFromServer()
        return False

    server = QLocalServer(app)
    QLocalServer.removeServer(_SINGLETON_KEY)
    if not server.listen(_SINGLETON_KEY):
        return True
    app._rolling_single_instance_server = server
    return True
