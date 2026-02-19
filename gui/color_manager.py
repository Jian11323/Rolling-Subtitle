#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
颜色管理模块
提供48色选择器弹出框，用于自定义文本颜色
"""

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QColorDialog
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from typing import Optional

from utils.logger import get_logger

logger = get_logger()


class Color48Picker(QDialog):
    """48色选择器弹出框"""
    
    colorSelected = pyqtSignal(str)  # 颜色选择信号，传递十六进制颜色值
    
    # 48色标准颜色列表（常用颜色）
    COLORS_48 = [
        # 第一行：基本颜色
        '#000000', '#FFFFFF', '#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#FF00FF', '#00FFFF',
        # 第二行：深色系
        '#800000', '#008000', '#000080', '#808000', '#800080', '#008080', '#808080', '#C0C0C0',
        # 第三行：红色系
        '#FF8080', '#FF4040', '#FF0000', '#CC0000', '#990000', '#660000', '#FFC0C0', '#FFA0A0',
        # 第四行：绿色系
        '#80FF80', '#40FF40', '#00FF00', '#00CC00', '#009900', '#006600', '#C0FFC0', '#A0FFA0',
        # 第五行：蓝色系
        '#8080FF', '#4040FF', '#0000FF', '#0000CC', '#000099', '#000066', '#C0C0FF', '#A0A0FF',
        # 第六行：黄色/橙色系
        '#FFFF80', '#FFFF40', '#FFFF00', '#CCCC00', '#999900', '#666600', '#FFFFC0', '#FFFFA0',
    ]
    
    def __init__(self, initial_color: str = "#000000", default_color: Optional[str] = None, parent=None):
        """
        初始化48色选择器
        
        Args:
            initial_color: 初始颜色值（十六进制格式，如 #FF0000）
            default_color: 默认颜色值（十六进制格式），如果为None则不显示恢复默认按钮
            parent: 父窗口
        """
        super().__init__(parent)
        self.selected_color = initial_color.upper() if initial_color else "#000000"
        self.default_color = default_color.upper() if default_color else None
        self._init_ui()
    
    def _init_ui(self):
        """初始化UI"""
        self.setWindowTitle("选择颜色")
        self.setModal(True)
        self.setMinimumSize(400, 350)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)
        
        # 当前颜色预览
        preview_frame = QWidget()
        preview_layout = QHBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(10)
        
        preview_label = QLabel("当前颜色:")
        preview_label.setStyleSheet("font-size: 13px; color: #333333;")
        preview_layout.addWidget(preview_label)
        
        self.color_preview = QLabel()
        self.color_preview.setFixedSize(80, 40)
        self.color_preview.setStyleSheet(
            f"background-color: {self.selected_color}; "
            "border: 2px solid #333333; "
            "border-radius: 4px;"
        )
        preview_layout.addWidget(self.color_preview)
        
        self.color_value_label = QLabel(self.selected_color)
        self.color_value_label.setStyleSheet("font-size: 13px; color: #333333; font-family: monospace;")
        self.color_value_label.setMinimumWidth(100)
        preview_layout.addWidget(self.color_value_label)
        
        preview_layout.addStretch()
        main_layout.addWidget(preview_frame)
        
        # 48色网格
        colors_label = QLabel("48色标准颜色:")
        colors_label.setStyleSheet("font-size: 13px; color: #333333; font-weight: bold;")
        main_layout.addWidget(colors_label)
        
        colors_grid = QWidget()
        grid_layout = QGridLayout(colors_grid)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(5)
        
        # 创建颜色按钮（8列）
        cols = 8
        for i, color in enumerate(self.COLORS_48):
            row = i // cols
            col = i % cols
            
            color_btn = QPushButton()
            color_btn.setFixedSize(40, 40)
            color_btn.setStyleSheet(
                f"background-color: {color}; "
                "border: 2px solid #CCCCCC; "
                "border-radius: 4px;"
            )
            color_btn.setToolTip(color)
            color_btn.clicked.connect(lambda checked, c=color: self._on_color_clicked(c))
            grid_layout.addWidget(color_btn, row, col)
        
        main_layout.addWidget(colors_grid)
        
        # 自定义颜色按钮
        custom_frame = QWidget()
        custom_layout = QHBoxLayout(custom_frame)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        custom_layout.setSpacing(10)
        
        custom_label = QLabel("自定义颜色:")
        custom_label.setStyleSheet("font-size: 13px; color: #333333;")
        custom_layout.addWidget(custom_label)
        
        custom_btn = QPushButton("打开颜色选择器")
        custom_btn.setStyleSheet("""
            QPushButton {
                background-color: #4A90E2;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 15px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #357ABD;
            }
            QPushButton:pressed {
                background-color: #2E5F8F;
            }
        """)
        custom_btn.clicked.connect(self._open_custom_color_dialog)
        custom_layout.addWidget(custom_btn)
        custom_layout.addStretch()
        main_layout.addWidget(custom_frame)
        
        # 按钮区域
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(10)
        
        # 恢复默认按钮（如果有默认颜色）
        if self.default_color:
            reset_btn = QPushButton("恢复默认")
            reset_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FF9800;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 15px;
                    font-size: 13px;
                }
                QPushButton:hover {
                    background-color: #F57C00;
                }
                QPushButton:pressed {
                    background-color: #E65100;
                }
            """)
            reset_btn.clicked.connect(self._reset_to_default)
            button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        
        # 确定按钮
        ok_btn = QPushButton("确定")
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        ok_btn.clicked.connect(self._on_ok)
        button_layout.addWidget(ok_btn)
        
        # 取消按钮
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #CCCCCC;
                color: black;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #BBBBBB;
            }
            QPushButton:pressed {
                background-color: #AAAAAA;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        main_layout.addWidget(button_frame)
    
    def _on_color_clicked(self, color: str):
        """颜色按钮点击事件"""
        self.selected_color = color.upper()
        self._update_preview()
    
    def _open_custom_color_dialog(self):
        """打开系统颜色选择对话框"""
        color = QColorDialog.getColor(QColor(self.selected_color), self, "选择自定义颜色")
        if color.isValid():
            self.selected_color = color.name().upper()
            self._update_preview()
    
    def _reset_to_default(self):
        """恢复为默认颜色"""
        if self.default_color:
            self.selected_color = self.default_color
            self._update_preview()
    
    def _update_preview(self):
        """更新颜色预览"""
        self.color_preview.setStyleSheet(
            f"background-color: {self.selected_color}; "
            "border: 2px solid #333333; "
            "border-radius: 4px;"
        )
        self.color_value_label.setText(self.selected_color)
    
    def _on_ok(self):
        """确定按钮点击事件"""
        self.colorSelected.emit(self.selected_color)
        self.accept()
    
    def get_color(self) -> str:
        """获取选中的颜色"""
        return self.selected_color
