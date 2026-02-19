#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置窗口模块
负责显示和修改程序设置
使用PyQt5实现
"""

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QLabel, QPushButton, QCheckBox, QSlider, QSpinBox, QDoubleSpinBox,
    QLineEdit, QScrollArea, QMessageBox, QFrame, QColorDialog,
    QRadioButton, QButtonGroup, QPlainTextEdit, QComboBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtGui import QFont, QDesktopServices, QColor
from typing import Optional, Dict, Any
from pathlib import Path
import re

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config, APP_VERSION
from utils.logger import get_logger
from utils.resource_path import get_resource_path
from .color_manager import Color48Picker

logger = get_logger()

# 设置页统一布局与样式常量
MARGIN_TAB = 16
SPACING_TAB = 16
SPACING_BLOCK = 20

# 共用 QSS（区块标题、正文标签、输入控件、保存按钮）
STYLE_SECTION_TITLE = "font-weight: bold; font-size: 13pt; color: #333333; margin-bottom: 4px;"
STYLE_LABEL = "font-size: 13px; color: #555555;"
STYLE_HINT = "font-size: 12px; color: #888888;"
STYLE_SLIDER = """
    QSlider::groove:horizontal {
        border: 1px solid #CCCCCC;
        height: 6px;
        background: #E0E0E0;
        border-radius: 3px;
    }
    QSlider::handle:horizontal {
        background: #4A90E2;
        border: 1px solid #4A90E2;
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }
    QSlider::handle:horizontal:hover { background: #357ABD; }
"""
STYLE_SPINBOX = """
    QSpinBox, QDoubleSpinBox {
        padding: 6px;
        border: 1px solid #CCCCCC;
        border-radius: 4px;
        font-size: 13px;
    }
    QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #4A90E2; }
"""
STYLE_COMBOBOX = """
    QComboBox {
        padding: 6px;
        border: 1px solid #CCCCCC;
        border-radius: 4px;
        font-size: 13px;
        min-height: 20px;
    }
    QComboBox:focus { border: 1px solid #4A90E2; }
"""
STYLE_SAVE_BTN = """
    QPushButton {
        background-color: #4CAF50;
        color: white;
        border: none;
        border-radius: 4px;
        font-size: 14px;
        font-weight: bold;
        padding: 8px 20px;
    }
    QPushButton:hover { background-color: #45a049; }
    QPushButton:pressed { background-color: #3d8b40; }
"""


class SettingsWindow(QDialog):
    """设置窗口"""
    
    def __init__(self, parent=None):
        """
        初始化设置窗口
        
        Args:
            parent: 父窗口
        """
        super().__init__(parent)
        self.config = Config()
        
        # 气象预警图片路径（兼容打包后的路径）
        self.weather_images_dir = get_resource_path("气象预警信号图片")
        self.current_weather_image = None  # 当前显示的图片对象
        
        # 数据源分类定义
        self.source_vars = {}
        self.individual_source_urls = []  # 存储所有单项数据源的URL
        self.fanstudio_source_urls = []  # 存储所有Fan Studio单项数据源的URL（不包括All源）
        self._updating_mutual_exclusion = False  # 防止回调循环的标志
        self._is_all_selected = False  # 标记当前是否处于全选状态
        # 初始化基础URL（必须在初始化列表之后调用，因为创建标签页时会使用这些列表）
        self._update_base_urls()
        
        # 设置UI（只在初始化时调用一次）
        self._setup_ui()
    
    def _update_base_urls(self):
        """更新基础URL（固定使用fanstudio.tech）"""
        base_domain = "fanstudio.tech"
        self.all_source_url = f"wss://ws.{base_domain}/all"
        self.base_domain = base_domain
    
    def _setup_ui(self):
        """设置UI（只在初始化时调用一次）"""
        # 设置窗口属性
        self.setWindowTitle("设置")
        
        # 获取屏幕尺寸，确保窗口不超出屏幕
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.desktop().screenGeometry()
        max_width = min(520, screen.width() - 40)  # 初始宽度 520，留出边距
        max_height = min(550, screen.height() - 100)  # 高度 550，留出边距（含任务栏）
        
        self.setMinimumSize(420, 300)  # 最小宽度 420，避免内容挤在一起
        self.resize(max_width, max_height)  # 初始尺寸
        # 最大尺寸不超过屏幕，留出更多边距
        self.setMaximumSize(screen.width() - 20, screen.height() - 40)  # 最大尺寸不超过屏幕
        # 使用非模态窗口，避免阻塞主界面事件循环
        self.setModal(False)
        
        # 设置窗口背景为白色
        self.setStyleSheet("background-color: white;")
        
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 创建标签页
        self.notebook = QTabWidget()
        main_layout.addWidget(self.notebook)
        
        # 标签页顺序：外观与显示、数据源、翻译、日志、关于
        self._create_appearance_tab()
        self._create_data_source_tab()
        self._create_translation_tab()
        self._create_log_tab()
        self._create_about_tab()
        
        # 创建底部按钮区域
        self._create_bottom_buttons(main_layout)
        
        # 居中显示
        self._center_window()
    
    def showEvent(self, event):
        """窗口显示时的事件处理，确保窗口不超出屏幕"""
        super().showEvent(event)
        # 在显示后再次调整窗口位置和大小，确保不超出屏幕
        self._adjust_window_to_screen()
    
    def _adjust_window_to_screen(self):
        """调整窗口大小和位置，确保不超出屏幕"""
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.desktop().screenGeometry()
        
        # 获取当前窗口尺寸
        window_width = self.width()
        window_height = self.height()
        
        # 如果窗口高度超过屏幕，调整窗口高度
        max_height = screen.height() - 40  # 留出40像素边距
        if window_height > max_height:
            window_height = max_height
            self.resize(window_width, window_height)
        
        # 如果窗口宽度超过屏幕，调整窗口宽度
        max_width = screen.width() - 20  # 留出20像素边距
        if window_width > max_width:
            window_width = max_width
            self.resize(window_width, window_height)
        
        # 计算理想位置（居中或相对于父窗口）
        if self.parent():
            parent_geometry = self.parent().geometry()
            x = parent_geometry.x() + (parent_geometry.width() - window_width) // 2
            y = parent_geometry.y() + (parent_geometry.height() - window_height) // 2
        else:
            x = (screen.width() - window_width) // 2
            y = (screen.height() - window_height) // 2
        
        # 确保窗口不超出屏幕边界
        # 水平方向：确保窗口在屏幕内
        x = max(10, min(x, screen.width() - window_width - 10))
        
        # 垂直方向：优先保证窗口完全可见
        # 如果窗口底部超出屏幕，向上移动
        if y + window_height > screen.height() - 10:
            y = screen.height() - window_height - 10
        # 如果窗口顶部超出屏幕，向下移动
        if y < 10:
            y = 10
        # 确保窗口底部不超出屏幕
        if y + window_height > screen.height() - 10:
            y = screen.height() - window_height - 10
        
        self.move(x, y)
    
    def _center_window(self):
        """窗口居中显示，确保不超出屏幕"""
        self._adjust_window_to_screen()
    
    def _create_appearance_tab(self):
        """创建「外观与显示」标签页（合并原显示设置、渲染方式、字体颜色、自定义文本）"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scrollable_widget = QWidget()
        main_layout = QVBoxLayout(scrollable_widget)
        main_layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        main_layout.setSpacing(SPACING_TAB)
        
        # ---------- 1. 基本显示 ----------
        block1 = QWidget()
        block1_layout = QVBoxLayout(block1)
        block1_layout.setContentsMargins(0, 0, 0, 0)
        block1_layout.setSpacing(12)
        sec1 = QLabel("基本显示")
        sec1.setStyleSheet(STYLE_SECTION_TITLE)
        block1_layout.addWidget(sec1)
        
        # 滚动速度
        speed_row = QWidget()
        speed_row_layout = QHBoxLayout(speed_row)
        speed_row_layout.setContentsMargins(0, 0, 0, 0)
        speed_row_layout.setSpacing(10)
        speed_label = QLabel("滚动速度:")
        speed_label.setStyleSheet(STYLE_LABEL)
        speed_slider = QSlider(Qt.Horizontal)
        speed_slider.setMinimum(1)
        speed_slider.setMaximum(200)
        speed_slider.setValue(int(self.config.gui_config.text_speed * 10))
        speed_slider.setStyleSheet(STYLE_SLIDER)
        speed_label_value = QLabel(f"{self.config.gui_config.text_speed:.1f}")
        speed_label_value.setStyleSheet("font-size: 13px; color: #333333; min-width: 40px;")
        speed_slider.valueChanged.connect(lambda v: speed_label_value.setText(f"{v / 10.0:.1f}"))
        speed_row_layout.addWidget(speed_label)
        speed_row_layout.addWidget(speed_slider)
        speed_row_layout.addWidget(speed_label_value)
        block1_layout.addWidget(speed_row)
        
        # 字体大小
        font_row = QWidget()
        font_row_layout = QHBoxLayout(font_row)
        font_row_layout.setContentsMargins(0, 0, 0, 0)
        font_row_layout.setSpacing(10)
        font_label = QLabel("字体大小:")
        font_label.setStyleSheet(STYLE_LABEL)
        font_slider = QSlider(Qt.Horizontal)
        font_slider.setMinimum(10)
        font_slider.setMaximum(100)
        font_slider.setValue(self.config.gui_config.font_size)
        font_slider.setStyleSheet(STYLE_SLIDER)
        font_label_value = QLabel(f"{self.config.gui_config.font_size}px")
        font_label_value.setStyleSheet("font-size: 13px; color: #333333; min-width: 50px;")
        font_slider.valueChanged.connect(lambda v: font_label_value.setText(f"{v}px"))
        font_row_layout.addWidget(font_label)
        font_row_layout.addWidget(font_slider)
        font_row_layout.addWidget(font_label_value)
        block1_layout.addWidget(font_row)
        
        # 显示时区
        from utils.timezone_names_zh import get_tz_options, iana_to_display
        timezone_options = get_tz_options()
        timezone_label = QLabel("显示时区:")
        timezone_label.setStyleSheet(STYLE_LABEL)
        block1_layout.addWidget(timezone_label)
        timezone_combo = QComboBox()
        timezone_combo.setEditable(False)
        for display, iana_id in timezone_options:
            timezone_combo.addItem(display, iana_id)
        current_tz = getattr(self.config.gui_config, 'timezone', 'Asia/Shanghai')
        idx = timezone_combo.findData(current_tz)
        if idx < 0:
            idx = timezone_combo.findText(iana_to_display(current_tz))
        if idx < 0:
            idx = timezone_combo.findText("UTC+8 北京")
        timezone_combo.setCurrentIndex(max(0, idx))
        timezone_combo.setStyleSheet(STYLE_COMBOBOX)
        block1_layout.addWidget(timezone_combo)
        timezone_hint = QLabel("修改时区后需重启软件生效。")
        timezone_hint.setStyleSheet(STYLE_HINT)
        block1_layout.addWidget(timezone_hint)
        main_layout.addWidget(block1)
        main_layout.addSpacing(SPACING_BLOCK)
        
        # ---------- 2. 窗口 ----------
        block2 = QWidget()
        block2_layout = QVBoxLayout(block2)
        block2_layout.setContentsMargins(0, 0, 0, 0)
        block2_layout.setSpacing(12)
        sec2 = QLabel("窗口")
        sec2.setStyleSheet(STYLE_SECTION_TITLE)
        block2_layout.addWidget(sec2)
        size_row = QHBoxLayout()
        size_row.setSpacing(15)
        width_label = QLabel("窗口宽度:")
        width_label.setStyleSheet(STYLE_LABEL)
        width_spin = QSpinBox()
        width_spin.setMinimum(200)
        width_spin.setMaximum(3000)
        width_spin.setValue(self.config.gui_config.window_width)
        width_spin.setStyleSheet(STYLE_SPINBOX)
        height_label = QLabel("窗口高度:")
        height_label.setStyleSheet(STYLE_LABEL)
        height_spin = QSpinBox()
        height_spin.setMinimum(50)
        height_spin.setMaximum(500)
        height_spin.setValue(self.config.gui_config.window_height)
        height_spin.setStyleSheet(STYLE_SPINBOX)
        size_row.addWidget(width_label)
        size_row.addWidget(width_spin)
        size_row.addWidget(height_label)
        size_row.addWidget(height_spin)
        size_row.addStretch()
        block2_layout.addLayout(size_row)
        opacity_label = QLabel("窗口透明度:")
        opacity_label.setStyleSheet(STYLE_LABEL)
        block2_layout.addWidget(opacity_label)
        opacity_row = QWidget()
        opacity_row_layout = QHBoxLayout(opacity_row)
        opacity_row_layout.setContentsMargins(0, 0, 0, 0)
        opacity_slider = QSlider(Qt.Horizontal)
        opacity_slider.setMinimum(1)
        opacity_slider.setMaximum(10)
        opacity_slider.setValue(int(self.config.gui_config.opacity * 10))
        opacity_slider.setStyleSheet(STYLE_SLIDER)
        opacity_label_value = QLabel(f"{self.config.gui_config.opacity:.1f}")
        opacity_label_value.setStyleSheet("font-size: 13px; color: #333333; min-width: 40px;")
        opacity_slider.valueChanged.connect(lambda v: opacity_label_value.setText(f"{v / 10.0:.1f}"))
        opacity_row_layout.addWidget(opacity_slider)
        opacity_row_layout.addWidget(opacity_label_value)
        block2_layout.addWidget(opacity_row)
        main_layout.addWidget(block2)
        main_layout.addSpacing(SPACING_BLOCK)
        
        # ---------- 3. 性能与渲染 ----------
        block3 = QWidget()
        block3_layout = QVBoxLayout(block3)
        block3_layout.setContentsMargins(0, 0, 0, 0)
        block3_layout.setSpacing(12)
        sec3 = QLabel("性能与渲染")
        sec3.setStyleSheet(STYLE_SECTION_TITLE)
        block3_layout.addWidget(sec3)
        render_row = QHBoxLayout()
        cpu_radio = QRadioButton("CPU 渲染（软件）")
        gpu_radio = QRadioButton("GPU 渲染（OpenGL）")
        cpu_radio.setStyleSheet(STYLE_LABEL)
        gpu_radio.setStyleSheet(STYLE_LABEL)
        if self.config.gui_config.use_gpu_rendering:
            gpu_radio.setChecked(True)
        else:
            cpu_radio.setChecked(True)
        cpu_radio.setToolTip("兼容性更好，修改后需重启软件生效")
        gpu_radio.setToolTip("硬件加速，修改后需重启软件生效")
        render_row.addWidget(cpu_radio)
        render_row.addWidget(gpu_radio)
        render_row.addStretch()
        block3_layout.addLayout(render_row)
        perf_row = QWidget()
        perf_row_layout = QHBoxLayout(perf_row)
        perf_row_layout.setContentsMargins(0, 0, 0, 0)
        perf_row_layout.setSpacing(60)
        vsync_checkbox = QCheckBox("启用垂直同步")
        vsync_checkbox.setChecked(self.config.gui_config.vsync_enabled)
        vsync_checkbox.setStyleSheet(STYLE_LABEL)
        fps_label = QLabel("目标帧率:")
        fps_label.setStyleSheet(STYLE_LABEL)
        fps_spin = QSpinBox()
        fps_spin.setMinimum(1)
        fps_spin.setMaximum(240)
        fps_spin.setValue(self.config.gui_config.target_fps)
        fps_spin.setToolTip("1–240 fps。开启 VSync 时实际帧率跟随显示器。")
        fps_spin.setStyleSheet(STYLE_SPINBOX)
        perf_row_layout.addWidget(vsync_checkbox)
        perf_row_layout.addWidget(fps_label)
        perf_row_layout.addWidget(fps_spin)
        perf_row_layout.addWidget(QLabel("fps"))
        perf_row_layout.addStretch()
        block3_layout.addWidget(perf_row)
        main_layout.addWidget(block3)
        main_layout.addSpacing(SPACING_BLOCK)
        
        # ---------- 4. 颜色 ----------
        block4 = QWidget()
        block4_layout = QVBoxLayout(block4)
        block4_layout.setContentsMargins(0, 0, 0, 0)
        block4_layout.setSpacing(12)
        sec4 = QLabel("颜色")
        sec4.setStyleSheet(STYLE_SECTION_TITLE)
        block4_layout.addWidget(sec4)
        report_color_value = self.config.message_config.report_color.upper()
        warning_color_value = self.config.message_config.warning_color.upper()
        custom_text_color_value = getattr(self.config.message_config, 'custom_text_color', '#01FF00').upper()
        self.current_report_color = report_color_value
        self.current_warning_color = warning_color_value
        self.current_custom_text_color = custom_text_color_value
        
        def _add_color_row(parent_layout, label_text, color_value, color_type):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(10)
            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-size: 13px; color: #555555;")
            lbl.setMinimumWidth(120)  # 统一标签宽度，三行颜色预览/色值/按钮纵向对齐
            row_layout.addWidget(lbl)
            preview = QLabel()
            preview.setFixedSize(40, 25)
            preview.setStyleSheet(f"background-color: {color_value}; border: 1px solid #000; border-radius: 3px;")
            row_layout.addWidget(preview)
            value_label = QLabel(color_value)
            value_label.setMinimumWidth(80)
            value_label.setStyleSheet("font-size: 13px; color: #333333; font-family: monospace;")
            row_layout.addWidget(value_label)
            btn = QPushButton("修改颜色")
            btn.setStyleSheet("font-size: 13px; padding: 4px 10px;")
            btn.clicked.connect(lambda: self._open_color_picker(color_type))
            row_layout.addWidget(btn)
            reset_btn = QPushButton("恢复默认")
            reset_btn.setStyleSheet("font-size: 12px; padding: 4px 10px;")
            reset_btn.clicked.connect(lambda: self._reset_color(color_type))
            row_layout.addWidget(reset_btn)
            row_layout.addStretch()
            parent_layout.addWidget(row)
            return preview, value_label
        
        self.report_color_preview, self.report_color_label = _add_color_row(block4_layout, "地震信息颜色:", report_color_value, 'report')
        self.warning_color_preview, self.warning_color_label = _add_color_row(block4_layout, "地震预警颜色:", warning_color_value, 'warning')
        self.custom_text_color_preview, self.custom_text_color_label = _add_color_row(block4_layout, "自定义文本颜色:", custom_text_color_value, 'custom_text')
        main_layout.addWidget(block4)
        main_layout.addSpacing(SPACING_BLOCK)
        
        # ---------- 5. 自定义文本 ----------
        block5 = QWidget()
        block5_layout = QVBoxLayout(block5)
        block5_layout.setContentsMargins(0, 0, 0, 0)
        block5_layout.setSpacing(12)
        sec5 = QLabel("自定义文本")
        sec5.setStyleSheet(STYLE_SECTION_TITLE)
        block5_layout.addWidget(sec5)
        custom_hint = QLabel("在「数据源」页选择「自定义文本」后，非预警时将显示此处编辑的文本。修改并保存后立即生效，无需重启。")
        custom_hint.setStyleSheet(STYLE_HINT)
        custom_hint.setWordWrap(True)
        block5_layout.addWidget(custom_hint)
        self.custom_text_edit = QPlainTextEdit()
        self.custom_text_edit.setPlaceholderText("输入要滚动显示的自定义文本...")
        self.custom_text_edit.setMinimumHeight(100)
        self.custom_text_edit.setPlainText(self.config.message_config.custom_text or "")
        block5_layout.addWidget(self.custom_text_edit)
        main_layout.addWidget(block5)
        
        # 保存变量引用（供 _save_appearance_settings 使用）
        self.display_vars = {
            'speed': speed_slider,
            'font_size': font_slider,
            'width': width_spin,
            'height': height_spin,
            'opacity': opacity_slider,
            'vsync_enabled': vsync_checkbox,
            'target_fps': fps_spin,
            'timezone': timezone_combo,
        }
        self.render_vars = {'use_gpu_rendering': gpu_radio}
        
        main_layout.addStretch()
        
        # 保存按钮
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 10, 0, 0)
        button_layout.addStretch()
        save_btn = QPushButton("保存")
        save_btn.setMinimumWidth(120)
        save_btn.setMinimumHeight(35)
        save_btn.setStyleSheet(STYLE_SAVE_BTN)
        save_btn.clicked.connect(self._save_appearance_settings)
        button_layout.addWidget(save_btn)
        button_layout.addStretch()
        main_layout.addWidget(button_frame)
        
        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "外观与显示")
    
    def _create_data_source_tab(self):
        """创建数据源设置标签页"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scrollable_widget = QWidget()
        scroll_layout = QVBoxLayout(scrollable_widget)
        scroll_layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        scroll_layout.setSpacing(SPACING_TAB)
        
        # 说明文字
        info_label = QLabel("提示：预警数据源只解析预警数据，历史数据源只解析速报数据。修改数据源后需重启程序生效。")
        info_label.setStyleSheet("color: #666; font-size: 14px; padding: 10px; background-color: #F0F0F0; border-radius: 4px;")
        info_label.setWordWrap(True)
        scroll_layout.addWidget(info_label)
        
        font = QFont()
        font.setBold(True)
        font.setPointSize(16)
        
        # 地震预警
        warning_label = QLabel("地震预警")
        warning_label.setFont(font)
        warning_label.setStyleSheet("color: #000000; padding-top: 10px; padding-bottom: 5px;")
        scroll_layout.addWidget(warning_label)
        
        # Fan Studio预警
        fs_warning_label = QLabel("Fan Studio预警")
        fs_warning_font = QFont()
        fs_warning_font.setBold(True)
        fs_warning_font.setPointSize(15)
        fs_warning_label.setFont(fs_warning_font)
        scroll_layout.addWidget(fs_warning_label)
        # Fan Studio预警：只解析预警数据
        self._add_source_checkbox(scrollable_widget, "fanstudio_warning", "Fan Studio预警（解析所有预警数据）", default_value=True)

        # Wolfx 预警（地震预警区：HTTP + WSS 全预警 与 WSS 单项互斥）
        wolfx_warning_label = QLabel("Wolfx 预警")
        wolfx_warning_label.setFont(fs_warning_font)
        scroll_layout.addWidget(wolfx_warning_label)
        self._add_source_checkbox(scrollable_widget, "https://api.wolfx.jp/sc_eew.json", "四川地震局预警 (HTTP)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "https://api.wolfx.jp/jma_eew.json", "日本气象厅预警 (HTTP)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "https://api.wolfx.jp/fj_eew.json", "福建地震局预警 (HTTP)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "https://api.wolfx.jp/cenc_eew.json", "中国地震预警网预警 (HTTP)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "https://api.wolfx.jp/cwa_eew.json", "台湾气象署预警 (HTTP)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "wss://ws-api.wolfx.jp/all_eew", "Wolfx 全预警 (WSS)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "wss://ws-api.wolfx.jp/sc_eew", "四川地震局预警 (WSS)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "wss://ws-api.wolfx.jp/jma_eew", "日本气象厅预警 (WSS)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "wss://ws-api.wolfx.jp/fj_eew", "福建地震局预警 (WSS)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "wss://ws-api.wolfx.jp/cenc_eew", "中国地震预警网预警 (WSS)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "wss://ws-api.wolfx.jp/cwa_eew", "台湾气象署预警 (WSS)", default_value=False)
        self._setup_wolfx_eew_mutual_exclusion()

        # NIED 数据源（地震预警区）
        nied_label = QLabel("NIED 数据源")
        nied_label.setFont(fs_warning_font)
        scroll_layout.addWidget(nied_label)
        self._add_source_checkbox(scrollable_widget, "wss://sismotide.top/nied", "日本防災科研所预警 (WSS)", default_value=False)
        
        # 地震速报 / 自定义文本 二选一（仅允许：地震预警+地震速报 或 地震预警+自定义文本）
        mode_label = QLabel("非预警时显示")
        mode_label.setFont(font)
        mode_label.setStyleSheet("color: #000000; padding-top: 15px; padding-bottom: 5px;")
        scroll_layout.addWidget(mode_label)
        self.report_mode_group = QButtonGroup(scrollable_widget)
        self.radio_report = QRadioButton("地震速报")
        self.radio_custom_text = QRadioButton("自定义文本")
        self.report_mode_group.addButton(self.radio_report)
        self.report_mode_group.addButton(self.radio_custom_text)
        use_custom = getattr(self.config.message_config, 'use_custom_text', False)
        self.radio_report.setChecked(not use_custom)
        self.radio_custom_text.setChecked(use_custom)
        scroll_layout.addWidget(self.radio_report)
        scroll_layout.addWidget(self.radio_custom_text)
        mode_hint = QLabel("提示：切换「地震速报」/「自定义文本」需重启软件后生效。自定义文本内容在「外观与显示」页的「自定义文本」区块编辑。")
        mode_hint.setStyleSheet("color: #666; font-size: 14px;")
        mode_hint.setWordWrap(True)
        scroll_layout.addWidget(mode_hint)
        
        # 地震历史
        history_label = QLabel("地震历史")
        history_label.setFont(font)
        history_label.setStyleSheet("color: #000000; padding-top: 15px; padding-bottom: 5px;")
        scroll_layout.addWidget(history_label)
        
        # Fan Studio速报
        fs_report_label = QLabel("Fan Studio速报")
        fs_report_label.setFont(fs_warning_font)
        scroll_layout.addWidget(fs_report_label)
        # Fan Studio速报：只解析速报数据
        self._add_source_checkbox(scrollable_widget, "fanstudio_report", "Fan Studio速报（解析所有速报数据）", default_value=True)
        
        # 日本气象厅地震情报
        p2p_label = QLabel("日本气象厅地震情报")
        p2p_label.setFont(fs_warning_font)
        scroll_layout.addWidget(p2p_label)
        self._add_source_checkbox(scrollable_widget, "https://api.p2pquake.net/v2/history?codes=551&limit=3", "日本气象厅地震情报", default_value=True)
        self._add_source_checkbox(scrollable_widget, "https://api.p2pquake.net/v2/jma/tsunami?limit=1", "日本气象厅海啸预报", default_value=True)

        # Wolfx 速报（地震历史区：HTTP + WSS 单项）
        wolfx_report_label = QLabel("Wolfx 速报")
        wolfx_report_label.setFont(fs_warning_font)
        scroll_layout.addWidget(wolfx_report_label)
        self._add_source_checkbox(scrollable_widget, "https://api.wolfx.jp/cenc_eqlist.json", "中国地震台网中心速报 (HTTP)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "https://api.wolfx.jp/jma_eqlist.json", "日本气象厅速报 (HTTP)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "wss://ws-api.wolfx.jp/cenc_eqlist", "中国地震台网中心速报 (WSS)", default_value=False)
        self._add_source_checkbox(scrollable_widget, "wss://ws-api.wolfx.jp/jma_eqlist", "日本气象厅速报 (WSS)", default_value=False)
        
        scroll_layout.addStretch()
        
        # 按钮区域（全选和保存）
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 10, 0, 0)
        button_layout.addStretch()
        
        # 全选按钮
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setMinimumWidth(100)
        self.select_all_btn.setMinimumHeight(35)
        self.select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #4A90E2;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #357ABD;
            }
            QPushButton:pressed {
                background-color: #2E5F8F;
            }
        """)
        self.select_all_btn.clicked.connect(self._toggle_select_all)
        button_layout.addWidget(self.select_all_btn)
        
        button_layout.addSpacing(10)
        
        # 保存按钮
        save_btn = QPushButton("保存")
        save_btn.setMinimumWidth(120)
        save_btn.setMinimumHeight(35)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        save_btn.clicked.connect(self._save_data_source_settings)
        button_layout.addWidget(save_btn)
        button_layout.addStretch()
        
        scroll_layout.addWidget(button_frame)
        
        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "数据源")
    
    def _add_source_checkbox(self, parent, url, name, is_all_source=False, default_value=False):
        """添加数据源复选框"""
        # 特殊处理：fanstudio_warning和fanstudio_report
        if url in ["fanstudio_warning", "fanstudio_report"]:
            # 所有数据源默认启用，所以fanstudio_warning和fanstudio_report也默认启用
            base_domain = "fanstudio.tech"
            
            if url == "fanstudio_warning":
                # 确保所有预警数据源启用
                warning_sources = ['cea', 'cea-pr', 'sichuan', 'cwa-eew', 'jma', 'sa', 'kma-eew']
                for source in warning_sources:
                    source_url = f"wss://ws.{base_domain}/{source}"
                    self.config.enabled_sources[source_url] = True
                initial_value = True
            elif url == "fanstudio_report":
                # 确保所有速报数据源启用
                report_sources = ['cenc', 'ningxia', 'guangxi', 'shanxi', 'beijing', 'cwa', 'hko', 
                                 'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma', 'fssn']
                for source in report_sources:
                    source_url = f"wss://ws.{base_domain}/{source}"
                    self.config.enabled_sources[source_url] = True
                initial_value = True
            else:
                initial_value = True
        else:
            config_value = self.config.enabled_sources.get(url)
            if config_value is None:
                initial_value = default_value
                self.config.enabled_sources[url] = default_value
            else:
                initial_value = config_value
                self.config.enabled_sources[url] = config_value
        
        checkbox = QCheckBox(name, parent)
        checkbox.setChecked(initial_value)
        self.source_vars[url] = checkbox
        
        # 如果不是All源，记录到单项数据源列表
        if not is_all_source and url and url not in ["fanstudio_warning", "fanstudio_report"]:
            self.individual_source_urls.append(url)
            # 如果是Fan Studio数据源（WebSocket URL），记录到Fan Studio列表
            if 'fanstudio.tech' in url or 'fanstudio.hk' in url:
                self.fanstudio_source_urls.append(url)
        
        # 不再需要互斥逻辑，因为all数据源已隐藏，所有单项数据源都从all数据源解析
        
        # 添加到父布局
        if isinstance(parent.layout(), QVBoxLayout):
            parent.layout().addWidget(checkbox)

    # Wolfx 预警 WSS：全预警(all_eew) 与 单项(sc_eew, jma_eew, ...) 互斥
    WOLFX_ALL_EEW_URL = "wss://ws-api.wolfx.jp/all_eew"
    WOLFX_WSS_EEW_INDIVIDUAL = [
        "wss://ws-api.wolfx.jp/sc_eew", "wss://ws-api.wolfx.jp/jma_eew", "wss://ws-api.wolfx.jp/fj_eew",
        "wss://ws-api.wolfx.jp/cenc_eew", "wss://ws-api.wolfx.jp/cwa_eew",
    ]

    def _setup_wolfx_eew_mutual_exclusion(self):
        """Wolfx 全预警 (WSS) 与 单项预警 (WSS) 互斥：勾选全预警则取消所有单项，勾选任一项单项则取消全预警"""
        if self.WOLFX_ALL_EEW_URL not in self.source_vars:
            return
        all_cb = self.source_vars[self.WOLFX_ALL_EEW_URL]
        individual_cbs = [self.source_vars[u] for u in self.WOLFX_WSS_EEW_INDIVIDUAL if u in self.source_vars]

        def on_all_toggled(checked):
            if not checked:
                return
            for cb in individual_cbs:
                if cb.isChecked():
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)

        def on_individual_toggled(checked):
            if not checked:
                return
            if all_cb.isChecked():
                all_cb.blockSignals(True)
                all_cb.setChecked(False)
                all_cb.blockSignals(False)

        all_cb.toggled.connect(on_all_toggled)
        for cb in individual_cbs:
            cb.toggled.connect(on_individual_toggled)
    
    def _toggle_select_all(self):
        """切换全选/恢复默认选中状态"""
        if self._is_all_selected:
            # 当前是全选状态，恢复默认选中
            self._restore_default_selection()
            self._is_all_selected = False
            self.select_all_btn.setText("全选")
        else:
            # 当前是默认状态，全选所有数据源
            self._select_all_sources()
            self._is_all_selected = True
            self.select_all_btn.setText("恢复默认")
    
    def _select_all_sources(self):
        """全选所有数据源（Wolfx 预警 WSS 取全预警，与单项互斥）"""
        for url, checkbox in self.source_vars.items():
            if url and url != self.all_source_url:  # 跳过空URL和all数据源
                checkbox.setChecked(True)
        # 全选时 Wolfx 预警 WSS 使用「全预警」，取消单项 WSS
        if self.WOLFX_ALL_EEW_URL in self.source_vars:
            self.source_vars[self.WOLFX_ALL_EEW_URL].setChecked(True)
    
    def _restore_default_selection(self):
        """恢复默认选中状态"""
        # 默认选中的数据源：Fan Studio预警、Fan Studio速报、日本气象厅地震情报
        # 先全部取消选中
        for url, checkbox in self.source_vars.items():
            if url and url != self.all_source_url:
                checkbox.setChecked(False)
        
        # 选中默认数据源（Fan Studio 预警/速报、日本气象厅地震情报、日本气象厅海啸预报；Wolfx/NIED 保持不选）
        if "fanstudio_warning" in self.source_vars:
            self.source_vars["fanstudio_warning"].setChecked(True)
        if "fanstudio_report" in self.source_vars:
            self.source_vars["fanstudio_report"].setChecked(True)
        if "https://api.p2pquake.net/v2/history?codes=551&limit=3" in self.source_vars:
            self.source_vars["https://api.p2pquake.net/v2/history?codes=551&limit=3"].setChecked(True)
        if "https://api.p2pquake.net/v2/jma/tsunami?limit=1" in self.source_vars:
            self.source_vars["https://api.p2pquake.net/v2/jma/tsunami?limit=1"].setChecked(True)
    
    def _create_translation_tab(self):
        """创建翻译设置标签页"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scrollable_widget = QWidget()
        main_layout = QVBoxLayout(scrollable_widget)
        main_layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        main_layout.setSpacing(SPACING_TAB)
        
        mode_frame = QWidget()
        mode_layout = QVBoxLayout(mode_frame)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(15)
        mode_title = QLabel("地名处理方式")
        mode_title.setStyleSheet(STYLE_SECTION_TITLE)
        mode_layout.addWidget(mode_title)
        
        # 地名修正选项（用于速报）
        fix_frame = QWidget()
        fix_layout = QVBoxLayout(fix_frame)
        fix_layout.setContentsMargins(0, 0, 0, 0)
        fix_layout.setSpacing(5)
        
        fix_checkbox = QCheckBox("速报使用地名修正")
        fix_checkbox.setChecked(self.config.translation_config.use_place_name_fix)
        fix_checkbox.setStyleSheet("font-size: 14px; padding: 5px;")
        fix_layout.addWidget(fix_checkbox)
        
        fix_info = QLabel("速报消息根据经纬度自动修正地名（支持usgs, emsc, bcsf, gfz, usp, kma数据源）\n无需配置API密钥")
        fix_info.setStyleSheet("color: #666666; font-size: 12px; padding-left: 25px; line-height: 1.5;")
        fix_info.setWordWrap(True)
        fix_layout.addWidget(fix_info)
        mode_layout.addWidget(fix_frame)
        
        mode_layout.addSpacing(5)
        
        # 百度翻译选项（用于预警）
        baidu_frame = QWidget()
        baidu_layout = QVBoxLayout(baidu_frame)
        baidu_layout.setContentsMargins(0, 0, 0, 0)
        baidu_layout.setSpacing(5)
        
        baidu_checkbox = QCheckBox("预警使用百度翻译")
        baidu_checkbox.setChecked(self.config.translation_config.enabled)
        baidu_checkbox.setStyleSheet("font-size: 14px; padding: 5px;")
        baidu_layout.addWidget(baidu_checkbox)
        
        baidu_info = QLabel("预警消息将日语、韩语、英语地名翻译为中文\n需要配置百度翻译API密钥")
        baidu_info.setStyleSheet("color: #666666; font-size: 12px; padding-left: 25px; line-height: 1.5;")
        baidu_info.setWordWrap(True)
        baidu_layout.addWidget(baidu_info)
        mode_layout.addWidget(baidu_frame)
        
        main_layout.addWidget(mode_frame)
        
        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("color: #E0E0E0;")
        main_layout.addWidget(separator)
        
        # API配置区域（仅在使用百度翻译时显示）
        config_frame = QWidget()
        config_layout = QVBoxLayout(config_frame)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(15)
        
        # 配置标题
        config_title = QLabel("API 配置（预警使用百度翻译时需要）")
        config_title_font = QFont()
        config_title_font.setBold(True)
        config_title_font.setPointSize(13)
        config_title.setFont(config_title_font)
        config_title.setStyleSheet("color: #333333; margin-bottom: 5px;")
        config_layout.addWidget(config_title)
        
        # 根据选择显示/隐藏API配置区域
        def update_api_config_visibility():
            if baidu_checkbox.isChecked():
                config_frame.setVisible(True)
            else:
                config_frame.setVisible(False)
        
        baidu_checkbox.toggled.connect(update_api_config_visibility)
        # 初始化显示状态
        update_api_config_visibility()
        
        # App ID 输入组
        app_id_group = QWidget()
        app_id_layout = QVBoxLayout(app_id_group)
        app_id_layout.setContentsMargins(0, 0, 0, 0)
        app_id_layout.setSpacing(5)
        
        app_id_label = QLabel("百度翻译 App ID:")
        app_id_label.setStyleSheet("font-size: 13px; color: #555555;")
        app_id_layout.addWidget(app_id_label)
        
        app_id_entry = QLineEdit()
        app_id_entry.setText(self.config.translation_config.baidu_app_id)
        app_id_entry.setEchoMode(QLineEdit.Password)
        app_id_entry.setMaxLength(100)
        app_id_entry.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #4A90E2;
            }
        """)
        app_id_layout.addWidget(app_id_entry)
        config_layout.addWidget(app_id_group)
        
        # Secret Key 输入组
        secret_key_group = QWidget()
        secret_key_layout = QVBoxLayout(secret_key_group)
        secret_key_layout.setContentsMargins(0, 0, 0, 0)
        secret_key_layout.setSpacing(5)
        
        secret_key_label = QLabel("百度翻译 Secret Key:")
        secret_key_label.setStyleSheet("font-size: 13px; color: #555555;")
        secret_key_layout.addWidget(secret_key_label)
        
        secret_key_entry = QLineEdit()
        secret_key_entry.setText(self.config.translation_config.baidu_secret_key)
        secret_key_entry.setEchoMode(QLineEdit.Password)
        secret_key_entry.setMaxLength(100)
        secret_key_entry.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 1px solid #CCCCCC;
                border-radius: 4px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #4A90E2;
            }
        """)
        secret_key_layout.addWidget(secret_key_entry)
        config_layout.addWidget(secret_key_group)
        
        # 获取API密钥链接
        link_label = QLabel('获取API密钥请访问: <a href="https://fanyi-api.baidu.com/" style="color: #4A90E2; text-decoration: none;">百度翻译开放平台</a>')
        link_label.setOpenExternalLinks(True)
        link_label.setStyleSheet("font-size: 12px; color: #666666; padding-top: 5px;")
        config_layout.addWidget(link_label)
        
        main_layout.addWidget(config_frame)
        
        # 提示信息区域
        hint_frame = QWidget()
        hint_frame.setStyleSheet("""
            QWidget {
                background-color: #FFF9E6;
                border: 1px solid #FFE082;
                border-radius: 4px;
                padding: 10px;
            }
        """)
        hint_layout = QVBoxLayout(hint_frame)
        hint_layout.setContentsMargins(12, 10, 12, 10)
        hint_layout.setSpacing(5)
        
        hint_text = "提示：\n• 速报消息使用地名修正（根据经纬度自动修正，无需API密钥）\n• 预警消息使用百度翻译（需要配置API密钥）\n• 配置后需要保存设置并重启程序才能生效"
        hint_label = QLabel(hint_text)
        hint_label.setStyleSheet("color: #E65100; font-size: 12px; line-height: 1.5;")
        hint_label.setWordWrap(True)
        hint_layout.addWidget(hint_label)
        
        main_layout.addWidget(hint_frame)
        
        # 添加弹性空间
        main_layout.addStretch()
        
        # 保存按钮区域
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 10, 0, 0)
        button_layout.addStretch()  # 左侧弹性空间，使按钮居中
        
        save_btn = QPushButton("保存")
        save_btn.setMinimumWidth(120)
        save_btn.setMinimumHeight(35)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        save_btn.clicked.connect(self._save_translation_settings)
        button_layout.addWidget(save_btn)
        button_layout.addStretch()  # 右侧弹性空间，使按钮居中
        
        main_layout.addWidget(button_frame)
        
        # 保存变量引用
        self.translation_vars = {
            'baidu_checkbox': baidu_checkbox,
            'fix_checkbox': fix_checkbox,
            'app_id': app_id_entry,
            'secret_key': secret_key_entry,
        }
        
        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "翻译")
    
    def _create_log_tab(self):
        """创建日志设置标签页"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scrollable_widget = QWidget()
        layout = QVBoxLayout(scrollable_widget)
        layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        layout.setSpacing(SPACING_TAB)
        
        title_label = QLabel("日志设置")
        title_label.setStyleSheet(STYLE_SECTION_TITLE)
        layout.addWidget(title_label)
        
        # 说明文字
        desc_label = QLabel("配置日志输出选项")
        desc_label.setStyleSheet("color: #666; padding-bottom: 15px;")
        layout.addWidget(desc_label)
        
        # 输出日志到文件
        output_file_checkbox = QCheckBox("输出日志到文件")
        output_file_checkbox.setChecked(self.config.log_config.output_to_file)
        output_file_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 14px;
                padding: 5px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
        """)
        layout.addWidget(output_file_checkbox)
        
        # 说明
        output_file_desc = QLabel("启用后，日志将保存到 log.txt 文件中")
        output_file_desc.setWordWrap(True)  # 启用自动换行
        output_file_desc.setStyleSheet("color: #888; font-size: 12px; padding-left: 30px; padding-bottom: 10px;")
        layout.addWidget(output_file_desc)
        
        # 每次程序启动前清空日志
        clear_log_checkbox = QCheckBox("每次程序启动前清空日志")
        clear_log_checkbox.setChecked(self.config.log_config.clear_log_on_startup)
        clear_log_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 14px;
                padding: 5px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
        """)
        layout.addWidget(clear_log_checkbox)
        
        # 说明
        clear_log_desc = QLabel("启用后，每次启动程序时会清空日志文件")
        clear_log_desc.setWordWrap(True)  # 启用自动换行
        clear_log_desc.setStyleSheet("color: #888; font-size: 12px; padding-left: 30px; padding-bottom: 10px;")
        layout.addWidget(clear_log_desc)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("color: #ddd;")
        layout.addWidget(line)
        
        # 按日期分割日志
        split_date_checkbox = QCheckBox("按日期分割日志")
        split_date_checkbox.setChecked(self.config.log_config.split_by_date)
        split_date_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 14px;
                padding: 5px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
        """)
        layout.addWidget(split_date_checkbox)
        
        # 说明
        split_date_desc = QLabel("启用后，日志文件将按日期命名（log_YYYYMMDD.txt），每天自动创建新文件")
        split_date_desc.setWordWrap(True)  # 启用自动换行
        split_date_desc.setStyleSheet("color: #888; font-size: 12px; padding-left: 30px; padding-bottom: 10px;")
        layout.addWidget(split_date_desc)
        
        # 日志大小设置
        log_size_layout = QHBoxLayout()
        log_size_label = QLabel("日志文件最大大小（MB）：")
        log_size_label.setStyleSheet("font-size: 14px;")
        log_size_layout.addWidget(log_size_label)
        
        log_size_spinbox = QSpinBox()
        log_size_spinbox.setMinimum(1)
        log_size_spinbox.setMaximum(1000)
        log_size_spinbox.setValue(self.config.log_config.max_log_size)
        log_size_spinbox.setSuffix(" MB")
        log_size_spinbox.setStyleSheet("""
            QSpinBox {
                font-size: 14px;
                padding: 5px;
                border: 1px solid #ccc;
                border-radius: 3px;
            }
        """)
        log_size_layout.addWidget(log_size_spinbox)
        log_size_layout.addStretch()
        layout.addLayout(log_size_layout)
        
        # 说明
        log_size_desc = QLabel("当日志文件达到此大小时，将自动创建备份文件（仅在未启用按日期分割时生效）")
        log_size_desc.setWordWrap(True)  # 启用自动换行
        log_size_desc.setStyleSheet("color: #888; font-size: 12px; padding-left: 0px; padding-bottom: 10px;")
        layout.addWidget(log_size_desc)
        
        layout.addStretch()
        
        # 底部按钮
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 10, 0, 0)  # 与其他标签页保持一致
        button_layout.addStretch()  # 左侧弹性空间，使按钮居中
        
        # 为保持与其他标签页一致，统一保存按钮尺寸
        save_btn = QPushButton("保存")
        save_btn.setMinimumWidth(120)
        save_btn.setMinimumHeight(35)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
                padding: 8px 20px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        save_btn.clicked.connect(lambda: self._save_log_settings(
            output_file_checkbox, clear_log_checkbox, split_date_checkbox, log_size_spinbox
        ))
        button_layout.addWidget(save_btn)
        button_layout.addStretch()  # 右侧弹性空间，使按钮居中
        
        layout.addWidget(button_frame)
        
        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "日志")
    
    def _save_log_settings(self, output_file_checkbox, clear_log_checkbox, split_date_checkbox, log_size_spinbox):
        """保存日志设置"""
        try:
            self.config.log_config.output_to_file = output_file_checkbox.isChecked()
            self.config.log_config.clear_log_on_startup = clear_log_checkbox.isChecked()
            self.config.log_config.split_by_date = split_date_checkbox.isChecked()
            self.config.log_config.max_log_size = log_size_spinbox.value()
            
            # 验证配置
            if not self.config.log_config.validate():
                QMessageBox.warning(self, "警告", "日志配置验证失败，请检查设置")
                return
            
            # 保存到文件
            self.config.save_config()
            
            QMessageBox.information(self, "成功", "日志设置已保存！\n需要重启程序才能生效。")
            logger.debug("日志设置已保存")
            
        except Exception as e:
            logger.error(f"保存日志设置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")
    
    def _open_baidu_translate_link(self):
        """打开百度翻译开放平台链接"""
        try:
            QDesktopServices.openUrl(QUrl("https://fanyi-api.baidu.com/"))
        except Exception as e:
            logger.error(f"打开百度翻译开放平台链接失败: {e}")
            QMessageBox.critical(self, "错误", f"无法打开链接: {e}")
    
    def _save_translation_settings(self):
        """保存翻译设置"""
        try:
            # 更新地名修正设置（用于速报）
            self.config.translation_config.use_place_name_fix = self.translation_vars['fix_checkbox'].isChecked()
            
            # 更新百度翻译设置（用于预警）
            # 获取API密钥
            app_id = self.translation_vars['app_id'].text().strip()
            secret_key = self.translation_vars['secret_key'].text().strip()
            
            # 如果选择了使用百度翻译，需要检查API密钥
            if self.translation_vars['baidu_checkbox'].isChecked():
                if app_id and secret_key:
                    self.config.translation_config.enabled = True
                else:
                    QMessageBox.warning(self, "警告", "启用预警百度翻译需要配置API密钥！\n翻译功能将保持禁用状态。")
                    self.config.translation_config.enabled = False
            else:
                    self.config.translation_config.enabled = False
            
            # 更新API密钥
            self.config.translation_config.baidu_app_id = app_id
            self.config.translation_config.baidu_secret_key = secret_key
            
            # 保存到文件
            self.config.save_config()
            
            QMessageBox.information(
                self,
                "提示",
                "翻译设置已保存，程序将自动重启以应用更改。"
            )
            logger.debug("翻译设置已保存")
            self._restart_application()
            return
            
        except Exception as e:
            logger.error(f"保存翻译设置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")

    
    def _create_about_tab(self):
        """创建关于标签页"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scrollable_widget = QWidget()
        layout = QVBoxLayout(scrollable_widget)
        layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        layout.setSpacing(SPACING_TAB)
        sep_style = "background-color: #E0E0E0; max-height: 1px;"
        body_style = "color: #555555; font-size: 13px; padding-left: 10px; padding-bottom: 2px;"

        # 标题与版本
        title_label = QLabel("地震预警及速报滚动实况")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #0066CC; padding-bottom: 2px;")
        layout.addWidget(title_label)
        version_label = QLabel(f"版本 v{APP_VERSION} Beta测试版")
        version_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #FF6600; padding-bottom: 6px;")
        layout.addWidget(version_label)
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFrameShadow(QFrame.Sunken)
        sep1.setStyleSheet(sep_style)
        layout.addWidget(sep1)
        layout.addSpacing(4)

        # 数据源支持
        data_source_label = QLabel("数据源支持")
        data_source_label.setStyleSheet(STYLE_SECTION_TITLE)
        layout.addWidget(data_source_label)
        for name in ["Fan Studio", "P2PQuake", "Wolfx防灾", "NIED 日本防災科研所"]:
            lb = QLabel(f"• {name}")
            lb.setStyleSheet(body_style)
            layout.addWidget(lb)
        layout.addSpacing(SPACING_BLOCK - 4)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        sep2.setStyleSheet(sep_style)
        layout.addWidget(sep2)
        layout.addSpacing(4)

        # 开发者
        developer_label = QLabel("开发者")
        developer_label.setStyleSheet(STYLE_SECTION_TITLE)
        layout.addWidget(developer_label)
        for name in ["星落"]:
            lb = QLabel(f"• {name}")
            lb.setStyleSheet(body_style)
            layout.addWidget(lb)
        layout.addSpacing(SPACING_BLOCK - 4)
        sep2b = QFrame()
        sep2b.setFrameShape(QFrame.HLine)
        sep2b.setFrameShadow(QFrame.Sunken)
        sep2b.setStyleSheet(sep_style)
        layout.addWidget(sep2b)
        layout.addSpacing(4)

        # QQ群
        qq_label = QLabel("QQ群")
        qq_label.setStyleSheet(STYLE_SECTION_TITLE)
        layout.addWidget(qq_label)
        qq_value = QLabel("947523679")
        qq_value.setStyleSheet(body_style)
        layout.addWidget(qq_value)
        layout.addSpacing(SPACING_BLOCK - 4)
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.HLine)
        sep3.setFrameShadow(QFrame.Sunken)
        sep3.setStyleSheet(sep_style)
        layout.addWidget(sep3)
        layout.addSpacing(4)

        # 特别致谢
        thanks_label = QLabel("特别致谢")
        thanks_label.setStyleSheet(STYLE_SECTION_TITLE)
        layout.addWidget(thanks_label)
        thanks_frame = QWidget()
        thanks_frame.setStyleSheet(
            "QWidget { background-color: #F5F5F5; border-radius: 4px; }"
        )
        thanks_layout = QVBoxLayout(thanks_frame)
        thanks_layout.setContentsMargins(12, 10, 12, 10)
        thanks_layout.setSpacing(6)
        for text in ["感谢所有数据源提供方为地震监测事业做出的贡献。", "感谢所有用户的支持与反馈。"]:
            tl = QLabel(text)
            tl.setWordWrap(True)
            tl.setStyleSheet("color: #555555; font-size: 13px; line-height: 1.4;")
            thanks_layout.addWidget(tl)
        layout.addWidget(thanks_frame)
        layout.addStretch()

        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "关于")
    
    def _create_bottom_buttons(self, main_layout):
        """创建底部按钮区域"""
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        # 恢复默认按钮（左侧）
        restore_btn = QPushButton("恢复默认")
        restore_btn.setStyleSheet("background-color: #6c9ecc; color: white;")
        restore_btn.clicked.connect(self._restore_default_and_confirm)
        button_layout.addWidget(restore_btn)
        
        button_layout.addStretch()
        
        # 取消按钮（灰色）
        cancel_btn = QPushButton("取消")
        cancel_btn.setStyleSheet("background-color: #cccccc; color: black;")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        main_layout.addWidget(button_frame)
    
    def _restart_application(self):
        """重启应用程序。exe 下通过延迟或批处理先退出再启动新进程，避免 PyInstaller 解压冲突。"""
        import subprocess
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QTimer
        try:
            if getattr(sys, 'frozen', False):
                # 打包后的 exe：先退出，再由批处理延迟启动新进程，避免与当前进程共用解压目录
                exe_path = sys.executable
                args = sys.argv[1:]
                try:
                    import tempfile
                    fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="restart_")
                    os.close(fd)
                    with open(bat_path, "w", encoding="utf-8") as f:
                        f.write("@echo off\n")
                        f.write("ping 127.0.0.1 -n 3 > nul\n")  # 约 2 秒延迟
                        arg_str = " ".join(f'"{a}"' for a in args)
                        f.write(f'start "" "{exe_path}" {arg_str}\n')
                        f.write("del \"%~f0\"\n")  # 批处理删除自身
                    # 分离方式启动批处理，当前进程退出后批处理仍会执行
                    subprocess.Popen(
                        ["cmd", "/c", bat_path],
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
                    )
                except Exception as e:
                    logger.warning(f"批处理重启失败，改用延迟 Popen: {e}")
                    def _delayed_start():
                        try:
                            subprocess.Popen([exe_path] + sys.argv[1:])
                        except Exception as e2:
                            logger.error(f"延迟启动失败: {e2}")
                        QApplication.instance().quit()
                    QTimer.singleShot(2500, _delayed_start)
                    return
                QApplication.instance().quit()
                return
            # Python 脚本：直接启动新进程并退出
            python_exe = sys.executable
            script_path = sys.argv[0]
            subprocess.Popen([python_exe, script_path] + sys.argv[1:])
            QApplication.instance().quit()
        except Exception as e:
            logger.error(f"重启应用程序失败: {e}")
            QMessageBox.warning(
                self, "错误",
                f"无法自动重启程序：{e}\n\n请手动关闭程序后重新打开以使设置生效。"
            )
    
    def _restore_default_and_confirm(self):
        """恢复默认数据源选中，弹窗提供「保存」与「取消」；点保存则保存并重启。"""
        if hasattr(self, '_restore_default_selection') and hasattr(self, 'source_vars'):
            self._restore_default_selection()
            self._is_all_selected = False
            if hasattr(self, 'select_all_btn'):
                self.select_all_btn.setText("全选")
            msg = QMessageBox(self)
            msg.setWindowTitle("提示")
            msg.setIcon(QMessageBox.Information)
            msg.setText("数据源已恢复为默认选中（Fan Studio 预警/速报、日本气象厅地震情报、日本气象厅海啸预报）。点击「保存」将保存并重启软件。")
            save_btn = msg.addButton("保存", QMessageBox.AcceptRole)
            msg.addButton("取消", QMessageBox.RejectRole)
            msg.exec_()
            if msg.clickedButton() == save_btn:
                try:
                    self._save_data_source_settings(silent_restart=True)
                except Exception as e:
                    logger.error(f"保存并重启失败: {e}")
                    QMessageBox.critical(self, "错误", f"保存失败：{e}")
        else:
            QMessageBox.information(self, "提示", "当前页面无数据源选项，请切换到「数据源」标签页使用恢复默认。")
    
    def _save_all_settings(self):
        """保存所有设置"""
        try:
            self._save_data_source_settings()
            self._save_appearance_settings()
            self._save_translation_settings()
            QMessageBox.information(
                self, "成功",
                "所有设置已保存！\n数据源和翻译设置需要重启程序才能生效。"
            )
        except Exception as e:
            logger.error(f"保存设置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")
    
    def _save_data_source_settings(self, silent_restart=False):
        """保存数据源设置。silent_restart=True 时不弹「已保存」提示，直接重启。"""
        try:
            # 更新基础URL
            self._update_base_urls()
            
            all_url = self.all_source_url
            
            # 始终启用all数据源（隐藏但必须启用）
            self.config.enabled_sources[all_url] = True
            
            # 检查Fan Studio预警和速报的启用状态
            fanstudio_warning_enabled = self.source_vars.get("fanstudio_warning", None)
            fanstudio_report_enabled = self.source_vars.get("fanstudio_report", None)
            
            # 根据选择启用相应的Fan Studio数据源
            # 预警数据源列表
            warning_sources = ['cea', 'cea-pr', 'sichuan', 'cwa-eew', 'jma', 'sa', 'kma-eew']
            # 速报数据源列表
            report_sources = ['cenc', 'ningxia', 'guangxi', 'shanxi', 'beijing', 'cwa', 'hko', 
                             'usgs', 'emsc', 'bcsf', 'gfz', 'usp', 'kma', 'fssn']
            # 气象预警
            weather_source = 'weatheralarm'
            
            # 如果启用了Fan Studio预警，启用所有预警数据源
            # 否则，禁用所有预警数据源（设置为False）
            warning_checked = fanstudio_warning_enabled and fanstudio_warning_enabled.isChecked()
            for source in warning_sources:
                url = f"wss://ws.{self.base_domain}/{source}"
                self.config.enabled_sources[url] = warning_checked
                logger.debug(f"设置预警数据源 {source} 的状态为: {warning_checked}")
            
            # 如果启用了Fan Studio速报，启用所有速报数据源
            # 否则，禁用所有速报数据源（设置为False）
            report_checked = fanstudio_report_enabled and fanstudio_report_enabled.isChecked()
            for source in report_sources:
                url = f"wss://ws.{self.base_domain}/{source}"
                self.config.enabled_sources[url] = report_checked
                logger.debug(f"设置速报数据源 {source} 的状态为: {report_checked}")
            
            # 始终启用气象预警（默认开启，不可关闭）
            weather_url = f"wss://ws.{self.base_domain}/{weather_source}"
            self.config.enabled_sources[weather_url] = True
            
            # 更新其他数据源配置（P2PQuake等）
            for url, checkbox in self.source_vars.items():
                if url and url != all_url and url not in ["fanstudio_warning", "fanstudio_report"]:
                    self.config.enabled_sources[url] = checkbox.isChecked()
            
            # 更新WebSocket URL列表（只包含all数据源和其他非fanstudio数据源）
            # all数据源必须包含，单项fanstudio数据源不直接连接，只作为过滤器
            ws_urls = []
            # 确保all数据源被包含（无论enabled_sources中的状态）
            if all_url not in ws_urls:
                ws_urls.append(all_url)
                logger.debug(f"已添加all数据源到ws_urls: {all_url}")
            
            # 添加其他非fanstudio数据源
            for url in self.config.enabled_sources.keys():
                if url.startswith(('ws://', 'wss://')) and self.config.enabled_sources.get(url, False):
                    # 跳过all数据源（已经添加）
                    if url == all_url:
                        continue
                    # 如果是非fanstudio数据源，也包含
                    if 'fanstudio.tech' not in url and 'fanstudio.hk' not in url:
                        ws_urls.append(url)
                        logger.debug(f"已添加非fanstudio数据源到ws_urls: {url}")
            
            self.config.ws_urls = ws_urls
            logger.info(f"已更新ws_urls，包含{len(ws_urls)}个WebSocket数据源: {ws_urls}")
            
            # 地震速报 / 自定义文本 二选一
            self.config.message_config.use_custom_text = self.radio_custom_text.isChecked()
            
            # 保存到文件
            self.config.save_config()
            
            logger.debug("数据源设置已保存")
            
            if not silent_restart:
                QMessageBox.information(
                    self,
                    "提示",
                    "数据源设置已保存，程序将自动重启以应用更改。\n切换「地震速报」/「自定义文本」需重启后生效。"
                )
            self._restart_application()
            return
            
        except Exception as e:
            logger.error(f"保存数据源设置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")
    
    def _open_color_picker(self, color_type: str):
        """
        打开颜色选择器
        
        Args:
            color_type: 颜色类型，'report'、'warning' 或 'custom_text'
        """
        try:
            if color_type == 'report':
                initial_color = self.current_report_color
                default_color = '#00FFFF'  # 默认青色
            elif color_type == 'warning':
                initial_color = self.current_warning_color
                default_color = '#FF0000'  # 默认红色
            elif color_type == 'custom_text':
                initial_color = self.current_custom_text_color
                default_color = '#01FF00'  # 默认绿色
            else:
                logger.error(f"未知的颜色类型: {color_type}")
                return
            
            # 创建颜色选择器对话框
            color_picker = Color48Picker(initial_color, default_color, self)
            color_picker.colorSelected.connect(lambda color: self._on_color_selected(color_type, color))
            
            # 显示对话框
            if color_picker.exec_() == QDialog.Accepted:
                # 颜色已在信号中处理
                pass
                
        except Exception as e:
            logger.error(f"打开颜色选择器失败: {e}")
            QMessageBox.critical(self, "错误", f"打开颜色选择器失败: {e}")
    
    def _on_color_selected(self, color_type: str, color: str):
        """
        颜色选择回调
        
        Args:
            color_type: 颜色类型，'report' 或 'warning'
            color: 选中的颜色值（十六进制格式）
        """
        try:
            color_upper = color.upper()
            
            if color_type == 'report':
                self.current_report_color = color_upper
                self.report_color_preview.setStyleSheet(
                    f"background-color: {color_upper}; "
                    "border: 1px solid #000; "
                    "border-radius: 3px;"
                )
                self.report_color_label.setText(color_upper)
            elif color_type == 'warning':
                self.current_warning_color = color_upper
                self.warning_color_preview.setStyleSheet(
                    f"background-color: {color_upper}; "
                    "border: 1px solid #000; "
                    "border-radius: 3px;"
                )
                self.warning_color_label.setText(color_upper)
            elif color_type == 'custom_text':
                self.current_custom_text_color = color_upper
                self.custom_text_color_preview.setStyleSheet(
                    f"background-color: {color_upper}; "
                    "border: 1px solid #000; "
                    "border-radius: 3px;"
                )
                self.custom_text_color_label.setText(color_upper)
            
            logger.debug(f"颜色已选择: {color_type} -> {color_upper}")
            
        except Exception as e:
            logger.error(f"处理颜色选择失败: {e}")
    
    def _reset_color(self, color_type: str):
        """
        恢复默认颜色
        
        Args:
            color_type: 颜色类型，'report'、'warning' 或 'custom_text'
        """
        try:
            if color_type == 'report':
                default_color = '#00FFFF'  # 默认青色
                self.current_report_color = default_color
                self.report_color_preview.setStyleSheet(
                    f"background-color: {default_color}; "
                    "border: 1px solid #000; "
                    "border-radius: 3px;"
                )
                self.report_color_label.setText(default_color)
            elif color_type == 'warning':
                default_color = '#FF0000'  # 默认红色
                self.current_warning_color = default_color
                self.warning_color_preview.setStyleSheet(
                    f"background-color: {default_color}; "
                    "border: 1px solid #000; "
                    "border-radius: 3px;"
                )
                self.warning_color_label.setText(default_color)
            elif color_type == 'custom_text':
                default_color = '#01FF00'  # 默认绿色
                self.current_custom_text_color = default_color
                self.custom_text_color_preview.setStyleSheet(
                    f"background-color: {default_color}; "
                    "border: 1px solid #000; "
                    "border-radius: 3px;"
                )
                self.custom_text_color_label.setText(default_color)
            
            logger.debug(f"颜色已恢复默认: {color_type} -> {default_color}")
            
        except Exception as e:
            logger.error(f"恢复默认颜色失败: {e}")
    
    def _save_display_settings(self):
        """保存显示设置"""
        try:
            old_timezone = getattr(self.config.gui_config, 'timezone', 'Asia/Shanghai')
            new_timezone = self.display_vars['timezone'].currentData()
            if new_timezone is None:
                new_timezone = self.display_vars['timezone'].currentText().strip()
            timezone_changed = (old_timezone != new_timezone)
            
            # 更新GUI配置
            self.config.gui_config.text_speed = self.display_vars['speed'].value() / 10.0
            self.config.gui_config.font_size = self.display_vars['font_size'].value()
            self.config.gui_config.window_width = self.display_vars['width'].value()
            self.config.gui_config.window_height = self.display_vars['height'].value()
            self.config.gui_config.opacity = self.display_vars['opacity'].value() / 10.0
            self.config.gui_config.vsync_enabled = self.display_vars['vsync_enabled'].isChecked()
            self.config.gui_config.target_fps = self.display_vars['target_fps'].value()
            self.config.gui_config.timezone = new_timezone
            
            # 保存到文件
            self.config.save_config()
            
            # 通知主窗口更新（热更新，立即生效）
            self.config._notify_config_changed()
            
            if timezone_changed:
                QMessageBox.information(self, "成功", "显示设置已保存。\n时区已变更，请重启软件后生效。")
            else:
                QMessageBox.information(self, "成功", "显示设置已保存！\n设置已立即生效，无需重启程序。")
            logger.debug("显示设置已保存（热更新）")
            
        except Exception as e:
            logger.error(f"保存显示设置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")

    def _save_render_settings(self):
        """保存渲染方式设置（仅渲染方式页使用）"""
        try:
            self.config.gui_config.use_gpu_rendering = self.render_vars['use_gpu_rendering'].isChecked()
            self.config.save_config()
            self.config._notify_config_changed()
            msg = QMessageBox(self)
            msg.setWindowTitle("成功")
            msg.setText("渲染方式已保存，请重启软件后生效。")
            msg.setIcon(QMessageBox.Information)
            cancel_btn = msg.addButton("取消", QMessageBox.RejectRole)
            restart_btn = msg.addButton("重启", QMessageBox.AcceptRole)
            msg.exec_()
            if msg.clickedButton() == restart_btn:
                logger.debug("用户选择重启，正在重启软件...")
                os.execv(sys.executable, [sys.executable] + sys.argv)
            logger.debug("渲染方式已保存")
        except Exception as e:
            logger.error(f"保存渲染方式失败: {e}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")
    
    def _save_color_settings(self):
        """保存字体颜色设置"""
        try:
            # 更新颜色配置
            self.config.message_config.report_color = self.current_report_color
            self.config.message_config.warning_color = self.current_warning_color
            self.config.message_config.custom_text_color = self.current_custom_text_color
            
            # 保存到文件
            self.config.save_config()
            
            # 通知主窗口更新（热更新，立即生效）
            self.config._notify_config_changed()
            
            QMessageBox.information(self, "成功", "字体颜色设置已保存！\n设置已立即生效，无需重启程序。")
            logger.debug("字体颜色设置已保存（热更新）")
            
        except Exception as e:
            logger.error(f"保存字体颜色设置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")
    
    def _save_appearance_settings(self):
        """保存「外观与显示」页全部设置（显示、渲染、颜色、自定义文本），统一提示是否需重启。"""
        try:
            old_timezone = getattr(self.config.gui_config, 'timezone', 'Asia/Shanghai')
            new_timezone = self.display_vars['timezone'].currentData()
            if new_timezone is None:
                new_timezone = self.display_vars['timezone'].currentText().strip()
            timezone_changed = (old_timezone != new_timezone)
            old_gpu = self.config.gui_config.use_gpu_rendering
            new_gpu = self.render_vars['use_gpu_rendering'].isChecked()
            render_changed = (old_gpu != new_gpu)
            
            # 写入 gui_config（显示 + 渲染）
            self.config.gui_config.text_speed = self.display_vars['speed'].value() / 10.0
            self.config.gui_config.font_size = self.display_vars['font_size'].value()
            self.config.gui_config.window_width = self.display_vars['width'].value()
            self.config.gui_config.window_height = self.display_vars['height'].value()
            self.config.gui_config.opacity = self.display_vars['opacity'].value() / 10.0
            self.config.gui_config.vsync_enabled = self.display_vars['vsync_enabled'].isChecked()
            self.config.gui_config.target_fps = self.display_vars['target_fps'].value()
            self.config.gui_config.timezone = new_timezone
            self.config.gui_config.use_gpu_rendering = new_gpu
            
            # 写入 message_config（颜色 + 自定义文本）
            self.config.message_config.report_color = self.current_report_color
            self.config.message_config.warning_color = self.current_warning_color
            self.config.message_config.custom_text_color = self.current_custom_text_color
            self.config.message_config.custom_text = self.custom_text_edit.toPlainText().strip() or ""
            
            self.config.save_config()
            self.config._notify_config_changed()
            
            need_restart = timezone_changed or render_changed
            if need_restart:
                msg = QMessageBox(self)
                msg.setWindowTitle("成功")
                msg.setText("外观与显示设置已保存。\n时区或渲染方式已变更，请重启软件后生效。")
                msg.setIcon(QMessageBox.Information)
                cancel_btn = msg.addButton("取消", QMessageBox.RejectRole)
                restart_btn = msg.addButton("重启", QMessageBox.AcceptRole)
                msg.exec_()
                if msg.clickedButton() == restart_btn:
                    logger.debug("用户选择重启，正在重启软件...")
                    os.execv(sys.executable, [sys.executable] + sys.argv)
            else:
                QMessageBox.information(self, "成功", "外观与显示设置已保存！\n设置已立即生效，无需重启程序。")
            logger.debug("外观与显示设置已保存")
        except Exception as e:
            logger.error(f"保存外观与显示设置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")
    
    def _match_weather_image(self, weather_data: Dict[str, Any]) -> Optional[Path]:
        """
        根据气象预警数据匹配图片文件
        
        Args:
            weather_data: 气象预警数据字典，包含 'headline', 'title', 'type' 等字段
            
        Returns:
            匹配的图片文件路径，如果未找到则返回None
        """
        try:
            # 从headline或title中提取预警信息
            headline = weather_data.get('headline', '') or weather_data.get('title', '')
            if not headline:
                return None
            
            # 提取预警类型和颜色
            # 例如："广东省阳江市发布暴雨橙色预警信号" -> "暴雨橙色预警"
            # 匹配模式：{类型}{颜色}预警
            pattern = r'发布(.+?)(红色|橙色|黄色|蓝色|白色)预警'
            match = re.search(pattern, headline)
            
            if match:
                warning_type = match.group(1)  # 预警类型，如"暴雨"
                warning_color = match.group(2)  # 预警颜色，如"橙色"
                
                # 构建图片文件名
                image_filename = f"{warning_type}{warning_color}预警.jpg"
                image_path = self.weather_images_dir / image_filename
                
                if image_path.exists():
                    return image_path
            
            # 如果正则匹配失败，尝试从type字段匹配
            # type字段格式：p0002002（需要查找对应的映射表）
            # 这里先使用简单的文件名匹配
            logger.debug(f"无法从headline匹配图片: {headline}")
            return None
            
        except Exception as e:
            logger.error(f"匹配气象预警图片时出错: {e}")
            return None
    
    def update_weather_image(self, weather_data: Dict[str, Any]):
        """
        更新气象预警图片显示（已移除，不再在设置页面显示）
        
        Args:
            weather_data: 气象预警数据字典
        """
        # 不再在设置页面显示气象预警图片
        pass
