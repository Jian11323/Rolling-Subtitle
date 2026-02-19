#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI模块
包含主窗口、滚动文本组件和消息管理
使用PyQt5实现，解决窗口静止时卡顿问题
"""

from .main_window import MainWindow
from .scrolling_text import ScrollingText, ScrollingTextCPU
from .message_manager import MessageQueue, MessageBuffer, MessageItem
from .settings_window import SettingsWindow

__all__ = ['MainWindow', 'ScrollingText', 'ScrollingTextCPU', 'MessageQueue', 'MessageBuffer', 'MessageItem', 'SettingsWindow']
