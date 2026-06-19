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
    QRadioButton, QButtonGroup, QPlainTextEdit, QComboBox, QGroupBox,
    QSizePolicy, QStyle, QShortcut,
)
from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QTimer
from PyQt5.QtGui import QFont, QDesktopServices, QColor, QFontDatabase, QKeySequence, QFontMetrics
from typing import Optional, Dict, Any, List, Tuple
import re
import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    Config,
    APP_VERSION,
    APP_DECLARATION_TEXT,
    P2PQUAKE_HTTP_SOURCE_KEYS,
    p2pquake_master_enabled,
    BMKG_HTTP_URL,
    GEONET_HTTP_URL,
    INGV_HTTP_URL,
    EARLYEST_HTTP_URL,
    JMA_ATOM_LONG_URL,
    DEFAULT_HTTP_POLL_INTERVALS,
)
from utils.logger import get_logger
from utils.resource_path import get_executable_path
from .color_manager import Color48Picker

logger = get_logger()

P2PQUAKE_WSS_URL = "wss://api.p2pquake.net/v2/ws"

# 设置页统一布局与样式常量
MARGIN_TAB = 16
SPACING_TAB = 16
SPACING_BLOCK = 20

# 共用 QSS（与高级版一致：16pt/16px 字号与新布局）
STYLE_SECTION_TITLE = "font-weight: bold; font-size: 16pt; color: #333333; margin-bottom: 4px;"
# 设置卡片内分区小标题（比 STYLE_SECTION_TITLE 略轻，用于同页多区块）
STYLE_CARD_SUBHEAD = "font-weight: bold; font-size: 15px; color: #444444; margin-top: 6px; margin-bottom: 2px;"
STYLE_LABEL = "font-size: 16px; color: #555555; line-height: 22pt;"
STYLE_HINT = "font-size: 16px; color: #888888; line-height: 22pt;"
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
        font-size: 16px;
    }
    QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #4A90E2; }
