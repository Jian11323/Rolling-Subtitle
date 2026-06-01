#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
告警 UI 子包：字幕条左侧「地震预警」标识闪烁 + 状态机式告警序列控制器。
"""

from .alert_controller import AlertController, AlertState, build_warning_hint_segments

__all__ = [
    "AlertController",
    "AlertState",
    "build_warning_hint_segments",
]
