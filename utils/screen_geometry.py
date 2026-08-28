#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多屏几何辅助：按窗口/坐标定位所在屏，避免副屏坐标被主屏尺寸错误夹紧。"""

from __future__ import annotations

from typing import Optional, Tuple

from PyQt5.QtCore import QPoint, QRect
from PyQt5.QtWidgets import QApplication, QWidget


def _desktop():
    app = QApplication.instance()
    if app is None:
        return None
    return QApplication.desktop()


def available_geometry_for(
    widget: Optional[QWidget] = None,
    point: Optional[QPoint] = None,
) -> QRect:
    """返回目标所在屏的可用工作区；无法判定时回退主屏。"""
    desk = _desktop()
    if desk is None:
        return QRect(0, 0, 1920, 1080)
    try:
        if widget is not None:
            return QRect(desk.availableGeometry(widget))
        if point is not None:
            idx = desk.screenNumber(point)
            if idx < 0:
                idx = desk.primaryScreen()
            return QRect(desk.availableGeometry(idx))
    except Exception:
        pass
    try:
        return QRect(desk.availableGeometry())
    except Exception:
        return QRect(0, 0, 1920, 1080)


def is_rect_on_any_screen(
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    min_visible_w: int = 80,
    min_visible_h: int = 24,
) -> bool:
    """窗口矩形是否与任一屏幕有足够交集（副屏拔掉后可据此判定失效）。"""
    desk = _desktop()
    if desk is None:
        return True
    win = QRect(int(x), int(y), max(1, int(w)), max(1, int(h)))
    try:
        count = int(desk.screenCount())
    except Exception:
        count = 1
    for i in range(max(1, count)):
        try:
            geo = desk.availableGeometry(i)
        except Exception:
            continue
        inter = win.intersected(geo)
        if inter.width() >= min_visible_w and inter.height() >= min_visible_h:
            return True
    return False


def clamp_top_left_to_screen(
    x: int,
    y: int,
    w: int,
    h: int,
    screen: QRect,
    *,
    margin: int = 10,
) -> Tuple[int, int]:
    """将左上角限制在指定屏可用区域内（坐标含副屏偏移，可为负）。"""
    m = max(0, int(margin))
    sw = max(1, screen.width())
    sh = max(1, screen.height())
    max_x = screen.x() + max(0, sw - int(w) - m)
    max_y = screen.y() + max(0, sh - int(h) - m)
    nx = max(screen.x() + m, min(int(x), max_x))
    ny = max(screen.y() + m, min(int(y), max_y))
    if int(w) >= sw - 2 * m:
        nx = screen.x() + m
    if int(h) >= sh - 2 * m:
        ny = screen.y() + m
    return nx, ny


def center_top_left_on_screen(w: int, h: int, screen: QRect) -> Tuple[int, int]:
    """在指定屏内居中，返回左上角坐标。"""
    x = screen.x() + (screen.width() - int(w)) // 2
    y = screen.y() + (screen.height() - int(h)) // 2
    return clamp_top_left_to_screen(x, y, w, h, screen, margin=0)


def place_window(
    window: QWidget,
    saved_x: int = -1,
    saved_y: int = -1,
    *,
    prefer_widget: Optional[QWidget] = None,
) -> None:
    """
    恢复已保存位置（仍落在某块屏上），否则在 prefer_widget / 自身所在屏居中。
    """
    w = max(1, window.width())
    h = max(1, window.height())
    if saved_x != -1 and saved_y != -1 and is_rect_on_any_screen(saved_x, saved_y, w, h):
        window.move(int(saved_x), int(saved_y))
        return
    anchor = prefer_widget if prefer_widget is not None else window
    screen = available_geometry_for(widget=anchor)
    nx, ny = center_top_left_on_screen(w, h, screen)
    window.move(nx, ny)