"""
STYLE_COMBOBOX = """
    QComboBox {
        padding: 6px;
        border: 1px solid #CCCCCC;
        border-radius: 4px;
        font-size: 16px;
        min-height: 24px;
    }
    QComboBox:focus { border: 1px solid #4A90E2; }
"""
STYLE_LINEEDIT = "QLineEdit { padding: 6px; border: 1px solid #CCCCCC; border-radius: 4px; font-size: 16px; } QLineEdit:focus { border: 1px solid #4A90E2; }"
STYLE_GROUPBOX = "QGroupBox { font-weight: bold; font-size: 16pt; color: #333333; border: 1px solid #CCCCCC; border-radius: 4px; margin-top: 10px; padding-top: 8px; } QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
STYLE_SOURCE_TITLE = "font-weight: bold; font-size: 16px; color: #000000;"
STYLE_ABOUT_ITEM = "font-size: 18px; color: #555555;"
STYLE_STATUS_CONNECTED = "font-size: 15px; color: #2E7D32; font-weight: bold;"
STYLE_STATUS_DISCONNECTED = "font-size: 15px; color: #C62828; font-weight: bold;"
STYLE_STATUS_NEUTRAL = "font-size: 15px; color: #757575;"

# 字体列表去重与精简：去掉「中」「中文」「_GB2312」等变体后缀，每种字体只保留一条，显示名用精简后的名称
_FONT_SUFFIXES: Tuple[str, ...] = (
    ' 中', ' 中文', ' LIC', ' UI', ' Light', ' Bold', ' Semibold', ' Semilight', ' Thin', ' Medium', ' Regular', ' Italic', ' Black', ' DemiBold', ' ExtraLight',
    ' _GB2312', ' _GB18030', ' _Big5', '_GB2312', '_GB18030', '_Big5',
)


def _font_base_name(name: str) -> str:
    """去掉常见变体后缀得到字体「基名」"""
    s = (name or '').strip()
    for suf in sorted(_FONT_SUFFIXES, key=len, reverse=True):
        if s.endswith(suf):
            return s[:-len(suf)].strip()
    return s


def _get_deduplicated_font_list() -> List[Tuple[str, str]]:
    """返回 [(显示名, 实际字体族)], 每种字体一条，显示名已精简；优先选用系统能 exactMatch 的字体名以保证应用后生效。"""
    db = QFontDatabase()
    families = db.families()
    base_to_candidates: Dict[str, List[str]] = {}
    for f in sorted(families):
        base = _font_base_name(f)
        if not base:
            continue
        base_to_candidates.setdefault(base, []).append(f)
    test_font = QFont()
    test_font.setPointSize(12)
    result: List[Tuple[str, str]] = []
    for base in sorted(base_to_candidates.keys()):
        candidates = base_to_candidates[base]
        # 优先选用 setFamily 后 exactMatch 为 True 的（保证保存后主窗口字体能生效）
        chosen = None
        for f in candidates:
            test_font.setFamily(f)
            if test_font.exactMatch():
                chosen = f
                break
        if chosen is None:
            chosen = candidates[0]
        result.append((base, chosen))
    return result
STYLE_SAVE_BTN = """
    QPushButton {
        background-color: #4CAF50;
        color: white;
        border: none;
        border-radius: 4px;
        font-size: 16px;
        font-weight: bold;
        padding: 8px 20px;
    }
    QPushButton:hover { background-color: #45a049; }
    QPushButton:pressed { background-color: #3d8b40; }
"""
STYLE_SELECT_ALL_BTN = """
    QPushButton {
        background-color: #4A90E2;
        color: white;
        border: none;
        border-radius: 4px;
        font-size: 16px;
        font-weight: bold;
        padding: 8px 20px;
    }
    QPushButton:hover { background-color: #357ABD; }
    QPushButton:pressed { background-color: #2E5F8F; }
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

        # 数据源分类定义
        self.source_vars = {}
        self.http_poll_spinboxes: Dict[str, QSpinBox] = {}
        self.source_parse_labels = {}   # parse_key -> QLabel，显示「已解析/未解析」或「已连接/未连接」
        self.source_status_texts: Dict[str, tuple] = {}  # key -> (connected_text, disconnected_text, tooltip)
        # 数据源状态页：按分钟记录绿/红条（True=绿，False=红）
        self._status_minute_bars: Dict[str, List[bool]] = {}
        self._status_last_minute_key: Dict[str, str] = {}
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
        max_width = min(500, screen.width() - 40)   # 宽度 500，留出边距
        max_height = min(700, screen.height() - 100)  # 高度 700，留出边距（含任务栏）
        
        self.setMinimumSize(420, 300)  # 最小宽度 420，避免内容挤在一起
        self.resize(max_width, max_height)  # 初始尺寸 500×700
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
        
        # 标签页顺序：外观与显示、数据源、数据源状态、高级、关于
        self._create_appearance_tab()
        self._create_data_source_tab()
        self._create_data_source_status_tab()
        self._create_advanced_tab()
        self._create_about_tab()
        
        # 创建底部按钮区域
        self._create_bottom_buttons(main_layout)
        
        # 居中显示
        self._center_window()
        
        # 自定义数据源状态定时刷新（仅「高级」页可见时运行，切换离开或关闭时停止）
        self._custom_source_status_timer = QTimer(self)
        self._custom_source_status_timer.setInterval(2000)
        self._custom_source_status_timer.timeout.connect(self._update_custom_source_status)
        # 数据源页连接/解析状态定时刷新
        self._data_source_tab_index = 1
        self._data_source_status_tab_index = 2
        self._status_refresh_timer = QTimer(self)
        self._status_refresh_timer.setInterval(2000)
        self._status_refresh_timer.timeout.connect(self._on_status_refresh_tick)
        self._advanced_tab_index = 3  # 高级页在 notebook 中的索引
        self.notebook.currentChanged.connect(self._on_settings_tab_changed)
    
    def _on_settings_tab_changed(self, index: int):
        """切换标签页时：仅在「高级」页启动状态刷新定时器，离开时停止。"""
        if index in (self._data_source_tab_index, self._data_source_status_tab_index):
            if not self._status_refresh_timer.isActive():
                self._status_refresh_timer.start()
            if index == self._data_source_tab_index:
                self._update_parse_status_labels()
            else:
                self._update_data_source_health_table()
        else:
            self._status_refresh_timer.stop()

        if index == self._advanced_tab_index:
            if not self._custom_source_status_timer.isActive():
                self._custom_source_status_timer.start()
            self._update_custom_source_status()
        else:
            self._custom_source_status_timer.stop()

    def _on_status_refresh_tick(self):
        """定时刷新数据源页状态。"""
        if not self.isVisible():
            return
        current_index = self.notebook.currentIndex()
        if current_index == self._data_source_tab_index:
            self._update_parse_status_labels()
        elif current_index == self._data_source_status_tab_index:
            self._update_data_source_health_table()

    def _update_parse_status_labels(self):
        """根据配置刷新解析/连接状态标签。"""
        try:
            mc = self.config.message_config
            for key, lbl in self.source_parse_labels.items():
                if not lbl:
                    continue
                cb = self.source_vars.get(key) or getattr(self, f"{key}_cb", None)
                if cb is not None and hasattr(cb, "isChecked"):
                    enabled = bool(cb.isChecked())
                else:
                    enabled = bool(getattr(mc, key, False))
                status_texts = self.source_status_texts.get(key, ("已解析", "未解析", "解析状态：已解析 / 未解析"))
                connected_text, disconnected_text, tooltip = status_texts
                lbl.setToolTip(tooltip)
                if enabled:
                    lbl.setText(connected_text)
                    lbl.setStyleSheet(STYLE_STATUS_CONNECTED)
                else:
                    lbl.setText(disconnected_text)
                    lbl.setStyleSheet(STYLE_STATUS_NEUTRAL)
        except Exception as e:
            logger.debug(f"更新解析状态标签失败: {e}")
    
    def _update_custom_source_status(self):
        """根据当前自定义数据源 URL 与主窗口 manager 更新状态标签。仅当在「高级」页且标签已创建时执行。"""
        if not self.isVisible():
            return
        if self.notebook.currentIndex() != self._advanced_tab_index:
            return
        if not hasattr(self, 'custom_source_status_label') or self.custom_source_status_label is None:
            return
        try:
            # 优先使用当前输入框中的 URL（未保存也可预览状态）
            if hasattr(self, 'advanced_vars') and 'custom_url_entry' in self.advanced_vars:
                url = (self.advanced_vars['custom_url_entry'].text() or "").strip()
            else:
                url = (self.config.custom_data_source_url or "").strip()
            if not url:
                self.custom_source_status_label.setText("状态：未配置")
                return
            parent = self.parent()
            if parent is None:
                self.custom_source_status_label.setText("状态：未连接")
                return
            low = url.lower()
            if low.startswith("http://") or low.startswith("https://"):
                http_mgr = getattr(parent, "data_sources", None) or {}
                poll_mgr = http_mgr.get("http_polling") if isinstance(http_mgr, dict) else None
                if poll_mgr is None or not hasattr(poll_mgr, "get_custom_source_status"):
                    self.custom_source_status_label.setText("状态：未连接")
                    return
                status = poll_mgr.get_custom_source_status(url)
                if status == "ok":
                    self.custom_source_status_label.setText("状态：已连接")
                elif status == "error":
                    self.custom_source_status_label.setText("状态：已断开")
                else:
                    self.custom_source_status_label.setText("状态：未连接")
                return
            if low.startswith("ws://") or low.startswith("wss://"):
                state_map = {}
                if hasattr(parent, "get_data_source_status"):
                    state_map = parent.get_data_source_status() or {}
                state = state_map.get(url, "unconnected")
                if state == "connected":
                    self.custom_source_status_label.setText("状态：已连接")
                elif state == "connecting":
                    self.custom_source_status_label.setText("状态：重连中")
                elif state == "disconnected":
                    self.custom_source_status_label.setText("状态：已断开")
                else:
                    self.custom_source_status_label.setText("状态：未连接")
                return
            self.custom_source_status_label.setText("状态：未连接")
        except Exception as e:
            logger.debug(f"更新自定义数据源状态失败: {e}")
            if hasattr(self, 'custom_source_status_label') and self.custom_source_status_label is not None:
                self.custom_source_status_label.setText("状态：未连接")
    
    def showEvent(self, event):
        """窗口显示时的事件处理，确保窗口不超出屏幕"""
        super().showEvent(event)
        # 在显示后再次调整窗口位置和大小，确保不超出屏幕
        self._adjust_window_to_screen()
        if self.notebook.currentIndex() == self._data_source_tab_index:
            if not self._status_refresh_timer.isActive():
                self._status_refresh_timer.start()
            self._update_parse_status_labels()
        elif self.notebook.currentIndex() == self._data_source_status_tab_index:
            if not self._status_refresh_timer.isActive():
                self._status_refresh_timer.start()
            self._update_data_source_health_table()

    def hideEvent(self, event):
        """窗口隐藏或关闭时停止自定义数据源状态刷新定时器"""
        self._status_refresh_timer.stop()
        self._custom_source_status_timer.stop()
        super().hideEvent(event)
    
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
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)
        
        # ---------- 1. 基本显示 ----------
        group_basic = QGroupBox("基本显示")
        group_basic.setStyleSheet(STYLE_GROUPBOX)
        block1 = QWidget()
        block1_layout = QGridLayout(block1)
        block1_layout.setContentsMargins(0, 0, 0, 0)
        block1_layout.setHorizontalSpacing(4)
        block1_layout.setVerticalSpacing(2)
        
        # 滚动速度
        speed_label = QLabel("滚动速度:")
        speed_label.setStyleSheet(STYLE_LABEL)
        speed_label.setMinimumWidth(80)
        speed_slider = QSlider(Qt.Horizontal)
        speed_slider.setMinimum(1)
        speed_slider.setMaximum(200)
        speed_slider.setValue(int(self.config.gui_config.text_speed * 10))
        speed_slider.setStyleSheet(STYLE_SLIDER)
        speed_slider.setFixedWidth(240)
        speed_label_value = QLabel(f"{self.config.gui_config.text_speed:.1f}")
        speed_label_value.setStyleSheet("font-size: 16px; color: #333333; min-width: 40px;")
        speed_slider.valueChanged.connect(lambda v: speed_label_value.setText(f"{v / 10.0:.1f}"))
        block1_layout.addWidget(speed_label, 1, 0)
        block1_layout.addWidget(speed_slider, 1, 1)
        block1_layout.addWidget(speed_label_value, 1, 2)
        
        # 字体、字体大小（第0行）；字体加粗、字体倾斜（第1行）—— 使用内部 QGridLayout 保证列对齐
        font_family_combo = QComboBox()
        font_family_combo.setEditable(False)
        for display_name, actual_family in _get_deduplicated_font_list():
            font_family_combo.addItem(display_name, actual_family)
        current_font = getattr(self.config.gui_config, 'font_family', None) or "SimSun"
        idx = font_family_combo.findData(current_font)
        if idx < 0:
            idx = font_family_combo.findText(_font_base_name(current_font))
        if idx >= 0:
            font_family_combo.setCurrentIndex(idx)
        else:
            font_family_combo.setCurrentIndex(0)
        font_family_combo.setStyleSheet(STYLE_COMBOBOX)
        font_family_combo.setFixedWidth(140)
        font_family_label = QLabel("字体:")
        font_family_label.setStyleSheet(STYLE_LABEL)
        font_size_label = QLabel("字体大小:")
        font_size_label.setStyleSheet(STYLE_LABEL)
        font_size_combo = QComboBox()
        font_size_combo.setEditable(False)
        for i in range(10, 101, 2):
            font_size_combo.addItem(f"{i}px", i)
        current_fs = max(10, min(100, self.config.gui_config.font_size))
        idx_fs = font_size_combo.findData(current_fs)
        if idx_fs < 0:
            idx_fs = font_size_combo.findData((current_fs // 2) * 2)
        font_size_combo.setCurrentIndex(max(0, idx_fs))
        font_size_combo.setStyleSheet(STYLE_COMBOBOX)
        font_size_combo.setFixedWidth(88)
        font_bold_cb = QCheckBox("字体加粗")
        font_bold_cb.setChecked(getattr(self.config.gui_config, 'font_bold', False))
        font_bold_cb.setStyleSheet("font-size: 16px;")
        font_italic_cb = QCheckBox("字体倾斜")
        font_italic_cb.setChecked(getattr(self.config.gui_config, 'font_italic', False))
        font_italic_cb.setStyleSheet("font-size: 16px;")
        font_block = QWidget()
        font_block_layout = QGridLayout(font_block)
        font_block_layout.setContentsMargins(0, 0, 0, 0)
        font_block_layout.setHorizontalSpacing(4)
        font_block_layout.setVerticalSpacing(4)
        font_block_layout.addWidget(font_family_label, 0, 0)
        font_block_layout.addWidget(font_family_combo, 0, 1)
        font_block_layout.addWidget(font_size_label, 0, 2)
        font_block_layout.addWidget(font_size_combo, 0, 3)
        font_block_layout.addWidget(font_bold_cb, 1, 0, 1, 2)
        font_block_layout.addWidget(font_italic_cb, 1, 2, 1, 2)
        font_block_layout.setColumnStretch(4, 1)
        block1_layout.addWidget(font_block, 2, 0, 1, 4)
        
        # 显示时区
        from utils.timezone_names_zh import get_tz_options, iana_to_display
        timezone_options = get_tz_options()
        timezone_label = QLabel("显示时区:")
        timezone_label.setStyleSheet(STYLE_LABEL)
        timezone_label.setMinimumWidth(80)
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
        timezone_combo.setFixedWidth(120)
        timezone_hint = QLabel("修改时区后需重启软件生效。")
        timezone_hint.setStyleSheet(STYLE_HINT)
        timezone_hint.setWordWrap(True)
        tz_row = QWidget()
        tz_row_layout = QHBoxLayout(tz_row)
        tz_row_layout.setContentsMargins(0, 0, 0, 0)
        tz_row_layout.setSpacing(8)
        tz_row_layout.addWidget(timezone_combo)
        tz_row_layout.addWidget(timezone_hint)
        tz_row_layout.addStretch()
        block1_layout.addWidget(timezone_label, 3, 0)
        block1_layout.addWidget(tz_row, 3, 1, 1, 5)
        group_basic_layout = QVBoxLayout(group_basic)
        group_basic_layout.setContentsMargins(10, 12, 10, 10)
        group_basic_layout.addWidget(block1)
        main_layout.addWidget(group_basic)
        main_layout.addSpacing(10)
        
        # ---------- 2. 窗口 ----------
        group_window = QGroupBox("窗口")
        group_window.setStyleSheet(STYLE_GROUPBOX)
        block2 = QWidget()
        block2_layout = QVBoxLayout(block2)
        block2_layout.setContentsMargins(0, 0, 0, 0)
        block2_layout.setSpacing(6)
        size_row = QHBoxLayout()
        size_row.setSpacing(10)
        width_label = QLabel("窗口宽度:")
        width_label.setStyleSheet(STYLE_LABEL)
        width_spin = QSpinBox()
        width_spin.setMinimum(200)
        width_spin.setMaximum(20000)  # 不受分辨率限制，允许超出屏幕
        width_spin.setValue(min(20000, max(200, self.config.gui_config.window_width)))
        width_spin.setStyleSheet(STYLE_SPINBOX)
        height_label = QLabel("窗口高度:")
        height_label.setStyleSheet(STYLE_LABEL)
        height_spin = QSpinBox()
        height_spin.setMinimum(50)
        height_spin.setMaximum(5000)  # 不受分辨率限制，允许超出屏幕
        height_spin.setValue(min(5000, max(50, self.config.gui_config.window_height)))
        height_spin.setStyleSheet(STYLE_SPINBOX)
        size_row.addWidget(width_label)
        size_row.addWidget(width_spin)
        size_row.addWidget(height_label)
        size_row.addWidget(height_spin)
        size_row.addStretch()
        block2_layout.addLayout(size_row)
        opacity_row = QWidget()
        opacity_row_layout = QHBoxLayout(opacity_row)
        opacity_row_layout.setContentsMargins(0, 0, 0, 0)
        opacity_row_layout.setSpacing(8)
        opacity_label = QLabel("窗口透明度:")
        opacity_label.setStyleSheet(STYLE_LABEL)
        opacity_label.setMinimumWidth(80)
        opacity_row_layout.addWidget(opacity_label)
        opacity_slider = QSlider(Qt.Horizontal)
        opacity_slider.setMinimum(1)
        opacity_slider.setMaximum(10)
        opacity_slider.setValue(int(self.config.gui_config.opacity * 10))
        opacity_slider.setStyleSheet(STYLE_SLIDER)
        opacity_slider.setFixedWidth(240)
        opacity_label_value = QLabel(f"{self.config.gui_config.opacity:.1f}")
        opacity_label_value.setStyleSheet("font-size: 16px; color: #333333; min-width: 40px;")
        opacity_slider.valueChanged.connect(lambda v: opacity_label_value.setText(f"{v / 10.0:.1f}"))
        opacity_row_layout.addWidget(opacity_slider)
        opacity_row_layout.addWidget(opacity_label_value)
        opacity_row_layout.addStretch()
        block2_layout.addWidget(opacity_row)
        always_on_top_cb = QCheckBox("窗口置顶")
        always_on_top_cb.setChecked(getattr(self.config.gui_config, 'always_on_top', False))
        always_on_top_cb.setStyleSheet("font-size: 16px;")
        always_on_top_cb.setToolTip("开启后主窗口始终置于其他窗口之上")
        block2_layout.addWidget(always_on_top_cb)
        group_window_layout = QVBoxLayout(group_window)
        group_window_layout.setContentsMargins(10, 12, 10, 10)
        group_window_layout.addWidget(block2)
        main_layout.addWidget(group_window)
        main_layout.addSpacing(10)

        # 水印设置（QGroupBox，含背景水印文字 + 字体/字号/位置）
        group_wm = QGroupBox("水印设置")
        group_wm.setStyleSheet(STYLE_GROUPBOX)
        block_wm = QWidget()
        block_wm_layout = QVBoxLayout(block_wm)
        block_wm_layout.setContentsMargins(0, 0, 0, 0)
        block_wm_layout.setSpacing(8)
        watermark_label = QLabel("背景水印:")
        watermark_label.setStyleSheet(STYLE_LABEL)
        watermark_edit = QLineEdit()
        watermark_edit.setPlaceholderText("留空则不显示")
        watermark_edit.setText(getattr(self.config.gui_config, 'watermark_text', "") or "")
        watermark_edit.setStyleSheet(STYLE_LINEEDIT)
        watermark_text_row = QHBoxLayout()
        watermark_text_row.setSpacing(8)
        watermark_text_row.addWidget(watermark_label)
        watermark_text_row.addWidget(watermark_edit)
        watermark_text_row.addStretch()
        block_wm_layout.addLayout(watermark_text_row)
        wm_hint = QLabel("可为背景水印单独设置字体/字号和显示位置；自动字号按主字体大小缩放。")
        wm_hint.setStyleSheet(STYLE_HINT)
        wm_hint.setWordWrap(True)
        wm_hint.setMaximumWidth(380)
        block_wm_layout.addWidget(wm_hint)
        watermark_font_combo = QComboBox()
        watermark_font_combo.setEditable(False)
        current_main_font = getattr(self.config.gui_config, 'font_family', None) or "SimSun"
        follow_label = f"跟随主字体（当前：{current_main_font}）"
        watermark_font_combo.addItem(follow_label, "")
        for display_name, actual_family in _get_deduplicated_font_list():
            watermark_font_combo.addItem(display_name, actual_family)
        wm_ff = getattr(self.config.gui_config, 'watermark_font_family', "") or ""
        if wm_ff:
            idx_ff = watermark_font_combo.findData(wm_ff)
            if idx_ff >= 0:
                watermark_font_combo.setCurrentIndex(idx_ff)
        watermark_font_combo.setStyleSheet(STYLE_COMBOBOX)
        watermark_font_combo.setMaximumWidth(280)
        wm_font_row = QHBoxLayout()
        wm_adv_label = QLabel("水印字体:")
        wm_adv_label.setStyleSheet(STYLE_LABEL)
        wm_font_row.addWidget(wm_adv_label)
        wm_font_row.addWidget(watermark_font_combo)
        wm_font_row.addStretch()
        block_wm_layout.addLayout(wm_font_row)
        watermark_font_auto_cb = QCheckBox("自动字号")
        wm_fs = int(getattr(self.config.gui_config, 'watermark_font_size', 0) or 0)
        auto_initial = (wm_fs <= 0)
        watermark_font_auto_cb.setChecked(auto_initial)
        watermark_font_size_spin = QSpinBox()
        watermark_font_size_spin.setRange(8, 100)
        base_fs = getattr(self.config.gui_config, 'font_size', 40)
        auto_fs = max(8, int(base_fs * 0.7))
        watermark_font_size_spin.setValue(wm_fs if wm_fs > 0 else auto_fs)
        watermark_font_size_spin.setStyleSheet(STYLE_SPINBOX)
        watermark_font_size_spin.setFixedWidth(72)
        watermark_font_size_spin.setEnabled(not auto_initial)
        def _on_wm_font_auto_changed(checked: bool):
            watermark_font_size_spin.setEnabled(not checked)
        watermark_font_auto_cb.toggled.connect(_on_wm_font_auto_changed)
        wm_size_row = QHBoxLayout()
        wm_size_row.setSpacing(12)
        wm_size_row.addWidget(watermark_font_auto_cb)
        wm_size_row.addWidget(watermark_font_size_spin)
        wm_size_row.addStretch()
        block_wm_layout.addLayout(wm_size_row)
        watermark_pos_combo = QComboBox()
        watermark_pos_combo.setStyleSheet(STYLE_COMBOBOX)
        watermark_pos_combo.setMaximumWidth(200)
        watermark_pos_combo.addItem("斜向 45 度平铺（整屏）", "diagonal")
        watermark_pos_combo.addItem("左上角", "top_left")
        watermark_pos_combo.addItem("右上角", "top_right")
        watermark_pos_combo.addItem("左下角", "bottom_left")
        watermark_pos_combo.addItem("右下角", "bottom_right")
        current_pos = getattr(self.config.gui_config, 'watermark_position', 'diagonal') or 'diagonal'
        idx_pos = watermark_pos_combo.findData(current_pos)
        if idx_pos < 0:
            idx_pos = watermark_pos_combo.findData("diagonal")
        watermark_pos_combo.setCurrentIndex(max(0, idx_pos))
        wm_pos_row = QHBoxLayout()
        wm_pos_label = QLabel("水印位置:")
        wm_pos_label.setStyleSheet(STYLE_LABEL)
        wm_pos_row.addWidget(wm_pos_label)
        wm_pos_row.addWidget(watermark_pos_combo)
        wm_pos_row.addStretch()
        block_wm_layout.addLayout(wm_pos_row)
        group_wm_layout = QVBoxLayout(group_wm)
        group_wm_layout.setContentsMargins(10, 12, 10, 10)
        group_wm_layout.addWidget(block_wm)
        main_layout.addWidget(group_wm)
        main_layout.addSpacing(10)

        # ---------- 3. 性能与渲染 ----------
        group_render = QGroupBox("性能与渲染")
        group_render.setStyleSheet(STYLE_GROUPBOX)
        block3 = QWidget()
        block3_layout = QVBoxLayout(block3)
        block3_layout.setContentsMargins(0, 0, 0, 0)
        block3_layout.setSpacing(6)
        render_row = QHBoxLayout()
        cpu_radio = QRadioButton("CPU 渲染（软件）")
        opengl_radio = QRadioButton("GPU 渲染（OpenGL）")
        cpu_radio.setStyleSheet(STYLE_LABEL)
        opengl_radio.setStyleSheet(STYLE_LABEL)
        backend = getattr(self.config.gui_config, 'render_backend', None) or ("opengl" if self.config.gui_config.use_gpu_rendering else "cpu")
        if backend == "opengl":
            opengl_radio.setChecked(True)
        else:
            cpu_radio.setChecked(True)
        cpu_radio.setToolTip("兼容性更好，修改后需重启软件生效")
        opengl_radio.setToolTip("硬件加速（OpenGL），修改后需重启软件生效")
        render_row.addWidget(cpu_radio)
        render_row.addWidget(opengl_radio)
        render_row.addStretch()
        block3_layout.addLayout(render_row)
        perf_row = QWidget()
        perf_row_layout = QHBoxLayout(perf_row)
        perf_row_layout.setContentsMargins(0, 0, 0, 0)
        perf_row_layout.setSpacing(12)
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
        # 目标帧率子组：标签 + 输入框 + 单位，内部紧凑 8px
        fps_group = QWidget()
        fps_group_layout = QHBoxLayout(fps_group)
        fps_group_layout.setContentsMargins(0, 0, 0, 0)
        fps_group_layout.setSpacing(8)
        fps_group_layout.addWidget(fps_label)
        fps_group_layout.addWidget(fps_spin)
        fps_group_layout.addWidget(QLabel("fps"))
        perf_row_layout.addWidget(vsync_checkbox)
        perf_row_layout.addWidget(fps_group)
        perf_row_layout.addStretch()
        block3_layout.addWidget(perf_row)
        group_render_layout = QVBoxLayout(group_render)
        group_render_layout.setContentsMargins(10, 12, 10, 10)
        group_render_layout.addWidget(block3)
        main_layout.addWidget(group_render)
        main_layout.addSpacing(10)

        # ---------- 4. 颜色 ----------
        group_color = QGroupBox("颜色")
        group_color.setStyleSheet(STYLE_GROUPBOX)
        block4 = QWidget()
        block4_layout = QVBoxLayout(block4)
        block4_layout.setContentsMargins(0, 0, 0, 0)
        block4_layout.setSpacing(2)
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
            row_layout.setSpacing(8)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(STYLE_LABEL)
            lbl.setMinimumWidth(120)  # 统一标签宽度，三行颜色预览/色值/按钮纵向对齐
            row_layout.addWidget(lbl)
            preview = QLabel()
            preview.setFixedSize(40, 25)
            preview.setStyleSheet(f"background-color: {color_value}; border: 1px solid #000; border-radius: 3px;")
            row_layout.addWidget(preview)
            value_label = QLabel(color_value)
            value_label.setMinimumWidth(80)
            value_label.setStyleSheet("font-size: 16px; color: #333333; font-family: monospace;")
            # value_label 不加入 layout，仅保留引用供颜色更新使用
            btn = QPushButton("修改颜色")
            btn.setStyleSheet("font-size: 16px; padding: 4px 10px;")
            btn.clicked.connect(lambda: self._open_color_picker(color_type))
            row_layout.addWidget(btn)
            reset_btn = QPushButton("恢复默认")
            reset_btn.setStyleSheet(STYLE_HINT + " padding: 4px 10px;")
            reset_btn.clicked.connect(lambda: self._reset_color(color_type))
            row_layout.addWidget(reset_btn)
            row_layout.addStretch()
            parent_layout.addWidget(row)
            return preview, value_label
        
        self.report_color_preview, self.report_color_label = _add_color_row(block4_layout, "地震信息颜色:", report_color_value, 'report')
        self.warning_color_preview, self.warning_color_label = _add_color_row(block4_layout, "地震预警颜色:", warning_color_value, 'warning')
        self.custom_text_color_preview, self.custom_text_color_label = _add_color_row(block4_layout, "自定义文本颜色:", custom_text_color_value, 'custom_text')
        group_color_layout = QVBoxLayout(group_color)
        group_color_layout.setContentsMargins(10, 12, 10, 10)
        group_color_layout.addWidget(block4)
        main_layout.addWidget(group_color)
        main_layout.addSpacing(10)

        # ---------- 预警/消息更新 ----------
        group_alert = QGroupBox("预警/消息更新")
        group_alert.setStyleSheet(STYLE_GROUPBOX)
        block_alert_update = QWidget()
        block_alert_update_layout = QVBoxLayout(block_alert_update)
        block_alert_update_layout.setContentsMargins(0, 0, 0, 0)
        block_alert_update_layout.setSpacing(6)
        self.show_one_alert_per_received_checkbox = QCheckBox("收到预警更新报立即切换")
        self.show_one_alert_per_received_checkbox.setChecked(
            getattr(self.config.message_config, 'show_one_alert_per_received', False)
        )
        self.show_one_alert_per_received_checkbox.setToolTip(
            "开启后，收到预警更新报时立即切换并显示最新内容；关闭时仅后台替换，不打断当前滚动。默认关闭。"
        )
        self.show_one_alert_per_received_checkbox.setStyleSheet("font-size: 16px;")
        block_alert_update_layout.addWidget(self.show_one_alert_per_received_checkbox)
        self.force_single_line_checkbox = QCheckBox("强制单行")
        self.force_single_line_checkbox.setChecked(
            getattr(self.config.message_config, 'force_single_line', True)
        )
        self.force_single_line_checkbox.setToolTip(
            "开启后，将数据源中的换行符替换为空格，保证滚动字幕始终单行显示。关闭则保留多行（由数据源决定）。"
        )
        self.force_single_line_checkbox.setStyleSheet("font-size: 16px;")
        block_alert_update_layout.addWidget(self.force_single_line_checkbox)
        mc = self.config.message_config
        self.custom_text_return_after_warning_checkbox = QCheckBox("预警后限时显示速报再回自定义（beta版）")
        self.custom_text_return_after_warning_checkbox.setChecked(
            getattr(self.config.message_config, 'custom_text_return_after_warning', False)
        )
        self.custom_text_return_after_warning_checkbox.setToolTip(
            "仅在「数据源」为「自定义文本」时生效。开启后：默认显示自定义文本；有预警时优先显示预警；预警结束且有速报或在无预警时直接收到速报时，将限时显示速报，超时（默认 5 分钟，可在配置中调整）后自动恢复为仅显示自定义文本。"
        )
        self.custom_text_return_after_warning_checkbox.setStyleSheet("font-size: 16px;")
        block_alert_update_layout.addWidget(self.custom_text_return_after_warning_checkbox)
        custom_text_return_row = QHBoxLayout()
        custom_text_return_row.setSpacing(8)
        custom_text_return_label = QLabel("速报最多显示（分钟）:")
        custom_text_return_label.setStyleSheet(STYLE_LABEL)
        custom_text_return_minutes_spin = QSpinBox()
        custom_text_return_minutes_spin.setRange(1, 60)
        return_sec = getattr(mc, 'custom_text_return_seconds', 300) or 300
        current_return_min = max(1, min(60, return_sec // 60))
        custom_text_return_minutes_spin.setValue(current_return_min)
        custom_text_return_minutes_spin.setStyleSheet(STYLE_SPINBOX)
        custom_text_return_minutes_spin.setToolTip("默认 5 分钟；越大则速报展示越久再切回自定义文本。")
        return_after_checked = getattr(self.config.message_config, 'custom_text_return_after_warning', False)
        custom_text_return_minutes_spin.setEnabled(return_after_checked)
        self.custom_text_return_after_warning_checkbox.toggled.connect(
            lambda checked: self._on_custom_text_return_after_warning_toggled(checked, custom_text_return_minutes_spin)
        )
        custom_text_return_row.addWidget(custom_text_return_label)
        custom_text_return_row.addWidget(custom_text_return_minutes_spin)
        custom_text_return_row.addStretch()
        block_alert_update_layout.addLayout(custom_text_return_row)
        warning_min_display_row = QHBoxLayout()
        warning_min_display_row.setSpacing(8)
        min_display_label = QLabel("预警最少展示时长（分钟）:")
        min_display_label.setStyleSheet(STYLE_LABEL)
        warning_min_display_spin = QSpinBox()
        warning_min_display_spin.setRange(1, 60)
        current_min = max(1, int(getattr(mc, 'warning_min_display_seconds', 300)) // 60)
        warning_min_display_spin.setValue(current_min)
        warning_min_display_spin.setStyleSheet(STYLE_SPINBOX)
        warning_min_display_spin.setToolTip("一旦展示则在此时间内不因发震时间过期被移除。单位：分钟，默认 5 分钟。")
        warning_min_display_row.addWidget(min_display_label)
        warning_min_display_row.addWidget(warning_min_display_spin)
        warning_min_display_row.addStretch()
        block_alert_update_layout.addLayout(warning_min_display_row)
        self.disable_warning_expiry_test_cb = QCheckBox(
            "关闭预警有效期（仅供测试，勿长期开启）"
        )
        self.disable_warning_expiry_test_cb.setChecked(
            bool(getattr(mc, "disable_warning_expiry_for_test", False))
        )
        self.disable_warning_expiry_test_cb.setToolTip(
            "开启后：不按发震时间丢弃入队预警；缓冲区也不按发震时间或「展示满最少展示时长」移出预警。"
            "便于用历史报文测试告警条与分阶段文案。"
        )
        self.disable_warning_expiry_test_cb.setStyleSheet("font-size: 16px;")
        block_alert_update_layout.addWidget(self.disable_warning_expiry_test_cb)
        alert_hint = QLabel("保存后立即生效，无需重启。")
        alert_hint.setStyleSheet(STYLE_HINT)
        block_alert_update_layout.addWidget(alert_hint)
        group_alert_layout = QVBoxLayout(group_alert)
        group_alert_layout.setContentsMargins(10, 12, 10, 10)
        group_alert_layout.addWidget(block_alert_update)
        main_layout.addWidget(group_alert)
        main_layout.addSpacing(10)

        # ---------- 自动更新 ----------
        group_auto_update = QGroupBox("自动更新")
        group_auto_update.setStyleSheet(STYLE_GROUPBOX)
        block_auto_update = QWidget()
        block_auto_update_layout = QVBoxLayout(block_auto_update)
        block_auto_update_layout.setContentsMargins(0, 0, 0, 0)
        block_auto_update_layout.setSpacing(6)
        auto_update_startup_cb = QCheckBox("启动时检查更新")
        auto_update_startup_cb.setChecked(
            getattr(self.config.gui_config, 'auto_update_check_on_startup', True)
        )
        auto_update_startup_cb.setStyleSheet("font-size: 16px;")
        block_auto_update_layout.addWidget(auto_update_startup_cb)
        check_update_btn = QPushButton("检查更新")
        check_update_btn.clicked.connect(self._on_auto_update_check_clicked)
        block_auto_update_layout.addWidget(check_update_btn)
        group_auto_update_layout = QVBoxLayout(group_auto_update)
        group_auto_update_layout.setContentsMargins(10, 12, 10, 10)
        group_auto_update_layout.addWidget(block_auto_update)
        main_layout.addWidget(group_auto_update)
        main_layout.addSpacing(10)

        # ---------- 5. 非预警时显示 ----------
        group_mode = QGroupBox("非预警时显示")
        group_mode.setStyleSheet(STYLE_GROUPBOX)
        gm_layout = QVBoxLayout(group_mode)
        gm_layout.setContentsMargins(12, 14, 12, 12)
        gm_layout.setSpacing(12)
        self.report_mode_group = QButtonGroup(scrollable_widget)
        self.radio_report = QRadioButton("地震速报")
        self.radio_custom_text = QRadioButton("自定义文本")
        self.report_mode_group.addButton(self.radio_report)
        self.report_mode_group.addButton(self.radio_custom_text)
        use_custom = getattr(self.config.message_config, 'use_custom_text', False)
        self.radio_report.setChecked(not use_custom)
        self.radio_custom_text.setChecked(use_custom)
        self.radio_report.setStyleSheet(STYLE_LABEL + " padding: 2px 0;")
        self.radio_custom_text.setStyleSheet(STYLE_LABEL + " padding: 2px 0;")
        gm_layout.addWidget(self.radio_report)
        gm_layout.addWidget(self.radio_custom_text)
        mode_hint = QLabel("提示：切换「地震速报」/「自定义文本」需重启软件后生效。自定义文本内容请在下方「自定义文本」区块编辑。")
        mode_hint.setStyleSheet(STYLE_HINT)
        mode_hint.setWordWrap(True)
        gm_layout.addWidget(mode_hint)
        main_layout.addWidget(group_mode)
        main_layout.addSpacing(10)

        # ---------- 6. 自定义文本 ----------
        group_custom = QGroupBox("自定义文本")
        group_custom.setStyleSheet(STYLE_GROUPBOX)
        block5 = QWidget()
        block5_layout = QVBoxLayout(block5)
        block5_layout.setContentsMargins(0, 0, 0, 0)
        block5_layout.setSpacing(6)
        custom_hint = QLabel("在「数据源」页选择「自定义文本」后，非预警时将显示此处编辑的文本。修改并保存后立即生效，无需重启。")
        custom_hint.setStyleSheet(STYLE_HINT)
        custom_hint.setWordWrap(True)
        custom_hint.setMaximumWidth(360)
        block5_layout.addWidget(custom_hint)
        self.custom_text_edit = QPlainTextEdit()
        self.custom_text_edit.setPlaceholderText("输入要滚动显示的自定义文本...")
        self.custom_text_edit.setMinimumHeight(100)
        self.custom_text_edit.setMaximumWidth(360)
        self.custom_text_edit.setPlainText(self.config.message_config.custom_text or "")
        block5_layout.addWidget(self.custom_text_edit)
        group_custom_layout = QVBoxLayout(group_custom)
        group_custom_layout.setContentsMargins(10, 12, 10, 10)
        group_custom_layout.addWidget(block5)
        main_layout.addWidget(group_custom)

        # 保存变量引用（供 _save_appearance_settings 使用）
        self.display_vars = {
            'speed': speed_slider,
            'font_size': font_size_combo,
            'font_family': font_family_combo,
            'font_bold': font_bold_cb,
            'font_italic': font_italic_cb,
            'width': width_spin,
            'height': height_spin,
            'opacity': opacity_slider,
            'vsync_enabled': vsync_checkbox,
            'target_fps': fps_spin,
            'timezone': timezone_combo,
            'always_on_top': always_on_top_cb,
            'watermark_text': watermark_edit,
            'watermark_font_family': watermark_font_combo,
            'watermark_font_auto': watermark_font_auto_cb,
            'watermark_font_size': watermark_font_size_spin,
            'watermark_position': watermark_pos_combo,
            'auto_update_check_on_startup': auto_update_startup_cb,
            'warning_min_display_seconds': warning_min_display_spin,
            'custom_text_return_seconds': custom_text_return_minutes_spin,
        }
        self.render_vars = {'cpu_radio': cpu_radio, 'opengl_radio': opengl_radio}
        
        main_layout.addStretch()
        
        # 保存按钮
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 6, 0, 0)
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
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scrollable_widget = QWidget()
        scrollable_widget.setMinimumWidth(0)
        scrollable_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        scroll_layout = QVBoxLayout(scrollable_widget)
        scroll_layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        scroll_layout.setSpacing(22)

        fanstudio_http_poll_sources = [
            ("https://api.fanstudio.tech/we/typhoon.php", "台风实时与历史数据"),
            ("https://api.fanstudio.tech/we/aqi.php", "城市空气质量指数"),
        ]
        intl_sources = [
            (BMKG_HTTP_URL, "BMKG 印尼地震速报", False),
            (GEONET_HTTP_URL, "GeoNet 新西兰地震速报", False),
            (INGV_HTTP_URL, "INGV 意大利地震速报", False),
            (EARLYEST_HTTP_URL, "Early-est 地震预警", False),
            (JMA_ATOM_LONG_URL, "JMA-Atom 火山情报（长周期）", False),
        ]

        # Fan Studio（QGroupBox）
        group_warning = QGroupBox("Fan Studio")
        group_warning.setStyleSheet(STYLE_GROUPBOX)
        gw_layout = QVBoxLayout(group_warning)
        gw_layout.setContentsMargins(12, 14, 12, 12)
        gw_layout.setSpacing(12)
        fs_all_label = QLabel("Fan Studio")
        fs_all_label.setStyleSheet(STYLE_SOURCE_TITLE + " line-height: 22pt;")
        gw_layout.addWidget(fs_all_label)
        fs_hint = QLabel(
            "勾选「Fan Studio」后连接；下方子源决定解析范围"
        )
        fs_hint.setStyleSheet(STYLE_HINT)
        fs_hint.setWordWrap(True)
        gw_layout.addWidget(fs_hint)
        self.fanstudio_all_connect_cb = QCheckBox("Fan Studio")
        self.fanstudio_all_connect_cb.setChecked(self.config.enabled_sources.get(self.all_source_url, True))
        self.fanstudio_all_connect_cb.setStyleSheet("font-size: 16px; line-height: 22pt; padding: 2px 0;")
        gw_layout.addWidget(self.fanstudio_all_connect_cb)
        # CENC 烈度速报（cenc-ir）为 Fan Studio 独立连接，不在 /all 通道中
        self._add_source_checkbox(
            group_warning,
            "wss://ws.fanstudio.tech/cenc-ir",
            "中国地震台网中心地震烈度速报",
            default_value=True,
            status_key="wss://ws.fanstudio.tech/cenc-ir",
            status_tooltip="连接状态：已连接 / 未连接",
            status_connected_text="已连接",
            status_disconnected_text="未连接",
        )
        self._add_source_checkbox(
            group_warning,
            "https://api.fanstudio.tech/we/typhoon.php",
            "台风实时与历史数据",
            default_value=True,
            status_key="https://api.fanstudio.tech/we/typhoon.php",
            status_tooltip="解析状态：已解析 / 未解析",
            status_connected_text="已解析",
            status_disconnected_text="未解析",
        )
        self._add_source_checkbox(
            group_warning,
            "https://api.fanstudio.tech/we/aqi.php",
            "城市空气质量指数",
            default_value=True,
            status_key="https://api.fanstudio.tech/we/aqi.php",
            status_tooltip="解析状态：已解析 / 未解析",
            status_connected_text="已解析",
            status_disconnected_text="未解析",
        )
        # Fan Studio 所有子源纵向排列
        def _fs_cb(cfg_name: str, text: str) -> QCheckBox:
            cb = QCheckBox(text)
            cb.setChecked(getattr(self.config.message_config, cfg_name, True))
            cb.setStyleSheet("font-size: 16px; line-height: 22pt; padding: 2px 0;")
            status_label = QLabel("已解析")
            status_label.setStyleSheet(STYLE_STATUS_CONNECTED)
            status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            status_label.setToolTip("解析状态：已解析 / 未解析")
            self.source_parse_labels[cfg_name] = status_label
            self.source_status_texts[cfg_name] = ("已解析", "未解析", "解析状态：已解析 / 未解析")
            row_layout = QHBoxLayout()
            row_layout.addWidget(cb)
            row_layout.addStretch()
            row_layout.addWidget(status_label)
            gw_layout.addLayout(row_layout)
            return cb
        # 预警子源
        self.fanstudio_parse_cea_cb = _fs_cb('fanstudio_parse_cea', "中国地震预警网")
        self.fanstudio_parse_cea_pr_cb = _fs_cb('fanstudio_parse_cea_pr', "中国地震预警省网")
        self.fanstudio_parse_cwa_eew_cb = _fs_cb('fanstudio_parse_cwa_eew', "台湾气象署地震预警")
        self.fanstudio_parse_jma_cb = _fs_cb('fanstudio_parse_jma', "日本气象厅地震预警")
        self.fanstudio_parse_sa_cb = _fs_cb('fanstudio_parse_sa', "美国ShakeAlert地震预警")
        self.fanstudio_parse_kma_eew_cb = _fs_cb('fanstudio_parse_kma_eew', "韩国气象厅地震预警")
        # 速报 / 气象 / 海啸子源
        self.fanstudio_parse_weatheralarm_cb = _fs_cb('fanstudio_parse_weatheralarm', "中国气象局气象预警")
        self.fanstudio_parse_tsunami_cb = _fs_cb('fanstudio_parse_tsunami', "自然资源部海啸预警中心")
        self.fanstudio_parse_cenc_cb = _fs_cb('fanstudio_parse_cenc', "中国地震台网中心")
        self.fanstudio_parse_ningxia_cb = _fs_cb('fanstudio_parse_ningxia', "宁夏回族自治区地震局")
        self.fanstudio_parse_guangxi_cb = _fs_cb('fanstudio_parse_guangxi', "广西壮族自治区地震局")
        self.fanstudio_parse_shanxi_cb = _fs_cb('fanstudio_parse_shanxi', "山西省地震局")
        self.fanstudio_parse_beijing_cb = _fs_cb('fanstudio_parse_beijing', "北京市地震局")
        self.fanstudio_parse_yunnan_cb = _fs_cb('fanstudio_parse_yunnan', "云南省地震局")
        self.fanstudio_parse_cwa_cb = _fs_cb('fanstudio_parse_cwa', "台湾气象署速报")
        self.fanstudio_parse_hko_cb = _fs_cb('fanstudio_parse_hko', "香港天文台速报")
        self.fanstudio_parse_usgs_cb = _fs_cb('fanstudio_parse_usgs', "美国地质调查局速报")
        self.fanstudio_parse_emsc_cb = _fs_cb('fanstudio_parse_emsc', "欧洲地中海地震中心速报")
        self.fanstudio_parse_bcsf_cb = _fs_cb('fanstudio_parse_bcsf', "法国中央地震研究所速报")
        self.fanstudio_parse_gfz_cb = _fs_cb('fanstudio_parse_gfz', "德国地学研究中心速报")
        self.fanstudio_parse_usp_cb = _fs_cb('fanstudio_parse_usp', "巴西圣保罗大学速报")
        self.fanstudio_parse_kma_cb = _fs_cb('fanstudio_parse_kma', "韩国气象厅速报")
        self.fanstudio_parse_fssn_cb = _fs_cb('fanstudio_parse_fssn', "FSSN")
        self.fanstudio_parse_fssn_cmt_cb = _fs_cb('fanstudio_parse_fssn_cmt', "FSSN 矩心矩张量解")
        scroll_layout.addWidget(group_warning)

        # Wolfx 聚合源 (wss://ws-api.wolfx.jp/all_eew)
        group_ali = QGroupBox("Wolfx")
        group_ali.setStyleSheet(STYLE_GROUPBOX)
        ga_layout = QVBoxLayout(group_ali)
        ga_layout.setContentsMargins(12, 14, 12, 12)
        ga_layout.setSpacing(12)
        ali_hint = QLabel(
            "勾选「Wolfx」后连接"
        )
        ali_hint.setStyleSheet(STYLE_HINT)
        ali_hint.setWordWrap(True)
        ga_layout.addWidget(ali_hint)
        wolfx_url = "wss://ws-api.wolfx.jp/all_eew"
        self.wolfx_all_connect_cb = QCheckBox("Wolfx")
        self.wolfx_all_connect_cb.setChecked(self.config.enabled_sources.get(wolfx_url, True))
        self.wolfx_all_connect_cb.setStyleSheet("font-size: 16px; line-height: 22pt; padding: 2px 0;")
        ga_layout.addWidget(self.wolfx_all_connect_cb)

        def _wolfx_row(parse_key: str, title: str):
            cb = QCheckBox(title)
            cb.setChecked(getattr(self.config.message_config, parse_key, True))
            cb.setStyleSheet("font-size: 16px; line-height: 22pt; padding: 2px 0;")
            st = QLabel("未解析")
            st.setStyleSheet(STYLE_STATUS_NEUTRAL)
            st.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            st.setToolTip("解析状态：已解析 / 未解析")
            self.source_parse_labels[parse_key] = st
            row = QHBoxLayout()
            row.addWidget(cb)
            row.addStretch()
            row.addWidget(st)
            ga_layout.addLayout(row)
            return cb

        self.ali_all_parse_nied_cb = _wolfx_row('ali_all_parse_nied', "緊急地震速報（JMA）")
        self.ali_all_parse_early_est_cb = _wolfx_row('ali_all_parse_early_est', "四川省地震局")
        self.ali_all_parse_jma_volcano_cb = _wolfx_row('ali_all_parse_jma_volcano', "福建省地震局")
        self.ali_all_parse_bmkg_cb = _wolfx_row('ali_all_parse_bmkg', "中国地震台网地震预警")
        self.ali_all_parse_cq_eew_cb = _wolfx_row('ali_all_parse_cq_eew', "重庆市地震局")
        wolfx_cwa_url = "wss://ws-api.wolfx.jp/cwa_eew"
        self._add_source_checkbox(
            group_ali,
            wolfx_cwa_url,
            "台湾中央气象署",
            default_value=False
        )
        scroll_layout.addWidget(group_ali)

        # 国际/独立 HTTP 数据源（开关与访问间隔分开展示）
        group_intl = QGroupBox("国际数据源")
        group_intl.setStyleSheet(STYLE_GROUPBOX)
        gi_layout = QVBoxLayout(group_intl)
        gi_layout.setContentsMargins(12, 14, 12, 12)
        gi_layout.setSpacing(12)
        intl_hint = QLabel("勾选后启用对应 HTTP 拉取。")
        intl_hint.setStyleSheet(STYLE_HINT)
        intl_hint.setWordWrap(True)
        gi_layout.addWidget(intl_hint)
        for url, label, default_on in intl_sources:
            self._add_source_checkbox(
                group_intl,
                url,
                label,
                default_value=default_on,
                status_key=url,
                status_tooltip="拉取状态：已启用 / 未启用",
                status_connected_text="已启用",
                status_disconnected_text="未启用",
            )
        scroll_layout.addWidget(group_intl)

        # 地震历史（QGroupBox）
        group_history = QGroupBox("P2PQuake")
        group_history.setStyleSheet(STYLE_GROUPBOX)
        gh_layout = QVBoxLayout(group_history)
        gh_layout.setContentsMargins(12, 14, 12, 12)
        gh_layout.setSpacing(12)
        p2p_hint = QLabel(
            "勾选「P2PQuake」将同时启用 HTTP 数据Get与 WebSocket；"
            "取消勾选则两者均关闭。下方两项决定地震情報 / 津波予報是否参与解析。"
        )
        p2p_hint.setStyleSheet(STYLE_HINT)
        p2p_hint.setWordWrap(True)
        gh_layout.addWidget(p2p_hint)
        p2p_wss_url = P2PQUAKE_WSS_URL
        p2p_status_col_w = 88
        self.p2pquake_connect_cb = QCheckBox("P2PQuake（HTTP + WebSocket）")
        self.p2pquake_connect_cb.setChecked(p2pquake_master_enabled(self.config.enabled_sources))
        self.p2pquake_connect_cb.setStyleSheet("font-size: 16px; line-height: 22pt; padding: 2px 0;")
        gh_layout.addWidget(self.p2pquake_connect_cb)
        if p2p_wss_url not in self.individual_source_urls:
            self.individual_source_urls.append(p2p_wss_url)
        def _p2p_parse_row(parse_key: str, title: str) -> QCheckBox:
            cb = QCheckBox(title)
            cb.setChecked(getattr(self.config.message_config, parse_key, True))
            cb.setStyleSheet("font-size: 16px; line-height: 22pt; padding: 2px 0;")
            st = QLabel("未解析")
            st.setMinimumWidth(p2p_status_col_w)
            st.setFixedWidth(p2p_status_col_w)
            st.setStyleSheet(STYLE_STATUS_NEUTRAL)
            st.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            st.setToolTip("解析状态：已解析 / 未解析")
            self.source_parse_labels[parse_key] = st
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(cb)
            row.addStretch()
            row.addWidget(st)
            gh_layout.addLayout(row)
            cb.stateChanged.connect(self._update_parse_status_labels)
            return cb

        self.p2pquake_parse_551_cb = _p2p_parse_row("p2pquake_parse_551", "P2PQuake 日本气象厅 地震情報")
        self.p2pquake_parse_552_cb = _p2p_parse_row("p2pquake_parse_552", "P2PQuake 日本气象厅 津波予報")
        scroll_layout.addWidget(group_history)

        poll_interval_sources = fanstudio_http_poll_sources + [
            (url, label) for url, label, _ in intl_sources
        ]
        group_poll = QGroupBox("数据源访问间隔")
        group_poll.setStyleSheet(STYLE_GROUPBOX)
        gp_layout = QVBoxLayout(group_poll)
        gp_layout.setContentsMargins(12, 14, 12, 12)
        gp_layout.setSpacing(12)
        poll_hint = QLabel("Get 轮询间隔（秒），最低 1 秒；各数据源独立设置。")
        poll_hint.setStyleSheet(STYLE_HINT)
        poll_hint.setWordWrap(True)
        gp_layout.addWidget(poll_hint)
        self._add_http_poll_interval_grid(gp_layout, poll_interval_sources)
        scroll_layout.addWidget(group_poll)
        
        scroll_layout.addStretch()
        
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 10, 0, 0)
        button_layout.addStretch()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setMinimumWidth(100)
        self.select_all_btn.setMinimumHeight(35)
        self.select_all_btn.setStyleSheet(STYLE_SELECT_ALL_BTN)
        self.select_all_btn.clicked.connect(self._toggle_select_all)
        button_layout.addWidget(self.select_all_btn)
        button_layout.addSpacing(10)
        save_btn = QPushButton("保存")
        save_btn.setMinimumWidth(120)
        save_btn.setMinimumHeight(35)
        save_btn.setStyleSheet(STYLE_SAVE_BTN)
        save_btn.clicked.connect(self._save_data_source_settings)
        button_layout.addWidget(save_btn)
        button_layout.addStretch()
        scroll_layout.addWidget(button_frame)
        
        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "数据源")
        self._update_parse_status_labels()
    
    def _make_http_poll_spinbox(self, url: str) -> QSpinBox:
        """为 HTTP 数据源创建 Get 间隔 SpinBox（最低 1 秒）。"""
        spin = QSpinBox()
        spin.setMinimum(1)
        spin.setMaximum(2147483647)
        spin.setSuffix(" 秒")
        default_val = self.config.get_http_poll_interval(url)
        spin.setValue(default_val)
        spin.setToolTip("HTTP 数据源 Get 轮询间隔（秒）")
        spin.setStyleSheet("font-size: 14px; min-width: 90px;")
        self.http_poll_spinboxes[url] = spin
        return spin

    def _add_http_poll_interval_grid(
        self,
        parent_layout: QVBoxLayout,
        sources: List[Tuple[str, str]],
    ) -> None:
        """在「数据源访问间隔」区块中以网格对齐标签与 Get 间隔输入框。"""
        if not sources:
            return
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        label_font = QFont()
        label_font.setPixelSize(16)
        fm = QFontMetrics(label_font)
        label_col_w = max(fm.width(label) for _, label in sources) + 12
        spin_col_w = 110
        hdr_style = "font-size: 14px; color: #666666; font-weight: bold;"
        hdr_name = QLabel("数据源")
        hdr_name.setStyleSheet(hdr_style)
        hdr_interval = QLabel("Get 间隔")
        hdr_interval.setStyleSheet(hdr_style)
        grid.addWidget(hdr_name, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(hdr_interval, 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
        for row, (url, label) in enumerate(sources, start=1):
            name_lbl = QLabel(label)
            name_lbl.setStyleSheet(STYLE_LABEL)
            name_lbl.setMinimumWidth(label_col_w)
            poll_spin = self._make_http_poll_spinbox(url)
            poll_spin.setFixedWidth(spin_col_w)
            grid.addWidget(name_lbl, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(poll_spin, row, 1, Qt.AlignLeft | Qt.AlignVCenter)
        grid.setColumnStretch(2, 1)
        parent_layout.addLayout(grid)

    def _add_http_source_row(
        self,
        parent,
        url: str,
        name: str,
        default_value: bool = False,
        status_key: Optional[str] = None,
    ):
        """添加带 Get 间隔的 HTTP 数据源行（开关 + 间隔 + 状态）。"""
        config_value = self.config.enabled_sources.get(url)
        initial_value = default_value if config_value is None else bool(config_value)
        checkbox = QCheckBox(name, parent)
        checkbox.setChecked(initial_value)
        checkbox.setStyleSheet("font-size: 16px; line-height: 22pt; padding: 2px 0;")
        self.source_vars[url] = checkbox
        if url not in self.individual_source_urls:
            self.individual_source_urls.append(url)
        poll_spin = self._make_http_poll_spinbox(url)
        sk = status_key or url
        status_label = QLabel("已解析" if initial_value else "未解析")
        status_label.setStyleSheet(STYLE_STATUS_CONNECTED if initial_value else STYLE_STATUS_NEUTRAL)
        status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_label.setToolTip("解析状态：已解析 / 未解析")
        self.source_parse_labels[sk] = status_label
        self.source_status_texts[sk] = ("已解析", "未解析", "解析状态：已解析 / 未解析")
        row_layout = QHBoxLayout()
        row_layout.addWidget(checkbox)
        row_layout.addWidget(QLabel("Get"))
        row_layout.addWidget(poll_spin)
        row_layout.addStretch()
        row_layout.addWidget(status_label)
        if isinstance(parent.layout(), QVBoxLayout):
            parent.layout().addLayout(row_layout)
        checkbox.stateChanged.connect(self._update_parse_status_labels)

    def _add_source_checkbox(
        self,
        parent,
        url,
        name,
        is_all_source=False,
        default_value=False,
        status_key=None,
        status_tooltip="解析状态：已解析 / 未解析",
        status_connected_text="已解析",
        status_disconnected_text="未解析",
        with_poll_interval: bool = False,
    ):
        """添加数据源复选框"""
        # 特殊处理：fanstudio_warning和fanstudio_report（仅用勾选控制解析范围，不写入单项 URL）
        if url in ["fanstudio_warning", "fanstudio_report"]:
            if url == "fanstudio_warning":
                initial_value = getattr(self.config.message_config, 'fanstudio_parse_warning', True)
            elif url == "fanstudio_report":
                initial_value = getattr(self.config.message_config, 'fanstudio_parse_report', True)
            else:
                initial_value = True
        else:
            config_value = self.config.enabled_sources.get(url)
            # 仅用于复选框初始显示；勿在打开设置页时写回 enabled_sources。
            # 否则「缺键」会被误写成默认值，用户只保存其他标签也会把错误连接开关固化进配置文件。
            if config_value is None:
                initial_value = default_value
            else:
                initial_value = config_value

        checkbox = QCheckBox(name, parent)
        checkbox.setChecked(initial_value)
        checkbox.setStyleSheet("font-size: 16px; line-height: 22pt; padding: 2px 0;")
        self.source_vars[url] = checkbox
        
        # 如果不是All源，记录到单项数据源列表
        if not is_all_source and url and url not in ["fanstudio_warning", "fanstudio_report"]:
            self.individual_source_urls.append(url)
            # 如果是Fan Studio数据源（WebSocket URL），记录到Fan Studio列表
            if 'fanstudio.tech' in url or 'fanstudio.hk' in url:
                self.fanstudio_source_urls.append(url)

        if status_key:
            status_label = QLabel(status_connected_text if initial_value else status_disconnected_text)
            status_label.setStyleSheet(STYLE_STATUS_CONNECTED if initial_value else STYLE_STATUS_NEUTRAL)
            status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            status_label.setToolTip(status_tooltip)
            self.source_parse_labels[status_key] = status_label
            self.source_status_texts[status_key] = (
                status_connected_text,
                status_disconnected_text,
                status_tooltip,
            )
            row_layout = QHBoxLayout()
            row_layout.addWidget(checkbox)
            if with_poll_interval and url:
                row_layout.addWidget(QLabel("Get"))
                row_layout.addWidget(self._make_http_poll_spinbox(url))
            row_layout.addStretch()
            row_layout.addWidget(status_label)
            if isinstance(parent.layout(), QVBoxLayout):
                parent.layout().addLayout(row_layout)
            else:
                parent.layout().addWidget(checkbox)
        else:
            if with_poll_interval and url:
                row_layout = QHBoxLayout()
                row_layout.addWidget(checkbox)
                row_layout.addWidget(QLabel("Get"))
                row_layout.addWidget(self._make_http_poll_spinbox(url))
                row_layout.addStretch()
                if isinstance(parent.layout(), QVBoxLayout):
                    parent.layout().addLayout(row_layout)
                else:
                    parent.layout().addWidget(checkbox)
            elif isinstance(parent.layout(), QVBoxLayout):
                parent.layout().addWidget(checkbox)
            else:
                parent.layout().addWidget(checkbox)

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
        self._update_parse_status_labels()
    
    def _select_all_sources(self):
        """全选所有数据源"""
        if hasattr(self, "fanstudio_all_connect_cb"):
            self.fanstudio_all_connect_cb.setChecked(True)
        if hasattr(self, "wolfx_all_connect_cb"):
            self.wolfx_all_connect_cb.setChecked(True)
        if hasattr(self, "p2pquake_connect_cb"):
            self.p2pquake_connect_cb.setChecked(True)
        for url, checkbox in self.source_vars.items():
            if url and url != self.all_source_url:  # 跳过空URL和all数据源
                checkbox.setChecked(True)
        # Fan Studio 细粒度子源也一起全选
        for attr in [
            'fanstudio_parse_cea_cb',
            'fanstudio_parse_cea_pr_cb',
            'fanstudio_parse_cwa_eew_cb',
            'fanstudio_parse_jma_cb',
            'fanstudio_parse_sa_cb',
            'fanstudio_parse_kma_eew_cb',
            'fanstudio_parse_cenc_cb',
            'fanstudio_parse_ningxia_cb',
            'fanstudio_parse_guangxi_cb',
            'fanstudio_parse_shanxi_cb',
            'fanstudio_parse_beijing_cb',
            'fanstudio_parse_yunnan_cb',
            'fanstudio_parse_cwa_cb',
            'fanstudio_parse_hko_cb',
            'fanstudio_parse_usgs_cb',
            'fanstudio_parse_emsc_cb',
            'fanstudio_parse_bcsf_cb',
            'fanstudio_parse_gfz_cb',
            'fanstudio_parse_usp_cb',
            'fanstudio_parse_kma_cb',
            'fanstudio_parse_fssn_cb',
            'fanstudio_parse_fssn_cmt_cb',
            'fanstudio_parse_weatheralarm_cb',
            'fanstudio_parse_tsunami_cb',
            'p2pquake_parse_551_cb',
            'p2pquake_parse_552_cb',
        ]:
            cb = getattr(self, attr, None)
            if cb is not None:
                cb.setChecked(True)
        self._update_parse_status_labels()
    
    def _restore_default_selection(self):
        """恢复默认选中状态"""
        for url, checkbox in self.source_vars.items():
            if url and url != self.all_source_url:
                checkbox.setChecked(bool(self.config.enabled_sources.get(url, False)))
        if hasattr(self, "fanstudio_all_connect_cb"):
            self.fanstudio_all_connect_cb.setChecked(self.config.enabled_sources.get(self.all_source_url, True))
        if hasattr(self, "wolfx_all_connect_cb"):
            self.wolfx_all_connect_cb.setChecked(
                self.config.enabled_sources.get("wss://ws-api.wolfx.jp/all_eew", True)
            )
        if hasattr(self, "p2pquake_connect_cb"):
            self.p2pquake_connect_cb.setChecked(p2pquake_master_enabled(self.config.enabled_sources))
        # Fan Studio 细粒度子源：恢复为默认勾选
        for attr, cfg_name in [
            ('fanstudio_parse_cea_cb', 'fanstudio_parse_cea'),
            ('fanstudio_parse_cea_pr_cb', 'fanstudio_parse_cea_pr'),
            ('fanstudio_parse_cwa_eew_cb', 'fanstudio_parse_cwa_eew'),
            ('fanstudio_parse_jma_cb', 'fanstudio_parse_jma'),
            ('fanstudio_parse_sa_cb', 'fanstudio_parse_sa'),
            ('fanstudio_parse_kma_eew_cb', 'fanstudio_parse_kma_eew'),
            ('fanstudio_parse_cenc_cb', 'fanstudio_parse_cenc'),
            ('fanstudio_parse_ningxia_cb', 'fanstudio_parse_ningxia'),
            ('fanstudio_parse_guangxi_cb', 'fanstudio_parse_guangxi'),
            ('fanstudio_parse_shanxi_cb', 'fanstudio_parse_shanxi'),
            ('fanstudio_parse_beijing_cb', 'fanstudio_parse_beijing'),
            ('fanstudio_parse_yunnan_cb', 'fanstudio_parse_yunnan'),
            ('fanstudio_parse_cwa_cb', 'fanstudio_parse_cwa'),
            ('fanstudio_parse_hko_cb', 'fanstudio_parse_hko'),
            ('fanstudio_parse_usgs_cb', 'fanstudio_parse_usgs'),
            ('fanstudio_parse_emsc_cb', 'fanstudio_parse_emsc'),
            ('fanstudio_parse_bcsf_cb', 'fanstudio_parse_bcsf'),
            ('fanstudio_parse_gfz_cb', 'fanstudio_parse_gfz'),
            ('fanstudio_parse_usp_cb', 'fanstudio_parse_usp'),
            ('fanstudio_parse_kma_cb', 'fanstudio_parse_kma'),
            ('fanstudio_parse_fssn_cb', 'fanstudio_parse_fssn'),
            ('fanstudio_parse_fssn_cmt_cb', 'fanstudio_parse_fssn_cmt'),
            ('fanstudio_parse_weatheralarm_cb', 'fanstudio_parse_weatheralarm'),
            ('fanstudio_parse_tsunami_cb', 'fanstudio_parse_tsunami'),
            ('p2pquake_parse_551_cb', 'p2pquake_parse_551'),
            ('p2pquake_parse_552_cb', 'p2pquake_parse_552'),
        ]:
            cb = getattr(self, attr, None)
            if cb is not None:
                default_val = getattr(self.config.message_config, cfg_name, True)
                cb.setChecked(bool(default_val))
        for url, spin in self.http_poll_spinboxes.items():
            spin.setValue(self.config.get_http_poll_interval(url))
        if hasattr(self, "custom_http_poll_spinbox"):
            self.custom_http_poll_spinbox.setValue(
                self.config.get_http_poll_interval("__custom_http__")
            )
        self._update_parse_status_labels()
    
    def _create_advanced_tab(self):
        """创建高级设置标签页（地名修正、日志、自定义数据源）"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scrollable_widget = QWidget()
        main_layout = QVBoxLayout(scrollable_widget)
        main_layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        main_layout.setSpacing(SPACING_TAB)
        
        # ---------- 1. 地名处理方式（二选一） ----------
        sec1_title = QLabel("地名处理方式")
        sec1_title.setStyleSheet(STYLE_SECTION_TITLE)
        main_layout.addWidget(sec1_title)

        mode_hint = QLabel("非中文数据源统一使用以下方式之一处理地名，二者不可同时启用。")
        mode_hint.setStyleSheet(STYLE_HINT + " line-height: 1.5;")
        mode_hint.setWordWrap(True)
        main_layout.addWidget(mode_hint)

        place_mode_group = QButtonGroup(scrollable_widget)

        fix_radio = QRadioButton("地名修正")
        fix_radio.setStyleSheet("font-size: 16px; padding: 5px;")
        place_mode_group.addButton(fix_radio, 0)
        main_layout.addWidget(fix_radio)
        fix_info = QLabel(
            "根据经纬度自动修正地名（支持 usgs、emsc、bcsf、gfz、usp、kma、bmkg、geonet、ingv、early_est 等数据源），无需 API 密钥。"
        )
        fix_info.setStyleSheet(STYLE_HINT + " padding-left: 25px; line-height: 1.5;")
        fix_info.setWordWrap(True)
        main_layout.addWidget(fix_info)

        baidu_radio = QRadioButton("百度翻译")
        baidu_radio.setStyleSheet("font-size: 16px; padding: 5px;")
        place_mode_group.addButton(baidu_radio, 1)
        main_layout.addWidget(baidu_radio)
        baidu_info = QLabel(
            "将日语、韩语、英语等非中文地名翻译为中文，适用于所有非中文数据源（含速报、预警、火山情报等）。"
            "需要配置百度翻译 API 密钥。"
        )
        baidu_info.setStyleSheet(STYLE_HINT + " padding-left: 25px; line-height: 1.5;")
        baidu_info.setWordWrap(True)
        main_layout.addWidget(baidu_info)

        tc = self.config.translation_config
        if getattr(tc, "enabled", False):
            baidu_radio.setChecked(True)
        else:
            fix_radio.setChecked(True)

        baidu_app_id_label = QLabel("百度翻译 AppID：")
        baidu_app_id_label.setStyleSheet(STYLE_LABEL)
        main_layout.addWidget(baidu_app_id_label)
        baidu_app_id_entry = QLineEdit()
        baidu_app_id_entry.setPlaceholderText("在百度翻译开放平台申请")
        baidu_app_id_entry.setText(getattr(tc, "baidu_app_id", "") or "")
        baidu_app_id_entry.setStyleSheet(STYLE_LINEEDIT)
        main_layout.addWidget(baidu_app_id_entry)
        baidu_secret_label = QLabel("百度翻译密钥：")
        baidu_secret_label.setStyleSheet(STYLE_LABEL)
        main_layout.addWidget(baidu_secret_label)
        baidu_secret_entry = QLineEdit()
        baidu_secret_entry.setPlaceholderText("与 AppID 对应的密钥")
        baidu_secret_entry.setEchoMode(QLineEdit.Password)
        baidu_secret_entry.setText(getattr(tc, "baidu_secret", "") or "")
        baidu_secret_entry.setStyleSheet(STYLE_LINEEDIT)
        main_layout.addWidget(baidu_secret_entry)

        link_label = QLabel(
            '获取 API 密钥：<a href="https://fanyi-api.baidu.com/" style="color: #4A90E2;">百度翻译开放平台</a>'
        )
        link_label.setOpenExternalLinks(True)
        link_label.setStyleSheet(STYLE_HINT + " padding-left: 25px;")
        main_layout.addWidget(link_label)

        def _update_baidu_api_visible():
            use_baidu = baidu_radio.isChecked()
            baidu_app_id_label.setVisible(use_baidu)
            baidu_app_id_entry.setVisible(use_baidu)
            baidu_secret_label.setVisible(use_baidu)
            baidu_secret_entry.setVisible(use_baidu)
            link_label.setVisible(use_baidu)

        fix_radio.toggled.connect(lambda _: _update_baidu_api_visible())
        baidu_radio.toggled.connect(lambda _: _update_baidu_api_visible())
        _update_baidu_api_visible()
        
        # 分隔线
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFrameShadow(QFrame.Sunken)
        sep1.setStyleSheet("color: #E0E0E0;")
        main_layout.addWidget(sep1)

        # ---------- 2. 预估烈度与告警闪烁（卡片布局，与「外观与显示」QGroupBox 风格一致） ----------
        ac = self.config.alert_config
        group_alert = QGroupBox("预警闪烁与有感提示")
        group_alert.setStyleSheet(STYLE_GROUPBOX)
        alert_outer = QVBoxLayout(group_alert)
        alert_outer.setContentsMargins(10, 12, 10, 10)
        alert_outer.setSpacing(4)

        alert_enable_cb = QCheckBox("启用预警闪烁与有感/强有感提示")
        alert_enable_cb.setChecked(bool(getattr(ac, 'enabled', False)))
        alert_enable_cb.setStyleSheet("font-size: 16px;")
        alert_enable_cb.setToolTip(
            "收到地震预警且满足最低震级与烈度条件时，先展示带安全提示的预警全文（提示期），"
            "再切回纯预警条文；日台类源不拼接提示、不进入本序列。"
            "有感/强有感阈值：烈度小于 5 与大于等于 6（5≤烈度<6 不拼接提示）。"
        )

        _alert_enable_revert = {'active': False}

        def _on_alert_enable_toggled(on: bool) -> None:
            # 每次由未勾选变为勾选都弹窗（含点「取消」后再勾选）；程序化撤回勾选时跳过。
            if _alert_enable_revert['active']:
                return
            if not on:
                return
            dlg = QDialog(self)
            dlg.setWindowTitle("功能风险提示")
            dlg.setModal(True)
            dlg.setMinimumWidth(460)
            dlg.setMaximumWidth(520)
            root = QVBoxLayout(dlg)
            root.setContentsMargins(24, 22, 24, 22)
            root.setSpacing(20)

            top = QHBoxLayout()
            top.setSpacing(18)
            icon_lbl = QLabel()
            ico = dlg.style().standardIcon(QStyle.SP_MessageBoxWarning)
            pm = ico.pixmap(48, 48)
            if not pm.isNull():
                icon_lbl.setPixmap(pm)
            icon_lbl.setFixedWidth(52)
            icon_lbl.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            top.addWidget(icon_lbl, 0, Qt.AlignTop)

            text_col = QVBoxLayout()
            text_col.setSpacing(10)
            text_col.setContentsMargins(0, 2, 0, 0)

            sub = QLabel("在开启本功能前，请阅读以下说明。")
            sub.setWordWrap(True)
            sub.setStyleSheet("font-size: 13px; color: #616161; line-height: 1.5;")

            body = QLabel()
            body.setTextFormat(Qt.RichText)
            body.setWordWrap(True)
            body.setOpenExternalLinks(False)
            body.setText(
                '<p style="margin: 0; line-height: 1.7;">'
                '<span style="font-size: 16pt; font-weight: bold; color: #C62828;">'
                "该功能尚未完成长期稳定验证，<br/>"
                "存在不稳定风险，<br/>"
                "请谨慎使用。"
                "</span></p>"
            )
            text_col.addWidget(sub)
            text_col.addWidget(body)
            top.addLayout(text_col, 1)
            root.addLayout(top)

            btn_row = QHBoxLayout()
            btn_row.setSpacing(12)
            btn_row.setContentsMargins(0, 8, 0, 0)
            btn_row.addStretch(1)
            ok_btn = QPushButton("我已知晓并继续开启")
            cancel_btn = QPushButton("取消")
            ok_btn.setMinimumHeight(40)
            cancel_btn.setMinimumHeight(40)
            ok_btn.setMinimumWidth(200)
            cancel_btn.setMinimumWidth(96)
            ok_btn.setCursor(Qt.PointingHandCursor)
            cancel_btn.setCursor(Qt.PointingHandCursor)
            ok_btn.setStyleSheet(
                "QPushButton { font-size: 14px; padding: 8px 16px; "
                "background: #1565C0; color: white; border: none; border-radius: 6px; }"
                "QPushButton:hover { background: #1976D2; }"
                "QPushButton:pressed { background: #0D47A1; }"
            )
            cancel_btn.setStyleSheet(
                "QPushButton { font-size: 14px; padding: 8px 16px; "
                "background: #F5F5F5; color: #333333; border: 1px solid #BDBDBD; border-radius: 6px; }"
                "QPushButton:hover { background: #EEEEEE; }"
            )
            btn_row.addWidget(ok_btn)
            btn_row.addWidget(cancel_btn)
            root.addLayout(btn_row)

            cancel_btn.setDefault(True)
            cancel_btn.setAutoDefault(True)
            ok_btn.setAutoDefault(False)
            ok_btn.clicked.connect(dlg.accept)
            cancel_btn.clicked.connect(dlg.reject)
            esc = QShortcut(QKeySequence(Qt.Key_Escape), dlg)
            esc.activated.connect(dlg.reject)

            if dlg.exec_() != QDialog.Accepted:
                _alert_enable_revert['active'] = True
                try:
                    alert_enable_cb.blockSignals(True)
                    alert_enable_cb.setChecked(False)
                    alert_enable_cb.blockSignals(False)
                finally:
                    _alert_enable_revert['active'] = False

        alert_enable_cb.toggled.connect(_on_alert_enable_toggled)
        alert_outer.addWidget(alert_enable_cb)

        def _subhead(text: str) -> QLabel:
            h = QLabel(text)
            h.setStyleSheet(STYLE_CARD_SUBHEAD)
            return h

        _al_w = 108  # 单列纵向：标签列略宽以免截断

        def _v_field_grid() -> QGridLayout:
            g = QGridLayout()
            g.setContentsMargins(0, 0, 0, 0)
            g.setHorizontalSpacing(8)
            g.setVerticalSpacing(5)
            g.setColumnStretch(2, 1)
            return g

        def _v_add_row(g: QGridLayout, row: int, lbl: QLabel, w: QWidget) -> None:
            lbl.setMinimumWidth(_al_w)
            g.addWidget(lbl, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
            g.addWidget(w, row, 1, Qt.AlignLeft)

        # —— 触发条件（单列纵向，避免超出窗口宽度） ——
        alert_outer.addWidget(_subhead("触发条件"))
        grid_trigger = _v_field_grid()

        min_mag_label = QLabel("最低震级")
        min_mag_label.setStyleSheet(STYLE_LABEL)
        min_mag_label.setToolTip("低于该震级的预警不进入告警序列。")
        min_mag_spin = QDoubleSpinBox()
        min_mag_spin.setRange(0.0, 10.0)
        min_mag_spin.setDecimals(1)
        min_mag_spin.setSingleStep(0.1)
        min_mag_spin.setValue(float(getattr(ac, 'min_magnitude', 3.0)))
        min_mag_spin.setSuffix(" M")
        min_mag_spin.setFixedWidth(100)
        min_mag_spin.setStyleSheet(STYLE_SPINBOX)
        _v_add_row(grid_trigger, 0, min_mag_label, min_mag_spin)

        alert_outer.addLayout(grid_trigger)

        # —— 闪烁与颜色 ——
        alert_outer.addWidget(_subhead("闪烁与颜色"))
        grid_flash = _v_field_grid()

        hint_dur_label = QLabel(
            "提示期时长与「预警/消息更新」中的发震时间有效期（及 JMA/四川 单独窗口）一致，"
            "按当前报文剩余有效时间兜底；字幕滚完一周可提前结束。"
        )
        hint_dur_label.setWordWrap(True)
        hint_dur_label.setStyleSheet(STYLE_LABEL + " color: #555555;")
        grid_flash.addWidget(hint_dur_label, 0, 0, 1, 2)

        int_label = QLabel("闪烁间隔")
        int_label.setStyleSheet(STYLE_LABEL)
        flash_interval_spin = QSpinBox()
        flash_interval_spin.setRange(50, 2000)
        flash_interval_spin.setSingleStep(50)
        flash_interval_spin.setValue(int(getattr(ac, 'flash_interval_ms', 400)))
        flash_interval_spin.setSuffix(" 毫秒")
        flash_interval_spin.setFixedWidth(120)
        flash_interval_spin.setStyleSheet(STYLE_SPINBOX)
        _v_add_row(grid_flash, 1, int_label, flash_interval_spin)

        color_label = QLabel("告警色")
        color_label.setStyleSheet(STYLE_LABEL)
        color_label.setToolTip("点击选择左侧标识闪烁颜色。")
        flash_color_btn = QPushButton(getattr(ac, 'flash_color', '#FF0000'))
        flash_color_btn.setFixedWidth(140)
        flash_color_btn.setCursor(Qt.PointingHandCursor)
        flash_color_btn.setStyleSheet(
            f"QPushButton {{ background-color: {getattr(ac, 'flash_color', '#FF0000')}; "
            f"color: white; padding: 6px 10px; border-radius: 4px; font-size: 14px; border: 1px solid #CCCCCC; }}"
        )

        def _on_pick_color():
            cur = QColor(flash_color_btn.text() or '#FF0000')
            picked = QColorDialog.getColor(cur, self, "选择闪烁颜色")
            if picked.isValid():
                hex_color = picked.name(QColor.HexRgb).upper()
                flash_color_btn.setText(hex_color)
                flash_color_btn.setStyleSheet(
                    f"QPushButton {{ background-color: {hex_color}; "
                    f"color: white; padding: 6px 10px; border-radius: 4px; font-size: 14px; border: 1px solid #CCCCCC; }}"
                )
        flash_color_btn.clicked.connect(_on_pick_color)
        _v_add_row(grid_flash, 2, color_label, flash_color_btn)

        alert_outer.addLayout(grid_flash)

        # —— 模拟 ——
        alert_outer.addWidget(_subhead("模拟"))
        sim_btn = QPushButton("模拟预警")
        sim_btn.setStyleSheet(STYLE_SELECT_ALL_BTN)
        sim_btn.setCursor(Qt.PointingHandCursor)
        sim_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sim_btn.clicked.connect(self._simulate_alert)
        alert_outer.addWidget(sim_btn)

        main_layout.addWidget(group_alert)
        main_layout.addSpacing(10)

        # 分隔线
        sep1b = QFrame()
        sep1b.setFrameShape(QFrame.HLine)
        sep1b.setFrameShadow(QFrame.Sunken)
        sep1b.setStyleSheet("color: #E0E0E0;")
        main_layout.addWidget(sep1b)
        
        # ---------- 3. 日志设置 ----------
        sec2_title = QLabel("日志设置")
        sec2_title.setStyleSheet(STYLE_SECTION_TITLE)
        main_layout.addWidget(sec2_title)
        output_file_checkbox = QCheckBox("输出日志到文件")
        output_file_checkbox.setChecked(self.config.log_config.output_to_file)
        output_file_checkbox.setStyleSheet("font-size: 16px; padding: 5px;")
        main_layout.addWidget(output_file_checkbox)
        output_file_desc = QLabel("启用后，日志将保存到 log.txt 文件中")
        output_file_desc.setStyleSheet(STYLE_HINT + " padding-left: 25px;")
        output_file_desc.setWordWrap(True)
        main_layout.addWidget(output_file_desc)
        clear_log_checkbox = QCheckBox("每次程序启动前清空日志")
        clear_log_checkbox.setChecked(self.config.log_config.clear_log_on_startup)
        clear_log_checkbox.setStyleSheet("font-size: 16px; padding: 5px;")
        main_layout.addWidget(clear_log_checkbox)
        clear_log_desc = QLabel("启用后，每次启动程序时会清空日志文件")
        clear_log_desc.setStyleSheet(STYLE_HINT + " padding-left: 25px;")
        clear_log_desc.setWordWrap(True)
        main_layout.addWidget(clear_log_desc)
        split_date_checkbox = QCheckBox("按日期分割日志")
        split_date_checkbox.setChecked(self.config.log_config.split_by_date)
        split_date_checkbox.setStyleSheet("font-size: 16px; padding: 5px;")
        main_layout.addWidget(split_date_checkbox)
        split_date_desc = QLabel("启用后，日志文件将按日期命名（log_YYYYMMDD.txt），每天自动创建新文件")
        split_date_desc.setStyleSheet(STYLE_HINT + " padding-left: 25px;")
        split_date_desc.setWordWrap(True)
        main_layout.addWidget(split_date_desc)
        log_size_layout = QHBoxLayout()
        log_size_label = QLabel("日志文件最大大小（MB）：")
        log_size_label.setStyleSheet(STYLE_LABEL)
        log_size_layout.addWidget(log_size_label)
        log_size_spinbox = QSpinBox()
        log_size_spinbox.setMinimum(1)
        log_size_spinbox.setMaximum(1000)
        log_size_spinbox.setValue(self.config.log_config.max_log_size)
        log_size_spinbox.setSuffix(" MB")
        log_size_spinbox.setStyleSheet(STYLE_SPINBOX)
        log_size_layout.addWidget(log_size_spinbox)
        log_size_layout.addStretch()
        main_layout.addLayout(log_size_layout)
        log_size_desc = QLabel("当日志文件达到此大小时，将自动创建备份文件（仅在未启用按日期分割时生效）")
        log_size_desc.setStyleSheet(STYLE_HINT)
        log_size_desc.setWordWrap(True)
        main_layout.addWidget(log_size_desc)
        
        # 分隔线
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        sep2.setStyleSheet("color: #E0E0E0;")
        main_layout.addWidget(sep2)
        
        # ---------- 3. 自定义数据源 ----------
        sec3_title = QLabel("自定义数据源")
        sec3_title.setStyleSheet(STYLE_SECTION_TITLE)
        main_layout.addWidget(sec3_title)
        custom_url_label = QLabel("自定义数据源 URL：")
        custom_url_label.setStyleSheet(STYLE_LABEL)
        main_layout.addWidget(custom_url_label)
        custom_url_entry = QLineEdit()
        custom_url_entry.setPlaceholderText("输入 http/https/ws/wss URL，留空则关闭")
        custom_url_entry.setText(self.config.custom_data_source_url or "")
        custom_url_entry.setStyleSheet(STYLE_LINEEDIT)
        main_layout.addWidget(custom_url_entry)
        custom_poll_layout = QHBoxLayout()
        custom_poll_label = QLabel("HTTP Get 间隔（秒）：")
        custom_poll_label.setStyleSheet(STYLE_LABEL)
        custom_poll_layout.addWidget(custom_poll_label)
        custom_http_poll_spinbox = QSpinBox()
        custom_http_poll_spinbox.setMinimum(1)
        custom_http_poll_spinbox.setMaximum(2147483647)
        custom_http_poll_spinbox.setSuffix(" 秒")
        custom_http_poll_spinbox.setValue(self.config.get_http_poll_interval("__custom_http__"))
        custom_http_poll_spinbox.setStyleSheet(STYLE_SPINBOX)
        custom_http_poll_spinbox.setToolTip("自定义 HTTP 数据源轮询间隔（仅 http/https 生效）")
        custom_poll_layout.addWidget(custom_http_poll_spinbox)
        custom_poll_layout.addStretch()
        main_layout.addLayout(custom_poll_layout)
        self.custom_http_poll_spinbox = custom_http_poll_spinbox
        custom_source_status_label = QLabel("状态：—")
        custom_source_status_label.setStyleSheet(STYLE_HINT)
        custom_source_status_label.setObjectName("custom_source_status_label")
        self.custom_source_status_label = custom_source_status_label
        main_layout.addWidget(custom_source_status_label)
        custom_hint = QLabel(
            "• HTTP/HTTPS：按上方 Get 间隔向该 URL 轮询；留空即关闭。\n"
            "• WS/WSS：请确保数据格式符合要求并能连接到服务器。"
        )
        custom_hint.setStyleSheet(STYLE_HINT + " line-height: 1.5;")
        custom_hint.setWordWrap(True)
        main_layout.addWidget(custom_hint)
        # 格式示例
        format_label = QLabel("预警源数据格式示例（二选一）：")
        format_label.setStyleSheet(STYLE_LABEL + " margin-top: 8px;")
        main_layout.addWidget(format_label)
        example_flat = (
            '格式一（平铺）：\n'
            '{\n'
            '  "eventID": "JMA_202512262525",\n'
            '  "placeName": "青森县东方冲",\n'
            '  "latitude": 41.1,\n'
            '  "longitude": 142.6,\n'
            '  "depth": 10,\n'
            '  "reportTime": "2025/12/25 25:25:00",\n'
            '  "shockTime": "2025/12/25 25:24:00",\n'
            '  "reportNum": 5,\n'
            '  "magnitude": "3.5",\n'
            '  "sourceName": "JMA"\n'
            '}'
        )
        example_flat_edit = QPlainTextEdit()
        example_flat_edit.setPlainText(example_flat)
        example_flat_edit.setReadOnly(True)
        example_flat_edit.setMaximumHeight(145)
        example_flat_edit.setStyleSheet(
            "QPlainTextEdit { font-family: Consolas,Monaco,monospace; font-size: 11px; "
            "background: #f5f5f5; border: 1px solid #ddd; border-radius: 4px; padding: 6px; }"
        )
        main_layout.addWidget(example_flat_edit)
        example_nested = (
            '格式二（嵌套 Data）：\n'
            '{\n'
            '  "Data": {\n'
            '    "id": "CWA_202601190730",\n'
            '    "updates": 4,\n'
            '    "shockTime": "2026-01-19 07:30:00",\n'
            '    "latitude": 23.33,\n'
            '    "longitude": 120.82,\n'
            '    "depth": 10.0,\n'
            '    "magnitude": 4.5,\n'
            '    "placeName": "高雄市桃源區"\n'
            '  }\n'
            '}'
        )
        example_nested_edit = QPlainTextEdit()
        example_nested_edit.setPlainText(example_nested)
        example_nested_edit.setReadOnly(True)
        example_nested_edit.setMaximumHeight(145)
        example_nested_edit.setStyleSheet(
            "QPlainTextEdit { font-family: Consolas,Monaco,monospace; font-size: 11px; "
            "background: #f5f5f5; border: 1px solid #ddd; border-radius: 4px; padding: 6px; }"
        )
        main_layout.addWidget(example_nested_edit)
        
        main_layout.addStretch()
        
        # 保存按钮
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 10, 0, 0)
        button_layout.addStretch()
        save_btn = QPushButton("保存高级设置")
        save_btn.setMinimumWidth(120)
        save_btn.setMinimumHeight(35)
        save_btn.setStyleSheet(STYLE_SAVE_BTN)
        save_btn.clicked.connect(lambda: self._save_advanced_settings(
            fix_radio, baidu_radio, output_file_checkbox, clear_log_checkbox,
            split_date_checkbox, log_size_spinbox, custom_url_entry,
            baidu_app_id_entry, baidu_secret_entry
        ))
        button_layout.addWidget(save_btn)
        button_layout.addStretch()
        main_layout.addWidget(button_frame)
        
        self.advanced_vars = {
            'fix_radio': fix_radio,
            'baidu_radio': baidu_radio,
            'output_file_checkbox': output_file_checkbox,
            'clear_log_checkbox': clear_log_checkbox,
            'split_date_checkbox': split_date_checkbox,
            'log_size_spinbox': log_size_spinbox,
            'custom_url_entry': custom_url_entry,
            'custom_source_status_label': custom_source_status_label,
            'baidu_app_id_entry': baidu_app_id_entry,
            'baidu_secret_entry': baidu_secret_entry,
            'alert_enable_cb': alert_enable_cb,
            'min_mag_spin': min_mag_spin,
            'flash_interval_spin': flash_interval_spin,
            'flash_color_btn': flash_color_btn,
        }
        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "高级")

    def _save_alert_settings(self) -> None:
        """从 advanced_vars 把告警面板控件值收回 ``Config.alert_config``。"""
        adv = getattr(self, 'advanced_vars', {}) or {}
        ac = self.config.alert_config

        cb = adv.get('alert_enable_cb')
        if cb is not None:
            ac.enabled = bool(cb.isChecked())

        spin = adv.get('min_mag_spin')
        if spin is not None:
            ac.min_magnitude = float(spin.value())

        spin = adv.get('flash_interval_spin')
        if spin is not None:
            ac.flash_interval_ms = max(50, min(2000, int(spin.value())))

        btn = adv.get('flash_color_btn')
        if btn is not None:
            text = (btn.text() or "").strip()
            if text:
                ac.flash_color = text

        ac.validate()

    def _simulate_alert(self) -> None:
        """通过主窗口接口发起一次模拟预警。"""
        try:
            mw = self.parent()
            if mw is None or not hasattr(mw, 'trigger_alert_simulation'):
                QMessageBox.information(
                    self,
                    "提示",
                    "未找到主窗口接口，无法模拟预警。",
                )
                return
            try:
                self._save_alert_settings()
            except Exception:
                pass
            mw.trigger_alert_simulation(
                place_name="测试地点",
                magnitude=5.0,
                epi_intensity=7.0,
            )
        except Exception as e:
            logger.error(f"模拟预警失败: {e}")

    def _save_advanced_settings(self, fix_radio, baidu_radio, output_file_checkbox, clear_log_checkbox,
                                  split_date_checkbox, log_size_spinbox, custom_url_entry,
                                  baidu_app_id_entry=None, baidu_secret_entry=None,
                                  show_message=True):
        """保存高级设置（地名处理、日志、自定义数据源）。show_message=False 时不弹成功提示（由调用方统一提示）。返回 True 表示保存成功，False 表示未保存（校验失败或异常）。"""
        try:
            custom_url = custom_url_entry.text().strip()
            if custom_url:
                low = custom_url.lower()
                if not (low.startswith('http://') or low.startswith('https://') or low.startswith('ws://') or low.startswith('wss://')):
                    QMessageBox.warning(
                        self, "警告",
                        "自定义数据源 URL 必须以 http://、https://、ws:// 或 wss:// 开头，请修改后重试。"
                    )
                    return False
            use_baidu = baidu_radio.isChecked()
            self.config.translation_config.enabled = use_baidu
            self.config.translation_config.use_place_name_fix = not use_baidu
            if baidu_app_id_entry is not None:
                self.config.translation_config.baidu_app_id = baidu_app_id_entry.text().strip()
            if baidu_secret_entry is not None:
                self.config.translation_config.baidu_secret = baidu_secret_entry.text().strip()
            if use_baidu:
                app_id = self.config.translation_config.baidu_app_id
                secret = self.config.translation_config.baidu_secret
                if not app_id or not secret:
                    QMessageBox.warning(
                        self, "警告",
                        "启用百度翻译需要配置 AppID 与密钥。\n翻译功能将保持禁用，请填写后重新保存。"
                    )
                    self.config.translation_config.enabled = False
                    self.config.translation_config.use_place_name_fix = True
            # 日志与数据源相关设置
            self.config.log_config.output_to_file = output_file_checkbox.isChecked()
            self.config.log_config.clear_log_on_startup = clear_log_checkbox.isChecked()
            self.config.log_config.split_by_date = split_date_checkbox.isChecked()
            self.config.log_config.max_log_size = log_size_spinbox.value()
            self.config.custom_data_source_url = custom_url
            if hasattr(self, "custom_http_poll_spinbox"):
                self.config.http_poll_intervals["__custom_http__"] = max(
                    1, int(self.custom_http_poll_spinbox.value())
                )

            try:
                self._save_alert_settings()
            except Exception as e_int:
                logger.debug(f"保存告警设置失败（忽略，不影响其他配置）: {e_int}")
            if not self.config.log_config.validate():
                QMessageBox.warning(self, "警告", "日志配置验证失败，请检查设置")
                return False
            self.config.save_config()
            if show_message:
                msg = QMessageBox(self)
                msg.setWindowTitle("成功")
                msg.setText("高级设置已保存。\n数据源与日志相关设置需重启程序后生效。")
                msg.setIcon(QMessageBox.Information)
                cancel_btn = msg.addButton("取消", QMessageBox.RejectRole)
                restart_btn = msg.addButton("重启", QMessageBox.AcceptRole)
                msg.exec_()
                if msg.clickedButton() == restart_btn:
                    logger.debug("用户选择重启，正在重启软件...")
                    self._restart_application()
            logger.debug("高级设置已保存")
            return True
        except Exception as e:
            logger.error(f"保存高级设置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")
            return False
    
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
        body_style = STYLE_ABOUT_ITEM + " padding-left: 10px; padding-bottom: 2px;"

        # 标题与版本（上方留白，避免贴顶）
        layout.addSpacing(12)
        title_label = QLabel("地震预警及速报滚动实况")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #0066CC; padding-bottom: 2px;")
        layout.addWidget(title_label)
        version_label = QLabel(f"版本 v{APP_VERSION} Beta测试版")
        version_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #FF6600; padding-bottom: 6px;")
        layout.addWidget(version_label)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFrameShadow(QFrame.Sunken)
        sep1.setStyleSheet(sep_style)
        layout.addWidget(sep1)
        layout.addSpacing(4)

        # 声明（与主窗口「更新说明」弹窗内红色声明一致）
        about_declaration = QLabel(APP_DECLARATION_TEXT)
        about_declaration.setWordWrap(True)
        about_declaration.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        about_declaration.setTextInteractionFlags(Qt.TextSelectableByMouse)
        about_declaration.setStyleSheet(
            "color: #B22222; font-weight: bold; font-size: 15px; "
            "line-height: 1.4; padding: 4px 0 0 0; margin: 0; background: transparent;"
        )
        layout.addWidget(about_declaration)
        layout.addSpacing(SPACING_BLOCK - 8)
        sep_decl = QFrame()
        sep_decl.setFrameShape(QFrame.HLine)
        sep_decl.setFrameShadow(QFrame.Sunken)
        sep_decl.setStyleSheet(sep_style)
        layout.addWidget(sep_decl)
        layout.addSpacing(4)

        # 数据源支持
        data_source_label = QLabel("数据源支持")
        data_source_label.setStyleSheet(STYLE_SECTION_TITLE)
        layout.addWidget(data_source_label)
        for name in ["Fan Studio", "P2PQuake", "NIED 日本防災科研所", "Wolfx"]:
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

        # 项目地址（GitHub）
        github_label = QLabel("项目地址")
        github_label.setStyleSheet(STYLE_SECTION_TITLE)
        layout.addWidget(github_label)
        github_url = "https://github.com/Jian11323/Rolling-Subtitle"
        github_link = QLabel(f'<a href="{github_url}">{github_url}</a>')
        github_link.setStyleSheet(body_style)
        github_link.setOpenExternalLinks(True)
        github_link.setTextFormat(Qt.RichText)
        github_link.setWordWrap(True)
        layout.addWidget(github_link)
        layout.addSpacing(SPACING_BLOCK - 4)
        sep_github = QFrame()
        sep_github.setFrameShape(QFrame.HLine)
        sep_github.setFrameShadow(QFrame.Sunken)
        sep_github.setStyleSheet(sep_style)
        layout.addWidget(sep_github)
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
            tl.setStyleSheet(STYLE_ABOUT_ITEM + " line-height: 1.4;")
            thanks_layout.addWidget(tl)
        layout.addWidget(thanks_frame)
        layout.addStretch()

        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "关于")

    def _create_data_source_status_tab(self):
        """创建数据源状态标签页（紧凑：数据源 + 状态 + 分钟条）"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: #F7F8FA; }")
        container = QWidget()
        container.setStyleSheet("background: #F7F8FA;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        layout.setSpacing(12)

        title = QLabel("服务器状态")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1F1F1F;")
        layout.addWidget(title)

        hint = QLabel("每分钟记录一次状态，最多显示最近60分钟")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 13px; color: #6D7580;")
        layout.addWidget(hint)

        self.data_source_status_cards_container = QWidget()
        self.data_source_status_cards_layout = QVBoxLayout(self.data_source_status_cards_container)
        self.data_source_status_cards_layout.setContentsMargins(0, 6, 0, 0)
        self.data_source_status_cards_layout.setSpacing(10)
        layout.addWidget(self.data_source_status_cards_container)
        layout.addStretch()

        scroll_area.setWidget(container)
        self.notebook.addTab(scroll_area, "数据源状态")

    def _format_ts(self, value: Any) -> str:
        try:
            ts = float(value or 0)
            if ts <= 0:
                return "-"
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "-"

    def _status_chip_text(self, connection_state: str, heartbeat_state: str) -> str:
        if connection_state == "connected" and heartbeat_state != "timeout":
            return "正常"
        if connection_state == "connecting":
            return "重连中"
        if heartbeat_state == "timeout":
            return "心跳超时"
        if connection_state == "disconnected":
            return "断开"
        return "未连接"

    def _status_chip_color(self, connection_state: str, heartbeat_state: str) -> str:
        if connection_state == "connected" and heartbeat_state != "timeout":
            return "#2ECC71"
        if connection_state == "connecting":
            return "#F39C12"
        if heartbeat_state == "timeout":
            return "#E74C3C"
        if connection_state == "disconnected":
            return "#E74C3C"
        return "#95A5A6"

    def _build_health_strip_widget(self, minute_bars: List[bool]) -> QWidget:
        strip = QWidget()
        row = QHBoxLayout(strip)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        total = 60
        # 未产生历史记录的分钟显示为灰色；仅真实异常分钟显示红色
        padded: List[Any] = ([None] * max(0, total - len(minute_bars))) + minute_bars[-total:]
        for ok in padded:
            bar = QFrame(strip)
            bar.setFixedSize(5, 14)
            if ok is True:
                bar.setStyleSheet("background: #2ECC71; border-radius: 2px;")
            elif ok is False:
                bar.setStyleSheet("background: #E74C3C; border-radius: 2px;")
            else:
                bar.setStyleSheet("background: #DDE2E6; border-radius: 2px;")
            row.addWidget(bar)
        row.addStretch()
        return strip

    def _compact_source_label(self, url: str, source_name: str) -> str:
        low = (url or "").lower()
        if "api.p2pquake.net" in low:
            return "P2PQuake"
        if "ws-api.wolfx.jp/all_eew" in low:
            return "Wolfx all"
        if "ws-api.wolfx.jp/cwa_eew" in low:
            return "Wolfx cwa"
        if "ws.fanstudio.tech/all" in low:
            return "Fan Studio"
        if "ws.fanstudio.tech/cenc-ir" in low:
            return "Fan Studio Cenc-IR"
        return source_name or url

    def _compute_health_percent(self, connection_state: str, heartbeat_state: str, timeout_count: int, heartbeat_age: Any, timeout_threshold: float) -> float:
        if connection_state == "disconnected":
            return 0.0
        if connection_state == "connecting":
            return 50.0
        if connection_state != "connected":
            return 30.0
        base = 100.0
        if heartbeat_state == "timeout":
            base -= 35.0
        if timeout_count > 0:
            base -= min(25.0, timeout_count * 2.0)
        try:
            if heartbeat_age is not None and timeout_threshold > 0:
                age = float(heartbeat_age)
                ratio = max(0.0, min(1.0, age / timeout_threshold))
                # 心跳越新分越高
                base -= ratio * 8.0
        except Exception:
            pass
        return max(0.0, min(100.0, base))

    def _clear_status_cards(self):
        if not hasattr(self, "data_source_status_cards_layout"):
            return
        while self.data_source_status_cards_layout.count():
            item = self.data_source_status_cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _update_data_source_health_table(self):
        """刷新「数据源状态」页卡片列表。"""
        try:
            if not hasattr(self, "data_source_status_cards_layout") or self.data_source_status_cards_layout is None:
                return
            parent = self.parent()
            status_map: Dict[str, str] = {}
            health_map: Dict[str, Dict[str, Any]] = {}
            if parent is not None and hasattr(parent, "get_data_source_status"):
                status_map = parent.get_data_source_status() or {}
            if parent is not None and hasattr(parent, "get_data_source_health_snapshot"):
                health_map = parent.get_data_source_health_snapshot() or {}

            urls = sorted(set(list(status_map.keys()) + list(health_map.keys())))
            self._clear_status_cards()
            if not urls:
                empty_label = QLabel("暂无可展示的数据源状态")
                empty_label.setStyleSheet("font-size: 15px; color: #8A8A8A; padding: 8px 0;")
                self.data_source_status_cards_layout.addWidget(empty_label)
                return

            for url in urls:
                health = health_map.get(url, {})
                source_name = self.config.get_source_name(url) or url
                compact_name = self._compact_source_label(url, source_name)
                connection_state = health.get("connection_state") or status_map.get(url, "unconnected")
                heartbeat_state = health.get("heartbeat_state", "unknown")

                status_text = self._status_chip_text(connection_state, heartbeat_state)
                status_color = self._status_chip_color(connection_state, heartbeat_state)
                is_ok = connection_state == "connected" and heartbeat_state != "timeout"
                minute_key = datetime.datetime.now().strftime("%Y%m%d%H%M")
                if self._status_last_minute_key.get(url) != minute_key:
                    history = self._status_minute_bars.setdefault(url, [])
                    history.append(bool(is_ok))
                    if len(history) > 60:
                        del history[:-60]
                    self._status_last_minute_key[url] = minute_key
                history = self._status_minute_bars.get(url, [])

                card = QFrame()
                card.setStyleSheet("QFrame { background: white; border: 1px solid #ECECEC; border-radius: 8px; }")
                card_layout = QVBoxLayout(card)
                card_layout.setContentsMargins(10, 8, 10, 8)
                card_layout.setSpacing(6)

                top_row = QHBoxLayout()
                left_title = QLabel(compact_name)
                left_title.setStyleSheet("font-size: 14px; color: #2F2F2F; font-weight: bold;")
                top_row.addWidget(left_title)
                top_row.addStretch()
                right_status = QLabel(f"状态：{status_text}")
                right_status.setStyleSheet(f"font-size: 13px; color: {status_color};")
                top_row.addWidget(right_status)
                card_layout.addLayout(top_row)
                card_layout.addWidget(self._build_health_strip_widget(history))

                self.data_source_status_cards_layout.addWidget(card)

            self.data_source_status_cards_layout.addStretch()
        except Exception as e:
            logger.debug(f"更新数据源健康状态失败: {e}")
    
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
            exe_path = get_executable_path()
            if getattr(sys, 'frozen', False):
                # 打包后的 exe：先退出，再由批处理延迟启动新进程，避免与当前进程共用解压目录
                args = sys.argv[1:]
                try:
                    import tempfile
                    fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="restart_")
                    os.close(fd)
                    # Windows 下 cmd 按系统 ANSI(如 GBK) 解析 .bat，用 gbk 写入以便中文路径正确
                    bat_encoding = "gbk" if os.name == "nt" else "utf-8"
                    exe_dir = os.path.dirname(exe_path)
                    with open(bat_path, "w", encoding=bat_encoding) as f:
                        f.write("@echo off\n")
                        f.write("ping 127.0.0.1 -n 3 > nul\n")  # 约 2 秒延迟
                        # 先切换到 exe 所在目录再启动，便于 onedir 下新进程正确找到同目录的 python313.dll 等
                        f.write(f'cd /d "{exe_dir}"\n')
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
                    exe_dir = os.path.dirname(exe_path)
                    def _delayed_start():
                        try:
                            subprocess.Popen(
                                [exe_path] + sys.argv[1:],
                                cwd=exe_dir if exe_dir else None,
                            )
                        except Exception as e2:
                            logger.error(f"延迟启动失败: {e2}")
                        QApplication.instance().quit()
                    QTimer.singleShot(2500, _delayed_start)
                    return
                QApplication.instance().quit()
                return
            # Python 脚本：直接启动新进程并退出（解释器用 sys.executable，脚本用 exe_path 即 argv[0]）
            subprocess.Popen([sys.executable, exe_path] + sys.argv[1:])
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
            msg.setText("数据源已恢复为默认选中（日本气象厅地震情报、日本气象厅海啸预报）。点击「保存」将保存并重启软件。")
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
            advanced_saved = False
            if hasattr(self, 'advanced_vars'):
                advanced_required = (
                    'fix_radio', 'baidu_radio', 'output_file_checkbox', 'clear_log_checkbox',
                    'split_date_checkbox', 'log_size_spinbox', 'custom_url_entry',
                    'baidu_app_id_entry', 'baidu_secret_entry',
                )
                if all(k in self.advanced_vars for k in advanced_required):
                    advanced_saved = self._save_advanced_settings(
                        self.advanced_vars['fix_radio'],
                        self.advanced_vars['baidu_radio'],
                        self.advanced_vars['output_file_checkbox'],
                        self.advanced_vars['clear_log_checkbox'],
                        self.advanced_vars['split_date_checkbox'],
                        self.advanced_vars['log_size_spinbox'],
                        self.advanced_vars['custom_url_entry'],
                        self.advanced_vars['baidu_app_id_entry'],
                        self.advanced_vars['baidu_secret_entry'],
                        show_message=False,
                    )
                else:
                    logger.warning("高级设置未就绪，请先打开「高级」标签页")
            if advanced_saved:
                msg = QMessageBox(self)
                msg.setWindowTitle("成功")
                msg.setText("所有设置已保存。\n数据源与高级设置需重启程序后生效。")
                msg.setIcon(QMessageBox.Information)
                cancel_btn = msg.addButton("取消", QMessageBox.RejectRole)
                restart_btn = msg.addButton("重启", QMessageBox.AcceptRole)
                msg.exec_()
                if msg.clickedButton() == restart_btn:
                    logger.debug("用户选择重启，正在重启软件...")
                    self._restart_application()
            else:
                QMessageBox.information(
                    self, "成功",
                    "所有设置已保存！\n数据源与高级设置需要重启程序才能生效。"
                )
        except Exception as e:
            logger.error(f"保存设置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")

    def _on_auto_update_check_clicked(self):
        try:
            from utils.app_update_check import run_interactive_update_check
            if run_interactive_update_check(self, self.config):
                os._exit(0)
        except Exception as e:
            logger.error(f"检查更新失败: {e}")
            QMessageBox.critical(self, "错误", str(e))
    
    def _save_data_source_settings(self, silent_restart=False):
        """保存数据源设置。silent_restart=True 时不弹「已保存」提示，直接重启。"""
        try:
            # 更新基础URL
            self._update_base_urls()
            
            all_url = self.all_source_url
            
            if hasattr(self, "fanstudio_all_connect_cb"):
                self.config.enabled_sources[all_url] = self.fanstudio_all_connect_cb.isChecked()
            
            # Fan Studio All：保留旧总开关配置字段（若无对应控件则保持原值），主要用于兼容旧逻辑
            # 当前公开版 UI 不再暴露这两个复选框。
            # Fan Studio All：细粒度子源解析开关
            for attr, cfg_name in [
                ('fanstudio_parse_cea_cb', 'fanstudio_parse_cea'),
                ('fanstudio_parse_cea_pr_cb', 'fanstudio_parse_cea_pr'),
                ('fanstudio_parse_cwa_eew_cb', 'fanstudio_parse_cwa_eew'),
                ('fanstudio_parse_jma_cb', 'fanstudio_parse_jma'),
                ('fanstudio_parse_sa_cb', 'fanstudio_parse_sa'),
                ('fanstudio_parse_kma_eew_cb', 'fanstudio_parse_kma_eew'),
                ('fanstudio_parse_cenc_cb', 'fanstudio_parse_cenc'),
                ('fanstudio_parse_ningxia_cb', 'fanstudio_parse_ningxia'),
                ('fanstudio_parse_guangxi_cb', 'fanstudio_parse_guangxi'),
                ('fanstudio_parse_shanxi_cb', 'fanstudio_parse_shanxi'),
                ('fanstudio_parse_beijing_cb', 'fanstudio_parse_beijing'),
                ('fanstudio_parse_yunnan_cb', 'fanstudio_parse_yunnan'),
                ('fanstudio_parse_cwa_cb', 'fanstudio_parse_cwa'),
                ('fanstudio_parse_hko_cb', 'fanstudio_parse_hko'),
                ('fanstudio_parse_usgs_cb', 'fanstudio_parse_usgs'),
                ('fanstudio_parse_emsc_cb', 'fanstudio_parse_emsc'),
                ('fanstudio_parse_bcsf_cb', 'fanstudio_parse_bcsf'),
                ('fanstudio_parse_gfz_cb', 'fanstudio_parse_gfz'),
                ('fanstudio_parse_usp_cb', 'fanstudio_parse_usp'),
                ('fanstudio_parse_kma_cb', 'fanstudio_parse_kma'),
                ('fanstudio_parse_fssn_cb', 'fanstudio_parse_fssn'),
                ('fanstudio_parse_fssn_cmt_cb', 'fanstudio_parse_fssn_cmt'),
                ('fanstudio_parse_weatheralarm_cb', 'fanstudio_parse_weatheralarm'),
                ('fanstudio_parse_tsunami_cb', 'fanstudio_parse_tsunami'),
            ]:
                cb = getattr(self, attr, None)
                if cb is not None:
                    setattr(self.config.message_config, cfg_name, cb.isChecked())
            # Wolfx All：勾选则解析对应子源
            if hasattr(self, 'ali_all_parse_nied_cb'):
                self.config.message_config.ali_all_parse_nied = self.ali_all_parse_nied_cb.isChecked()
            if hasattr(self, 'ali_all_parse_early_est_cb'):
                self.config.message_config.ali_all_parse_early_est = self.ali_all_parse_early_est_cb.isChecked()
            if hasattr(self, 'ali_all_parse_jma_volcano_cb'):
                self.config.message_config.ali_all_parse_jma_volcano = self.ali_all_parse_jma_volcano_cb.isChecked()
            if hasattr(self, 'ali_all_parse_bmkg_cb'):
                self.config.message_config.ali_all_parse_bmkg = self.ali_all_parse_bmkg_cb.isChecked()
            if hasattr(self, 'ali_all_parse_cq_eew_cb'):
                self.config.message_config.ali_all_parse_cq_eew = self.ali_all_parse_cq_eew_cb.isChecked()
            if hasattr(self, 'p2pquake_parse_551_cb'):
                self.config.message_config.p2pquake_parse_551 = self.p2pquake_parse_551_cb.isChecked()
            if hasattr(self, 'p2pquake_parse_552_cb'):
                self.config.message_config.p2pquake_parse_552 = self.p2pquake_parse_552_cb.isChecked()

            # P2PQuake 仅使用 WSS + 启动时 HTTP 聚合拉取（内部固定 URL），不启用 HTTP 轮询
            # 更新其他数据源配置（NIED、P2PQuake WSS 等）
            for url, checkbox in self.source_vars.items():
                if url and url != all_url:
                    self.config.enabled_sources[url] = checkbox.isChecked()
            p2pquake_wss_url = P2PQUAKE_WSS_URL
            if hasattr(self, "p2pquake_connect_cb"):
                p2p_master = self.p2pquake_connect_cb.isChecked()
                self.config.enabled_sources[p2pquake_wss_url] = p2p_master
                for http_u in P2PQUAKE_HTTP_SOURCE_KEYS:
                    self.config.enabled_sources[http_u] = p2p_master
            if hasattr(self, "wolfx_all_connect_cb"):
                self.config.enabled_sources["wss://ws-api.wolfx.jp/all_eew"] = (
                    self.wolfx_all_connect_cb.isChecked()
                )
            removed_ws = self.config._enforce_public_ws_sources()
            if removed_ws:
                logger.info(f"设置保存时已移除非公开 WebSocket 数据源: {removed_ws}")
            
            # 按固定顺序构建 ws_urls，确保轮播数据源顺序不变
            self.config.ws_urls = self.config._build_ws_urls_ordered()
            logger.info(f"已更新ws_urls，包含{len(self.config.ws_urls)}个WebSocket数据源: {self.config.ws_urls}")
            
            # 地震速报 / 自定义文本 二选一
            self.config.message_config.use_custom_text = self.radio_custom_text.isChecked()

            for url, spin in self.http_poll_spinboxes.items():
                self.config.http_poll_intervals[url] = max(1, int(spin.value()))
            if hasattr(self, "custom_http_poll_spinbox"):
                self.config.http_poll_intervals["__custom_http__"] = max(
                    1, int(self.custom_http_poll_spinbox.value())
                )
            self.config._ensure_http_poll_interval_defaults()
            
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
            required = ('timezone', 'speed', 'font_size', 'font_family', 'font_bold', 'font_italic', 'width', 'height', 'opacity', 'vsync_enabled', 'target_fps', 'watermark_text', 'watermark_font_family', 'watermark_font_auto', 'watermark_font_size', 'watermark_position')
            if not all(k in self.display_vars for k in required):
                logger.warning("显示设置未就绪，请先打开「外观与显示」页")
                return
            old_timezone = getattr(self.config.gui_config, 'timezone', 'Asia/Shanghai')
            new_timezone = self.display_vars['timezone'].currentData()
            if new_timezone is None:
                display_text = self.display_vars['timezone'].currentText().strip()
                from utils.timezone_names_zh import get_tz_options
                for disp, iana_id in get_tz_options():
                    if disp == display_text:
                        new_timezone = iana_id
                        break
                else:
                    new_timezone = old_timezone
            timezone_changed = (old_timezone != new_timezone)
            
            # 更新GUI配置
            self.config.gui_config.text_speed = self.display_vars['speed'].value() / 10.0
            self.config.gui_config.font_size = self.display_vars['font_size'].currentData()
            self.config.gui_config.font_family = (
                self.display_vars['font_family'].currentData()
                or self.display_vars['font_family'].currentText()
            )
            self.config.gui_config.font_bold = self.display_vars['font_bold'].isChecked()
            self.config.gui_config.font_italic = self.display_vars['font_italic'].isChecked()
            self.config.gui_config.window_width = self.display_vars['width'].value()
            self.config.gui_config.window_height = self.display_vars['height'].value()
            self.config.gui_config.opacity = self.display_vars['opacity'].value() / 10.0
            self.config.gui_config.vsync_enabled = self.display_vars['vsync_enabled'].isChecked()
            self.config.gui_config.target_fps = self.display_vars['target_fps'].value()
            self.config.gui_config.timezone = new_timezone
            self.config.gui_config.watermark_text = (self.display_vars['watermark_text'].text() or '').strip()
            wm_ff_widget = self.display_vars.get('watermark_font_family')
            if wm_ff_widget is not None:
                ff = wm_ff_widget.currentData() or wm_ff_widget.currentText() or ""
                self.config.gui_config.watermark_font_family = (ff or "").strip() if isinstance(ff, str) else ""
            wm_auto_widget = self.display_vars.get('watermark_font_auto')
            wm_size_widget = self.display_vars.get('watermark_font_size')
            if wm_auto_widget is not None and wm_size_widget is not None:
                if wm_auto_widget.isChecked():
                    self.config.gui_config.watermark_font_size = 0
                else:
                    self.config.gui_config.watermark_font_size = max(8, wm_size_widget.value())
            wm_pos_widget = self.display_vars.get('watermark_position')
            if wm_pos_widget is not None:
                pos = wm_pos_widget.currentData() or 'diagonal'
                self.config.gui_config.watermark_position = pos
                self.config.gui_config.watermark_angle = "45" if pos == "diagonal" else "horizontal"
            if 'always_on_top' in self.display_vars:
                self.config.gui_config.always_on_top = self.display_vars['always_on_top'].isChecked()

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
            render_required = ('cpu_radio', 'opengl_radio')
            if not all(k in self.render_vars for k in render_required):
                logger.warning("渲染设置未就绪，请先打开「外观与显示」页")
                return
            if self.render_vars['opengl_radio'].isChecked():
                new_backend = "opengl"
            else:
                new_backend = "cpu"
            self.config.gui_config.render_backend = new_backend
            self.config.gui_config.use_gpu_rendering = (new_backend != "cpu")
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
                self._restart_application()
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

    def _on_custom_text_return_after_warning_toggled(self, checked: bool, minutes_spin):
        """勾选「预警后限时显示速报再回自定义（beta版）」时弹出二次确认；取消则恢复未勾选。"""
        minutes_spin.setEnabled(checked)
        if not checked:
            return
        warning_text = (
            "功能仅为 Beta 测试版本，仅供测试与评估使用，不建议在直播场景中使用；"
            "开发者不提供任何明示或默示的适用性、稳定性保证，由此产生的一切后果及相关责任均由用户自行承担！"
        )
        msg = QMessageBox(self)
        msg.setWindowTitle("请确认")
        msg.setTextFormat(Qt.RichText)
        msg.setText(
            f'<p style="font-weight: bold; color: #000000;">{warning_text}</p>'
        )
        msg.setIcon(QMessageBox.Warning)
        confirm_btn = msg.addButton("确认", QMessageBox.AcceptRole)
        cancel_btn = msg.addButton("取消", QMessageBox.RejectRole)
        msg.setDefaultButton(cancel_btn)
        msg.exec_()
        if msg.clickedButton() != confirm_btn:
            self.custom_text_return_after_warning_checkbox.blockSignals(True)
            self.custom_text_return_after_warning_checkbox.setChecked(False)
            self.custom_text_return_after_warning_checkbox.blockSignals(False)
            minutes_spin.setEnabled(False)
    
    def _save_appearance_settings(self):
        """保存「外观与显示」页全部设置（显示、渲染、颜色、自定义文本），统一提示是否需重启。"""
        try:
            display_required = ('timezone', 'speed', 'font_size', 'font_family', 'font_bold', 'font_italic', 'width', 'height', 'opacity', 'vsync_enabled', 'target_fps', 'watermark_text', 'watermark_font_family', 'watermark_font_auto', 'watermark_font_size', 'watermark_position', 'auto_update_check_on_startup', 'warning_min_display_seconds', 'custom_text_return_seconds')
            render_required = ('cpu_radio', 'opengl_radio')
            if not all(k in self.display_vars for k in display_required) or not all(k in self.render_vars for k in render_required):
                logger.warning("外观与显示设置未就绪，请先打开「外观与显示」页")
                return
            old_timezone = getattr(self.config.gui_config, 'timezone', 'Asia/Shanghai')
            new_timezone = self.display_vars['timezone'].currentData()
            if new_timezone is None:
                display_text = self.display_vars['timezone'].currentText().strip()
                from utils.timezone_names_zh import get_tz_options
                for disp, iana_id in get_tz_options():
                    if disp == display_text:
                        new_timezone = iana_id
                        break
                else:
                    new_timezone = old_timezone
            timezone_changed = (old_timezone != new_timezone)
            old_backend = getattr(self.config.gui_config, 'render_backend', None) or ("opengl" if self.config.gui_config.use_gpu_rendering else "cpu")
            if self.render_vars['opengl_radio'].isChecked():
                new_backend = "opengl"
            else:
                new_backend = "cpu"
            render_changed = (old_backend != new_backend)
            
            # 写入 gui_config（显示 + 渲染）
            self.config.gui_config.text_speed = self.display_vars['speed'].value() / 10.0
            self.config.gui_config.font_size = self.display_vars['font_size'].currentData()
            self.config.gui_config.font_family = (
                self.display_vars['font_family'].currentData()
                or self.display_vars['font_family'].currentText()
            )
            self.config.gui_config.font_bold = self.display_vars['font_bold'].isChecked()
            self.config.gui_config.font_italic = self.display_vars['font_italic'].isChecked()
            self.config.gui_config.window_width = self.display_vars['width'].value()
            self.config.gui_config.window_height = self.display_vars['height'].value()
            self.config.gui_config.opacity = self.display_vars['opacity'].value() / 10.0
            self.config.gui_config.vsync_enabled = self.display_vars['vsync_enabled'].isChecked()
            self.config.gui_config.target_fps = self.display_vars['target_fps'].value()
            self.config.gui_config.timezone = new_timezone
            self.config.gui_config.always_on_top = self.display_vars['always_on_top'].isChecked() if 'always_on_top' in self.display_vars else False
            self.config.gui_config.auto_update_check_on_startup = self.display_vars['auto_update_check_on_startup'].isChecked()
            self.config.gui_config.watermark_text = (self.display_vars['watermark_text'].text() or "").strip()
            wm_ff_widget = self.display_vars.get('watermark_font_family')
            if wm_ff_widget is not None:
                ff = wm_ff_widget.currentData() or wm_ff_widget.currentText() or ""
                self.config.gui_config.watermark_font_family = (ff or "").strip() if isinstance(ff, str) else ""
            wm_auto_widget = self.display_vars.get('watermark_font_auto')
            wm_size_widget = self.display_vars.get('watermark_font_size')
            if wm_auto_widget is not None and wm_size_widget is not None:
                if wm_auto_widget.isChecked():
                    self.config.gui_config.watermark_font_size = 0
                else:
                    self.config.gui_config.watermark_font_size = max(8, wm_size_widget.value())
            wm_pos_widget = self.display_vars.get('watermark_position')
            if wm_pos_widget is not None:
                pos = wm_pos_widget.currentData() or 'diagonal'
                self.config.gui_config.watermark_position = pos
                self.config.gui_config.watermark_angle = "45" if pos == "diagonal" else "horizontal"
            self.config.gui_config.render_backend = new_backend
            self.config.gui_config.use_gpu_rendering = (new_backend != "cpu")

            # 写入 message_config（颜色 + 自定义文本 + 预警/消息更新）
            self.config.message_config.report_color = self.current_report_color
            self.config.message_config.warning_color = self.current_warning_color
            self.config.message_config.custom_text_color = self.current_custom_text_color
            self.config.message_config.custom_text = self.custom_text_edit.toPlainText().strip() or ""
            self.config.message_config.show_one_alert_per_received = self.show_one_alert_per_received_checkbox.isChecked()
            self.config.message_config.force_single_line = self.force_single_line_checkbox.isChecked()
            self.config.message_config.custom_text_return_after_warning = self.custom_text_return_after_warning_checkbox.isChecked()
            cb_exp = getattr(self, "disable_warning_expiry_test_cb", None)
            if cb_exp is not None:
                self.config.message_config.disable_warning_expiry_for_test = (
                    cb_exp.isChecked()
                )
            wm_min_spin = self.display_vars.get('warning_min_display_seconds')
            if wm_min_spin is not None:
                self.config.message_config.warning_min_display_seconds = max(60, wm_min_spin.value() * 60)
            ct_min_spin = self.display_vars.get('custom_text_return_seconds')
            if ct_min_spin is not None:
                self.config.message_config.custom_text_return_seconds = max(60, min(3600, ct_min_spin.value() * 60))

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
                    self._restart_application()
            else:
                QMessageBox.information(self, "成功", "外观与显示设置已保存！\n设置已立即生效，无需重启程序。")
            logger.debug("外观与显示设置已保存")
        except Exception as e:
            logger.error(f"保存外观与显示设置失败: {e}")
            QMessageBox.critical(self, "错误", f"保存设置失败: {e}")
    
    def update_weather_image(self, weather_data: Dict[str, Any]):
        """
        更新气象预警图片显示（已移除，不再在设置页面显示）
        
        Args:
            weather_data: 气象预警数据字典
        """
        # 不再在设置页面显示气象预警图片
        pass
