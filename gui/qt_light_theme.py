#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浅色对话框/滚动条主题工具。

主窗口常为纯黑背景；子 QDialog / QMessageBox 在 Windows 深色主题下易继承深色
Window/Base 调色板，导致标题区、滚动条轨道、MessageBox 正文出现黑块。
仅 setStyleSheet 不足以覆盖 palette 驱动的绘制，需显式设置 QPalette。
"""

from typing import Optional

from PyQt5.QtWidgets import QMessageBox, QWidget
from PyQt5.QtGui import QColor, QPalette

LIGHT_SCROLLBAR_QSS = """
QScrollBar:vertical {
    background: #F5F5F5;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #C0C0C0;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #A0A0A0;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: #F5F5F5;
}
QScrollBar:horizontal {
    background: #F5F5F5;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #C0C0C0;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: #A0A0A0;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: #F5F5F5;
}
QAbstractScrollArea::corner {
    background: #F5F5F5;
}
"""


def apply_light_palette(
    widget: QWidget,
    bg: str = "#FFFFFF",
    text: str = "#222222",
) -> None:
    """为对话框/子窗口设置浅色 QPalette，避免 Win 深色主题下继承黑底。"""
    bg_color = QColor(bg)
    text_color = QColor(text)
    pal = widget.palette()
    pal.setColor(QPalette.Window, bg_color)
    pal.setColor(QPalette.Base, bg_color)
    pal.setColor(QPalette.WindowText, text_color)
    pal.setColor(QPalette.Text, text_color)
    pal.setColor(QPalette.Button, bg_color)
    pal.setColor(QPalette.ButtonText, text_color)
    widget.setPalette(pal)
    widget.setAutoFillBackground(True)


def light_dialog_stylesheet(bg: str = "#FFFFFF") -> str:
    """返回适用于 QDialog 及其常见子控件的浅色背景 stylesheet。"""
    return (
        f"QDialog {{ background-color: {bg}; }}"
        f"QDialog QLabel {{ background-color: {bg}; }}"
        f"QDialog QFrame {{ background-color: {bg}; }}"
        f"QScrollArea {{ background-color: {bg}; border: none; }}"
    )


def _prepare_message_box(
    parent: Optional[QWidget],
    icon: QMessageBox.Icon,
    title: str,
    text: str,
) -> QMessageBox:
    msg = QMessageBox(parent)
    msg.setIcon(icon)
    msg.setWindowTitle(title)
    msg.setText(text)
    apply_light_palette(msg, "#FFFFFF", "#222222")
    msg.setStyleSheet(
        "QMessageBox { background-color: #FFFFFF; }"
        "QMessageBox QLabel { background-color: #FFFFFF; color: #222222; }"
        "QMessageBox QPushButton { background-color: #F0F0F0; color: #222222; "
        "border: 1px solid #CCCCCC; border-radius: 4px; padding: 4px 16px; min-width: 70px; }"
        "QMessageBox QPushButton:hover { background-color: #E0E0E0; }"
    )
    return msg


def show_info(parent: Optional[QWidget], title: str, text: str) -> None:
    _prepare_message_box(parent, QMessageBox.Information, title, text).exec_()


def show_warning(parent: Optional[QWidget], title: str, text: str) -> None:
    _prepare_message_box(parent, QMessageBox.Warning, title, text).exec_()


def show_critical(parent: Optional[QWidget], title: str, text: str) -> None:
    _prepare_message_box(parent, QMessageBox.Critical, title, text).exec_()


def show_question(
    parent: Optional[QWidget],
    title: str,
    text: str,
    buttons=QMessageBox.Yes | QMessageBox.No,
    default_button=QMessageBox.Yes,
) -> int:
    msg = _prepare_message_box(parent, QMessageBox.Question, title, text)
    msg.setStandardButtons(buttons)
    msg.setDefaultButton(default_button)
    return msg.exec_()


def styled_message_box(parent: Optional[QWidget] = None) -> QMessageBox:
    """创建已应用浅色主题的 QMessageBox，供自定义按钮场景使用。"""
    msg = QMessageBox(parent)
    apply_light_palette(msg, "#FFFFFF", "#222222")
    msg.setStyleSheet(
        "QMessageBox { background-color: #FFFFFF; }"
        "QMessageBox QLabel { background-color: #FFFFFF; color: #222222; }"
        "QMessageBox QPushButton { background-color: #F0F0F0; color: #222222; "
        "border: 1px solid #CCCCCC; border-radius: 4px; padding: 4px 16px; min-width: 70px; }"
        "QMessageBox QPushButton:hover { background-color: #E0E0E0; }"
    )
    return msg
