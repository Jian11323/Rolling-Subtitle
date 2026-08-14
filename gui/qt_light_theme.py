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

# 石色滚动条样式表，供 QScrollArea / QTableWidget 等复用
LIGHT_SCROLLBAR_QSS = """
QScrollBar:vertical {
    background: #F3F1ED;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #C8C4BC;
    min-height: 28px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #A8A49C;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: #F3F1ED;
}
QScrollBar:horizontal {
    background: #F3F1ED;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #C8C4BC;
    min-width: 28px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal:hover {
    background: #A8A49C;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: #F3F1ED;
}
QAbstractScrollArea::corner {
    background: #F3F1ED;
}
"""


def apply_light_palette(
    widget: QWidget,
    bg: str = "#FFFFFF",
    text: str = "#1F2937",
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
    widget.setAutoFillBackground(True)  # 强制用 palette 填充背景


def light_dialog_stylesheet(bg: str = "#FFFFFF") -> str:
    """返回适用于 QDialog 及其常见子控件的浅色背景 stylesheet。"""
    return (
        f"QDialog {{ background-color: {bg}; }}"
        f"QDialog QLabel {{ background-color: transparent; }}"
        f"QDialog QCheckBox {{ background-color: transparent; }}"
        f"QDialog QRadioButton {{ background-color: transparent; }}"
        f"QDialog QFrame {{ background-color: transparent; }}"
        f"QScrollArea {{ background-color: {bg}; border: none; }}"
        # 仅设置滚动内容根节点，避免裸规则渗到卡片内文字控件
        f"QScrollArea > QWidget > QWidget#settingsScrollBody {{ background-color: {bg}; }}"
    )


def _prepare_message_box(
    parent: Optional[QWidget],
    icon: QMessageBox.Icon,
    title: str,
    text: str,
) -> QMessageBox:
    """创建并应用浅色主题的 QMessageBox 实例。"""
    msg = QMessageBox(parent)
    msg.setIcon(icon)
    msg.setWindowTitle(title)
    msg.setText(text)
    apply_light_palette(msg, "#FFFFFF", "#1F2937")
    msg.setStyleSheet(
        "QMessageBox { background-color: #FFFFFF; }"
        "QMessageBox QLabel { background-color: #FFFFFF; color: #1F2937; }"
        "QMessageBox QPushButton { background-color: #F3F1ED; color: #1F2937; "
        "border: 1px solid #E5E2DC; border-radius: 8px; padding: 6px 16px; min-width: 70px; }"
        "QMessageBox QPushButton:hover { background-color: #EAE7E1; }"
    )
    return msg


def show_info(parent: Optional[QWidget], title: str, text: str) -> None:
    """显示浅色主题信息对话框。"""
    _prepare_message_box(parent, QMessageBox.Information, title, text).exec_()


def show_warning(parent: Optional[QWidget], title: str, text: str) -> None:
    """显示浅色主题警告对话框。"""
    _prepare_message_box(parent, QMessageBox.Warning, title, text).exec_()


def show_critical(parent: Optional[QWidget], title: str, text: str) -> None:
    """显示浅色主题错误对话框。"""
    _prepare_message_box(parent, QMessageBox.Critical, title, text).exec_()


def show_question(
    parent: Optional[QWidget],
    title: str,
    text: str,
    buttons=QMessageBox.Yes | QMessageBox.No,
    default_button=QMessageBox.Yes,
) -> int:
    """显示浅色主题确认对话框，返回用户点击的标准按钮。"""
    msg = _prepare_message_box(parent, QMessageBox.Question, title, text)
    msg.setStandardButtons(buttons)
    msg.setDefaultButton(default_button)
    return msg.exec_()


def styled_message_box(parent: Optional[QWidget] = None) -> QMessageBox:
    """创建已应用浅色主题的 QMessageBox，供自定义按钮场景使用。"""
    msg = QMessageBox(parent)
    apply_light_palette(msg, "#FFFFFF", "#1F2937")
    msg.setStyleSheet(
        "QMessageBox { background-color: #FFFFFF; }"
        "QMessageBox QLabel { background-color: #FFFFFF; color: #1F2937; }"
        "QMessageBox QPushButton { background-color: #F3F1ED; color: #1F2937; "
        "border: 1px solid #E5E2DC; border-radius: 8px; padding: 6px 16px; min-width: 70px; }"
        "QMessageBox QPushButton:hover { background-color: #EAE7E1; }"
    )
    return msg
