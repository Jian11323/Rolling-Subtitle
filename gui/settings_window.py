#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设置窗口模块
负责显示和修改程序设置
使用PyQt5实现
"""

from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QTabBar, QLabel, QPushButton, QCheckBox, QSlider, QSpinBox, QDoubleSpinBox,
    QLineEdit, QScrollArea, QMessageBox, QFrame, QColorDialog,
    QRadioButton, QButtonGroup, QPlainTextEdit, QComboBox, QGroupBox,
    QSizePolicy, QStyle, QShortcut, QFileDialog, QAbstractButton,
)
from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QTimer, QThread, QObject, QSize
from PyQt5.QtGui import QFont, QDesktopServices, QColor, QFontDatabase, QKeySequence, QFontMetrics, QPixmap, QPalette
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
    P2PQUAKE_WSS_URL,
    p2pquake_master_enabled,
    FANSTUDIO_ALL_URL,
    FANSTUDIO_TYPHOON_HTTP,
    JIAN_SUB_SOURCE_SPECS,
    JIAN_SHORT_TO_PARSE_FLAG,
    JIAN_MASTER_KEY,
    WOLFX_MASTER_KEY,
    WHEWS_MASTER_KEY,
    AUX_SOURCES_MASTER_KEY,
    WHEWS_WS_URLS,
    WHEWS_HOST_PRIMARY,
    WHEWS_HOST_BACKUP,
    DATA_PROVIDER_FANSTUDIO,
    DATA_PROVIDER_WHEWS,
    DATA_PROVIDER_JIAN,
    normalize_data_provider,
    wolfx_master_enabled,
    aux_sources_enabled,
    normalize_whews_host,
    is_whews_url,
    is_whews_dedicated_endpoint,
    WOLFX_ALL_EEW_URL,
    WOLFX_CWA_EEW_URL,
    WOLFX_CENC_EQLIST_URL,
    WOLFX_JMA_EQLIST_URL,
    NOWQUAKE_CENCINT_WSS_URL,
    EQSC_HTTP_MASTER,
    EQSC_HTTP_SOURCE_KEYS,
    EQSC_WS_URL,
    OPENQUAKE_WS_ALL_URL,
    openquake_master_enabled,
    enforce_weather_source_mutex,
    enforce_jma_report_mutex,
    MAIN_JMA_REPORT_PARSE_FLAGS,
    P2P_JMA_REPORT_PARSE_FLAG,
    WEATHER_SOURCE_FLAGS,
    DEFAULT_HTTP_POLL_INTERVALS,
)
from utils.logger import get_logger
from utils.resource_path import get_executable_path, get_resource_path
from utils.performance_presets import (
    PERFORMANCE_MODE_CUSTOM,
    PERFORMANCE_MODE_EXTREME,
    PERFORMANCE_MODE_MEDIUM,
    PERFORMANCE_MODE_LABELS,
    PERFORMANCE_MODES,
    performance_mode_budget_hint,
)
from .color_manager import Color48Picker
from .image_crop_dialog import ImageCropDialog
from .settings_auth_mixin import SettingsAuthMixin
from .qt_light_theme import (
    apply_light_palette,
    light_dialog_stylesheet,
    LIGHT_SCROLLBAR_QSS,
    show_info,
    show_warning,
    show_critical,
    styled_message_box,
)

logger = get_logger()

P2PQUAKE_WSS_URL = "wss://api.p2pquake.net/v2/ws"

# 设置页设计令牌（石色页底 + 同色调卡片，避免纯白块）
COLOR_PAGE_BG = "#F3F1ED"
COLOR_CARD_BG = "#F7F5F1"  # 略亮于页底，不再用 #FFFFFF
COLOR_INPUT_BG = "#FFFEFC"  # 输入框略提亮，便于辨认可编辑区
COLOR_TEXT = "#1F2937"
COLOR_TEXT_SECONDARY = "#6B7280"
COLOR_BORDER = "#E5E2DC"
COLOR_ACCENT = "#3B82F6"
COLOR_ACCENT_HOVER = "#2563EB"
COLOR_ACCENT_PRESSED = "#1D4ED8"
COLOR_LINK = "#3B82F6"

MARGIN_TAB = 14
SPACING_TAB = 12
SPACING_BLOCK = 12
GROUP_MARGINS = (14, 12, 14, 12)
GROUP_SPACING = 8

# 设置窗目标/最大宽度：单列表单，宁窄勿胖
SETTINGS_DEFAULT_WIDTH = 500
SETTINGS_MAX_WIDTH = 520
SETTINGS_MIN_WIDTH = 460


class _ContentWidthTabBar(QTabBar):
    """按标签文字实际像素宽度计宽，避免样式表低估中文导致挤叠或等宽虚高。"""

    PAD_H = 20  # 左右内边距合计（收紧，七标签更易一排放下）
    PAD_V = 14
    GAP = 4

    def tabSizeHint(self, index: int) -> QSize:
        fm = self.fontMetrics()
        text = self.tabText(index)
        try:
            text_w = fm.horizontalAdvance(text)
        except AttributeError:
            text_w = fm.width(text)
        # 选中态 font-weight:bold 会略增字宽，按字数预留
        bold_slack = max(2, len(text))
        w = text_w + self.PAD_H + self.GAP + bold_slack
        h = max(fm.height() + self.PAD_V, 32)
        base = super().tabSizeHint(index)
        return QSize(max(w, 36), max(h, base.height()))


class _FittingScrollArea(QScrollArea):
    """设置页滚动区：内容宽度跟随视口，且不把超宽 sizeHint 回传给对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        _set_widget_style(self, 
            f"QScrollArea {{ background-color: {COLOR_PAGE_BG}; border: none; }}"
        )
        vp = self.viewport()
        apply_light_palette(vp, COLOR_PAGE_BG, COLOR_TEXT)
        _set_widget_style(vp, f"background-color: {COLOR_PAGE_BG};")

    def sizeHint(self) -> QSize:
        # 不要用内部控件的理想宽度（长标签/令牌框会把设置窗撑到接近全屏）
        return QSize(SETTINGS_DEFAULT_WIDTH - 48, 480)

    def minimumSizeHint(self) -> QSize:
        return QSize(280, 200)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        body = self.widget()
        if body is None:
            return
        vw = self.viewport().width()
        if vw > 0:
            body.setMaximumWidth(vw)
            body.setMinimumWidth(0)


def _prepare_scroll_body(body: QWidget) -> None:
    """允许滚动内容在窄窗口下压缩，而不是撑破右侧。"""
    body.setMinimumWidth(0)
    body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    # 必须用 #id 限定，裸 background-color 会渗到卡片内 Label/CheckBox 形成灰底纹
    body.setObjectName("settingsScrollBody")
    body.setAttribute(Qt.WA_StyledBackground, True)
    apply_light_palette(body, COLOR_PAGE_BG, COLOR_TEXT)
    _set_widget_style(body, f"#settingsScrollBody {{ background-color: {COLOR_PAGE_BG}; }}")


def _prep_groupbox(group: QGroupBox) -> QGroupBox:
    """石色卡片 GroupBox：实色底避免主窗口黑底渗入（不用纯白）。"""
    group.setAttribute(Qt.WA_StyledBackground, True)
    apply_light_palette(group, COLOR_CARD_BG, COLOR_TEXT)
    _set_widget_style(group, STYLE_GROUPBOX)
    return group


def _prep_card_block(block: Optional[QWidget] = None) -> QWidget:
    """卡片内中间层：与卡片同色 + 浅色调色板。"""
    if block is None:
        block = QWidget()
    block.setAttribute(Qt.WA_StyledBackground, True)
    apply_light_palette(block, COLOR_CARD_BG, COLOR_TEXT)
    _set_widget_style(block, STYLE_INNER_BLOCK)
    return block


def _apply_group_layout(layout) -> None:
    """统一 GroupBox 内边距与间距。"""
    layout.setContentsMargins(*GROUP_MARGINS)
    layout.setSpacing(GROUP_SPACING)


def _make_settings_tab_shell():
    """创建设置页通用滚动壳，返回 (scroll_area, body, main_layout)。"""
    scroll_area = _FittingScrollArea()
    body = QWidget()
    _prepare_scroll_body(body)
    main_layout = QVBoxLayout(body)
    main_layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
    main_layout.setSpacing(SPACING_TAB)
    return scroll_area, body, main_layout


def _add_tab_save_row(main_layout, on_save) -> None:
    """在设置页底部加入居中「保存」按钮。"""
    button_frame = QWidget()
    button_layout = QHBoxLayout(button_frame)
    button_layout.setContentsMargins(0, 6, 0, 0)
    button_layout.addStretch()
    save_btn = QPushButton("保存")
    save_btn.setMinimumWidth(120)
    save_btn.setMinimumHeight(36)
    _set_widget_style(save_btn, STYLE_SAVE_BTN)
    save_btn.clicked.connect(on_save)
    button_layout.addWidget(save_btn)
    button_layout.addStretch()
    main_layout.addWidget(button_frame)


# 卡片内中间层：实色（透明会透出主窗口黑底）
STYLE_INNER_BLOCK = f"background-color: {COLOR_CARD_BG};"

STYLE_CLEAR_CHILD_BG = f"""
    QLabel, QCheckBox, QRadioButton, QSlider {{
        background-color: transparent;
    }}
    QTabWidget, QTabBar {{
        background-color: {COLOR_PAGE_BG};
    }}
"""

# 顶栏：下划线选中；宽度由 _ContentWidthTabBar 按字数计算
STYLE_TAB_WIDGET = f"""
    QTabWidget::pane {{
        border: none;
        border-top: 1px solid {COLOR_BORDER};
        background: {COLOR_PAGE_BG};
        top: 0px;
        margin-top: 0px;
        padding-top: 4px;
    }}
    QTabBar {{
        background: {COLOR_PAGE_BG};
        qproperty-drawBase: 0;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {COLOR_TEXT_SECONDARY};
        padding: 7px 8px 6px 8px;
        margin-right: 2px;
        border: none;
        border-bottom: 3px solid transparent;
        font-size: 14px;
    }}
    QTabBar::tab:selected {{
        background: transparent;
        color: {COLOR_TEXT};
        font-weight: bold;
        border-bottom: 3px solid {COLOR_ACCENT};
    }}
    QTabBar::tab:hover:!selected {{
        background: #EAE7E1;
        color: {COLOR_TEXT};
        border-bottom: 3px solid #D4D0C8;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
    }}
    QTabBar::scroller {{
        width: 24px;
    }}
    QTabBar QToolButton {{
        background: #EAE7E1;
        border: 1px solid {COLOR_BORDER};
        border-radius: 4px;
        margin: 2px 0;
        padding: 0;
    }}
    QTabBar QToolButton:hover {{
        background: #E0DCD4;
    }}
"""

STYLE_SECTION_TITLE = f"font-weight: bold; font-size: 19px; color: {COLOR_TEXT}; margin-bottom: 4px; background: transparent;"
STYLE_CARD_SUBHEAD = f"font-weight: bold; font-size: 17px; color: {COLOR_TEXT}; margin-top: 6px; margin-bottom: 2px; background: transparent;"
STYLE_LABEL = f"font-size: 17px; color: {COLOR_TEXT}; line-height: 24px; background: transparent;"
STYLE_HINT = f"font-size: 15px; color: {COLOR_TEXT_SECONDARY}; line-height: 22px; background: transparent;"
STYLE_VALUE = f"font-size: 17px; color: {COLOR_TEXT}; min-width: 40px; background: transparent;"
STYLE_CHECKBOX = f"font-size: 17px; color: {COLOR_TEXT}; spacing: 8px; background: transparent;"
STYLE_CHECKBOX_SOURCE = f"font-size: 17px; line-height: 24px; padding: 2px 0; spacing: 8px; background: transparent;"
STYLE_CHECKBOX_LOG = f"font-size: 17px; padding: 2px 0; spacing: 8px; background: transparent;"
STYLE_CHECKBOX_SMALL = f"font-size: 16px; color: {COLOR_TEXT}; spacing: 8px; background: transparent;"
STYLE_RADIO = f"font-size: 17px; color: {COLOR_TEXT}; spacing: 8px; background: transparent;"
STYLE_SLIDER = f"""
    QSlider::groove:horizontal {{
        border: none;
        height: 6px;
        background: {COLOR_BORDER};
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {COLOR_ACCENT};
        border: none;
        width: 16px;
        height: 16px;
        margin: -5px 0;
        border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{ background: {COLOR_ACCENT_HOVER}; }}
"""
STYLE_SPINBOX = f"""
    QSpinBox, QDoubleSpinBox {{
        padding: 7px 10px;
        border: 1px solid {COLOR_BORDER};
        border-radius: 8px;
        font-size: 17px;
        background: {COLOR_INPUT_BG};
        color: {COLOR_TEXT};
        min-height: 28px;
    }}
    QSpinBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {COLOR_ACCENT}; }}
"""
STYLE_COMBOBOX = f"""
    QComboBox {{
        padding: 7px 28px 7px 10px;
        border: 1px solid {COLOR_BORDER};
        border-radius: 8px;
        font-size: 17px;
        min-height: 32px;
        background: {COLOR_INPUT_BG};
        color: {COLOR_TEXT};
    }}
    QComboBox:focus {{ border: 1px solid {COLOR_ACCENT}; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 24px;
        border: none;
    }}
    QComboBox QAbstractItemView {{
        border: 1px solid {COLOR_BORDER};
        background: {COLOR_INPUT_BG};
        outline: 0;
        font-size: 17px;
        padding: 2px;
        selection-background-color: {COLOR_ACCENT};
        selection-color: #FFFFFF;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 34px;
        padding: 6px 10px;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background: {COLOR_ACCENT};
        color: #FFFFFF;
    }}
"""
STYLE_LINEEDIT = (
    f"QLineEdit {{ padding: 7px 10px; border: 1px solid {COLOR_BORDER}; border-radius: 8px; "
    f"font-size: 17px; background: {COLOR_INPUT_BG}; color: {COLOR_TEXT}; min-height: 28px; }} "
    f"QLineEdit:focus {{ border: 1px solid {COLOR_ACCENT}; }}"
)
STYLE_PLAINTEXT = (
    f"QPlainTextEdit {{ padding: 8px; border: 1px solid {COLOR_BORDER}; border-radius: 8px; "
    f"font-size: 17px; background: {COLOR_INPUT_BG}; color: {COLOR_TEXT}; }} "
    f"QPlainTextEdit:focus {{ border: 1px solid {COLOR_ACCENT}; }}"
)
STYLE_GROUPBOX = (
    f"QGroupBox {{ font-weight: bold; font-size: 19px; color: {COLOR_TEXT}; "
    f"background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; "
    f"border-radius: 12px; margin-top: 18px; "
    f"padding-top: 20px; padding-bottom: 12px; }} "
    f"QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 10px; "
    f"color: {COLOR_TEXT}; background-color: {COLOR_CARD_BG}; }} "
    # GroupBox 本地 stylesheet 会切断父级样式；子容器须实色，否则露出主窗口黑底
    f"QGroupBox > QWidget {{ background-color: {COLOR_CARD_BG}; }} "
    f"QGroupBox QLabel {{ background-color: transparent; color: {COLOR_TEXT}; }} "
    f"QGroupBox QCheckBox, QGroupBox QRadioButton {{ background-color: transparent; color: {COLOR_TEXT}; }} "
    f"QGroupBox QSlider {{ background-color: transparent; }}"
)
STYLE_SOURCE_TITLE = f"font-weight: bold; font-size: 18px; color: {COLOR_TEXT}; background: transparent;"
STYLE_ABOUT_ITEM = f"font-size: 17px; color: {COLOR_TEXT_SECONDARY}; background: transparent;"
STYLE_STATUS_CONNECTED = "font-size: 15px; color: #15803D; font-weight: bold; background: transparent;"
STYLE_STATUS_DISCONNECTED = "font-size: 15px; color: #DC2626; font-weight: bold; background: transparent;"
STYLE_STATUS_NEUTRAL = f"font-size: 15px; color: {COLOR_TEXT_SECONDARY}; background: transparent;"
STYLE_PROVIDER_RADIO = f"font-size: 17px; font-weight: bold; color: {COLOR_TEXT}; padding: 6px 4px; spacing: 8px; background: transparent;"

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


# 构建期暂缓子控件 setStyleSheet，建完后一次性刷上，减少布局 polish
_PENDING_WIDGET_STYLES: List[Tuple[QWidget, str]] = []
_DEFER_WIDGET_STYLES = False


def _begin_defer_widget_styles() -> None:
    """开始暂缓控件样式表应用。"""
    global _DEFER_WIDGET_STYLES, _PENDING_WIDGET_STYLES
    _DEFER_WIDGET_STYLES = True
    _PENDING_WIDGET_STYLES = []


def _set_widget_style(widget: QWidget, style: str) -> None:
    """设置控件样式；若在暂缓期则先入队。"""
    if _DEFER_WIDGET_STYLES:
        _PENDING_WIDGET_STYLES.append((widget, style))
    else:
        widget.setStyleSheet(style)


def _flush_deferred_widget_styles() -> None:
    """应用暂缓期内积累的控件样式表。"""
    global _DEFER_WIDGET_STYLES, _PENDING_WIDGET_STYLES
    _DEFER_WIDGET_STYLES = False
    pending = _PENDING_WIDGET_STYLES
    _PENDING_WIDGET_STYLES = []
    for widget, style in pending:
        try:
            widget.setStyleSheet(style)
        except RuntimeError:
            pass


# 字体列表缓存：QFontDatabase.families() 很快，但逐字体 exactMatch 在 Windows 上可达数秒
_FONT_LIST_CACHE: Optional[List[Tuple[str, str]]] = None


def _get_deduplicated_font_list() -> List[Tuple[str, str]]:
    """返回 [(显示名, 实际字体族)]，每种字体一条；结果进程内缓存。

    不再对每个候选调用 exactMatch（Windows 上数百次可耗时 1s+）。
    优先使用与基名完全一致的族名，否则取最短候选（通常即主族名）。
    """
    global _FONT_LIST_CACHE
    if _FONT_LIST_CACHE is not None:
        return _FONT_LIST_CACHE
    db = QFontDatabase()
    families = db.families()
    base_to_candidates: Dict[str, List[str]] = {}
    for f in families:
        base = _font_base_name(f)
        if not base:
            continue
        base_to_candidates.setdefault(base, []).append(f)
    result: List[Tuple[str, str]] = []
    for base in sorted(base_to_candidates.keys()):
        candidates = base_to_candidates[base]
        if base in candidates:
            chosen = base
        else:
            # 最短名多为「正族」；同长度时保持原序稳定
            chosen = min(candidates, key=lambda n: (len(n), n))
        result.append((base, chosen))
    _FONT_LIST_CACHE = result
    return result


_SETTINGS_TEXT_ENGINE_WARMED = False


def prefetch_settings_assets() -> None:
    """在 GUI 线程预热设置页重资源：字体列表 + 首次中文 LineEdit 排版。

    Windows 上进程内第一次给 QLineEdit 设中文约 0.5–0.7s（DirectWrite/字体回退），
    放到空闲预热后，真正打开设置窗时不再卡在水印等输入框。
    """
    global _SETTINGS_TEXT_ENGINE_WARMED
    try:
        _get_deduplicated_font_list()
    except Exception as e:
        logger.debug(f"预热设置页字体列表失败（可忽略）: {e}")
    if _SETTINGS_TEXT_ENGINE_WARMED:
        return
    try:
        # 无离屏控件消化首次中文 setText / 带样式 LineEdit 排版
        warm = QLineEdit()
        warm.setStyleSheet(STYLE_LINEEDIT)
        warm.setText("预热")
        warm.deleteLater()
        _SETTINGS_TEXT_ENGINE_WARMED = True
    except Exception as e:
        logger.debug(f"预热设置页文本引擎失败（可忽略）: {e}")


STYLE_SAVE_BTN = f"""
    QPushButton {{
        background-color: {COLOR_ACCENT};
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 15px;
        font-weight: bold;
        padding: 6px 12px;
        min-height: 30px;
    }}
    QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
    QPushButton:pressed {{ background-color: {COLOR_ACCENT_PRESSED}; }}
"""
STYLE_SECONDARY_BTN = f"""
    QPushButton {{
        background-color: {COLOR_INPUT_BG};
        color: {COLOR_TEXT};
        border: 1px solid {COLOR_BORDER};
        border-radius: 8px;
        font-size: 15px;
        padding: 6px 10px;
        min-height: 30px;
    }}
    QPushButton:hover {{ background-color: #EAE7E1; border-color: {COLOR_ACCENT}; }}
    QPushButton:pressed {{ background-color: #E0DCD4; }}
"""
STYLE_CANCEL_BTN = f"""
    QPushButton {{
        background-color: #E8E4DE;
        color: {COLOR_TEXT};
        border: none;
        border-radius: 8px;
        font-size: 15px;
        padding: 6px 10px;
        min-height: 30px;
    }}
    QPushButton:hover {{ background-color: #DCD7CF; }}
    QPushButton:pressed {{ background-color: #D0CBC2; }}
"""
STYLE_SELECT_ALL_BTN = f"""
    QPushButton {{
        background-color: {COLOR_ACCENT};
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 15px;
        font-weight: bold;
        padding: 6px 12px;
        min-height: 30px;
    }}
    QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
    QPushButton:pressed {{ background-color: {COLOR_ACCENT_PRESSED}; }}
"""
STYLE_AUDIO_COMPACT_BTN = f"""
    QPushButton {{
        background-color: {COLOR_ACCENT};
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 15px;
        font-weight: bold;
        padding: 5px 10px;
        min-height: 30px;
    }}
    QPushButton:hover {{ background-color: {COLOR_ACCENT_HOVER}; }}
    QPushButton:pressed {{ background-color: {COLOR_ACCENT_PRESSED}; }}
"""
STYLE_AUDIO_FILE_BTN = f"""
    QPushButton {{
        background-color: {COLOR_INPUT_BG};
        color: {COLOR_TEXT};
        border: 1px solid {COLOR_BORDER};
        border-radius: 8px;
        font-size: 15px;
        padding: 5px 8px;
        min-height: 28px;
        text-align: left;
    }}
    QPushButton:hover {{ border: 1px solid {COLOR_ACCENT}; background-color: #F8FAFC; }}
    QPushButton:pressed {{ background-color: #EFF6FF; }}
"""

_AUDIO_TIER_SOUND = (
    ('tier_felt_cb', 'felt_sound_enabled'),
    ('tier_critical_cb', 'critical_sound_enabled'),
)
_AUDIO_TIER_TTS = (
    ('tier_report_cb', 'report_tts_enabled'),
    ('tier_weather_cb', 'weather_tts_enabled'),
    ('tier_tsunami_cb', 'tsunami_tts_enabled'),
)


class _WAuthLoginWorker(QObject):
    """后台执行 WeJet WAuth 浏览器登录，避免卡住设置窗口。"""

    finished = pyqtSignal(object)
    progress = pyqtSignal(str)

    def run(self) -> None:
        """执行浏览器登录流程。"""
        from utils.wauth_login import WAuthLoginResult, login_with_browser

        try:
            result = login_with_browser(
                timeout_seconds=180.0,
                on_status=lambda msg: self.progress.emit(str(msg or "")),
            )
        except Exception as e:
            result = WAuthLoginResult(False, f"登录失败：{e}")
        self.finished.emit(result)


class SettingsWindow(SettingsAuthMixin, QDialog):
    """设置窗口"""

    # 后台线程鉴权结果回主线程（勿在非 GUI 线程直接改控件）
    fanstudio_auth_test_finished = pyqtSignal(bool, str, str)
    eqsc_auth_test_finished = pyqtSignal(bool, str, str)

    def __init__(self, parent=None, *, defer_secondary_tabs: bool = False):
        """
        初始化设置窗口

        Args:
            parent: 父窗口
            defer_secondary_tabs: 若为 True，仅先建「外观」页，便于尽快 show；
                调用方应在首次绘制后调用 complete_secondary_tabs()。
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
        # url -> 可复用卡片控件（避免每 2s deleteLater + 重建）
        self._status_card_by_url: Dict[str, Dict[str, Any]] = {}
        self._status_cards_url_order: List[str] = []
        self._status_cards_empty_label: Optional[QLabel] = None
        self._status_cards_stretch_item = None
        self.individual_source_urls = []  # 存储所有单项数据源的URL
        self.fanstudio_source_urls = []  # 存储所有Fan Studio单项数据源的URL（不包括All源）
        self._updating_mutual_exclusion = False  # 防止回调循环的标志
        self._is_all_selected = False  # 标记当前是否处于全选状态
        # 初始化基础URL（必须在初始化列表之后调用，因为创建标签页时会使用这些列表）
        self._update_base_urls()

        # 设置UI（只在初始化时调用一次）
        self._settings_dirty = False
        self._fanstudio_auth_testing = False
        self._eqsc_auth_testing = False
        self._defer_secondary_tabs = bool(defer_secondary_tabs)
        self._secondary_tabs_ready = not self._defer_secondary_tabs
        self.auto_save_settings_cb = None
        self.fanstudio_auth_test_finished.connect(self._on_fanstudio_auth_test_finished)
        self.eqsc_auth_test_finished.connect(self._on_eqsc_auth_test_finished)
        self._setup_ui()
        if self._secondary_tabs_ready:
            self._wire_dirty_tracking()
        self._auto_save_running = False
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(800)
        self._auto_save_timer.timeout.connect(self._perform_auto_save)

    def _update_base_urls(self):
        """更新基础 URL（固定使用 Fan Studio /all）"""
        self.all_source_url = FANSTUDIO_ALL_URL

    def _apply_window_chrome(self) -> None:
        """应用设置窗调色板与样式表（宜在控件树建完后再调用，避免布局插入时反复 polish）。"""
        apply_light_palette(self, COLOR_PAGE_BG, COLOR_TEXT)
        pal = self.palette()
        card = QColor(COLOR_CARD_BG)
        input_bg = QColor(COLOR_INPUT_BG)
        pal.setColor(QPalette.Window, QColor(COLOR_PAGE_BG))
        pal.setColor(QPalette.Base, input_bg)
        pal.setColor(QPalette.AlternateBase, card)
        pal.setColor(QPalette.Button, card)
        pal.setColor(QPalette.Light, card)
        pal.setColor(QPalette.Midlight, card)
        self.setPalette(pal)
        self.setAttribute(Qt.WA_StyledBackground, True)
        _set_widget_style(self, 
            f"QDialog {{ background-color: {COLOR_PAGE_BG}; }}"
            + light_dialog_stylesheet(COLOR_PAGE_BG)
            + LIGHT_SCROLLBAR_QSS
            + STYLE_TAB_WIDGET
            + STYLE_CLEAR_CHILD_BG
            + "QCheckBox, QRadioButton { spacing: 8px; background-color: transparent; }"
        )

    def _setup_ui(self):
        """设置UI（只在初始化时调用一次）"""
        # 设置窗口属性
        self.setWindowTitle("设置")
        
        # 按父窗口（主字幕条）所在屏约束尺寸，避免副屏被主屏分辨率错误限制
        from utils.screen_geometry import available_geometry_for
        anchor = self.parent() if isinstance(self.parent(), QWidget) else self
        screen = available_geometry_for(widget=anchor)
        max_width = min(SETTINGS_MAX_WIDTH, screen.width() - 40)
        init_width = min(SETTINGS_DEFAULT_WIDTH, max_width)
        max_height = min(800, screen.height() - 100)
        
        self.setMinimumSize(SETTINGS_MIN_WIDTH, 300)
        self.setMaximumSize(max_width, screen.height() - 40)
        self.resize(init_width, max_height)
        # 使用非模态窗口，避免阻塞主界面事件循环
        self.setModal(False)

        # 构建期关闭重绘；子样式与窗口 chrome 放到控件建完后再套，减少布局 polish
        self.setUpdatesEnabled(False)
        _begin_defer_widget_styles()
        try:
            # 创建主布局
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(10, 8, 10, 10)
            main_layout.setSpacing(6)
            
            # 创建标签页（先换自定义 TabBar，再 addTab，宽度按字数计算）
            self.notebook = QTabWidget()
            self.notebook.setTabBar(_ContentWidthTabBar())
            self.notebook.setDocumentMode(True)
            tab_bar = self.notebook.tabBar()
            tab_bar.setExpanding(False)
            tab_bar.setUsesScrollButtons(True)
            tab_bar.setElideMode(Qt.ElideNone)
            main_layout.addWidget(self.notebook)
            
            # 跨 Tab 共享的控件引用（外观 / 显示拆页后仍统一保存）
            self.display_vars = {}
            self.render_vars = {}
            self.performance_vars = {}

            # 标签页顺序：外观、显示、音频、数据源、数据源状态、高级、关于
            # 先建「外观」，其余可延后，缩短首次可见耗时
            self._create_appearance_tab()
            if not self._defer_secondary_tabs:
                self._create_secondary_tabs()
            
            # 创建底部按钮区域
            self._create_bottom_buttons(main_layout)

            if not self._defer_secondary_tabs:
                # 抑制长文案/令牌框把布局最小宽度撑爆
                self._tighten_horizontal_hints()

            _flush_deferred_widget_styles()
            self._apply_window_chrome()
        finally:
            # 异常时也要结束暂缓，避免后续控件样式一直入队不生效
            if _DEFER_WIDGET_STYLES:
                _flush_deferred_widget_styles()
            self.setUpdatesEnabled(True)
        
        # 居中显示
        self._center_window()
        
        # 自定义数据源状态定时刷新（仅「高级」页可见时运行，切换离开或关闭时停止）
        self._custom_source_status_timer = QTimer(self)
        self._custom_source_status_timer.setInterval(2000)
        self._custom_source_status_timer.timeout.connect(self._update_custom_source_status)
        # 数据源页连接/解析状态定时刷新（外观/显示拆开后索引 +1）
        self._appearance_tab_index = 0
        self._display_tab_index = 1
        self._audio_tab_index = 2
        self._data_source_tab_index = 3
        self._data_source_status_tab_index = 4
        self._advanced_tab_index = 5
        self._status_refresh_timer = QTimer(self)
        self._status_refresh_timer.setInterval(2000)
        self._status_refresh_timer.timeout.connect(self._on_status_refresh_tick)
        self.notebook.currentChanged.connect(self._on_settings_tab_changed)

    def _create_secondary_tabs(self) -> None:
        """创建除「外观」外的其余设置标签页（顺序须与索引常量一致）。"""
        self._create_display_tab()
        self._create_audio_tab()
        self._create_data_source_tab()
        self._create_data_source_status_tab()
        self._create_advanced_tab()
        self._create_about_tab()

    def complete_secondary_tabs(self) -> None:
        """补齐延后创建的标签页，并完成脏标记绑定。首次 show 后调用。"""
        if self._secondary_tabs_ready:
            return
        self.setUpdatesEnabled(False)
        _begin_defer_widget_styles()
        try:
            self._create_secondary_tabs()
            self._tighten_horizontal_hints()
            _flush_deferred_widget_styles()
        finally:
            if _DEFER_WIDGET_STYLES:
                _flush_deferred_widget_styles()
            self.setUpdatesEnabled(True)
        self._wire_dirty_tracking()
        self._secondary_tabs_ready = True
        self._defer_secondary_tabs = False
    
    def _on_settings_tab_changed(self, index: int):
        """切换标签页时：仅在「高级」页启动状态刷新定时器，离开时停止。"""
        if index in (self._data_source_tab_index, self._data_source_status_tab_index):
            if not self._status_refresh_timer.isActive():
                self._status_refresh_timer.start()
            if index == self._data_source_tab_index:
                self._update_parse_status_labels()
                self._sync_fanstudio_auth_status_label()
                self._sync_whews_cea_auth_status_label()
                self._sync_eqsc_auth_status_label()
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
            self._sync_fanstudio_auth_status_label()
            self._sync_whews_cea_auth_status_label()
            self._sync_eqsc_auth_status_label()
        elif current_index == self._data_source_status_tab_index:
            self._update_data_source_health_table()

    def _update_parse_status_labels(self):
        """根据本会话实际解析记录刷新「已解析」；「已启用」仍跟开关。"""
        try:
            parent = self.parent()
            parsed_keys = set()
            if parent is not None and hasattr(parent, "get_parsed_status_keys"):
                try:
                    parsed_keys = set(parent.get_parsed_status_keys() or [])
                except Exception:
                    parsed_keys = set()
            mc = self.config.message_config
            for key, lbl in self.source_parse_labels.items():
                if not lbl:
                    continue
                status_texts = self.source_status_texts.get(
                    key, ("已解析", "未解析", "解析状态：已解析 / 未解析")
                )
                connected_text, disconnected_text, tooltip = status_texts
                lbl.setToolTip(tooltip)
                # 「已启用/未启用」表示开关；「已解析/未解析」表示本会话是否收到过可解析数据
                # （含 Fan Studio initial_all；过期未上屏也会记为已解析）
                if connected_text == "已启用" or disconnected_text == "未启用":
                    cb = self.source_vars.get(key) or getattr(self, f"{key}_cb", None)
                    if cb is not None and hasattr(cb, "isChecked"):
                        enabled = bool(cb.isChecked())
                    else:
                        enabled = bool(getattr(mc, key, False))
                    if enabled:
                        lbl.setText(connected_text)
                        _set_widget_style(lbl, STYLE_STATUS_CONNECTED)
                    else:
                        lbl.setText(disconnected_text)
                        _set_widget_style(lbl, STYLE_STATUS_NEUTRAL)
                    continue
                if key in parsed_keys:
                    lbl.setText(connected_text)
                    _set_widget_style(lbl, STYLE_STATUS_CONNECTED)
                else:
                    lbl.setText(disconnected_text)
                    _set_widget_style(lbl, STYLE_STATUS_NEUTRAL)
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
            self._sync_fanstudio_auth_status_label()
            self._sync_whews_cea_auth_status_label()
            self._sync_eqsc_auth_status_label()
        elif self.notebook.currentIndex() == self._data_source_status_tab_index:
            if not self._status_refresh_timer.isActive():
                self._status_refresh_timer.start()
            self._update_data_source_health_table()

    def hideEvent(self, event):
        """窗口隐藏或关闭时停止自定义数据源状态刷新定时器"""
        self._status_refresh_timer.stop()
        self._custom_source_status_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        """关闭前提示未保存修改；启用自动保存时直接写盘。"""
        if getattr(self, "_settings_dirty", False) and self._is_auto_save_enabled():
            if self._save_all_settings(show_success_message=False):
                self._settings_dirty = False
                super().closeEvent(event)
                return
        if not getattr(self, "_settings_dirty", False):
            super().closeEvent(event)
            return
        msg = styled_message_box(self)
        msg.setWindowTitle("未保存的修改")
        msg.setText("有未保存的设置，是否在关闭前保存？")
        msg.setIcon(QMessageBox.Question)
        save_btn = msg.addButton("保存", QMessageBox.AcceptRole)
        discard_btn = msg.addButton("不保存", QMessageBox.DestructiveRole)
        msg.addButton("取消", QMessageBox.RejectRole)
        msg.exec_()
        clicked = msg.clickedButton()
        if clicked == save_btn:
            if self._save_all_settings(show_success_message=False):
                self._settings_dirty = False
                super().closeEvent(event)
            else:
                event.ignore()
        elif clicked == discard_btn:
            self._settings_dirty = False
            super().closeEvent(event)
        else:
            event.ignore()

    def _is_auto_save_enabled(self) -> bool:
        """是否启用了「修改后自动保存」。"""
        cb = getattr(self, "auto_save_settings_cb", None)
        if cb is not None:
            return cb.isChecked()
        return getattr(self.config.gui_config, "auto_save_settings", False)

    def _mark_settings_dirty(self, *_args) -> None:
        """标记当前有未保存修改；若开启自动保存则调度延迟写入。"""
        self._settings_dirty = True
        if self._is_auto_save_enabled():
            self._schedule_auto_save()

    def _schedule_auto_save(self) -> None:
        """启动或重启自动保存防抖定时器。"""
        if getattr(self, "_auto_save_running", False):
            return
        timer = getattr(self, "_auto_save_timer", None)
        if timer is not None:
            timer.start()

    def _perform_auto_save(self) -> None:
        """定时器回调：在启用自动保存且有脏数据时静默保存全部设置。"""
        if not getattr(self, "_settings_dirty", False):
            return
        if not self._is_auto_save_enabled():
            return
        self._auto_save_running = True
        try:
            self._save_all_settings(show_success_message=False)
        finally:
            self._auto_save_running = False

    def _clear_settings_dirty(self) -> None:
        """清除未保存标记（保存成功或用户放弃修改后调用）。"""
        self._settings_dirty = False

    def _wire_dirty_tracking(self) -> None:
        """用户修改任意控件时标记为未保存。"""
        def _mark(*_a):
            """任意控件变更时标记设置页为脏。"""
            self._mark_settings_dirty()

        for w in self.findChildren(QAbstractButton):
            if w.isCheckable():
                w.toggled.connect(_mark)
        for w in self.findChildren(QSpinBox):
            w.valueChanged.connect(_mark)
        for w in self.findChildren(QDoubleSpinBox):
            w.valueChanged.connect(_mark)
        for w in self.findChildren(QComboBox):
            w.currentIndexChanged.connect(_mark)
        for w in self.findChildren(QLineEdit):
            w.textChanged.connect(_mark)
        for w in self.findChildren(QPlainTextEdit):
            w.textChanged.connect(_mark)
        for w in self.findChildren(QSlider):
            w.valueChanged.connect(_mark)

    def _wire_weather_source_mutex(self) -> None:
        """气象预警源互斥：Fan Studio / WeJet / OpenQuakeAPI 仅能开启一个。"""
        self._weather_mutex_sync = False
        specs = [
            ("fanstudio_parse_weatheralarm_cb", "fanstudio_parse_weatheralarm"),
            ("whews_parse_weatheralarm_cb", "whews_parse_weatheralarm"),
            ("openquake_parse_cma_cb", "openquake_parse_cma"),
        ]
        tip = "气象预警全局仅能启用一个数据源（Fan Studio / WeJet / OpenQuakeAPI 互斥）"
        for cb_attr, _flag in specs:
            cb = getattr(self, cb_attr, None)
            if cb is None:
                continue
            cb.setToolTip(tip)
            try:
                cb.stateChanged.disconnect()
            except Exception:
                pass
            cb.stateChanged.connect(
                lambda _state, active=cb_attr, s=specs: self._on_weather_source_mutex_changed(
                    active, s
                )
            )

    def _wire_jma_report_mutex(self) -> None:
        """P2PQuake 551 与主源 JMA 情报互斥。"""
        self._jma_report_mutex_sync = False
        main_cbs = [f"{flag}_cb" for flag in MAIN_JMA_REPORT_PARSE_FLAGS]
        p2p_cb = f"{P2P_JMA_REPORT_PARSE_FLAG}_cb"
        tip = (
            "P2PQuake 地震情报（551）与主数据源 JMA 情报互斥，"
            "同时只能启用一侧，避免重复轮播。"
        )
        for attr in main_cbs + [p2p_cb]:
            cb = getattr(self, attr, None)
            if cb is None:
                continue
            prev = cb.toolTip() or ""
            cb.setToolTip(f"{prev}\n{tip}".strip() if prev else tip)
            cb.stateChanged.connect(
                lambda _state, active=attr: self._on_jma_report_mutex_changed(active)
            )

    def _on_jma_report_mutex_changed(self, active_attr: str) -> None:
        """勾选主源 JMA 或 P2P 551 时，关闭另一侧。"""
        if getattr(self, "_jma_report_mutex_sync", False):
            return
        cb = getattr(self, active_attr, None)
        if cb is None or not cb.isChecked():
            return
        self._jma_report_mutex_sync = True
        try:
            p2p_attr = f"{P2P_JMA_REPORT_PARSE_FLAG}_cb"
            main_attrs = [f"{flag}_cb" for flag in MAIN_JMA_REPORT_PARSE_FLAGS]
            if active_attr == p2p_attr:
                for other_attr in main_attrs:
                    other = getattr(self, other_attr, None)
                    if other is not None and other.isChecked():
                        other.setChecked(False)
            elif active_attr in main_attrs:
                other = getattr(self, p2p_attr, None)
                if other is not None and other.isChecked():
                    other.setChecked(False)
        finally:
            self._jma_report_mutex_sync = False

    def _apply_jma_report_mutex_to_ui(self, prefer: str = "main") -> None:
        """全选/恢复等批量勾选后，按 prefer 收敛 JMA 情报互斥。"""
        self._jma_report_mutex_sync = True
        try:
            p2p = getattr(self, f"{P2P_JMA_REPORT_PARSE_FLAG}_cb", None)
            main_any = any(
                (cb := getattr(self, f"{flag}_cb", None)) is not None and cb.isChecked()
                for flag in MAIN_JMA_REPORT_PARSE_FLAGS
            )
            p2p_on = p2p is not None and p2p.isChecked()
            if not (main_any and p2p_on):
                return
            if prefer == "p2p":
                for flag in MAIN_JMA_REPORT_PARSE_FLAGS:
                    other = getattr(self, f"{flag}_cb", None)
                    if other is not None and other.isChecked():
                        other.setChecked(False)
            elif p2p is not None:
                p2p.setChecked(False)
        finally:
            self._jma_report_mutex_sync = False

    def _on_weather_source_mutex_changed(
        self, active_attr: str, specs: List[Tuple[str, str]]
    ) -> None:
        """勾选一个气象源时自动关闭其余气象源。"""
        if getattr(self, "_weather_mutex_sync", False):
            return
        cb = getattr(self, active_attr, None)
        if cb is None or not cb.isChecked():
            return
        self._weather_mutex_sync = True
        try:
            for cb_attr, _flag in specs:
                if cb_attr == active_attr:
                    continue
                other = getattr(self, cb_attr, None)
                if other is not None and other.isChecked():
                    other.setChecked(False)
        finally:
            self._weather_mutex_sync = False

    def _on_cancel_clicked(self):
        """取消：从磁盘重新加载配置并刷新控件，避免未保存的修改残留"""
        try:
            self.config.load_config()
            self._reload_controls_from_config()
        except Exception as e:
            logger.error(f"取消时恢复配置失败: {e}")
        self.reject()

    def _reload_controls_from_config(self):
        """将各标签页控件同步为当前 Config 中的已保存值"""
        try:
            g = self.config.gui_config
            mc = self.config.message_config
            if hasattr(self, 'display_vars') and self.display_vars:
                if 'always_on_top' in self.display_vars:
                    self.display_vars['always_on_top'].setChecked(getattr(g, 'always_on_top', False))
                if 'borderless' in self.display_vars:
                    self.display_vars['borderless'].setChecked(getattr(g, 'borderless', False))
                if 'background_image_path' in self.display_vars:
                    _bgp = str(getattr(g, 'background_image_path', '') or '')
                    self.display_vars['background_image_path'].setText(_bgp)
                    _sync = getattr(self, '_sync_bg_preset_combo', None)
                    if callable(_sync):
                        _sync(_bgp)
                if 'background_blur_radius' in self.display_vars:
                    self.display_vars['background_blur_radius'].setValue(
                        int(getattr(g, 'background_blur_radius', 12) or 0)
                    )
                if 'background_overlay_opacity' in self.display_vars:
                    _ov = float(getattr(g, 'background_overlay_opacity', 0.35) or 0.0)
                    self.display_vars['background_overlay_opacity'].setValue(
                        int(round(max(0.0, min(0.9, _ov)) * 100))
                    )
                if 'speed' in self.display_vars:
                    self.display_vars['speed'].setValue(int(round(g.text_speed * 10)))
                if 'width' in self.display_vars:
                    self.display_vars['width'].setValue(int(g.window_width))
                if 'height' in self.display_vars:
                    self.display_vars['height'].setValue(int(g.window_height))
                if 'opacity' in self.display_vars:
                    self.display_vars['opacity'].setValue(int(round(g.opacity * 10)))
                if 'vsync_enabled' in self.display_vars:
                    self.display_vars['vsync_enabled'].setChecked(g.vsync_enabled)
                if 'target_fps' in self.display_vars:
                    self.display_vars['target_fps'].setValue(int(g.target_fps))
                if 'font_bold' in self.display_vars:
                    self.display_vars['font_bold'].setChecked(g.font_bold)
                if 'font_italic' in self.display_vars:
                    self.display_vars['font_italic'].setChecked(g.font_italic)
                if 'warning_min_display_seconds' in self.display_vars:
                    # 配置存秒，控件单位为分钟（1–15）；切勿把秒数直接 setValue
                    wm_sec = int(getattr(mc, 'warning_min_display_seconds', 300) or 300)
                    self.display_vars['warning_min_display_seconds'].setValue(
                        max(1, min(15, wm_sec // 60))
                    )
                if 'custom_text_return_seconds' in self.display_vars:
                    ct_sec = int(getattr(mc, 'custom_text_return_seconds', 300) or 300)
                    self.display_vars['custom_text_return_seconds'].setValue(
                        max(1, min(60, ct_sec // 60))
                    )
                if 'min_report_magnitude' in self.display_vars:
                    self.display_vars['min_report_magnitude'].setValue(
                        float(getattr(mc, 'min_report_magnitude', 0) or 0)
                    )
                if 'geo_filter_enabled' in self.display_vars:
                    self.display_vars['geo_filter_enabled'].setChecked(
                        bool(getattr(mc, 'geo_filter_enabled', False))
                    )
                if 'geo_filter_latitude' in self.display_vars:
                    self.display_vars['geo_filter_latitude'].setValue(
                        float(getattr(mc, 'geo_filter_latitude', 0.0) or 0.0)
                    )
                if 'geo_filter_longitude' in self.display_vars:
                    self.display_vars['geo_filter_longitude'].setValue(
                        float(getattr(mc, 'geo_filter_longitude', 0.0) or 0.0)
                    )
                if 'geo_filter_radius_km' in self.display_vars:
                    # QSpinBox 需要 int；配置里可能存成 float
                    self.display_vars['geo_filter_radius_km'].setValue(
                        int(float(getattr(mc, 'geo_filter_radius_km', 1000) or 1000))
                    )
                if 'weather_region_filter_enabled' in self.display_vars:
                    self.display_vars['weather_region_filter_enabled'].setChecked(
                        bool(getattr(mc, 'weather_region_filter_enabled', False))
                    )
                if 'weather_region_filter' in self.display_vars:
                    self.display_vars['weather_region_filter'].setText(
                        getattr(mc, 'weather_region_filter', '') or ''
                    )
                if 'weather_level_filter' in self.display_vars:
                    _wl = (getattr(mc, 'weather_level_filter', 'none') or 'none').strip().lower()
                    _combo = self.display_vars['weather_level_filter']
                    _idx = _combo.findData(_wl)
                    _combo.setCurrentIndex(_idx if _idx >= 0 else 0)
                if 'watermark_text' in self.display_vars:
                    self.display_vars['watermark_text'].setText(
                        getattr(g, 'watermark_text', '') or ''
                    )
                if 'watermark_font_family' in self.display_vars:
                    wm_ff = getattr(g, 'watermark_font_family', '') or ''
                    combo_ff = self.display_vars['watermark_font_family']
                    idx_ff = combo_ff.findData(wm_ff) if wm_ff else -1
                    if idx_ff >= 0:
                        combo_ff.setCurrentIndex(idx_ff)
                if 'watermark_font_auto' in self.display_vars and 'watermark_font_size' in self.display_vars:
                    wm_fs = int(getattr(g, 'watermark_font_size', 0) or 0)
                    auto_wm = wm_fs <= 0
                    self.display_vars['watermark_font_auto'].setChecked(auto_wm)
                    base_fs = int(getattr(g, 'font_size', 40) or 40)
                    auto_fs = max(8, int(base_fs * 0.7))
                    self.display_vars['watermark_font_size'].setValue(wm_fs if wm_fs > 0 else auto_fs)
                    self.display_vars['watermark_font_size'].setEnabled(not auto_wm)
                if 'watermark_position' in self.display_vars:
                    pos = getattr(g, 'watermark_position', 'diagonal') or 'diagonal'
                    combo_pos = self.display_vars['watermark_position']
                    idx_pos = combo_pos.findData(pos)
                    if idx_pos < 0:
                        idx_pos = combo_pos.findData('diagonal')
                    if idx_pos >= 0:
                        combo_pos.setCurrentIndex(idx_pos)
                if 'timezone' in self.display_vars:
                    tz = getattr(g, 'timezone', 'Asia/Shanghai') or 'Asia/Shanghai'
                    combo_tz = self.display_vars['timezone']
                    idx_tz = combo_tz.findData(tz)
                    if idx_tz >= 0:
                        combo_tz.setCurrentIndex(idx_tz)
                if 'font_size' in self.display_vars:
                    fs = getattr(g, 'font_size', 40)
                    combo_fs = self.display_vars['font_size']
                    idx_fs = combo_fs.findData(fs)
                    if idx_fs >= 0:
                        combo_fs.setCurrentIndex(idx_fs)
                if 'font_family' in self.display_vars:
                    ff = getattr(g, 'font_family', '') or ''
                    combo_family = self.display_vars['font_family']
                    idx_family = combo_family.findData(ff) if ff else -1
                    if idx_family >= 0:
                        combo_family.setCurrentIndex(idx_family)
                if 'minimize_to_tray' in self.display_vars:
                    self.display_vars['minimize_to_tray'].setChecked(
                        getattr(g, 'minimize_to_tray', False)
                    )
                if 'toast_notifications_enabled' in self.display_vars:
                    self.display_vars['toast_notifications_enabled'].setChecked(
                        getattr(g, 'toast_notifications_enabled', False)
                    )
                if 'auto_update_check_on_startup' in self.display_vars:
                    self.display_vars['auto_update_check_on_startup'].setChecked(
                        getattr(g, 'auto_update_check_on_startup', True)
                    )
            cb_auto = getattr(self, "auto_save_settings_cb", None)
            if cb_auto is not None:
                cb_auto.blockSignals(True)
                cb_auto.setChecked(getattr(g, "auto_save_settings", False))
                cb_auto.blockSignals(False)
            adv = getattr(self, 'advanced_vars', {}) or {}
            alert_cb = adv.get('alert_enable_cb')
            if alert_cb is not None:
                alert_cb.setChecked(bool(getattr(self.config.alert_config, 'enabled', False)))
            audio = getattr(self, 'audio_vars', {}) or {}
            if audio:
                self._refresh_audio_tab_from_config()
            if hasattr(self, 'render_vars') and self.render_vars:
                backend = getattr(g, 'render_backend', None) or (
                    'opengl' if g.use_gpu_rendering else 'cpu'
                )
                if 'cpu_radio' in self.render_vars:
                    self.render_vars['cpu_radio'].setChecked(backend != 'opengl')
                if 'opengl_radio' in self.render_vars:
                    self.render_vars['opengl_radio'].setChecked(backend == 'opengl')
            if hasattr(self, 'performance_vars') and self.performance_vars:
                combo = self.performance_vars.get('performance_mode_combo')
                if combo is not None:
                    mode = getattr(g, 'performance_mode', 'medium') or 'medium'
                    idx = combo.findData(mode)
                    if idx < 0:
                        idx = combo.findData(PERFORMANCE_MODE_CUSTOM)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
            if hasattr(self, 'source_vars'):
                for url, cb in self.source_vars.items():
                    cb.setChecked(self.config.enabled_sources.get(url, True))
            if hasattr(self, 'fanstudio_api_key_entry'):
                self.fanstudio_api_key_entry.setText(
                    getattr(self.config.ws_config, 'fanstudio_api_key', '') or ''
                )
            if hasattr(self, 'eqsc_login_token_entry'):
                self.eqsc_login_token_entry.setText(
                    getattr(self.config.ws_config, 'eqsc_login_token', '') or ''
                )
                self._refresh_eqsc_auth_status_label(force=True)
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
                ('whews_parse_jma_eew_cb', 'whews_parse_jma_eew'),
                ('whews_parse_jma_cb', 'whews_parse_jma'),
                ('whews_parse_jma_volcano_cb', 'whews_parse_jma_volcano'),
                ('whews_parse_cwa_eew_cb', 'whews_parse_cwa_eew'),
                ('whews_parse_sa_eew_cb', 'whews_parse_sa_eew'),
                ('whews_parse_kma_eew_cb', 'whews_parse_kma_eew'),
                ('whews_parse_cea_cb', 'whews_parse_cea'),
                ('whews_parse_cea_pr_cb', 'whews_parse_cea_pr'),
                ('whews_parse_cenc_cb', 'whews_parse_cenc'),
                ('whews_parse_cwa_cb', 'whews_parse_cwa'),
                ('whews_parse_hko_cb', 'whews_parse_hko'),
                ('whews_parse_usgs_cb', 'whews_parse_usgs'),
                ('whews_parse_emsc_cb', 'whews_parse_emsc'),
                ('whews_parse_bcsf_cb', 'whews_parse_bcsf'),
                ('whews_parse_gfz_cb', 'whews_parse_gfz'),
                ('whews_parse_usp_cb', 'whews_parse_usp'),
                ('whews_parse_kma_cb', 'whews_parse_kma'),
                ('whews_parse_bmkg_cb', 'whews_parse_bmkg'),
                ('whews_parse_geonet_cb', 'whews_parse_geonet'),
                ('whews_parse_tmd_cb', 'whews_parse_tmd'),
                ('whews_parse_ingv_cb', 'whews_parse_ingv'),
                ('whews_parse_nrcan_cb', 'whews_parse_nrcan'),
                ('whews_parse_mmd_cb', 'whews_parse_mmd'),
                ('whews_parse_beijing_cb', 'whews_parse_beijing'),
                ('whews_parse_yunnan_cb', 'whews_parse_yunnan'),
                ('whews_parse_ningxia_cb', 'whews_parse_ningxia'),
                ('whews_parse_tsunami_cb', 'whews_parse_tsunami'),
                ('whews_parse_ntwc_cb', 'whews_parse_ntwc'),
                ('whews_parse_ptwc_cb', 'whews_parse_ptwc'),
                ('whews_parse_incois_cb', 'whews_parse_incois'),
                ('whews_parse_jma_tsunami_cb', 'whews_parse_jma_tsunami'),
                ('whews_parse_phivolcs_cb', 'whews_parse_phivolcs'),
                ('whews_parse_sgc_cb', 'whews_parse_sgc'),
                ('whews_parse_ga_cb', 'whews_parse_ga'),
                ('whews_parse_cenais_cb', 'whews_parse_cenais'),
                ('whews_parse_gsras_cb', 'whews_parse_gsras'),
                ('whews_parse_bgs_cb', 'whews_parse_bgs'),
                ('whews_parse_ipma_cb', 'whews_parse_ipma'),
                ('whews_parse_ssn_cb', 'whews_parse_ssn'),
                ('whews_parse_afad_cb', 'whews_parse_afad'),
                ('whews_parse_sed_cb', 'whews_parse_sed'),
                ('whews_parse_noa_cb', 'whews_parse_noa'),
                ('whews_parse_scsn_cb', 'whews_parse_scsn'),
                ('whews_parse_iag_cb', 'whews_parse_iag'),
                ('whews_parse_igp_cb', 'whews_parse_igp'),
                ('whews_parse_nepal_cb', 'whews_parse_nepal'),
                ('whews_parse_typhoon_cb', 'whews_parse_typhoon'),
                ('whews_parse_weatheralarm_cb', 'whews_parse_weatheralarm'),
            ]:
                cb = getattr(self, attr, None)
                if cb is not None:
                    cb.setChecked(getattr(mc, cfg_name, True))
            if hasattr(self, 'ali_all_parse_nied_cb'):
                self.ali_all_parse_nied_cb.setChecked(getattr(mc, 'ali_all_parse_nied', True))
            if hasattr(self, 'ali_all_parse_early_est_cb'):
                self.ali_all_parse_early_est_cb.setChecked(getattr(mc, 'ali_all_parse_early_est', True))
            if hasattr(self, 'ali_all_parse_jma_volcano_cb'):
                self.ali_all_parse_jma_volcano_cb.setChecked(getattr(mc, 'ali_all_parse_jma_volcano', True))
            if hasattr(self, 'ali_all_parse_bmkg_cb'):
                self.ali_all_parse_bmkg_cb.setChecked(getattr(mc, 'ali_all_parse_bmkg', True))
            if hasattr(self, 'ali_all_parse_cq_eew_cb'):
                self.ali_all_parse_cq_eew_cb.setChecked(getattr(mc, 'ali_all_parse_cq_eew', True))
            if hasattr(self, 'p2pquake_parse_551_cb'):
                self.p2pquake_parse_551_cb.setChecked(getattr(mc, 'p2pquake_parse_551', True))
            if hasattr(self, 'p2pquake_parse_552_cb'):
                self.p2pquake_parse_552_cb.setChecked(getattr(mc, 'p2pquake_parse_552', True))
            if hasattr(self, 'p2pquake_parse_556_cb'):
                self.p2pquake_parse_556_cb.setChecked(getattr(mc, 'p2pquake_parse_556', True))
            for attr, cfg_name, default in [
                ('eqsc_parse_jma_eew_cb', 'eqsc_parse_jma_eew', True),
                ('eqsc_parse_jma_report_cb', 'eqsc_parse_jma_report', True),
                ('eqsc_parse_jma_tsunami_cb', 'eqsc_parse_jma_tsunami', True),
                ('eqsc_parse_cenc_cb', 'eqsc_parse_cenc', True),
                ('eqsc_parse_cenc_ir_cb', 'eqsc_parse_cenc_ir', True),
                ('eqsc_parse_cwa_cb', 'eqsc_parse_cwa', True),
                ('eqsc_parse_hko_cb', 'eqsc_parse_hko', True),
                ('eqsc_parse_usgs_cb', 'eqsc_parse_usgs', True),
                ('eqsc_parse_emsc_cb', 'eqsc_parse_emsc', True),
                ('eqsc_parse_typhoon_cb', 'eqsc_parse_typhoon', True),
                ('eqsc_parse_volcano_cb', 'eqsc_parse_volcano', False),
                ('openquake_parse_gq_cb', 'openquake_parse_gq', True),
                ('openquake_parse_nmefc_cb', 'openquake_parse_nmefc', True),
                ('openquake_parse_nmefc_wave_cb', 'openquake_parse_nmefc_wave', True),
                ('openquake_parse_nmefc_surge_cb', 'openquake_parse_nmefc_surge', True),
                ('openquake_parse_cma_cb', 'openquake_parse_cma', True),
            ]:
                cb = getattr(self, attr, None)
                if cb is not None:
                    cb.setChecked(getattr(mc, cfg_name, default))
            if hasattr(self, "openquake_gq_min_magnitude_spin"):
                self.openquake_gq_min_magnitude_spin.setValue(
                    float(getattr(mc, "openquake_gq_min_magnitude", 4.5) or 0.0)
                )
            if hasattr(self, "openquake_connect_cb"):
                self.openquake_connect_cb.setChecked(
                    openquake_master_enabled(self.config.enabled_sources)
                )
            if hasattr(self, 'radio_custom_text') and hasattr(self, 'radio_report'):
                use_custom = getattr(mc, 'use_custom_text', False)
                self.radio_custom_text.setChecked(use_custom)
                self.radio_report.setChecked(not use_custom)
            if hasattr(self, 'show_one_alert_per_received_checkbox'):
                self.show_one_alert_per_received_checkbox.setChecked(
                    bool(getattr(mc, 'show_one_alert_per_received', False))
                )
            if hasattr(self, 'custom_text_return_after_warning_checkbox'):
                self.custom_text_return_after_warning_checkbox.setChecked(
                    bool(getattr(mc, 'custom_text_return_after_warning', False))
                )
            if hasattr(self, 'disable_warning_expiry_test_cb'):
                self.disable_warning_expiry_test_cb.setChecked(
                    bool(getattr(mc, 'disable_warning_expiry_for_test', False))
                )
            if hasattr(self, 'custom_text_edit'):
                self.custom_text_edit.setPlainText(getattr(mc, 'custom_text', '') or '')
            if hasattr(self, 'whews_token_entry'):
                self.whews_token_entry.setText(
                    getattr(self.config.ws_config, 'whews_token', '') or ''
                )
            if hasattr(self, 'http_poll_spinboxes'):
                for url, spin in self.http_poll_spinboxes.items():
                    spin.setValue(max(1, int(self.config.get_http_poll_interval(url))))
            if hasattr(self, 'custom_http_poll_spinbox'):
                self.custom_http_poll_spinbox.setValue(
                    max(1, int(self.config.get_http_poll_interval("__custom_http__")))
                )
            adv = getattr(self, 'advanced_vars', {}) or {}
            insecure_cb = adv.get('custom_insecure_ssl_cb')
            if insecure_cb is not None:
                insecure_cb.setChecked(
                    bool(getattr(self.config, 'custom_data_source_insecure_ssl', False))
                )
            self.current_report_color = mc.report_color
            self.current_warning_color = mc.warning_color
            self.current_custom_text_color = getattr(mc, 'custom_text_color', '#01FF00')
        except Exception as e:
            logger.debug(f"刷新设置控件时部分项失败: {e}")
        finally:
            self._clear_settings_dirty()
    
    def _tighten_horizontal_hints(self) -> None:
        """让可换行文案与单行输入在水平方向可压缩，避免撑宽整个设置窗。"""
        for label in self.findChildren(QLabel):
            # Ignored：以父级实际宽度换行，杜绝「理想整行宽度」回传给对话框
            if label.wordWrap():
                label.setMinimumWidth(0)
                label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            else:
                # 关于页等超长单行（数据源名、URL）也允许收缩并改开换行
                fm = label.fontMetrics()
                try:
                    tw = fm.horizontalAdvance(label.text())
                except AttributeError:
                    tw = fm.width(label.text())
                if tw > SETTINGS_DEFAULT_WIDTH - 80:
                    label.setWordWrap(True)
                    label.setMinimumWidth(0)
                    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        for edit in self.findChildren(QLineEdit):
            edit.setMinimumWidth(0)
            edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for area in self.findChildren(_FittingScrollArea):
            area.setMinimumWidth(0)

    def _adjust_window_to_screen(self):
        """调整窗口大小和位置，确保不超出当前所属屏（跟随主窗/父窗所在副屏）。"""
        from utils.screen_geometry import (
            available_geometry_for,
            clamp_top_left_to_screen,
            center_top_left_on_screen,
        )

        parent = self.parent() if isinstance(self.parent(), QWidget) else None
        screen = available_geometry_for(widget=parent or self)

        max_width = min(SETTINGS_MAX_WIDTH, screen.width() - 40)
        max_height = screen.height() - 40
        # 复用旧实例时重设宽高上限（旧代码曾允许接近全屏宽）
        self.setMinimumWidth(min(SETTINGS_MIN_WIDTH, max_width))
        self.setMaximumWidth(max_width)
        self.setMaximumHeight(max_height)

        window_width = self.width()
        window_height = self.height()

        # 超过上限，或明显宽于默认宽（历史超宽几何）→ 收到默认宽
        if window_width > max_width or window_width > SETTINGS_DEFAULT_WIDTH + 8:
            window_width = min(SETTINGS_DEFAULT_WIDTH, max_width)
            self.resize(window_width, window_height)

        if window_height > max_height:
            window_height = max_height
            self.resize(window_width, window_height)

        window_width = self.width()
        window_height = self.height()

        # 相对父窗口居中；无父则在当前屏居中（坐标含副屏偏移）
        if parent is not None:
            parent_geometry = parent.frameGeometry()
            x = parent_geometry.x() + (parent_geometry.width() - window_width) // 2
            y = parent_geometry.y() + (parent_geometry.height() - window_height) // 2
            x, y = clamp_top_left_to_screen(
                x, y, window_width, window_height, screen, margin=10
            )
        else:
            x, y = center_top_left_on_screen(window_width, window_height, screen)

        self.move(x, y)
    
    def _center_window(self):
        """窗口居中显示，确保不超出屏幕"""
        self._adjust_window_to_screen()
    
    def _create_appearance_tab(self):
        """创建「外观」标签页：字体、背景、水印、颜色。"""
        scroll_area, scrollable_widget, main_layout = _make_settings_tab_shell()

        # ---------- 字体 ----------
        group_font = QGroupBox("字体")
        _prep_groupbox(group_font)

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
        _set_widget_style(font_family_combo, STYLE_COMBOBOX)
        font_family_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        font_family_combo.setMinimumContentsLength(4)
        font_family_combo.setMinimumWidth(100)
        font_family_combo.setMaximumWidth(160)
        font_family_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        font_family_label = QLabel("字体:")
        _set_widget_style(font_family_label, STYLE_LABEL)
        font_size_label = QLabel("字体大小:")
        _set_widget_style(font_size_label, STYLE_LABEL)
        font_size_combo = QComboBox()
        font_size_combo.setEditable(False)
        for i in range(10, 101, 2):
            font_size_combo.addItem(f"{i}px", i)
        current_fs = max(10, min(100, self.config.gui_config.font_size))
        idx_fs = font_size_combo.findData(current_fs)
        if idx_fs < 0:
            idx_fs = font_size_combo.findData((current_fs // 2) * 2)
        font_size_combo.setCurrentIndex(max(0, idx_fs))
        _set_widget_style(font_size_combo, STYLE_COMBOBOX)
        font_size_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        font_size_combo.setMinimumContentsLength(4)
        # 需容纳「100px」+ 下拉箭头，避免显示成「40p:」被裁切
        font_size_combo.setMinimumWidth(108)
        font_size_combo.setFixedWidth(108)
        font_bold_cb = QCheckBox("字体加粗")
        font_bold_cb.setChecked(getattr(self.config.gui_config, 'font_bold', False))
        _set_widget_style(font_bold_cb, STYLE_CHECKBOX)
        font_italic_cb = QCheckBox("字体倾斜")
        font_italic_cb.setChecked(getattr(self.config.gui_config, 'font_italic', False))
        _set_widget_style(font_italic_cb, STYLE_CHECKBOX)
        # 用 HBox 紧贴「标签 + 下拉」，避免 Grid 跨列把标签与选择框拉开
        font_block = _prep_card_block()
        font_block_layout = QVBoxLayout(font_block)
        font_block_layout.setContentsMargins(0, 0, 0, 0)
        font_block_layout.setSpacing(6)
        font_row = QHBoxLayout()
        font_row.setContentsMargins(0, 0, 0, 0)
        font_row.setSpacing(6)
        font_row.addWidget(font_family_label)
        font_row.addWidget(font_family_combo)
        font_row.addSpacing(12)
        font_row.addWidget(font_size_label)
        font_row.addWidget(font_size_combo)
        font_row.addStretch(1)
        font_block_layout.addLayout(font_row)
        style_row = QHBoxLayout()
        style_row.setContentsMargins(0, 0, 0, 0)
        style_row.setSpacing(16)
        style_row.addWidget(font_bold_cb)
        style_row.addWidget(font_italic_cb)
        style_row.addStretch(1)
        font_block_layout.addLayout(style_row)
        group_font_layout = QVBoxLayout(group_font)
        group_font_layout.setContentsMargins(*GROUP_MARGINS)
        group_font_layout.setSpacing(4)
        group_font_layout.addWidget(font_block)
        main_layout.addWidget(group_font)
        main_layout.addSpacing(SPACING_BLOCK)

        
        # ---------- 自定义背景 / 毛玻璃（独立分组，避免挤在「窗口」内被裁切） ----------
        from utils.builtin_backgrounds import (
            BUILTIN_BACKGROUNDS,
            builtin_display_name,
            is_builtin_background,
            make_builtin_path,
        )

        group_bg = QGroupBox("自定义背景")
        _prep_groupbox(group_bg)
        group_bg_layout = QVBoxLayout(group_bg)
        group_bg_layout.setContentsMargins(*GROUP_MARGINS)
        group_bg_layout.setSpacing(10)

        _bg_label_w = 112
        bg_preset_row = QHBoxLayout()
        bg_preset_row.setSpacing(8)
        bg_preset_label = QLabel("内置背景:")
        _set_widget_style(bg_preset_label, STYLE_LABEL)
        bg_preset_label.setFixedWidth(_bg_label_w)
        bg_preset_combo = QComboBox()
        _set_widget_style(bg_preset_combo, STYLE_COMBOBOX)
        # 按控件宽度伸缩，不按最长选项撑破右侧边框
        bg_preset_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        bg_preset_combo.setMinimumContentsLength(6)
        bg_preset_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bg_preset_combo.addItem("纯色（无图片）", "")
        for _fname, _label in BUILTIN_BACKGROUNDS:
            bg_preset_combo.addItem(_label, make_builtin_path(_fname))
        bg_preset_combo.addItem("自定义图片", "__custom__")
        bg_preset_row.addWidget(bg_preset_label)
        bg_preset_row.addWidget(bg_preset_combo, 1)
        group_bg_layout.addLayout(bg_preset_row)

        bg_path_row = QHBoxLayout()
        bg_path_row.setSpacing(8)
        bg_path_label = QLabel("背景图片:")
        _set_widget_style(bg_path_label, STYLE_LABEL)
        bg_path_label.setFixedWidth(_bg_label_w)
        bg_path_edit = QLineEdit()
        bg_path_edit.setReadOnly(True)
        bg_path_edit.setPlaceholderText("未选择（使用纯色背景）")
        _set_widget_style(bg_path_edit, STYLE_LINEEDIT)
        bg_path_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        _bg_cur = str(getattr(self.config.gui_config, "background_image_path", "") or "").strip()
        if _bg_cur:
            bg_path_edit.setText(_bg_cur)
        bg_browse_btn = QPushButton("选择…")
        bg_browse_btn.setFixedWidth(72)
        bg_browse_btn.setMinimumHeight(32)
        bg_crop_btn = QPushButton("裁切…")
        bg_crop_btn.setFixedWidth(72)
        bg_crop_btn.setMinimumHeight(32)
        bg_crop_btn.setToolTip("按当前字幕窗口尺寸裁切（内置与自定义均可）")
        bg_clear_btn = QPushButton("清除")
        bg_clear_btn.setFixedWidth(56)
        bg_clear_btn.setMinimumHeight(32)

        def _sync_bg_preset_combo(path: str) -> None:
            path = (path or "").strip()
            bg_preset_combo.blockSignals(True)
            try:
                if not path:
                    bg_preset_combo.setCurrentIndex(0)
                elif is_builtin_background(path):
                    idx = bg_preset_combo.findData(path)
                    bg_preset_combo.setCurrentIndex(idx if idx >= 0 else 0)
                else:
                    idx = bg_preset_combo.findData("__custom__")
                    if idx >= 0:
                        bg_preset_combo.setCurrentIndex(idx)
            finally:
                bg_preset_combo.blockSignals(False)
            bg_crop_btn.setEnabled(bool(path))

        def _on_bg_preset_changed(index: int) -> None:
            data = bg_preset_combo.itemData(index)
            if data == "__custom__":
                cur = (bg_path_edit.text() or "").strip()
                if not cur or is_builtin_background(cur):
                    _pick_background_image()
                else:
                    _sync_bg_preset_combo(cur)
                return
            if not data:
                bg_path_edit.clear()
                bg_path_edit.setToolTip("")
            else:
                path = str(data)
                bg_path_edit.setText(path)
                bg_path_edit.setToolTip(f"内置：{builtin_display_name(path)}")
            _sync_bg_preset_combo(bg_path_edit.text())

        def _pick_background_image():
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择背景图片",
                "",
                "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)",
            )
            if not path:
                cur = (bg_path_edit.text() or "").strip()
                if not cur or is_builtin_background(cur):
                    bg_path_edit.clear()
                    _sync_bg_preset_combo("")
                else:
                    _sync_bg_preset_combo(cur)
                return
            cropped = self._crop_background_image(path)
            if cropped is None:
                # 用户取消裁切：保留原自定义图，否则清空回到纯色/内置
                cur = (bg_path_edit.text() or "").strip()
                if not cur or is_builtin_background(cur):
                    bg_path_edit.clear()
                    _sync_bg_preset_combo("")
                else:
                    _sync_bg_preset_combo(cur)
                return
            # 同时保留原图，便于之后点「裁切…」重新选区
            stored = self._store_background_image(src_path=path, qimage=cropped)
            if stored:
                bg_path_edit.setText(stored)
                bg_path_edit.setToolTip(f"自定义：{stored}")
                _sync_bg_preset_combo(stored)

        def _recrop_background_image():
            from utils.builtin_backgrounds import resolve_background_image_file

            cur = (bg_path_edit.text() or "").strip()
            if not cur:
                show_info(self, "提示", "请先选择背景图后再裁切。")
                return
            # 内置图：直接裁切资源文件，结果存为自定义图并保留原图供再次裁切
            if is_builtin_background(cur):
                source = resolve_background_image_file(cur)
                if not source:
                    show_critical(self, "错误", "找不到内置背景图文件。")
                    return
                cropped = self._crop_background_image(source)
                if cropped is None:
                    return
                stored = self._store_background_image(src_path=source, qimage=cropped)
                if stored:
                    bg_path_edit.setText(stored)
                    bg_path_edit.setToolTip(f"自定义：{stored}")
                    _sync_bg_preset_combo(stored)
                return
            source = self._resolve_custom_background_source()
            if not source:
                show_critical(
                    self,
                    "错误",
                    "找不到可裁切的原图。请重新「选择…」上传图片（上传时会保留原图供再次裁切）。",
                )
                return
            cropped = self._crop_background_image(source)
            if cropped is None:
                return
            stored = self._store_background_image(qimage=cropped, keep_source=True)
            if stored:
                bg_path_edit.setText(stored)
                bg_path_edit.setToolTip(f"自定义：{stored}")
                _sync_bg_preset_combo(stored)

        def _clear_background_image():
            bg_path_edit.clear()
            bg_path_edit.setToolTip("")
            _sync_bg_preset_combo("")

        bg_browse_btn.clicked.connect(_pick_background_image)
        bg_crop_btn.clicked.connect(_recrop_background_image)
        bg_clear_btn.clicked.connect(_clear_background_image)
        bg_preset_combo.currentIndexChanged.connect(_on_bg_preset_changed)
        # 下拉列表宽度跟控件对齐，避免横向撑出设置页
        _bg_combo_show_popup = bg_preset_combo.showPopup

        def _show_bg_preset_popup():
            view = bg_preset_combo.view()
            w = max(int(bg_preset_combo.width()), 180)
            view.setMinimumWidth(w)
            view.setMaximumWidth(w + 48)
            _bg_combo_show_popup()

        bg_preset_combo.showPopup = _show_bg_preset_popup
        self._sync_bg_preset_combo = _sync_bg_preset_combo
        _sync_bg_preset_combo(_bg_cur)
        if _bg_cur and is_builtin_background(_bg_cur):
            bg_path_edit.setText(_bg_cur)
            bg_path_edit.setToolTip(f"内置：{builtin_display_name(_bg_cur)}")
        bg_path_row.addWidget(bg_path_label)
        bg_path_row.addWidget(bg_path_edit, 1)
        bg_path_row.addWidget(bg_browse_btn)
        bg_path_row.addWidget(bg_crop_btn)
        bg_path_row.addWidget(bg_clear_btn)
        group_bg_layout.addLayout(bg_path_row)

        blur_row = QHBoxLayout()
        blur_row.setSpacing(8)
        blur_label = QLabel("毛玻璃模糊:")
        _set_widget_style(blur_label, STYLE_LABEL)
        blur_label.setFixedWidth(_bg_label_w)
        blur_slider = QSlider(Qt.Horizontal)
        blur_slider.setMinimum(0)
        blur_slider.setMaximum(40)
        blur_slider.setValue(int(getattr(self.config.gui_config, "background_blur_radius", 12) or 0))
        _set_widget_style(blur_slider, STYLE_SLIDER)
        blur_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        blur_slider.setToolTip("0 = 关闭模糊；数值越大毛玻璃越强")
        blur_value = QLabel(str(blur_slider.value()))
        _set_widget_style(blur_value, STYLE_VALUE)
        blur_slider.valueChanged.connect(lambda v: blur_value.setText(str(v)))
        blur_row.addWidget(blur_label)
        blur_row.addWidget(blur_slider, 1)
        blur_row.addWidget(blur_value)
        group_bg_layout.addLayout(blur_row)

        overlay_row = QHBoxLayout()
        overlay_row.setSpacing(8)
        overlay_label = QLabel("遮罩浓度:")
        _set_widget_style(overlay_label, STYLE_LABEL)
        overlay_label.setFixedWidth(_bg_label_w)
        overlay_slider = QSlider(Qt.Horizontal)
        overlay_slider.setMinimum(0)
        overlay_slider.setMaximum(90)
        _ov = float(getattr(self.config.gui_config, "background_overlay_opacity", 0.35) or 0.0)
        overlay_slider.setValue(int(round(max(0.0, min(0.9, _ov)) * 100)))
        _set_widget_style(overlay_slider, STYLE_SLIDER)
        overlay_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        overlay_slider.setToolTip("半透明深色遮罩，保证字幕可读；0=无遮罩")
        overlay_value = QLabel(f"{overlay_slider.value() / 100.0:.2f}")
        _set_widget_style(overlay_value, STYLE_VALUE)
        overlay_slider.valueChanged.connect(
            lambda v: overlay_value.setText(f"{v / 100.0:.2f}")
        )
        overlay_row.addWidget(overlay_label)
        overlay_row.addWidget(overlay_slider, 1)
        overlay_row.addWidget(overlay_value)
        group_bg_layout.addLayout(overlay_row)

        bg_hint = QLabel("上传后裁切，再调模糊与遮罩（与整窗透明度独立）。")
        bg_hint.setToolTip("裁切比例随字幕窗口；液态玻璃效果与整窗不透明度相互独立。")
        _set_widget_style(bg_hint, STYLE_HINT)
        bg_hint.setWordWrap(True)
        group_bg_layout.addWidget(bg_hint)

        main_layout.addWidget(group_bg)
        main_layout.addSpacing(SPACING_BLOCK)

        # 水印设置（QGroupBox，含背景水印文字 + 字体/字号/位置）
        group_wm = QGroupBox("水印设置")
        _prep_groupbox(group_wm)
        block_wm = _prep_card_block()
        block_wm_layout = QVBoxLayout(block_wm)
        block_wm_layout.setContentsMargins(0, 0, 0, 0)
        block_wm_layout.setSpacing(8)
        watermark_label = QLabel("背景水印:")
        _set_widget_style(watermark_label, STYLE_LABEL)
        watermark_edit = QLineEdit()
        watermark_edit.setPlaceholderText("留空则不显示")
        watermark_edit.setText(getattr(self.config.gui_config, 'watermark_text', "") or "")
        _set_widget_style(watermark_edit, STYLE_LINEEDIT)
        watermark_text_row = QHBoxLayout()
        watermark_text_row.setSpacing(8)
        watermark_text_row.addWidget(watermark_label)
        watermark_text_row.addWidget(watermark_edit, 1)
        block_wm_layout.addLayout(watermark_text_row)
        wm_hint = QLabel("可单独设置水印字体、字号与位置。")
        wm_hint.setToolTip("自动字号按主字体大小缩放。")
        _set_widget_style(wm_hint, STYLE_HINT)
        wm_hint.setWordWrap(True)
        wm_hint.setMinimumWidth(0)
        wm_hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
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
        _set_widget_style(watermark_font_combo, STYLE_COMBOBOX)
        watermark_font_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        watermark_font_combo.setMinimumContentsLength(8)
        watermark_font_combo.setMinimumWidth(120)
        watermark_font_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wm_font_row = QHBoxLayout()
        wm_adv_label = QLabel("水印字体:")
        _set_widget_style(wm_adv_label, STYLE_LABEL)
        wm_font_row.addWidget(wm_adv_label)
        wm_font_row.addWidget(watermark_font_combo, 1)
        block_wm_layout.addLayout(wm_font_row)
        watermark_font_auto_cb = QCheckBox("自动字号")
        _set_widget_style(watermark_font_auto_cb, STYLE_CHECKBOX)
        wm_fs = int(getattr(self.config.gui_config, 'watermark_font_size', 0) or 0)
        auto_initial = (wm_fs <= 0)
        watermark_font_auto_cb.setChecked(auto_initial)
        watermark_font_size_spin = QSpinBox()
        watermark_font_size_spin.setRange(8, 100)
        base_fs = getattr(self.config.gui_config, 'font_size', 40)
        auto_fs = max(8, int(base_fs * 0.7))
        watermark_font_size_spin.setValue(wm_fs if wm_fs > 0 else auto_fs)
        _set_widget_style(watermark_font_size_spin, STYLE_SPINBOX)
        watermark_font_size_spin.setFixedWidth(72)
        watermark_font_size_spin.setEnabled(not auto_initial)
        def _on_wm_font_auto_changed(checked: bool):
            """水印字号「跟随主字体」勾选时禁用数值输入框。"""
            watermark_font_size_spin.setEnabled(not checked)
        watermark_font_auto_cb.toggled.connect(_on_wm_font_auto_changed)
        wm_size_row = QHBoxLayout()
        wm_size_row.setSpacing(12)
        wm_size_row.addWidget(watermark_font_auto_cb)
        wm_size_row.addWidget(watermark_font_size_spin)
        wm_size_row.addStretch()
        block_wm_layout.addLayout(wm_size_row)
        watermark_pos_combo = QComboBox()
        _set_widget_style(watermark_pos_combo, STYLE_COMBOBOX)
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
        _set_widget_style(wm_pos_label, STYLE_LABEL)
        wm_pos_row.addWidget(wm_pos_label)
        wm_pos_row.addWidget(watermark_pos_combo)
        wm_pos_row.addStretch()
        block_wm_layout.addLayout(wm_pos_row)
        group_wm_layout = QVBoxLayout(group_wm)
        group_wm_layout.setContentsMargins(*GROUP_MARGINS)
        group_wm_layout.addWidget(block_wm)
        main_layout.addWidget(group_wm)
        main_layout.addSpacing(SPACING_BLOCK)

        # ---------- 4. 颜色 ----------
        group_color = QGroupBox("颜色")
        _prep_groupbox(group_color)
        block4 = _prep_card_block()
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
            """在颜色区块添加一行：标签、预览、修改/恢复默认按钮。"""
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            lbl = QLabel(label_text)
            _set_widget_style(lbl, STYLE_LABEL)
            lbl.setMinimumWidth(120)  # 统一标签宽度，三行颜色预览/色值/按钮纵向对齐
            row_layout.addWidget(lbl)
            preview = QLabel()
            preview.setFixedSize(40, 25)
            _set_widget_style(preview, f"background-color: {color_value}; border: 1px solid #000; border-radius: 3px;")
            row_layout.addWidget(preview)
            value_label = QLabel(color_value)
            value_label.setMinimumWidth(80)
            _set_widget_style(value_label, STYLE_VALUE + " font-family: monospace;")
            # value_label 不加入 layout，仅保留引用供颜色更新使用
            btn = QPushButton("修改颜色")
            _set_widget_style(btn, STYLE_SECONDARY_BTN)
            btn.clicked.connect(lambda: self._open_color_picker(color_type))
            row_layout.addWidget(btn)
            reset_btn = QPushButton("恢复默认")
            _set_widget_style(reset_btn, STYLE_HINT + " padding: 4px 10px;")
            reset_btn.clicked.connect(lambda: self._reset_color(color_type))
            row_layout.addWidget(reset_btn)
            row_layout.addStretch()
            parent_layout.addWidget(row)
            return preview, value_label
        
        self.report_color_preview, self.report_color_label = _add_color_row(block4_layout, "地震信息颜色:", report_color_value, 'report')
        self.warning_color_preview, self.warning_color_label = _add_color_row(block4_layout, "地震预警颜色:", warning_color_value, 'warning')
        self.custom_text_color_preview, self.custom_text_color_label = _add_color_row(block4_layout, "自定义文本颜色:", custom_text_color_value, 'custom_text')
        group_color_layout = QVBoxLayout(group_color)
        group_color_layout.setContentsMargins(*GROUP_MARGINS)
        group_color_layout.addWidget(block4)
        main_layout.addWidget(group_color)
        main_layout.addSpacing(SPACING_BLOCK)

        
        self.display_vars.update({
            'font_size': font_size_combo,
            'font_family': font_family_combo,
            'font_bold': font_bold_cb,
            'font_italic': font_italic_cb,
            'background_image_path': bg_path_edit,
            'background_blur_radius': blur_slider,
            'background_overlay_opacity': overlay_slider,
            'watermark_text': watermark_edit,
            'watermark_font_family': watermark_font_combo,
            'watermark_font_auto': watermark_font_auto_cb,
            'watermark_font_size': watermark_font_size_spin,
            'watermark_position': watermark_pos_combo,
        })

        main_layout.addStretch()
        _add_tab_save_row(main_layout, self._save_appearance_settings)
        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "外观")

    def _create_display_tab(self):
        """创建「显示」标签页：滚动/窗口/过滤/渲染/预警与自定义文本等。"""
        scroll_area, scrollable_widget, main_layout = _make_settings_tab_shell()

        # ---------- 1. 基本显示 ----------
        group_basic = QGroupBox("基本显示")
        _prep_groupbox(group_basic)
        block1 = _prep_card_block()
        block1_layout = QGridLayout(block1)
        block1_layout.setContentsMargins(0, 0, 0, 0)
        block1_layout.setHorizontalSpacing(8)
        block1_layout.setVerticalSpacing(8)
        
        # 滚动速度
        speed_label = QLabel("滚动速度:")
        _set_widget_style(speed_label, STYLE_LABEL)
        speed_label.setMinimumWidth(80)
        speed_slider = QSlider(Qt.Horizontal)
        speed_slider.setMinimum(1)
        speed_slider.setMaximum(200)
        speed_slider.setValue(int(self.config.gui_config.text_speed * 10))
        _set_widget_style(speed_slider, STYLE_SLIDER)
        speed_slider.setMinimumWidth(80)
        speed_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        speed_label_value = QLabel(f"{self.config.gui_config.text_speed:.1f}")
        _set_widget_style(speed_label_value, STYLE_VALUE)
        speed_slider.valueChanged.connect(lambda v: speed_label_value.setText(f"{v / 10.0:.1f}"))
        block1_layout.addWidget(speed_label, 1, 0)
        block1_layout.addWidget(speed_slider, 1, 1)
        block1_layout.addWidget(speed_label_value, 1, 2)
        block1_layout.setColumnStretch(1, 1)
        
        # 显示时区：下拉与说明分行，避免窄宽度下换行被 GroupBox 底边裁切
        from utils.timezone_names_zh import get_tz_options, iana_to_display
        timezone_options = get_tz_options()
        timezone_label = QLabel("显示时区:")
        _set_widget_style(timezone_label, STYLE_LABEL)
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
        _set_widget_style(timezone_combo, STYLE_COMBOBOX)
        timezone_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        timezone_combo.setMinimumContentsLength(6)
        timezone_combo.setMinimumWidth(140)
        timezone_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        timezone_hint = QLabel("修改时区后立即生效（新消息按新时区显示）。")
        _set_widget_style(timezone_hint, STYLE_HINT)
        timezone_hint.setWordWrap(True)
        timezone_hint.setMinimumWidth(0)
        timezone_hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        block1_layout.addWidget(timezone_label, 2, 0)
        block1_layout.addWidget(timezone_combo, 2, 1, 1, 3)
        block1_layout.addWidget(timezone_hint, 3, 1, 1, 3)
        group_basic_layout = QVBoxLayout(group_basic)
        group_basic_layout.setContentsMargins(*GROUP_MARGINS)
        group_basic_layout.setSpacing(4)
        group_basic_layout.addWidget(block1)
        main_layout.addWidget(group_basic)
        main_layout.addSpacing(SPACING_BLOCK)
        
        # ---------- 2. 窗口 ----------
        group_window = QGroupBox("窗口")
        _prep_groupbox(group_window)
        block2 = _prep_card_block()
        block2_layout = QVBoxLayout(block2)
        block2_layout.setContentsMargins(0, 0, 0, 0)
        block2_layout.setSpacing(6)
        size_row = QHBoxLayout()
        size_row.setSpacing(10)
        width_label = QLabel("窗口宽度:")
        _set_widget_style(width_label, STYLE_LABEL)
        width_spin = QSpinBox()
        width_spin.setMinimum(200)
        width_spin.setMaximum(20000)  # 不受分辨率限制，允许超出屏幕
        width_spin.setValue(min(20000, max(200, int(self.config.gui_config.window_width))))
        _set_widget_style(width_spin, STYLE_SPINBOX)
        height_label = QLabel("窗口高度:")
        _set_widget_style(height_label, STYLE_LABEL)
        height_spin = QSpinBox()
        height_spin.setMinimum(50)
        height_spin.setMaximum(5000)  # 不受分辨率限制，允许超出屏幕
        height_spin.setValue(min(5000, max(50, int(self.config.gui_config.window_height))))
        _set_widget_style(height_spin, STYLE_SPINBOX)
        size_row.addWidget(width_label)
        size_row.addWidget(width_spin)
        size_row.addWidget(height_label)
        size_row.addWidget(height_spin)
        size_row.addStretch()
        block2_layout.addLayout(size_row)
        opacity_row = _prep_card_block()
        opacity_row_layout = QHBoxLayout(opacity_row)
        opacity_row_layout.setContentsMargins(0, 0, 0, 0)
        opacity_row_layout.setSpacing(8)
        opacity_label = QLabel("窗口不透明度:")
        _set_widget_style(opacity_label, STYLE_LABEL)
        opacity_label.setMinimumWidth(100)
        opacity_label.setToolTip("1.0 = 完全不透明；数值越小窗口越透明")
        opacity_row_layout.addWidget(opacity_label)
        opacity_slider = QSlider(Qt.Horizontal)
        opacity_slider.setMinimum(1)
        opacity_slider.setMaximum(10)
        opacity_slider.setValue(int(self.config.gui_config.opacity * 10))
        _set_widget_style(opacity_slider, STYLE_SLIDER)
        opacity_slider.setMinimumWidth(80)
        opacity_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        opacity_slider.setToolTip("1.0 = 完全不透明；数值越小窗口越透明")
        opacity_label_value = QLabel(f"{self.config.gui_config.opacity:.1f}")
        _set_widget_style(opacity_label_value, STYLE_VALUE)
        opacity_slider.valueChanged.connect(lambda v: opacity_label_value.setText(f"{v / 10.0:.1f}"))
        opacity_row_layout.addWidget(opacity_slider, 1)
        opacity_row_layout.addWidget(opacity_label_value)
        block2_layout.addWidget(opacity_row)
        always_on_top_cb = QCheckBox("窗口置顶")
        always_on_top_cb.setChecked(getattr(self.config.gui_config, 'always_on_top', False))
        _set_widget_style(always_on_top_cb, STYLE_CHECKBOX)
        always_on_top_cb.setToolTip("开启后主窗口始终置于其他窗口之上")
        block2_layout.addWidget(always_on_top_cb)
        borderless_cb = QCheckBox("无边框模式")
        borderless_cb.setChecked(getattr(self.config.gui_config, "borderless", False))
        _set_widget_style(borderless_cb, STYLE_CHECKBOX)
        borderless_cb.setToolTip("隐藏系统标题栏与边框；左键拖拽可移动窗口，右键打开菜单")
        block2_layout.addWidget(borderless_cb)
        minimize_tray_cb = QCheckBox("关闭窗口时最小化到系统托盘")
        minimize_tray_cb.setChecked(getattr(self.config.gui_config, 'minimize_to_tray', False))
        _set_widget_style(minimize_tray_cb, STYLE_CHECKBOX)
        block2_layout.addWidget(minimize_tray_cb)
        toast_notify_cb = QCheckBox("预警时显示系统通知")
        toast_notify_cb.setChecked(getattr(self.config.gui_config, 'toast_notifications_enabled', False))
        _set_widget_style(toast_notify_cb, STYLE_CHECKBOX)
        block2_layout.addWidget(toast_notify_cb)

        group_window_layout = QVBoxLayout(group_window)
        group_window_layout.setContentsMargins(*GROUP_MARGINS)
        group_window_layout.addWidget(block2)
        main_layout.addWidget(group_window)
        main_layout.addSpacing(SPACING_BLOCK)

        mc = self.config.message_config
        group_filter = QGroupBox("消息过滤")
        _prep_groupbox(group_filter)
        gf_layout = QVBoxLayout(group_filter)
        gf_layout.setContentsMargins(*GROUP_MARGINS)
        gf_layout.setSpacing(8)

        min_report_mag_row = QHBoxLayout()
        min_report_mag_row.setSpacing(6)
        min_report_mag_label = QLabel("速报最低震级：")
        min_report_mag_label.setToolTip("0 表示不限制")
        _set_widget_style(min_report_mag_label, STYLE_LABEL)
        min_report_mag_spin = QDoubleSpinBox()
        min_report_mag_spin.setRange(0.0, 10.0)
        min_report_mag_spin.setDecimals(1)
        min_report_mag_spin.setSingleStep(0.1)
        min_report_mag_spin.setValue(float(getattr(mc, 'min_report_magnitude', 0) or 0))
        min_report_mag_spin.setSuffix(" M")
        _set_widget_style(min_report_mag_spin, STYLE_SPINBOX)
        min_report_mag_spin.setFixedWidth(110)
        min_report_mag_row.addWidget(min_report_mag_label)
        min_report_mag_row.addWidget(min_report_mag_spin)
        min_report_mag_row.addStretch(1)
        gf_layout.addLayout(min_report_mag_row)

        geo_filter_cb = QCheckBox("关注区域过滤")
        geo_filter_cb.setChecked(getattr(mc, 'geo_filter_enabled', False))
        _set_widget_style(geo_filter_cb, STYLE_CHECKBOX)
        gf_layout.addWidget(geo_filter_cb)

        geo_lat_row = QHBoxLayout()
        geo_lat_row.setContentsMargins(18, 0, 0, 0)
        geo_lat_row.setSpacing(6)
        geo_lat_label = QLabel("圆心纬度：")
        _set_widget_style(geo_lat_label, STYLE_LABEL)
        geo_lat_spin = QDoubleSpinBox()
        geo_lat_spin.setRange(-90, 90)
        geo_lat_spin.setDecimals(4)
        geo_lat_spin.setValue(float(getattr(mc, 'geo_filter_latitude', 39.9042)))
        _set_widget_style(geo_lat_spin, STYLE_SPINBOX)
        geo_lat_spin.setMinimumWidth(100)
        geo_lat_spin.setMaximumWidth(120)
        geo_lon_label = QLabel("经度：")
        _set_widget_style(geo_lon_label, STYLE_LABEL)
        geo_lon_spin = QDoubleSpinBox()
        geo_lon_spin.setRange(-180, 180)
        geo_lon_spin.setDecimals(4)
        geo_lon_spin.setValue(float(getattr(mc, 'geo_filter_longitude', 116.4074)))
        _set_widget_style(geo_lon_spin, STYLE_SPINBOX)
        geo_lon_spin.setMinimumWidth(100)
        geo_lon_spin.setMaximumWidth(120)
        geo_lat_row.addWidget(geo_lat_label)
        geo_lat_row.addWidget(geo_lat_spin)
        geo_lat_row.addWidget(geo_lon_label)
        geo_lat_row.addWidget(geo_lon_spin)
        geo_lat_row.addStretch(1)
        gf_layout.addLayout(geo_lat_row)

        geo_radius_row = QHBoxLayout()
        geo_radius_row.setContentsMargins(18, 0, 0, 0)
        geo_radius_row.setSpacing(6)
        geo_radius_label = QLabel("半径 km：")
        _set_widget_style(geo_radius_label, STYLE_LABEL)
        geo_radius_spin = QSpinBox()
        geo_radius_spin.setRange(1, 20000)
        geo_radius_spin.setValue(int(getattr(mc, 'geo_filter_radius_km', 1000)))
        _set_widget_style(geo_radius_spin, STYLE_SPINBOX)
        geo_radius_spin.setMinimumWidth(90)
        geo_radius_spin.setMaximumWidth(110)
        geo_radius_row.addWidget(geo_radius_label)
        geo_radius_row.addWidget(geo_radius_spin)
        geo_radius_row.addStretch(1)
        gf_layout.addLayout(geo_radius_row)

        weather_region_cb = QCheckBox("气象地区过滤")
        weather_region_cb.setChecked(bool(getattr(mc, 'weather_region_filter_enabled', False)))
        _set_widget_style(weather_region_cb, STYLE_CHECKBOX)
        weather_region_cb.setToolTip(
            "开启后仅显示标题/描述中包含所填地区名的气象预警。\n"
            "多个地区用逗号、顿号或空格分隔，如：阳江,江门 或 海淀区、朝阳区。"
        )
        gf_layout.addWidget(weather_region_cb)

        weather_region_row = QHBoxLayout()
        weather_region_row.setContentsMargins(18, 0, 0, 0)
        weather_region_row.setSpacing(6)
        weather_region_label = QLabel("关注地区：")
        _set_widget_style(weather_region_label, STYLE_LABEL)
        weather_region_edit = QLineEdit()
        weather_region_edit.setPlaceholderText("例如：阳江市,海淀区（留空则不过滤）")
        weather_region_edit.setText(getattr(mc, 'weather_region_filter', '') or '')
        _set_widget_style(weather_region_edit, STYLE_LINEEDIT)
        weather_region_edit.setMinimumWidth(0)
        weather_region_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        weather_region_row.addWidget(weather_region_label)
        weather_region_row.addWidget(weather_region_edit, 1)
        gf_layout.addLayout(weather_region_row)

        weather_level_row = QHBoxLayout()
        weather_level_row.setContentsMargins(18, 0, 0, 0)
        weather_level_row.setSpacing(6)
        weather_level_label = QLabel("气象等级过滤：")
        _set_widget_style(weather_level_label, STYLE_LABEL)
        weather_level_combo = QComboBox()
        _set_widget_style(weather_level_combo, STYLE_COMBOBOX)
        weather_level_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        weather_level_combo.setMinimumContentsLength(8)
        weather_level_combo.setMinimumWidth(160)
        weather_level_combo.setMaximumWidth(220)
        weather_level_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        weather_level_combo.setToolTip(
            "不过滤：显示全部等级；\n"
            "黄色预警及以上：黄/橙/红；\n"
            "橙色预警及以上：橙/红；\n"
            "红色预警：仅红色。\n"
            "启用过滤后，无法识别等级的预警将被丢弃。"
        )
        _wl_options = (
            ("none", "不过滤"),
            ("yellow_up", "黄色预警及以上"),
            ("orange_up", "橙色预警及以上"),
            ("red", "红色预警"),
        )
        for _val, _label in _wl_options:
            weather_level_combo.addItem(_label, _val)
        _wl_cur = (getattr(mc, 'weather_level_filter', 'none') or 'none').strip().lower()
        _wl_idx = weather_level_combo.findData(_wl_cur)
        weather_level_combo.setCurrentIndex(_wl_idx if _wl_idx >= 0 else 0)
        weather_level_row.addWidget(weather_level_label)
        weather_level_row.addWidget(weather_level_combo)
        weather_level_row.addStretch(1)
        gf_layout.addLayout(weather_level_row)

        main_layout.addWidget(group_filter)
        main_layout.addSpacing(SPACING_BLOCK)

        # ---------- 3. 性能与渲染 ----------
        group_render = QGroupBox("性能与渲染")
        _prep_groupbox(group_render)
        block3 = _prep_card_block()
        block3_layout = QVBoxLayout(block3)
        block3_layout.setContentsMargins(0, 0, 0, 0)
        block3_layout.setSpacing(6)
        preset_row = QHBoxLayout()
        preset_label = QLabel("性能模式:")
        _set_widget_style(preset_label, STYLE_LABEL)
        performance_mode_combo = QComboBox()
        _set_widget_style(performance_mode_combo, STYLE_COMBOBOX)
        performance_mode_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        performance_mode_combo.setMinimumContentsLength(6)
        performance_mode_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for mode_id in PERFORMANCE_MODES:
            performance_mode_combo.addItem(PERFORMANCE_MODE_LABELS[mode_id], mode_id)
        current_mode = getattr(self.config.gui_config, "performance_mode", "medium") or "medium"
        mode_index = performance_mode_combo.findData(current_mode)
        if mode_index < 0:
            mode_index = performance_mode_combo.findData(PERFORMANCE_MODE_MEDIUM)
        performance_mode_combo.setCurrentIndex(max(0, mode_index))
        performance_mode_combo.setToolTip(
            "低性能：约 CPU≤2%、RSS≤100MB，30fps CPU 渲染；\n"
            "中性能：约 CPU≤3%、RSS≤160MB，30fps CPU 渲染；\n"
            "高性能：约 CPU≤4%、RSS≤210MB，30fps OpenGL；\n"
            "极致：约 CPU≤5%、RSS≤220MB，60fps OpenGL。\n"
            "优先保证滚动刷新流畅不卡顿。首次启动按本机自动匹配。"
        )
        apply_preset_btn = QPushButton("应用性能模式")
        _set_widget_style(apply_preset_btn, STYLE_SECONDARY_BTN)
        apply_preset_btn.setToolTip("按所选模式批量调整渲染、数据源与告警等设置")
        apply_preset_btn.clicked.connect(self._apply_performance_preset)
        preset_row.addWidget(preset_label)
        preset_row.addWidget(performance_mode_combo, 1)
        preset_row.addWidget(apply_preset_btn)
        block3_layout.addLayout(preset_row)
        preset_hint = QLabel("切换后覆盖渲染、数据源与告警等设置，立即生效。")
        preset_hint.setToolTip("会覆盖相关设置；预警显示能力保留，应用后热重载。")
        preset_hint.setWordWrap(True)
        _set_widget_style(preset_hint, STYLE_HINT)
        block3_layout.addWidget(preset_hint)
        render_row = QHBoxLayout()
        cpu_radio = QRadioButton("CPU 渲染（软件）")
        opengl_radio = QRadioButton("GPU 渲染（OpenGL）")
        _set_widget_style(cpu_radio, STYLE_LABEL)
        _set_widget_style(opengl_radio, STYLE_LABEL)
        backend = getattr(self.config.gui_config, 'render_backend', None) or ("opengl" if self.config.gui_config.use_gpu_rendering else "cpu")
        if backend == "opengl":
            opengl_radio.setChecked(True)
        else:
            cpu_radio.setChecked(True)
        cpu_radio.setToolTip("兼容性更好，修改后立即热切换生效")
        opengl_radio.setToolTip("硬件加速（OpenGL），修改后立即热切换生效")
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
        _set_widget_style(vsync_checkbox, STYLE_CHECKBOX)
        fps_label = QLabel("目标帧率:")
        _set_widget_style(fps_label, STYLE_LABEL)
        fps_spin = QSpinBox()
        fps_spin.setMinimum(1)
        fps_spin.setMaximum(240)
        fps_spin.setValue(int(self.config.gui_config.target_fps))
        fps_spin.setToolTip("1–240 fps。开启 VSync 时实际帧率跟随显示器。")
        _set_widget_style(fps_spin, STYLE_SPINBOX)
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
        group_render_layout.setContentsMargins(*GROUP_MARGINS)
        group_render_layout.addWidget(block3)
        main_layout.addWidget(group_render)
        main_layout.addSpacing(SPACING_BLOCK)

        # ---------- 预警/消息更新 ----------
        group_alert = QGroupBox("预警/消息更新")
        _prep_groupbox(group_alert)
        block_alert_update = _prep_card_block()
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
        _set_widget_style(self.show_one_alert_per_received_checkbox, STYLE_CHECKBOX)
        block_alert_update_layout.addWidget(self.show_one_alert_per_received_checkbox)
        self.force_single_line_checkbox = QCheckBox("强制单行")
        self.force_single_line_checkbox.setChecked(
            getattr(self.config.message_config, 'force_single_line', True)
        )
        self.force_single_line_checkbox.setToolTip(
            "开启后，将数据源中的换行符替换为空格，保证滚动字幕始终单行显示。关闭则保留多行（由数据源决定）。"
        )
        _set_widget_style(self.force_single_line_checkbox, STYLE_CHECKBOX)
        block_alert_update_layout.addWidget(self.force_single_line_checkbox)
        mc = self.config.message_config
        self.custom_text_return_after_warning_checkbox = QCheckBox("预警后限时显示速报（beta）")
        self.custom_text_return_after_warning_checkbox.setChecked(
            getattr(self.config.message_config, 'custom_text_return_after_warning', False)
        )
        self.custom_text_return_after_warning_checkbox.setToolTip(
            "仅在「数据源」为「自定义文本」时生效。开启后：默认显示自定义文本；有预警时优先显示预警；预警结束且有速报或在无预警时直接收到速报时，将限时显示速报，超时（默认 5 分钟，可在配置中调整）后自动恢复为仅显示自定义文本。"
        )
        _set_widget_style(self.custom_text_return_after_warning_checkbox, STYLE_CHECKBOX)
        block_alert_update_layout.addWidget(self.custom_text_return_after_warning_checkbox)
        custom_text_return_row = QHBoxLayout()
        custom_text_return_row.setSpacing(8)
        custom_text_return_label = QLabel("速报最多显示（分钟）:")
        _set_widget_style(custom_text_return_label, STYLE_LABEL)
        custom_text_return_minutes_spin = QSpinBox()
        custom_text_return_minutes_spin.setRange(1, 60)
        return_sec = getattr(mc, 'custom_text_return_seconds', 300) or 300
        current_return_min = max(1, min(60, return_sec // 60))
        custom_text_return_minutes_spin.setValue(current_return_min)
        _set_widget_style(custom_text_return_minutes_spin, STYLE_SPINBOX)
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
        _set_widget_style(min_display_label, STYLE_LABEL)
        warning_min_display_spin = QSpinBox()
        warning_min_display_spin.setRange(1, 15)
        current_min = max(1, int(getattr(mc, 'warning_min_display_seconds', 300)) // 60)
        warning_min_display_spin.setValue(min(15, current_min))
        _set_widget_style(warning_min_display_spin, STYLE_SPINBOX)
        warning_min_display_spin.setToolTip(
            "发震有效期已过后的短宽限（分钟），且实际宽限不会超过该源的发震有效期窗口。"
            "不会单独把预警拖到超过发震有效期很久。默认 5 分钟。"
        )
        warning_min_display_row.addWidget(min_display_label)
        warning_min_display_row.addWidget(warning_min_display_spin)
        warning_min_display_row.addStretch()
        block_alert_update_layout.addLayout(warning_min_display_row)
        self.disable_warning_expiry_test_cb = QCheckBox("关闭预警有效期（测试用）")
        self.disable_warning_expiry_test_cb.setChecked(
            bool(getattr(mc, "disable_warning_expiry_for_test", False))
        )
        self.disable_warning_expiry_test_cb.setToolTip(
            "开启后：不按发震时间丢弃入队预警；缓冲区也不按发震时间或展示宽限移出预警。"
            "便于用历史报文测试告警条与分阶段文案。"
        )
        _set_widget_style(self.disable_warning_expiry_test_cb, STYLE_CHECKBOX)
        block_alert_update_layout.addWidget(self.disable_warning_expiry_test_cb)
        alert_hint = QLabel("保存后立即生效，无需重启。")
        _set_widget_style(alert_hint, STYLE_HINT)
        block_alert_update_layout.addWidget(alert_hint)
        group_alert_layout = QVBoxLayout(group_alert)
        group_alert_layout.setContentsMargins(*GROUP_MARGINS)
        group_alert_layout.addWidget(block_alert_update)
        main_layout.addWidget(group_alert)
        main_layout.addSpacing(SPACING_BLOCK)

        # ---------- 自动更新 ----------
        group_auto_update = QGroupBox("自动更新")
        _prep_groupbox(group_auto_update)
        block_auto_update = _prep_card_block()
        block_auto_update_layout = QVBoxLayout(block_auto_update)
        block_auto_update_layout.setContentsMargins(0, 0, 0, 0)
        block_auto_update_layout.setSpacing(6)
        auto_update_startup_cb = QCheckBox("启动时检查更新")
        auto_update_startup_cb.setChecked(
            getattr(self.config.gui_config, 'auto_update_check_on_startup', True)
        )
        _set_widget_style(auto_update_startup_cb, STYLE_CHECKBOX)
        block_auto_update_layout.addWidget(auto_update_startup_cb)
        check_update_btn = QPushButton("检查更新")
        check_update_btn.clicked.connect(self._on_auto_update_check_clicked)
        block_auto_update_layout.addWidget(check_update_btn)
        group_auto_update_layout = QVBoxLayout(group_auto_update)
        group_auto_update_layout.setContentsMargins(*GROUP_MARGINS)
        group_auto_update_layout.addWidget(block_auto_update)
        main_layout.addWidget(group_auto_update)
        main_layout.addSpacing(SPACING_BLOCK)

        # ---------- 5. 非预警时显示 ----------
        group_mode = QGroupBox("非预警时显示")
        _prep_groupbox(group_mode)
        gm_layout = QVBoxLayout(group_mode)
        gm_layout.setContentsMargins(*GROUP_MARGINS)
        gm_layout.setSpacing(GROUP_SPACING)
        self.report_mode_group = QButtonGroup(scrollable_widget)
        self.radio_report = QRadioButton("地震速报")
        self.radio_custom_text = QRadioButton("自定义文本")
        self.report_mode_group.addButton(self.radio_report)
        self.report_mode_group.addButton(self.radio_custom_text)
        use_custom = getattr(self.config.message_config, 'use_custom_text', False)
        self.radio_report.setChecked(not use_custom)
        self.radio_custom_text.setChecked(use_custom)
        _set_widget_style(self.radio_report, STYLE_LABEL + " padding: 2px 0;")
        _set_widget_style(self.radio_custom_text, STYLE_LABEL + " padding: 2px 0;")
        gm_layout.addWidget(self.radio_report)
        gm_layout.addWidget(self.radio_custom_text)
        mode_hint = QLabel("切换后立即生效；自定义文本在下方编辑。")
        _set_widget_style(mode_hint, STYLE_HINT)
        mode_hint.setWordWrap(True)
        gm_layout.addWidget(mode_hint)
        main_layout.addWidget(group_mode)
        main_layout.addSpacing(SPACING_BLOCK)

        # ---------- 6. 自定义文本 ----------
        group_custom = QGroupBox("自定义文本")
        _prep_groupbox(group_custom)
        block5 = _prep_card_block()
        block5_layout = QVBoxLayout(block5)
        block5_layout.setContentsMargins(0, 0, 0, 0)
        block5_layout.setSpacing(6)
        custom_hint = QLabel("数据源选「自定义文本」后，非预警时显示此处内容。")
        custom_hint.setToolTip("修改并保存后立即生效，无需重启。")
        _set_widget_style(custom_hint, STYLE_HINT)
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
        group_custom_layout.setContentsMargins(*GROUP_MARGINS)
        group_custom_layout.addWidget(block5)
        main_layout.addWidget(group_custom)


        self.display_vars.update({
            'speed': speed_slider,
            'width': width_spin,
            'height': height_spin,
            'opacity': opacity_slider,
            'vsync_enabled': vsync_checkbox,
            'target_fps': fps_spin,
            'timezone': timezone_combo,
            'always_on_top': always_on_top_cb,
            'borderless': borderless_cb,
            'minimize_to_tray': minimize_tray_cb,
            'toast_notifications_enabled': toast_notify_cb,
            'min_report_magnitude': min_report_mag_spin,
            'geo_filter_enabled': geo_filter_cb,
            'geo_filter_latitude': geo_lat_spin,
            'geo_filter_longitude': geo_lon_spin,
            'geo_filter_radius_km': geo_radius_spin,
            'weather_region_filter_enabled': weather_region_cb,
            'weather_region_filter': weather_region_edit,
            'weather_level_filter': weather_level_combo,
            'auto_update_check_on_startup': auto_update_startup_cb,
            'warning_min_display_seconds': warning_min_display_spin,
            'custom_text_return_seconds': custom_text_return_minutes_spin,
        })

        self.render_vars = {'cpu_radio': cpu_radio, 'opengl_radio': opengl_radio}
        self.performance_vars = {
            'performance_mode_combo': performance_mode_combo,
            'apply_preset_btn': apply_preset_btn,
        }
        
        main_layout.addStretch()
        _add_tab_save_row(main_layout, self._save_appearance_settings)
        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "显示")

    def _audio_is_sound_mode(self) -> bool:
        """当前音频反馈方式是否为预设提示音（非 TTS）。"""
        av = getattr(self, 'audio_vars', {}) or {}
        radio = av.get('feedback_sound_radio')
        return radio is None or radio.isChecked()

    def _sync_eew_master_checkbox(self) -> None:
        """同步「地震预警」总开关与有感/强震 TTS 子开关状态。"""
        av = getattr(self, 'audio_vars', {}) or {}
        eew_cb = av.get('tier_eew_cb')
        if eew_cb is None:
            return
        ac = self.config.alert_config
        eew_cb.blockSignals(True)
        eew_cb.setChecked(
            bool(getattr(ac, 'felt_tts_enabled', False))
            and bool(getattr(ac, 'critical_tts_enabled', False))
        )
        eew_cb.blockSignals(False)

    def _apply_tier_cb_from_config(self) -> None:
        """从 Config.alert_config 回填各分级复选框的勾选状态。"""
        av = getattr(self, 'audio_vars', {}) or {}
        ac = self.config.alert_config
        for ui_key, attr in _AUDIO_TIER_SOUND:
            cb = av.get(ui_key)
            if cb is not None:
                cb.setChecked(bool(getattr(ac, attr, True)))
        for ui_key, attr in _AUDIO_TIER_TTS:
            cb = av.get(ui_key)
            if cb is not None:
                default = True
                cb.setChecked(bool(getattr(ac, attr, default)))
        self._sync_eew_master_checkbox()

    def _write_tier_cbs_to_config(self) -> None:
        """将分级复选框当前状态写回 Config.alert_config。"""
        av = getattr(self, 'audio_vars', {}) or {}
        ac = self.config.alert_config
        if self._audio_is_sound_mode():
            for ui_key, attr in _AUDIO_TIER_SOUND:
                cb = av.get(ui_key)
                if cb is not None:
                    setattr(ac, attr, bool(cb.isChecked()))
        else:
            eew_cb = av.get('tier_eew_cb')
            eew_on = bool(eew_cb.isChecked()) if eew_cb is not None else False
            ac.felt_tts_enabled = eew_on
            ac.critical_tts_enabled = eew_on
            for ui_key, attr in _AUDIO_TIER_TTS:
                cb = av.get(ui_key)
                if cb is not None:
                    setattr(ac, attr, bool(cb.isChecked()))

    def _sync_audio_tier_checkboxes(self, is_sound: bool, *, from_user_switch: bool = False) -> None:
        """切换反馈方式时，互斥同步「预警分级开关」复选框。"""
        av = getattr(self, 'audio_vars', {}) or {}
        if from_user_switch:
            if is_sound:
                for ui_key, _attr in _AUDIO_TIER_SOUND:
                    cb = av.get(ui_key)
                    if cb is not None:
                        cb.setChecked(True)
                for ui_key, _attr in _AUDIO_TIER_TTS:
                    cb = av.get(ui_key)
                    if cb is not None:
                        cb.setChecked(False)
                eew_cb = av.get('tier_eew_cb')
                if eew_cb is not None:
                    eew_cb.setChecked(False)
            else:
                for ui_key, _attr in _AUDIO_TIER_SOUND:
                    cb = av.get(ui_key)
                    if cb is not None:
                        cb.setChecked(False)
                for ui_key, _attr in _AUDIO_TIER_TTS:
                    cb = av.get(ui_key)
                    if cb is not None:
                        cb.setChecked(True)
                eew_cb = av.get('tier_eew_cb')
                if eew_cb is not None:
                    eew_cb.setChecked(True)
        else:
            self._apply_tier_cb_from_config()

    def _on_audio_feedback_mode_changed(self) -> None:
        """用户切换「提示音 / TTS」时同步分级开关与控件可用性。"""
        av = getattr(self, 'audio_vars', {}) or {}
        sound_radio = av.get('feedback_sound_radio')
        if sound_radio is None:
            return
        self._sync_audio_tier_checkboxes(bool(sound_radio.isChecked()), from_user_switch=True)
        self._update_audio_mode_ui()

    def _update_audio_mode_ui(self) -> None:
        """根据反馈方式启用/禁用预设音与 TTS 控件组。"""
        av = getattr(self, 'audio_vars', {}) or {}
        sound_radio = av.get('feedback_sound_radio')
        if sound_radio is None:
            return
        is_sound = bool(sound_radio.isChecked())
        sound_keys = (
            'felt_path_btn', 'felt_repeat_spin', 'critical_path_btn', 'critical_repeat_spin',
            'nhk_path_btn', 'nhk_repeat_spin',
            'jma_eew_path_btn', 'jma_eew_repeat_spin',
        )
        tts_keys = (
            'tts_rate_spin', 'warning_tts_repeat_spin',
            'report_tts_repeat_spin', 'weather_tts_repeat_spin', 'tsunami_tts_repeat_spin',
            'tts_policy_combo', 'tts_cooldown_spin',
            'warning_tts_test_btn', 'report_tts_test_btn',
            'weather_tts_test_btn', 'tsunami_tts_test_btn',
        )
        for key in sound_keys:
            w = av.get(key)
            if w is not None:
                w.setEnabled(is_sound)
        for ui_key, _attr in _AUDIO_TIER_SOUND:
            w = av.get(ui_key)
            if w is not None:
                w.setEnabled(is_sound)
                if not is_sound:
                    w.blockSignals(True)
                    w.setChecked(False)
                    w.blockSignals(False)
        for ui_key, _attr in _AUDIO_TIER_TTS:
            w = av.get(ui_key)
            if w is not None:
                w.setEnabled(not is_sound)
                if is_sound:
                    w.blockSignals(True)
                    w.setChecked(False)
                    w.blockSignals(False)
        eew_cb = av.get('tier_eew_cb')
        if eew_cb is not None:
            eew_cb.setEnabled(not is_sound)
            if is_sound:
                eew_cb.blockSignals(True)
                eew_cb.setChecked(False)
                eew_cb.blockSignals(False)
        for key in tts_keys:
            w = av.get(key)
            if w is not None:
                w.setEnabled(not is_sound)
        nhk_cb = av.get('nhk_news_bell_cb')
        if nhk_cb is not None:
            nhk_cb.setEnabled(True)
        for key in ('nhk_path_btn', 'nhk_repeat_spin'):
            w = av.get(key)
            if w is not None:
                w.setEnabled(is_sound and (bool(nhk_cb.isChecked()) if nhk_cb is not None else True))
        nhk_test = av.get('nhk_test_btn')
        if nhk_test is not None:
            nhk_test.setEnabled(is_sound)
        jma_eew_cb = av.get('jma_eew_alert_cb')
        if jma_eew_cb is not None:
            jma_eew_cb.setEnabled(True)
        for key in ('jma_eew_path_btn', 'jma_eew_repeat_spin'):
            w = av.get(key)
            if w is not None:
                w.setEnabled(is_sound and (bool(jma_eew_cb.isChecked()) if jma_eew_cb is not None else True))
        jma_test = av.get('jma_eew_test_btn')
        if jma_test is not None:
            jma_test.setEnabled(is_sound)

    def _refresh_audio_tab_from_config(self) -> None:
        """从磁盘配置刷新音频标签页全部控件。"""
        av = getattr(self, 'audio_vars', {}) or {}
        if not av:
            return
        ac = self.config.alert_config
        mode = str(getattr(ac, 'alert_feedback_mode', 'sound') or 'sound')
        sound_radio = av.get('feedback_sound_radio')
        tts_radio = av.get('feedback_tts_radio')
        if sound_radio is not None and tts_radio is not None:
            sound_radio.blockSignals(True)
            tts_radio.blockSignals(True)
            sound_radio.setChecked(mode != 'tts')
            tts_radio.setChecked(mode == 'tts')
            sound_radio.blockSignals(False)
            tts_radio.blockSignals(False)
        self._apply_tier_cb_from_config()
        spin_map = (
            ('felt_repeat_spin', 'felt_sound_repeat'),
            ('critical_repeat_spin', 'critical_sound_repeat'),
            ('warning_tts_repeat_spin', 'felt_tts_repeat'),
            ('report_tts_repeat_spin', 'report_tts_repeat'),
            ('weather_tts_repeat_spin', 'weather_tts_repeat'),
            ('tsunami_tts_repeat_spin', 'tsunami_tts_repeat'),
            ('tts_rate_spin', 'tts_rate'),
            ('tts_cooldown_spin', 'tts_cooldown_seconds'),
        )
        for ui_key, cfg_key in spin_map:
            spin = av.get(ui_key)
            if spin is None:
                continue
            try:
                spin.setValue(int(getattr(ac, cfg_key, spin.value()) or spin.value()))
            except RuntimeError:
                continue
        combo = av.get('tts_policy_combo')
        if combo is not None:
            policy = str(getattr(ac, 'tts_repeat_policy', 'smart') or 'smart')
            idx = combo.findData(policy)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        for btn_key, path_attr, default_rel in (
            ('felt_path_btn', 'felt_sound_path', 'media/eewalert.wav'),
            ('critical_path_btn', 'critical_sound_path', 'media/eewcritical.wav'),
            ('nhk_path_btn', 'nhk_news_bell_path', 'media/NHK一級ニュースベル.wav'),
            ('jma_eew_path_btn', 'jma_eew_alert_sound_path', 'media/NHK緊急地震速報の音.wav'),
        ):
            btn = av.get(btn_key)
            if btn is not None:
                path_val = getattr(ac, path_attr, '') or ''
                btn.setProperty('_sound_path', path_val)
                name = os.path.basename((path_val or default_rel).replace('\\', '/'))
                btn.setToolTip(name)
                avail = max(40, btn.width() - 12) if btn.width() > 0 else 120
                btn.setText(QFontMetrics(btn.font()).elidedText(name, Qt.ElideMiddle, avail))
        nhk_cb = av.get('nhk_news_bell_cb')
        if nhk_cb is not None:
            nhk_cb.setChecked(bool(getattr(ac, 'nhk_news_bell_enabled', False)))
        jma_eew_cb = av.get('jma_eew_alert_cb')
        if jma_eew_cb is not None:
            jma_eew_cb.setChecked(bool(getattr(ac, 'jma_eew_alert_sound_enabled', True)))
        jma_eew_spin = av.get('jma_eew_repeat_spin')
        if jma_eew_spin is not None:
            try:
                jma_eew_spin.setValue(int(getattr(ac, 'jma_eew_alert_sound_repeat', 2) or 2))
            except RuntimeError:
                pass
        self._update_audio_mode_ui()

    def _create_audio_tab(self):
        """创建音频与语音播报设置标签页。"""
        scroll_area = _FittingScrollArea()
        scrollable_widget = QWidget()
        _prepare_scroll_body(scrollable_widget)
        main_layout = QVBoxLayout(scrollable_widget)
        main_layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        main_layout.setSpacing(SPACING_TAB)

        ac = self.config.alert_config
        _tts_lbl_w = 72
        _tts_field_gap = 12
        _tts_field_x = _tts_lbl_w + _tts_field_gap
        _tts_repeat_col_gap = 24
        # 需容纳 STYLE_SPINBOX 左右 padding + 上下箭头，过窄会只剩按钮看不见数字
        _spin_w = 64
        _test_w = 72

        mode_group = QGroupBox("音频设置")
        _prep_groupbox(mode_group)
        mode_layout = QVBoxLayout(mode_group)
        mode_layout.setContentsMargins(*GROUP_MARGINS)
        mode_layout.setSpacing(4)
        mode_hint = QLabel("提示音与语音播报二选一。")
        _set_widget_style(mode_hint, STYLE_HINT)
        mode_hint.setWordWrap(True)
        mode_layout.addWidget(mode_hint)
        feedback_sound_radio = QRadioButton("预设提示音（WAV）")
        feedback_tts_radio = QRadioButton("语音播报（TTS / Windows SAPI）")
        _set_widget_style(feedback_sound_radio, STYLE_RADIO)
        _set_widget_style(feedback_tts_radio, STYLE_RADIO)
        current_mode = str(getattr(ac, 'alert_feedback_mode', 'sound') or 'sound')
        feedback_sound_radio.setChecked(current_mode != 'tts')
        feedback_tts_radio.setChecked(current_mode == 'tts')
        mode_layout.addWidget(feedback_sound_radio)
        mode_layout.addWidget(feedback_tts_radio)
        main_layout.addWidget(mode_group)

        tier_group = QGroupBox("预警分级开关")
        _prep_groupbox(tier_group)
        tier_grid = QGridLayout(tier_group)
        tier_grid.setContentsMargins(*GROUP_MARGINS)
        tier_grid.setHorizontalSpacing(8)
        tier_grid.setVerticalSpacing(10)
        tier_grid.setColumnStretch(0, 1)
        tier_grid.setColumnStretch(2, 1)
        tier_grid.setColumnMinimumWidth(1, 2)

        def _tier_event_label(text: str) -> QLabel:
            """创建分级表格左侧事件类型标签。"""
            lbl = QLabel(text)
            _set_widget_style(lbl, STYLE_LABEL)
            return lbl

        def _tier_half_row(label_text: str, cb: QCheckBox) -> QWidget:
            """创建「标签 + 复选框」半行布局容器。"""
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(8)
            lay.addWidget(_tier_event_label(label_text))
            lay.addStretch()
            lay.addWidget(cb)
            return row

        tier_felt_cb = QCheckBox()
        tier_critical_cb = QCheckBox()
        nhk_news_bell_cb = QCheckBox()
        nhk_news_bell_cb.setChecked(bool(getattr(ac, 'nhk_news_bell_enabled', False)))
        nhk_news_bell_cb.setToolTip("仅地震情报：震度 6 弱及以上时播放（不含预警）。")
        jma_eew_alert_cb = QCheckBox()
        jma_eew_alert_cb.setChecked(bool(getattr(ac, 'jma_eew_alert_sound_enabled', True)))
        jma_eew_alert_cb.setToolTip("JMA 緊急地震速報由「予報」升级为「警報」时播放。")
        tier_eew_cb = QCheckBox()
        tier_eew_cb.setToolTip("同时控制有感地震与强震预警的语音播报。")
        tier_report_cb = QCheckBox()
        tier_weather_cb = QCheckBox()
        tier_weather_cb.setToolTip("朗读内容与滚动字幕一致（不含左侧图标）。")
        tier_tsunami_cb = QCheckBox()
        tier_tsunami_cb.setToolTip("朗读内容与滚动字幕一致。")

        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setFrameShadow(QFrame.Sunken)
        divider.setFixedWidth(2)

        left_panel = _prep_card_block()
        left_lay = QVBoxLayout(left_panel)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(10)
        left_lay.addStretch()
        left_lay.addWidget(_tier_half_row("有感地震", tier_felt_cb))
        left_lay.addWidget(_tier_half_row("强震预警", tier_critical_cb))
        left_lay.addWidget(_tier_half_row("NHK 一级新闻铃", nhk_news_bell_cb))
        left_lay.addWidget(_tier_half_row("JMA 警報音", jma_eew_alert_cb))
        left_lay.addStretch()

        tier_grid.addWidget(left_panel, 0, 0, 4, 1)
        tier_grid.addWidget(divider, 0, 1, 4, 1)
        tier_grid.addWidget(_tier_half_row("地震预警", tier_eew_cb), 0, 2)
        tier_grid.addWidget(_tier_half_row("地震速报", tier_report_cb), 1, 2)
        tier_grid.addWidget(_tier_half_row("气象预警", tier_weather_cb), 2, 2)
        tier_grid.addWidget(_tier_half_row("海啸预警", tier_tsunami_cb), 3, 2)
        main_layout.addWidget(tier_group)

        sound_group = QGroupBox("预设提示音")
        _prep_groupbox(sound_group)
        sound_outer = QVBoxLayout(sound_group)
        sound_outer.setContentsMargins(*GROUP_MARGINS)
        sound_outer.setSpacing(8)

        _sound_title_w = 72
        _sound_path_w = 132
        _sound_row_h = 34
        _repeat_lbl_w = 36

        def _sound_basename(path: str, default_rel: str) -> str:
            """取提示音文件路径的 basename 用于按钮展示。"""
            p = (path or "").strip() or default_rel.replace("\\", "/")
            return os.path.basename(p.replace("\\", "/"))

        def _update_sound_btn_text(btn: QPushButton, path: str, default_rel: str) -> None:
            """更新提示音选择按钮的省略文件名与 tooltip。"""
            name = _sound_basename(path, default_rel)
            btn.setToolTip(name)
            avail = max(40, btn.width() - 12)
            btn.setText(QFontMetrics(btn.font()).elidedText(name, Qt.ElideMiddle, avail))

        sound_grid = QGridLayout()
        sound_grid.setContentsMargins(0, 0, 0, 0)
        sound_grid.setHorizontalSpacing(6)
        sound_grid.setVerticalSpacing(12)
        sound_grid.setColumnMinimumWidth(0, _sound_title_w)
        sound_grid.setColumnMinimumWidth(1, _sound_path_w)
        sound_grid.setColumnMinimumWidth(2, _repeat_lbl_w)
        sound_grid.setColumnMinimumWidth(3, _spin_w)
        sound_grid.setColumnMinimumWidth(4, _test_w)

        def _build_sound_row(
            row, title, tooltip, path_value, default_rel, repeat_value, tier,
            grid=sound_grid, test_callback=None,
        ):
            """构建预设提示音一行：标题、文件选择、重复次数与测试按钮。"""
            title_lbl = QLabel(title)
            _set_widget_style(title_lbl, STYLE_LABEL)
            title_lbl.setToolTip(tooltip)
            title_lbl.setFixedWidth(_sound_title_w)
            path_btn = QPushButton()
            path_btn.setCursor(Qt.PointingHandCursor)
            _set_widget_style(path_btn, STYLE_AUDIO_FILE_BTN)
            path_btn.setFixedWidth(_sound_path_w)
            path_btn.setFixedHeight(_sound_row_h)
            path_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            path_btn.setProperty("_sound_path", path_value or "")
            path_btn.setProperty("_sound_default", default_rel)

            def _refresh_path_btn():
                """刷新路径按钮上的省略文件名显示。"""
                _update_sound_btn_text(
                    path_btn,
                    str(path_btn.property("_sound_path") or ""),
                    str(path_btn.property("_sound_default") or default_rel),
                )

            def _pick_sound():
                """打开文件对话框选择自定义提示音 WAV/MP3。"""
                start_dir = ""
                cur = (path_btn.property("_sound_path") or "").strip()
                if cur and os.path.isfile(cur):
                    start_dir = os.path.dirname(cur)
                elif get_resource_path(default_rel).is_file():
                    start_dir = str(get_resource_path(default_rel).parent)
                picked, _ = QFileDialog.getOpenFileName(
                    self, f"选择{title}", start_dir,
                    "音频文件 (*.wav *.mp3);;所有文件 (*.*)",
                )
                if picked:
                    path_btn.setProperty("_sound_path", picked)
                    _refresh_path_btn()

            path_btn.clicked.connect(_pick_sound)
            _refresh_path_btn()
            repeat_lbl = QLabel("重复")
            _set_widget_style(repeat_lbl, STYLE_LABEL)
            repeat_lbl.setFixedWidth(_repeat_lbl_w)
            repeat_lbl.setAlignment(Qt.AlignCenter)
            repeat_spin = QSpinBox()
            repeat_spin.setRange(1, 10)
            repeat_spin.setValue(max(1, min(10, int(repeat_value or 1))))
            repeat_spin.setFixedWidth(_spin_w)
            repeat_spin.setFixedHeight(_sound_row_h)
            _set_widget_style(repeat_spin, STYLE_SPINBOX)
            test_btn = QPushButton("测试")
            test_btn.setFixedWidth(_test_w)
            test_btn.setFixedHeight(_sound_row_h)
            _set_widget_style(test_btn, STYLE_AUDIO_COMPACT_BTN)

            def _test_sound():
                """保存设置后播放当前行对应分级的测试提示音。"""
                self._save_audio_settings()
                if test_callback is not None:
                    test_callback()
                    return
                from utils.audio_alert import play_alert_sound
                play_alert_sound(self.config, "warning", tier=tier, force=True)

            test_btn.clicked.connect(_test_sound)
            grid.addWidget(title_lbl, row, 0, Qt.AlignVCenter)
            grid.addWidget(path_btn, row, 1)
            grid.addWidget(repeat_lbl, row, 2, Qt.AlignVCenter)
            grid.addWidget(repeat_spin, row, 3)
            grid.addWidget(test_btn, row, 4)
            return path_btn, repeat_spin, test_btn

        felt_path_btn, felt_repeat_spin, _ = _build_sound_row(
            0, "有感预警", "震级低于 4.8 且报文烈度低于 7（或无报文烈度）时播放。",
            getattr(ac, 'felt_sound_path', '') or '', "media/eewalert.wav",
            int(getattr(ac, 'felt_sound_repeat', 1) or 1), "felt",
        )
        critical_path_btn, critical_repeat_spin, _ = _build_sound_row(
            1, "强震预警", "震级不低于 4.8 或报文烈度不低于 7 时播放。",
            getattr(ac, 'critical_sound_path', '') or '', "media/eewcritical.wav",
            int(getattr(ac, 'critical_sound_repeat', 1) or 1), "critical",
        )
        sound_outer.addLayout(sound_grid)

        nhk_group = QGroupBox()
        _prep_groupbox(nhk_group)
        nhk_outer = QVBoxLayout(nhk_group)
        nhk_outer.setContentsMargins(*GROUP_MARGINS)
        nhk_outer.setSpacing(8)
        nhk_title_lbl = QLabel("NHK 一级新闻铃")
        _set_widget_style(nhk_title_lbl, STYLE_SECTION_TITLE)
        nhk_desc_lbl = QLabel("仅地震情报，震度 6 弱及以上时播放。")
        nhk_desc_lbl.setToolTip("不含地震预警；与 JMA 警报音无关。")
        _set_widget_style(nhk_desc_lbl, STYLE_HINT)
        nhk_desc_lbl.setWordWrap(True)
        nhk_outer.addWidget(nhk_title_lbl)
        nhk_outer.addWidget(nhk_desc_lbl)

        nhk_sound_grid = QGridLayout()
        nhk_sound_grid.setContentsMargins(0, 0, 0, 0)
        nhk_sound_grid.setHorizontalSpacing(6)
        nhk_sound_grid.setVerticalSpacing(12)
        nhk_sound_grid.setColumnMinimumWidth(0, _sound_title_w)
        nhk_sound_grid.setColumnMinimumWidth(1, _sound_path_w)
        nhk_sound_grid.setColumnMinimumWidth(2, _repeat_lbl_w)
        nhk_sound_grid.setColumnMinimumWidth(3, _spin_w)
        nhk_sound_grid.setColumnMinimumWidth(4, _test_w)
        nhk_path_btn, nhk_repeat_spin, nhk_test_btn = _build_sound_row(
            0, "提示音", "仅 P2PQuake 日本气象厅地震情报（code 551），不含緊急地震速報。",
            getattr(ac, 'nhk_news_bell_path', '') or '', "media/NHK一級ニュースベル.wav",
            int(getattr(ac, 'nhk_news_bell_repeat', 1) or 1), "nhk",
            grid=nhk_sound_grid,
        )

        def _test_nhk_bell():
            from utils.audio_alert import play_nhk_news_bell
            self._save_audio_settings()
            play_nhk_news_bell(self.config, force=True)

        try:
            nhk_test_btn.clicked.disconnect()
        except TypeError:
            pass
        nhk_test_btn.clicked.connect(_test_nhk_bell)
        nhk_outer.addLayout(nhk_sound_grid)
        main_layout.addWidget(sound_group)
        main_layout.addWidget(nhk_group)

        jma_eew_group = QGroupBox()
        _prep_groupbox(jma_eew_group)
        jma_eew_outer = QVBoxLayout(jma_eew_group)
        jma_eew_outer.setContentsMargins(*GROUP_MARGINS)
        jma_eew_outer.setSpacing(8)
        jma_eew_title_lbl = QLabel("JMA 紧急地震速报警报音")
        _set_widget_style(jma_eew_title_lbl, STYLE_SECTION_TITLE)
        jma_eew_desc_lbl = QLabel("予報升为警報时播放（含首报即为警報）。")
        jma_eew_desc_lbl.setToolTip("与 NHK 一级新闻铃无关；一级新闻铃仅用于地震情报。")
        _set_widget_style(jma_eew_desc_lbl, STYLE_HINT)
        jma_eew_desc_lbl.setWordWrap(True)
        jma_eew_outer.addWidget(jma_eew_title_lbl)
        jma_eew_outer.addWidget(jma_eew_desc_lbl)

        jma_eew_sound_grid = QGridLayout()
        jma_eew_sound_grid.setContentsMargins(0, 0, 0, 0)
        jma_eew_sound_grid.setHorizontalSpacing(6)
        jma_eew_sound_grid.setVerticalSpacing(12)
        jma_eew_sound_grid.setColumnMinimumWidth(0, _sound_title_w)
        jma_eew_sound_grid.setColumnMinimumWidth(1, _sound_path_w)
        jma_eew_sound_grid.setColumnMinimumWidth(2, _repeat_lbl_w)
        jma_eew_sound_grid.setColumnMinimumWidth(3, _spin_w)
        jma_eew_sound_grid.setColumnMinimumWidth(4, _test_w)
        def _test_jma_eew_alert():
            from utils.audio_alert import play_jma_eew_alert_sound
            play_jma_eew_alert_sound(self.config, force=True)

        jma_eew_path_btn, jma_eew_repeat_spin, jma_eew_test_btn = _build_sound_row(
            0, "提示音", "JMA / Wolfx JMA 緊急地震速報升级为警報时播放。",
            getattr(ac, 'jma_eew_alert_sound_path', '') or '', "media/NHK緊急地震速報の音.wav",
            int(getattr(ac, 'jma_eew_alert_sound_repeat', 2) or 2), "jma_eew_alert",
            grid=jma_eew_sound_grid,
            test_callback=_test_jma_eew_alert,
        )
        jma_eew_outer.addLayout(jma_eew_sound_grid)
        main_layout.addWidget(jma_eew_group)

        tts_group = QGroupBox("语音播报 (TTS)")
        _prep_groupbox(tts_group)
        tts_outer = QVBoxLayout(tts_group)
        tts_outer.setContentsMargins(*GROUP_MARGINS)
        tts_outer.setSpacing(6)
        tts_hint = QLabel("预警/速报精简朗读；气象/海啸与字幕一致。")
        tts_hint.setToolTip("需 Windows 10+ 且中文语音包。气象/海啸不含左侧图标。")
        _set_widget_style(tts_hint, STYLE_HINT)
        tts_hint.setWordWrap(True)
        tts_outer.addWidget(tts_hint)

        def _form_row(label_text: str, widget: QWidget, parent: QWidget) -> QWidget:
            """TTS 设置区：固定宽度标签 + 控件的单行表单。"""
            row = QWidget(parent)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(_tts_field_gap)
            lbl = QLabel(label_text)
            _set_widget_style(lbl, STYLE_LABEL)
            lbl.setFixedWidth(_tts_lbl_w)
            row_layout.addWidget(lbl)
            row_layout.addWidget(widget, 1)
            return row

        tts_rate_spin = QSpinBox(tts_group)
        tts_rate_spin.setRange(80, 300)
        tts_rate_spin.setValue(max(80, min(300, int(getattr(ac, 'tts_rate', 150) or 150))))
        tts_rate_spin.setSuffix(" 字/分")
        _set_widget_style(tts_rate_spin, STYLE_SPINBOX)
        tts_rate_spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tts_outer.addWidget(_form_row("语速", tts_rate_spin, tts_group))

        tts_repeat_row = QWidget(tts_group)
        tts_repeat_grid = QGridLayout(tts_repeat_row)
        tts_repeat_grid.setContentsMargins(0, 0, 0, 0)
        tts_repeat_grid.setHorizontalSpacing(_tts_field_gap)
        tts_repeat_grid.setVerticalSpacing(4)
        tts_repeat_grid.setColumnMinimumWidth(0, _tts_lbl_w)
        tts_repeat_grid.setColumnStretch(2, 1)

        def _add_tts_repeat_cell(parent, label, value):
            """TTS 连播区：标签 + SpinBox 单元格，返回容器与 spin 引用。"""
            cell = QWidget(parent)
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(2)
            lbl = QLabel(label)
            _set_widget_style(lbl, STYLE_LABEL)
            spin = QSpinBox(cell)
            spin.setRange(1, 10)
            spin.setValue(max(1, min(10, int(value or 1))))
            spin.setFixedWidth(_spin_w)
            _set_widget_style(spin, STYLE_SPINBOX)
            cell_layout.addWidget(lbl)
            cell_layout.addWidget(spin)
            return cell, spin

        tts_repeat_cells = QWidget(tts_repeat_row)
        tts_repeat_cells_grid = QGridLayout(tts_repeat_cells)
        tts_repeat_cells_grid.setContentsMargins(0, 0, 0, 0)
        tts_repeat_cells_grid.setHorizontalSpacing(_tts_repeat_col_gap)
        tts_repeat_cells_grid.setVerticalSpacing(4)
        tts_repeat_cells_grid.setColumnStretch(2, 1)

        tts_repeat_lbl = QLabel("连播")
        _set_widget_style(tts_repeat_lbl, STYLE_LABEL)
        tts_repeat_lbl.setFixedWidth(_tts_lbl_w)
        warning_cell, warning_tts_repeat_spin = _add_tts_repeat_cell(
            tts_repeat_cells, "预警", int(getattr(ac, 'felt_tts_repeat', 1) or 1))
        report_cell, report_tts_repeat_spin = _add_tts_repeat_cell(
            tts_repeat_cells, "速报", int(getattr(ac, 'report_tts_repeat', 1) or 1))
        weather_cell, weather_tts_repeat_spin = _add_tts_repeat_cell(
            tts_repeat_cells, "气象", int(getattr(ac, 'weather_tts_repeat', 1) or 1))
        tsunami_cell, tsunami_tts_repeat_spin = _add_tts_repeat_cell(
            tts_repeat_cells, "海啸", int(getattr(ac, 'tsunami_tts_repeat', 1) or 1))
        tts_repeat_cells_grid.addWidget(warning_cell, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        tts_repeat_cells_grid.addWidget(report_cell, 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
        tts_repeat_cells_grid.addWidget(weather_cell, 1, 0, Qt.AlignLeft | Qt.AlignVCenter)
        tts_repeat_cells_grid.addWidget(tsunami_cell, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
        tts_repeat_cells.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tts_repeat_grid.addWidget(tts_repeat_lbl, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        tts_repeat_grid.addWidget(tts_repeat_cells, 0, 1, 2, 1)
        tts_outer.addWidget(tts_repeat_row)

        tts_policy_combo = QComboBox(tts_group)
        _set_widget_style(tts_policy_combo, STYLE_COMBOBOX)
        tts_policy_combo.addItem("智能（首报/变化）", "smart")
        tts_policy_combo.addItem("仅首报", "first_only")
        tts_policy_combo.addItem("每次更新", "always")
        policy = str(getattr(ac, 'tts_repeat_policy', 'smart') or 'smart')
        pidx = tts_policy_combo.findData(policy)
        tts_policy_combo.setCurrentIndex(pidx if pidx >= 0 else 0)
        tts_policy_combo.setToolTip(
            "适用于气象/海啸预警。\n"
            "智能：首报必播；内容变化时重播；否则受「同事件最短间隔」限制。\n"
            "仅首报：同一事件只朗读第一次。\n"
            "每次更新：每条更新都朗读，间隔不少于「同事件最短间隔」。\n"
            "地震预警：收到更新报即朗读，不受此策略与间隔限制。\n"
            "地震速报：收到即朗读，同一事件仅朗读一次（CENC 自动测定与正式测定分别朗读）。"
        )
        tts_policy_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tts_outer.addWidget(_form_row("重复策略", tts_policy_combo, tts_group))

        tts_cooldown_spin = QSpinBox(tts_group)
        tts_cooldown_spin.setRange(0, 600)
        tts_cooldown_spin.setValue(max(0, min(600, int(getattr(ac, 'tts_cooldown_seconds', 60) or 60))))
        tts_cooldown_spin.setSuffix(" 秒")
        _set_widget_style(tts_cooldown_spin, STYLE_SPINBOX)
        tts_cooldown_spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tts_cooldown_spin.setToolTip(
            "适用于气象/海啸预警的重复策略。\n"
            "智能策略下，同一事件内容未变化时，距上次播报至少间隔此秒数才会再次朗读。\n"
            "每次更新策略下，两次朗读的最小间隔（不少于 10 秒）。\n"
            "地震预警不受此间隔限制；地震速报按同事件去重，不使用此间隔。"
        )
        tts_outer.addWidget(_form_row("最短间隔", tts_cooldown_spin, tts_group))
        tts_cooldown_hint = QLabel("最短间隔仅作用于气象/海啸。")
        tts_cooldown_hint.setToolTip("预警更新报即朗读；速报按同事件去重（CENC 自动/正式测定分别朗读）。")
        _set_widget_style(tts_cooldown_hint, STYLE_HINT)
        tts_cooldown_hint.setWordWrap(True)
        tts_cooldown_hint_row = QWidget()
        tts_cooldown_hint_layout = QHBoxLayout(tts_cooldown_hint_row)
        tts_cooldown_hint_layout.setContentsMargins(0, 0, 0, 0)
        tts_cooldown_hint_layout.setSpacing(_tts_field_gap)
        tts_cooldown_hint_spacer = QWidget()
        tts_cooldown_hint_spacer.setFixedWidth(_tts_field_x)
        tts_cooldown_hint_layout.addWidget(tts_cooldown_hint_spacer)
        tts_cooldown_hint_layout.addWidget(tts_cooldown_hint, 1)
        tts_outer.addWidget(tts_cooldown_hint_row)

        tts_test_wrap = QWidget(tts_group)
        tts_test_v = QVBoxLayout(tts_test_wrap)
        tts_test_v.setContentsMargins(0, 0, 0, 0)
        tts_test_v.setSpacing(4)
        tts_test_row1 = QHBoxLayout()
        tts_test_row1.setContentsMargins(0, 0, 0, 0)
        tts_test_row1.setSpacing(6)
        tts_test_row2 = QHBoxLayout()
        tts_test_row2.setContentsMargins(0, 0, 0, 0)
        tts_test_row2.setSpacing(6)
        warning_tts_test_btn = QPushButton("预警")
        _set_widget_style(warning_tts_test_btn, STYLE_AUDIO_COMPACT_BTN)
        report_tts_test_btn = QPushButton("速报")
        _set_widget_style(report_tts_test_btn, STYLE_AUDIO_COMPACT_BTN)
        weather_tts_test_btn = QPushButton("气象")
        _set_widget_style(weather_tts_test_btn, STYLE_AUDIO_COMPACT_BTN)
        tsunami_tts_test_btn = QPushButton("海啸")
        _set_widget_style(tsunami_tts_test_btn, STYLE_AUDIO_COMPACT_BTN)
        for btn in (
            warning_tts_test_btn, report_tts_test_btn,
            weather_tts_test_btn, tsunami_tts_test_btn,
        ):
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tts_test_row1.addWidget(warning_tts_test_btn)
        tts_test_row1.addWidget(report_tts_test_btn)
        tts_test_row2.addWidget(weather_tts_test_btn)
        tts_test_row2.addWidget(tsunami_tts_test_btn)
        tts_test_v.addLayout(tts_test_row1)
        tts_test_v.addLayout(tts_test_row2)

        def _test_tts_kind(kind: str, label: str) -> None:
            """保存音频设置后，用内置样例测试 TTS。"""
            from utils.tts_alert import test_tts_from_latest
            self._save_audio_settings()
            if not test_tts_from_latest(self.config, kind):
                show_info(
                    self,
                    "测试朗读",
                    f"暂无{label}样例，请稍后再试。",
                )

        def _test_tts_warning():
            """测试预警类 TTS。"""
            _test_tts_kind("warning", "预警")

        def _test_tts_report():
            """测试速报类 TTS。"""
            _test_tts_kind("report", "速报")

        def _test_tts_weather():
            """测试气象预警 TTS。"""
            _test_tts_kind("weather", "气象")

        def _test_tts_tsunami():
            """测试海啸预警 TTS。"""
            _test_tts_kind("tsunami", "海啸")

        warning_tts_test_btn.clicked.connect(_test_tts_warning)
        report_tts_test_btn.clicked.connect(_test_tts_report)
        weather_tts_test_btn.clicked.connect(_test_tts_weather)
        tsunami_tts_test_btn.clicked.connect(_test_tts_tsunami)
        tts_test_row = QWidget(tts_group)
        tts_test_row_layout = QHBoxLayout(tts_test_row)
        tts_test_row_layout.setContentsMargins(0, 0, 0, 0)
        tts_test_row_layout.setSpacing(_tts_field_gap)
        tts_test_lbl = QLabel("测试")
        _set_widget_style(tts_test_lbl, STYLE_LABEL)
        tts_test_lbl.setFixedWidth(_tts_lbl_w)
        tts_test_lbl.setAlignment(Qt.AlignTop)
        tts_test_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tts_test_row_layout.addWidget(tts_test_lbl)
        tts_test_row_layout.addWidget(tts_test_wrap, 1)
        tts_outer.addWidget(tts_test_row)
        main_layout.addWidget(tts_group)

        self.audio_vars = {
            'feedback_sound_radio': feedback_sound_radio,
            'feedback_tts_radio': feedback_tts_radio,
            'tier_felt_cb': tier_felt_cb,
            'tier_critical_cb': tier_critical_cb,
            'tier_eew_cb': tier_eew_cb,
            'tier_report_cb': tier_report_cb,
            'tier_weather_cb': tier_weather_cb,
            'tier_tsunami_cb': tier_tsunami_cb,
            'felt_path_btn': felt_path_btn,
            'felt_repeat_spin': felt_repeat_spin,
            'critical_path_btn': critical_path_btn,
            'critical_repeat_spin': critical_repeat_spin,
            'nhk_news_bell_cb': nhk_news_bell_cb,
            'nhk_path_btn': nhk_path_btn,
            'nhk_repeat_spin': nhk_repeat_spin,
            'nhk_test_btn': nhk_test_btn,
            'jma_eew_alert_cb': jma_eew_alert_cb,
            'jma_eew_path_btn': jma_eew_path_btn,
            'jma_eew_repeat_spin': jma_eew_repeat_spin,
            'jma_eew_test_btn': jma_eew_test_btn,
            'tts_rate_spin': tts_rate_spin,
            'warning_tts_repeat_spin': warning_tts_repeat_spin,
            'report_tts_repeat_spin': report_tts_repeat_spin,
            'weather_tts_repeat_spin': weather_tts_repeat_spin,
            'tsunami_tts_repeat_spin': tsunami_tts_repeat_spin,
            'tts_policy_combo': tts_policy_combo,
            'tts_cooldown_spin': tts_cooldown_spin,
            'warning_tts_test_btn': warning_tts_test_btn,
            'report_tts_test_btn': report_tts_test_btn,
            'weather_tts_test_btn': weather_tts_test_btn,
            'tsunami_tts_test_btn': tsunami_tts_test_btn,
        }
        feedback_sound_radio.toggled.connect(lambda _: self._on_audio_feedback_mode_changed())
        feedback_tts_radio.toggled.connect(lambda _: self._on_audio_feedback_mode_changed())
        nhk_news_bell_cb.toggled.connect(lambda _: self._update_audio_mode_ui())
        jma_eew_alert_cb.toggled.connect(lambda _: self._update_audio_mode_ui())
        self._apply_tier_cb_from_config()
        self._update_audio_mode_ui()

        button_frame = QFrame()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 6, 0, 0)
        button_layout.addStretch()
        save_btn = QPushButton("保存音频设置")
        save_btn.setMinimumWidth(120)
        save_btn.setMinimumHeight(35)
        _set_widget_style(save_btn, STYLE_SAVE_BTN)
        save_btn.clicked.connect(self._save_audio_settings_and_persist)
        button_layout.addWidget(save_btn)
        button_layout.addStretch()
        main_layout.addWidget(button_frame)

        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "音频")

    def _save_audio_settings(self) -> None:
        """从 audio_vars 写回 Config.alert_config（不持久化）。"""
        av = getattr(self, 'audio_vars', {}) or {}
        if not av:
            return
        ac = self.config.alert_config
        tts_radio = av.get('feedback_tts_radio')
        if tts_radio is not None and tts_radio.isChecked():
            ac.alert_feedback_mode = 'tts'
        else:
            ac.alert_feedback_mode = 'sound'
        self._write_tier_cbs_to_config()
        for btn_key, attr in (
            ('felt_path_btn', 'felt_sound_path'),
            ('critical_path_btn', 'critical_sound_path'),
            ('nhk_path_btn', 'nhk_news_bell_path'),
            ('jma_eew_path_btn', 'jma_eew_alert_sound_path'),
        ):
            btn = av.get(btn_key)
            if btn is not None:
                setattr(ac, attr, (btn.property("_sound_path") or "").strip())
        nhk_cb = av.get('nhk_news_bell_cb')
        if nhk_cb is not None:
            ac.nhk_news_bell_enabled = bool(nhk_cb.isChecked())
        jma_eew_cb = av.get('jma_eew_alert_cb')
        if jma_eew_cb is not None:
            ac.jma_eew_alert_sound_enabled = bool(jma_eew_cb.isChecked())
        for spin_key, attr, lo, hi in (
            ('felt_repeat_spin', 'felt_sound_repeat', 1, 10),
            ('critical_repeat_spin', 'critical_sound_repeat', 1, 10),
            ('nhk_repeat_spin', 'nhk_news_bell_repeat', 1, 10),
            ('jma_eew_repeat_spin', 'jma_eew_alert_sound_repeat', 1, 10),
            ('warning_tts_repeat_spin', 'felt_tts_repeat', 1, 10),
            ('report_tts_repeat_spin', 'report_tts_repeat', 1, 10),
            ('weather_tts_repeat_spin', 'weather_tts_repeat', 1, 10),
            ('tsunami_tts_repeat_spin', 'tsunami_tts_repeat', 1, 10),
            ('tts_rate_spin', 'tts_rate', 80, 300),
            ('tts_cooldown_spin', 'tts_cooldown_seconds', 0, 600),
        ):
            spin = av.get(spin_key)
            if spin is not None:
                setattr(ac, attr, max(lo, min(hi, int(spin.value()))))
        warning_spin = av.get('warning_tts_repeat_spin')
        if warning_spin is not None:
            ac.critical_tts_repeat = ac.felt_tts_repeat
        combo = av.get('tts_policy_combo')
        if combo is not None:
            ac.tts_repeat_policy = str(combo.currentData() or 'smart')
        ac.validate()

    def _save_audio_settings_and_persist(self) -> None:
        """保存音频设置并写入磁盘，弹出结果提示。"""
        self._save_audio_settings()
        if self.config.save_config():
            self._clear_settings_dirty()
            show_info(self, "成功", "音频设置已保存")
        else:
            show_warning(self, "错误", "音频设置保存失败")

    def _create_data_source_tab(self):
        """创建数据源设置标签页（主数据源二选一 + 全局辅助源）。"""
        scroll_area = _FittingScrollArea()
        scrollable_widget = QWidget()
        _prepare_scroll_body(scrollable_widget)
        scroll_layout = QVBoxLayout(scrollable_widget)
        scroll_layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        scroll_layout.setSpacing(SPACING_BLOCK)

        fanstudio_http_poll_sources = [
            (FANSTUDIO_TYPHOON_HTTP, "台风实时与历史数据"),
        ]
        jian_sources = list(JIAN_SUB_SOURCE_SPECS)

        # 顶部：主数据源三选一
        group_provider = QGroupBox("主数据源")
        _prep_groupbox(group_provider)
        gp_layout = QVBoxLayout(group_provider)
        gp_layout.setContentsMargins(*GROUP_MARGINS)
        gp_layout.setSpacing(GROUP_SPACING)
        provider_row = QHBoxLayout()
        provider_row.setSpacing(24)
        self.data_provider_group = QButtonGroup(self)
        self.radio_provider_fanstudio = QRadioButton("Fan Studio")
        self.radio_provider_whews = QRadioButton("WeJet")
        self.radio_provider_jian = QRadioButton("Jian Project")
        for rb in (self.radio_provider_fanstudio, self.radio_provider_whews, self.radio_provider_jian):
            _set_widget_style(rb, STYLE_PROVIDER_RADIO)
            provider_row.addWidget(rb)
        self.data_provider_group.addButton(self.radio_provider_fanstudio, 0)
        self.data_provider_group.addButton(self.radio_provider_whews, 1)
        self.data_provider_group.addButton(self.radio_provider_jian, 2)
        provider_row.addStretch()
        gp_layout.addLayout(provider_row)
        provider_hint = QLabel("三者择一；选中并保存后启用该主源连接，并清空缓冲重连。")
        provider_hint.setToolTip(
            "保存后仅连接当前主提供者。"
            "Wolfx / EQSC / P2PQuake / OpenQuakeAPI 为辅助源；可用总开关整体启停，开启后各分区全部展示。"
        )
        _set_widget_style(provider_hint, STYLE_HINT)
        provider_hint.setWordWrap(True)
        gp_layout.addWidget(provider_hint)
        scroll_layout.addWidget(group_provider)

        # ---------- Fan Studio 面板 ----------
        self.ds_panel_fanstudio = QWidget()
        apply_light_palette(self.ds_panel_fanstudio, COLOR_PAGE_BG, COLOR_TEXT)
        self.ds_panel_fanstudio.setAttribute(Qt.WA_StyledBackground, True)
        _set_widget_style(self.ds_panel_fanstudio, f"background-color: {COLOR_PAGE_BG};")
        fs_panel_layout = QVBoxLayout(self.ds_panel_fanstudio)
        fs_panel_layout.setContentsMargins(0, 0, 0, 0)
        fs_panel_layout.setSpacing(SPACING_BLOCK)

        group_warning = QGroupBox("Fan Studio")
        _prep_groupbox(group_warning)
        gw_layout = QVBoxLayout(group_warning)
        gw_layout.setContentsMargins(*GROUP_MARGINS)
        gw_layout.setSpacing(GROUP_SPACING)
        fs_apply_hint = QLabel(
            '需 API Key 鉴权。<a href="https://api.fanstudio.tech/dev-platform/" style="color: #3B82F6;">前往申请</a>'
        )
        fs_apply_hint.setToolTip("应用列表选择「地震情报实况栏」，填写信息等待审核。")
        fs_apply_hint.setOpenExternalLinks(True)
        _set_widget_style(fs_apply_hint, STYLE_HINT)
        fs_apply_hint.setWordWrap(True)
        gw_layout.addWidget(fs_apply_hint)
        fs_hint = QLabel("鉴权后接入完整数据流；下方子源决定解析范围。")
        fs_hint.setToolTip("未鉴权仅返回公开精简数据。主数据源选中 Fan Studio 并保存后即连接。")
        _set_widget_style(fs_hint, STYLE_HINT)
        fs_hint.setWordWrap(True)
        gw_layout.addWidget(fs_hint)

        api_key_label = QLabel("Fan Studio API Key：")
        _set_widget_style(api_key_label, STYLE_LABEL)
        gw_layout.addWidget(api_key_label)
        api_key_row = QHBoxLayout()
        api_key_row.setSpacing(8)
        self.fanstudio_api_key_entry = QLineEdit()
        self.fanstudio_api_key_entry.setPlaceholderText("sk- 开头的 API 密钥")
        self.fanstudio_api_key_entry.setEchoMode(QLineEdit.Password)
        self.fanstudio_api_key_entry.setText(
            getattr(self.config.ws_config, "fanstudio_api_key", "") or ""
        )
        _set_widget_style(self.fanstudio_api_key_entry, STYLE_LINEEDIT)
        self.fanstudio_api_key_entry.setToolTip(
            "连接 /all 后发送鉴权；未填写时仍可连接，但仅接收公开精简数据流。"
        )
        self.fanstudio_api_key_entry.textChanged.connect(
            lambda _text: self._refresh_fanstudio_auth_status_label(force=True)
        )
        api_key_row.addWidget(self.fanstudio_api_key_entry, 1)
        self.fanstudio_auth_btn = QPushButton("连接")
        _set_widget_style(self.fanstudio_auth_btn, STYLE_AUDIO_COMPACT_BTN)
        self.fanstudio_auth_btn.setToolTip("测试 API Key 鉴权（发送 auth 并等待 auth_success / error）")
        self.fanstudio_auth_btn.clicked.connect(self._on_fanstudio_auth_test_clicked)
        api_key_row.addWidget(self.fanstudio_auth_btn)
        gw_layout.addLayout(api_key_row)
        self.fanstudio_auth_status_label = QLabel("请输入 Key")
        _set_widget_style(self.fanstudio_auth_status_label, STYLE_HINT)
        self.fanstudio_auth_status_label.setWordWrap(True)
        gw_layout.addWidget(self.fanstudio_auth_status_label)
        self._refresh_fanstudio_auth_status_label(force=True)

        def _fs_cb(cfg_name: str, text: str) -> QCheckBox:
            """创建 Fan Studio 子源复选框行（含解析状态标签）。"""
            cb = QCheckBox(text)
            cb.setChecked(getattr(self.config.message_config, cfg_name, True))
            _set_widget_style(cb, STYLE_CHECKBOX_SOURCE)
            status_label = QLabel("未解析")
            _set_widget_style(status_label, STYLE_STATUS_NEUTRAL)
            status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            status_label.setToolTip("解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析")
            self.source_parse_labels[cfg_name] = status_label
            self.source_status_texts[cfg_name] = ("已解析", "未解析", "解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析")
            row_layout = QHBoxLayout()
            row_layout.addWidget(cb)
            row_layout.addStretch()
            row_layout.addWidget(status_label)
            gw_layout.addLayout(row_layout)
            return cb

        self.fanstudio_parse_cea_cb = _fs_cb('fanstudio_parse_cea', "中国地震预警网")
        self.fanstudio_parse_cea_pr_cb = _fs_cb('fanstudio_parse_cea_pr', "中国地震预警省网")
        self.fanstudio_parse_cwa_eew_cb = _fs_cb('fanstudio_parse_cwa_eew', "台湾气象署地震预警")
        self.fanstudio_parse_jma_cb = _fs_cb('fanstudio_parse_jma', "日本气象厅地震预警")
        self.fanstudio_parse_sa_cb = _fs_cb('fanstudio_parse_sa', "美国ShakeAlert地震预警")
        self.fanstudio_parse_kma_eew_cb = _fs_cb('fanstudio_parse_kma_eew', "韩国气象厅地震预警")
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
        fs_panel_layout.addWidget(group_warning)
        scroll_layout.addWidget(self.ds_panel_fanstudio)

        # ---------- WeJet 面板 ----------
        self.ds_panel_whews = QWidget()
        apply_light_palette(self.ds_panel_whews, COLOR_PAGE_BG, COLOR_TEXT)
        self.ds_panel_whews.setAttribute(Qt.WA_StyledBackground, True)
        _set_widget_style(self.ds_panel_whews, f"background-color: {COLOR_PAGE_BG};")
        wh_panel_layout = QVBoxLayout(self.ds_panel_whews)
        wh_panel_layout.setContentsMargins(0, 0, 0, 0)
        wh_panel_layout.setSpacing(SPACING_BLOCK)

        group_whews = QGroupBox("WeJet")
        _prep_groupbox(group_whews)
        wh_layout = QVBoxLayout(group_whews)
        wh_layout.setContentsMargins(*GROUP_MARGINS)
        wh_layout.setSpacing(GROUP_SPACING)
        wh_apply_hint = QLabel(
            '需 WAuth 令牌。推荐「统一登录」，或'
            '<a href="https://auth.beecld.com/login?redirect=%2Fprofile" style="color: #3B82F6;">个人中心</a>'
            '复制 wat_ 令牌。'
        )
        wh_apply_hint.setOpenExternalLinks(True)
        _set_widget_style(wh_apply_hint, STYLE_HINT)
        wh_apply_hint.setWordWrap(True)
        wh_layout.addWidget(wh_apply_hint)
        wh_hint = QLabel("填写令牌后保存生效；子源由下方勾选控制。")
        wh_hint.setToolTip("主数据源选中 WeJet 并保存后建连；建连后 5 秒内以纯文本发送令牌。JMA 预警/情报请用下方 P2PQuake。")
        _set_widget_style(wh_hint, STYLE_HINT)
        wh_hint.setWordWrap(True)
        wh_layout.addWidget(wh_hint)

        host_row = QHBoxLayout()
        host_row.setSpacing(16)
        host_label = QLabel("API 主机：")
        _set_widget_style(host_label, STYLE_LABEL)
        host_row.addWidget(host_label)
        self.whews_host_group = QButtonGroup(self)
        self.radio_whews_host_primary = QRadioButton("主站")
        self.radio_whews_host_backup = QRadioButton("国内站")
        self.radio_whews_host_primary.setToolTip(
            f"{WHEWS_HOST_PRIMARY}：/ws/all 走主站；CEA 仍固定连国内站 /ws/cea_all"
        )
        self.radio_whews_host_backup.setToolTip(
            f"{WHEWS_HOST_BACKUP}：/ws/all 与 CEA（/ws/cea_all）均走国内站"
        )
        for rb in (self.radio_whews_host_primary, self.radio_whews_host_backup):
            _set_widget_style(rb, STYLE_RADIO)
            host_row.addWidget(rb)
        self.whews_host_group.addButton(self.radio_whews_host_primary, 0)
        self.whews_host_group.addButton(self.radio_whews_host_backup, 1)
        host_row.addStretch()
        wh_layout.addLayout(host_row)
        cur_host = normalize_whews_host(getattr(self.config.ws_config, "whews_host", WHEWS_HOST_PRIMARY))
        if cur_host == WHEWS_HOST_BACKUP:
            self.radio_whews_host_backup.setChecked(True)
        else:
            self.radio_whews_host_primary.setChecked(True)

        token_label = QLabel("WeJet 令牌：")
        _set_widget_style(token_label, STYLE_LABEL)
        wh_layout.addWidget(token_label)
        self.whews_token_entry = QLineEdit()
        self.whews_token_entry.setPlaceholderText("wat_ 开头的令牌")
        self.whews_token_entry.setEchoMode(QLineEdit.Password)
        self.whews_token_entry.setText(getattr(self.config.ws_config, "whews_token", "") or "")
        _set_widget_style(self.whews_token_entry, STYLE_LINEEDIT)
        self.whews_token_entry.setToolTip("建连后以纯文本首帧发送；5 秒内未发送则断开；鉴权失败关闭码 4401")
        wh_layout.addWidget(self.whews_token_entry)

        login_row = QHBoxLayout()
        login_row.setSpacing(8)
        self.whews_login_btn = QPushButton("WeJet 统一登录")
        _set_widget_style(self.whews_login_btn, STYLE_SECONDARY_BTN)
        self.whews_login_btn.setToolTip(
            "打开浏览器完成 WAuth 登录，自动写入本应用专用 wat_ 令牌。"
            "开发者后台须登记回调：http://127.0.0.1:18765/callback"
        )
        self.whews_login_btn.clicked.connect(self._on_whews_unified_login)
        login_row.addWidget(self.whews_login_btn)
        self.whews_login_status = QLabel("")
        _set_widget_style(self.whews_login_status, STYLE_HINT)
        self.whews_login_status.setWordWrap(True)
        login_row.addWidget(self.whews_login_status, 1)
        wh_layout.addLayout(login_row)

        cea_hint = QLabel(
            "CEA / CEA-PR 固定经国内站 /ws/cea_all 自动鉴权（软件内置 App，一次完成两源），"
            "与上方主站/国内站选择无关；/ws/all 仍跟随所选主机。"
        )
        cea_hint.setWordWrap(True)
        _set_widget_style(cea_hint, STYLE_HINT)
        wh_layout.addWidget(cea_hint)

        self.whews_cea_auth_status_label = QLabel("CEA App 鉴权：未连接")
        _set_widget_style(self.whews_cea_auth_status_label, STYLE_HINT)
        self.whews_cea_auth_status_label.setWordWrap(True)
        wh_layout.addWidget(self.whews_cea_auth_status_label)
        self._refresh_whews_cea_auth_status_label(force=True)

        def _wh_cb(cfg_name: str, text: str) -> QCheckBox:
            """创建 WeJet 子源复选框行。"""
            cb = QCheckBox(text)
            cb.setChecked(getattr(self.config.message_config, cfg_name, True))
            _set_widget_style(cb, STYLE_CHECKBOX_SOURCE)
            status_label = QLabel("未解析")
            _set_widget_style(status_label, STYLE_STATUS_NEUTRAL)
            status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            status_label.setToolTip("解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析")
            self.source_parse_labels[cfg_name] = status_label
            self.source_status_texts[cfg_name] = ("已解析", "未解析", "解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析")
            row = QHBoxLayout()
            row.addWidget(cb)
            row.addStretch()
            row.addWidget(status_label)
            wh_layout.addLayout(row)
            return cb

        self.whews_parse_jma_eew_cb = _wh_cb("whews_parse_jma_eew", "日本气象厅地震预警")
        self.whews_parse_jma_cb = _wh_cb("whews_parse_jma", "日本气象厅地震情报")
        self.whews_parse_jma_volcano_cb = _wh_cb("whews_parse_jma_volcano", "日本气象厅火山情报")
        self.whews_parse_cwa_eew_cb = _wh_cb("whews_parse_cwa_eew", "台湾气象署地震预警")
        self.whews_parse_sa_eew_cb = _wh_cb("whews_parse_sa_eew", "美国 ShakeAlert 地震预警")
        self.whews_parse_kma_eew_cb = _wh_cb("whews_parse_kma_eew", "韩国气象厅地震预警")
        self.whews_parse_cea_cb = _wh_cb("whews_parse_cea", "中国地震预警网（CEA）")
        self.whews_parse_cea_pr_cb = _wh_cb("whews_parse_cea_pr", "中国地震预警省网（CEA-PR）")
        self.whews_parse_weatheralarm_cb = _wh_cb("whews_parse_weatheralarm", "中国气象局气象预警")
        self.whews_parse_tsunami_cb = _wh_cb("whews_parse_tsunami", "自然资源部海啸预警中心")
        self.whews_parse_ntwc_cb = _wh_cb("whews_parse_ntwc", "美国国家海啸预警中心 (NTWC)")
        self.whews_parse_ptwc_cb = _wh_cb("whews_parse_ptwc", "太平洋海啸预警中心 (PTWC)")
        self.whews_parse_incois_cb = _wh_cb("whews_parse_incois", "印度海啸早期预警中心 (INCOIS)")
        self.whews_parse_jma_tsunami_cb = _wh_cb("whews_parse_jma_tsunami", "日本气象厅海啸预警")
        self.whews_parse_cenc_cb = _wh_cb("whews_parse_cenc", "中国地震台网中心")
        self.whews_parse_cwa_cb = _wh_cb("whews_parse_cwa", "台湾气象署速报")
        self.whews_parse_hko_cb = _wh_cb("whews_parse_hko", "香港天文台速报")
        self.whews_parse_usgs_cb = _wh_cb("whews_parse_usgs", "美国地质调查局速报")

        self.whews_parse_emsc_cb = _wh_cb("whews_parse_emsc", "欧洲地中海地震中心速报")
        self.whews_parse_bcsf_cb = _wh_cb("whews_parse_bcsf", "法国中央地震研究所速报")
        self.whews_parse_gfz_cb = _wh_cb("whews_parse_gfz", "德国地学研究中心速报")
        self.whews_parse_usp_cb = _wh_cb("whews_parse_usp", "巴西圣保罗大学速报")
        self.whews_parse_kma_cb = _wh_cb("whews_parse_kma", "韩国气象厅速报")
        self.whews_parse_bmkg_cb = _wh_cb("whews_parse_bmkg", "BMKG 印尼地震速报")
        self.whews_parse_geonet_cb = _wh_cb("whews_parse_geonet", "GeoNet 新西兰地震速报")
        self.whews_parse_tmd_cb = _wh_cb("whews_parse_tmd", "泰国地震局速报")
        self.whews_parse_ingv_cb = _wh_cb("whews_parse_ingv", "INGV 意大利地震速报")
        self.whews_parse_nrcan_cb = _wh_cb("whews_parse_nrcan", "加拿大自然资源部速报")
        self.whews_parse_mmd_cb = _wh_cb("whews_parse_mmd", "马来西亚气象局速报")
        self.whews_parse_phivolcs_cb = _wh_cb("whews_parse_phivolcs", "菲律宾火山地震研究所速报")
        self.whews_parse_sgc_cb = _wh_cb("whews_parse_sgc", "哥伦比亚地质服务局速报")
        self.whews_parse_ga_cb = _wh_cb("whews_parse_ga", "澳大利亚地球科学局速报")
        self.whews_parse_cenais_cb = _wh_cb("whews_parse_cenais", "古巴国家地震研究中心速报")
        self.whews_parse_gsras_cb = _wh_cb("whews_parse_gsras", "希腊地震研究与监测中心速报")
        self.whews_parse_bgs_cb = _wh_cb("whews_parse_bgs", "英国地质调查局速报")
        self.whews_parse_ipma_cb = _wh_cb("whews_parse_ipma", "葡萄牙海洋与大气研究所速报")
        self.whews_parse_ssn_cb = _wh_cb("whews_parse_ssn", "墨西哥国家地震局速报")
        self.whews_parse_afad_cb = _wh_cb("whews_parse_afad", "土耳其灾害和应急管理总局速报")
        self.whews_parse_sed_cb = _wh_cb("whews_parse_sed", "瑞士地震局速报")
        self.whews_parse_noa_cb = _wh_cb("whews_parse_noa", "挪威地震阵列速报")
        self.whews_parse_scsn_cb = _wh_cb("whews_parse_scsn", "南加州地震网络速报")
        self.whews_parse_iag_cb = _wh_cb("whews_parse_iag", "阿根廷国家地震研究所速报")
        self.whews_parse_igp_cb = _wh_cb("whews_parse_igp", "秘鲁地质矿产与金属研究所速报")
        self.whews_parse_nepal_cb = _wh_cb("whews_parse_nepal", "尼泊尔地震局速报")
        self.whews_parse_typhoon_cb = _wh_cb("whews_parse_typhoon", "台风实况（/ws/typhoon）")
        self.whews_parse_beijing_cb = _wh_cb("whews_parse_beijing", "北京地震局速报")
        self.whews_parse_yunnan_cb = _wh_cb("whews_parse_yunnan", "云南地震局速报")
        self.whews_parse_ningxia_cb = _wh_cb("whews_parse_ningxia", "宁夏地震局速报")

        wh_panel_layout.addWidget(group_whews)
        scroll_layout.addWidget(self.ds_panel_whews)

        # ---------- Jian Project 面板 ----------
        self.ds_panel_jian = QWidget()
        apply_light_palette(self.ds_panel_jian, COLOR_PAGE_BG, COLOR_TEXT)
        self.ds_panel_jian.setAttribute(Qt.WA_StyledBackground, True)
        _set_widget_style(self.ds_panel_jian, f"background-color: {COLOR_PAGE_BG};")
        jp_panel_layout = QVBoxLayout(self.ds_panel_jian)
        jp_panel_layout.setContentsMargins(0, 0, 0, 0)
        jp_panel_layout.setSpacing(SPACING_BLOCK)

        group_jian_main = QGroupBox("Jian Project")
        _prep_groupbox(group_jian_main)
        gj_main_layout = QVBoxLayout(group_jian_main)
        gj_main_layout.setContentsMargins(*GROUP_MARGINS)
        gj_main_layout.setSpacing(GROUP_SPACING)
        jian_apply_hint = QLabel(
            '公开 WebSocket：<a href="https://api.sismotide.top/api/" style="color: #3B82F6;">'
            'api.sismotide.top</a>（无需令牌；测站数据不在此配置）'
        )
        jian_apply_hint.setOpenExternalLinks(True)
        _set_widget_style(jian_apply_hint, STYLE_HINT)
        jian_apply_hint.setWordWrap(True)
        gj_main_layout.addWidget(jian_apply_hint)

        def _jian_cb(cfg_name: str, text: str) -> QCheckBox:
            cb = QCheckBox(text)
            cb.setChecked(getattr(self.config.message_config, cfg_name, True))
            _set_widget_style(cb, STYLE_CHECKBOX_SOURCE)
            status_label = QLabel("未解析")
            _set_widget_style(status_label, STYLE_STATUS_NEUTRAL)
            status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            status_label.setToolTip("解析状态：本会话已解析到该源数据 / 尚未解析")
            self.source_parse_labels[cfg_name] = status_label
            self.source_status_texts[cfg_name] = ("已解析", "未解析", "解析状态：本会话已解析到该源数据 / 尚未解析")
            row = QHBoxLayout()
            row.addWidget(cb)
            row.addStretch()
            row.addWidget(status_label)
            gj_main_layout.addLayout(row)
            return cb

        for short, label in jian_sources:
            flag = JIAN_SHORT_TO_PARSE_FLAG.get(short)
            if not flag:
                continue
            setattr(self, f"{flag}_cb", _jian_cb(flag, label))
        jp_panel_layout.addWidget(group_jian_main)
        scroll_layout.addWidget(self.ds_panel_jian)

        # ---------- 辅助数据源（总开关 + Wolfx/EQSC/P2P 全部展开） ----------
        group_aux_provider = QGroupBox("辅助数据源")
        _prep_groupbox(group_aux_provider)
        gap_layout = QVBoxLayout(group_aux_provider)
        gap_layout.setContentsMargins(*GROUP_MARGINS)
        gap_layout.setSpacing(GROUP_SPACING)
        self.aux_sources_master_cb = QCheckBox("启用辅助数据源")
        self.aux_sources_master_cb.setChecked(
            aux_sources_enabled(self.config.enabled_sources)
        )
        self.aux_sources_master_cb.setToolTip(
            "关闭后隐藏下方辅助源分区，并停止连接 Wolfx、EQSC、P2PQuake、OpenQuakeAPI。"
        )
        _set_widget_style(self.aux_sources_master_cb, STYLE_CHECKBOX_SOURCE)
        gap_layout.addWidget(self.aux_sources_master_cb)
        aux_hint = QLabel(
            "含 Wolfx、EQSC、P2PQuake、OpenQuakeAPI；开启后各辅助源全部展示，可与任一主源并存。"
        )
        _set_widget_style(aux_hint, STYLE_HINT)
        aux_hint.setWordWrap(True)
        gap_layout.addWidget(aux_hint)
        scroll_layout.addWidget(group_aux_provider)
        self.group_aux_provider = group_aux_provider

        self.aux_panels_container = QWidget()
        apply_light_palette(self.aux_panels_container, COLOR_PAGE_BG, COLOR_TEXT)
        self.aux_panels_container.setAttribute(Qt.WA_StyledBackground, True)
        aux_container_layout = QVBoxLayout(self.aux_panels_container)
        aux_container_layout.setContentsMargins(0, 0, 0, 0)
        aux_container_layout.setSpacing(SPACING_BLOCK)

        self.aux_panel_wolfx = QWidget()
        apply_light_palette(self.aux_panel_wolfx, COLOR_PAGE_BG, COLOR_TEXT)
        self.aux_panel_wolfx.setAttribute(Qt.WA_StyledBackground, True)
        aw_layout = QVBoxLayout(self.aux_panel_wolfx)
        aw_layout.setContentsMargins(0, 0, 0, 0)
        aw_layout.setSpacing(SPACING_BLOCK)

        self.aux_panel_eqsc = QWidget()
        apply_light_palette(self.aux_panel_eqsc, COLOR_PAGE_BG, COLOR_TEXT)
        self.aux_panel_eqsc.setAttribute(Qt.WA_StyledBackground, True)
        ae_layout = QVBoxLayout(self.aux_panel_eqsc)
        ae_layout.setContentsMargins(0, 0, 0, 0)
        ae_layout.setSpacing(SPACING_BLOCK)

        self.aux_panel_p2p = QWidget()
        apply_light_palette(self.aux_panel_p2p, COLOR_PAGE_BG, COLOR_TEXT)
        self.aux_panel_p2p.setAttribute(Qt.WA_StyledBackground, True)
        ap_layout = QVBoxLayout(self.aux_panel_p2p)
        ap_layout.setContentsMargins(0, 0, 0, 0)
        ap_layout.setSpacing(SPACING_BLOCK)

        self.aux_panel_openquake = QWidget()
        apply_light_palette(self.aux_panel_openquake, COLOR_PAGE_BG, COLOR_TEXT)
        self.aux_panel_openquake.setAttribute(Qt.WA_StyledBackground, True)
        ao_layout = QVBoxLayout(self.aux_panel_openquake)
        ao_layout.setContentsMargins(0, 0, 0, 0)
        ao_layout.setSpacing(SPACING_BLOCK)

        # ---------- Wolfx 面板 ----------
        group_wolfx = QGroupBox("Wolfx")
        _prep_groupbox(group_wolfx)
        gw_layout = QVBoxLayout(group_wolfx)
        gw_layout.setContentsMargins(*GROUP_MARGINS)
        gw_layout.setSpacing(GROUP_SPACING)
        wolfx_hint = QLabel("预警与列表经 all_eew；台湾走独立通道。")
        wolfx_hint.setToolTip("中国地震台网/JMA 地震情報经 all_eew 推送，需同时勾选对应项。")
        _set_widget_style(wolfx_hint, STYLE_HINT)
        wolfx_hint.setWordWrap(True)
        gw_layout.addWidget(wolfx_hint)
        self.wolfx_all_connect_cb = QCheckBox("Wolfx")
        self.wolfx_all_connect_cb.setChecked(
            wolfx_master_enabled(self.config.enabled_sources)
        )
        _set_widget_style(self.wolfx_all_connect_cb, STYLE_CHECKBOX_SOURCE)
        gw_layout.addWidget(self.wolfx_all_connect_cb)

        def _wolfx_row(parse_key: str, title: str):
            """创建 Wolfx 子源复选框行（含解析状态标签）。"""
            cb = QCheckBox(title)
            cb.setChecked(getattr(self.config.message_config, parse_key, True))
            _set_widget_style(cb, STYLE_CHECKBOX_SOURCE)
            st = QLabel("未解析")
            _set_widget_style(st, STYLE_STATUS_NEUTRAL)
            st.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            st.setToolTip(
                "解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析"
            )
            self.source_parse_labels[parse_key] = st
            self.source_status_texts[parse_key] = (
                "已解析",
                "未解析",
                "解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析",
            )
            row = QHBoxLayout()
            row.addWidget(cb)
            row.addStretch()
            row.addWidget(st)
            gw_layout.addLayout(row)
            return cb

        self.ali_all_parse_nied_cb = _wolfx_row("ali_all_parse_nied", "緊急地震速報（JMA）")
        self.ali_all_parse_early_est_cb = _wolfx_row("ali_all_parse_early_est", "四川省地震局")
        self.ali_all_parse_jma_volcano_cb = _wolfx_row(
            "ali_all_parse_jma_volcano", "福建省地震局"
        )
        self.ali_all_parse_bmkg_cb = _wolfx_row("ali_all_parse_bmkg", "中国地震台网地震预警")
        self.ali_all_parse_cq_eew_cb = _wolfx_row("ali_all_parse_cq_eew", "重庆市地震局")
        self._add_source_checkbox(
            group_wolfx,
            WOLFX_CWA_EEW_URL,
            "台湾中央气象署",
            default_value=False,
        )
        self._add_source_checkbox(
            group_wolfx,
            WOLFX_CENC_EQLIST_URL,
            "中国地震台网地震信息",
            default_value=False,
            status_key=WOLFX_CENC_EQLIST_URL,
            status_tooltip="解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析",
            status_connected_text="已解析",
            status_disconnected_text="未解析",
        )
        self._add_source_checkbox(
            group_wolfx,
            WOLFX_JMA_EQLIST_URL,
            "JMA 地震情報",
            default_value=False,
            status_key=WOLFX_JMA_EQLIST_URL,
            status_tooltip="解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析",
            status_connected_text="已解析",
            status_disconnected_text="未解析",
        )
        aw_layout.addWidget(group_wolfx)

        group_history = QGroupBox("P2PQuake")
        _prep_groupbox(group_history)
        gh_layout = QVBoxLayout(group_history)
        gh_layout.setContentsMargins(*GROUP_MARGINS)
        gh_layout.setSpacing(GROUP_SPACING)
        p2p_hint = QLabel("勾选后连接；启动时 HTTP 补拉，之后靠 WSS。")
        p2p_hint.setToolTip("下方两项决定地震情報 / 津波予報是否参与解析。")
        _set_widget_style(p2p_hint, STYLE_HINT)
        p2p_hint.setWordWrap(True)
        gh_layout.addWidget(p2p_hint)
        p2p_wss_url = P2PQUAKE_WSS_URL
        p2p_status_col_w = 88
        self.p2pquake_connect_cb = QCheckBox("P2PQuake")
        self.p2pquake_connect_cb.setToolTip("启动 HTTP 补拉 + WebSocket")
        self.p2pquake_connect_cb.setChecked(p2pquake_master_enabled(self.config.enabled_sources))
        _set_widget_style(self.p2pquake_connect_cb, STYLE_CHECKBOX_SOURCE)
        gh_layout.addWidget(self.p2pquake_connect_cb)
        if p2p_wss_url not in self.individual_source_urls:
            self.individual_source_urls.append(p2p_wss_url)

        def _p2p_parse_row(parse_key: str, title: str) -> QCheckBox:
            """创建 P2PQuake 解析范围复选框行。"""
            cb = QCheckBox(title)
            cb.setChecked(getattr(self.config.message_config, parse_key, True))
            _set_widget_style(cb, STYLE_CHECKBOX_SOURCE)
            st = QLabel("未解析")
            st.setMinimumWidth(p2p_status_col_w)
            st.setFixedWidth(p2p_status_col_w)
            _set_widget_style(st, STYLE_STATUS_NEUTRAL)
            st.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            st.setToolTip("解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析")
            self.source_parse_labels[parse_key] = st
            self.source_status_texts[parse_key] = ("已解析", "未解析", "解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析")
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
        self.p2pquake_parse_556_cb = _p2p_parse_row("p2pquake_parse_556", "P2PQuake 日本气象厅 緊急地震速報")
        ap_layout.addWidget(group_history)

        # CENC 烈度速报（Nowquake）
        group_cenc_ir = QGroupBox("CENC 烈度速报")
        _prep_groupbox(group_cenc_ir)
        gci_layout = QVBoxLayout(group_cenc_ir)
        gci_layout.setContentsMargins(*GROUP_MARGINS)
        gci_layout.setSpacing(GROUP_SPACING)
        cenc_ir_hint = QLabel("经 Nowquake 接入 CENC 烈度速报。")
        cenc_ir_hint.setToolTip("WebSocket 推送；建连时 HTTP 拉取最新一条。数据仅供参考。")
        _set_widget_style(cenc_ir_hint, STYLE_HINT)
        cenc_ir_hint.setWordWrap(True)
        gci_layout.addWidget(cenc_ir_hint)
        self._add_source_checkbox(
            group_cenc_ir,
            NOWQUAKE_CENCINT_WSS_URL,
            "CENC 烈度速报（Nowquake）",
            default_value=False,
            status_key=NOWQUAKE_CENCINT_WSS_URL,
            status_tooltip="连接状态：已启用 / 未启用",
            status_connected_text="已启用",
            status_disconnected_text="未启用",
        )

        # EQSC 面板
        group_eqsc = QGroupBox("EQSC")
        _prep_groupbox(group_eqsc)
        ge_layout = QVBoxLayout(group_eqsc)
        ge_layout.setContentsMargins(*GROUP_MARGINS)
        ge_layout.setSpacing(GROUP_SPACING)
        eqsc_hint = QLabel(
            'HTTP 轮询（官方称 WebSocket 不稳定故不用）。登录密钥在 '
            '<a href="https://equake.top/auth" style="color: #3B82F6;">equake.top/auth</a>'
            ' 申请；软件自动换取 AccessToken。'
        )
        eqsc_hint.setOpenExternalLinks(True)
        _set_widget_style(eqsc_hint, STYLE_HINT)
        eqsc_hint.setWordWrap(True)
        ge_layout.addWidget(eqsc_hint)

        eqsc_token_label = QLabel("EQSC 登录密钥：")
        _set_widget_style(eqsc_token_label, STYLE_LABEL)
        ge_layout.addWidget(eqsc_token_label)
        eqsc_token_row = QHBoxLayout()
        eqsc_token_row.setSpacing(8)
        self.eqsc_login_token_entry = QLineEdit()
        self.eqsc_login_token_entry.setPlaceholderText("在 equake.top/auth 申请的登录密钥")
        self.eqsc_login_token_entry.setEchoMode(QLineEdit.Password)
        self.eqsc_login_token_entry.setText(
            getattr(self.config.ws_config, "eqsc_login_token", "") or ""
        )
        _set_widget_style(self.eqsc_login_token_entry, STYLE_LINEEDIT)
        self.eqsc_login_token_entry.setToolTip(
            "仅填写登录密钥；软件内部自动换取 AccessToken 用于 HTTP 鉴权。"
        )
        self.eqsc_login_token_entry.textChanged.connect(
            lambda _text: self._refresh_eqsc_auth_status_label(force=True)
        )
        eqsc_token_row.addWidget(self.eqsc_login_token_entry, 1)
        self.eqsc_auth_btn = QPushButton("连接")
        _set_widget_style(self.eqsc_auth_btn, STYLE_AUDIO_COMPACT_BTN)
        self.eqsc_auth_btn.setToolTip("测试登录密钥并换取 AccessToken")
        self.eqsc_auth_btn.clicked.connect(self._on_eqsc_auth_test_clicked)
        eqsc_token_row.addWidget(self.eqsc_auth_btn)
        ge_layout.addLayout(eqsc_token_row)
        self.eqsc_auth_status_label = QLabel("请输入登录密钥")
        _set_widget_style(self.eqsc_auth_status_label, STYLE_HINT)
        self.eqsc_auth_status_label.setWordWrap(True)
        ge_layout.addWidget(self.eqsc_auth_status_label)
        self._refresh_eqsc_auth_status_label(force=True)

        self._add_source_checkbox(
            group_eqsc,
            EQSC_HTTP_MASTER,
            "EQSC HTTP 轮询",
            default_value=False,
            status_key=EQSC_HTTP_MASTER,
            status_tooltip="启用状态：已启用 / 未启用（勾选后按下方子项 HTTP 轮询）",
            status_connected_text="已启用",
            status_disconnected_text="未启用",
        )

        eqsc_status_col_w = 88

        def _eqsc_parse_row(parse_key: str, title: str, default: bool = True) -> QCheckBox:
            """创建 EQSC 解析范围复选框行。"""
            cb = QCheckBox(title)
            cb.setChecked(getattr(self.config.message_config, parse_key, default))
            _set_widget_style(cb, STYLE_CHECKBOX_SOURCE)
            st = QLabel("未解析")
            st.setMinimumWidth(eqsc_status_col_w)
            st.setFixedWidth(eqsc_status_col_w)
            _set_widget_style(st, STYLE_STATUS_NEUTRAL)
            st.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            st.setToolTip("解析状态：本会话已解析到该源数据（含 initial；过期未上屏也算） / 尚未解析")
            self.source_parse_labels[parse_key] = st
            self.source_status_texts[parse_key] = (
                "已解析",
                "未解析",
                "解析状态：本会话已解析到该源数据（含 initial；过期未上屏也算） / 尚未解析",
            )
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(cb)
            row.addStretch()
            row.addWidget(st)
            ge_layout.addLayout(row)
            cb.stateChanged.connect(self._update_parse_status_labels)
            return cb

        self.eqsc_parse_jma_eew_cb = _eqsc_parse_row("eqsc_parse_jma_eew", "JMA 紧急地震速报")
        self.eqsc_parse_jma_report_cb = _eqsc_parse_row("eqsc_parse_jma_report", "JMA 地震情报")
        self.eqsc_parse_jma_tsunami_cb = _eqsc_parse_row("eqsc_parse_jma_tsunami", "JMA 海啸情报")
        self.eqsc_parse_cenc_cb = _eqsc_parse_row("eqsc_parse_cenc", "CENC 地震列表")
        self.eqsc_parse_cenc_ir_cb = _eqsc_parse_row("eqsc_parse_cenc_ir", "CENC 烈度速报")
        self.eqsc_parse_cwa_cb = _eqsc_parse_row("eqsc_parse_cwa", "CWA 地震列表")
        self.eqsc_parse_hko_cb = _eqsc_parse_row("eqsc_parse_hko", "HKO 地震列表")
        self.eqsc_parse_usgs_cb = _eqsc_parse_row("eqsc_parse_usgs", "USGS 地震列表")
        self.eqsc_parse_emsc_cb = _eqsc_parse_row("eqsc_parse_emsc", "EMSC 地震列表")
        self.eqsc_parse_typhoon_cb = _eqsc_parse_row("eqsc_parse_typhoon", "NMC 台风")
        self.eqsc_parse_volcano_cb = _eqsc_parse_row("eqsc_parse_volcano", "JMA 火山", default=False)
        eqsc_poll_sources = [
            (url, label)
            for url, label in (
                (EQSC_HTTP_SOURCE_KEYS[0], "JMA EEW"),
                (EQSC_HTTP_SOURCE_KEYS[1], "JMA 情报"),
                (EQSC_HTTP_SOURCE_KEYS[2], "JMA 海啸"),
                (EQSC_HTTP_SOURCE_KEYS[3], "CENC"),
                (EQSC_HTTP_SOURCE_KEYS[4], "CENC 烈度"),
                (EQSC_HTTP_SOURCE_KEYS[5], "CWA"),
                (EQSC_HTTP_SOURCE_KEYS[6], "HKO"),
                (EQSC_HTTP_SOURCE_KEYS[7], "USGS"),
                (EQSC_HTTP_SOURCE_KEYS[8], "EMSC"),
                (EQSC_HTTP_SOURCE_KEYS[9], "台风"),
                (EQSC_HTTP_SOURCE_KEYS[10], "火山"),
            )
        ]
        self._add_http_poll_interval_grid(ge_layout, eqsc_poll_sources)
        ae_layout.addWidget(group_eqsc)

        # OpenQuakeAPI 面板
        group_openquake = QGroupBox("OpenQuakeAPI")
        _prep_groupbox(group_openquake)
        go_layout = QVBoxLayout(group_openquake)
        go_layout.setContentsMargins(*GROUP_MARGINS)
        go_layout.setSpacing(GROUP_SPACING)
        oq_hint = QLabel(
            '经 '
            '<a href="https://docs.aloys23.link/docs/openquake/overview" style="color: #3B82F6;">'
            "OpenQuakeAPI</a> /ws/all 聚合推送：GlobalQuake、NMEFC 海啸/海浪/风暴潮、CMA 气象预警。"
        )
        oq_hint.setOpenExternalLinks(True)
        _set_widget_style(oq_hint, STYLE_HINT)
        oq_hint.setWordWrap(True)
        go_layout.addWidget(oq_hint)
        oq_status_col_w = 88
        self.openquake_connect_cb = QCheckBox("OpenQuakeAPI")
        self.openquake_connect_cb.setToolTip("连接 wss://api.aloys23.link/ws/all")
        self.openquake_connect_cb.setChecked(
            openquake_master_enabled(self.config.enabled_sources)
        )
        _set_widget_style(self.openquake_connect_cb, STYLE_CHECKBOX_SOURCE)
        go_layout.addWidget(self.openquake_connect_cb)
        if OPENQUAKE_WS_ALL_URL not in self.individual_source_urls:
            self.individual_source_urls.append(OPENQUAKE_WS_ALL_URL)

        def _oq_parse_row(parse_key: str, title: str, default: bool = True) -> QCheckBox:
            """创建 OpenQuakeAPI 解析范围复选框行。"""
            cb = QCheckBox(title)
            cb.setChecked(getattr(self.config.message_config, parse_key, default))
            _set_widget_style(cb, STYLE_CHECKBOX_SOURCE)
            st = QLabel("未解析")
            st.setMinimumWidth(oq_status_col_w)
            st.setFixedWidth(oq_status_col_w)
            _set_widget_style(st, STYLE_STATUS_NEUTRAL)
            st.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            st.setToolTip(
                "解析状态：本会话已解析到该源数据（含过期未上屏） / 尚未解析"
            )
            self.source_parse_labels[parse_key] = st
            self.source_status_texts[parse_key] = (
                "已解析",
                "未解析",
                "解析状态：本会话已解析到该源数据（含过期未上屏） / 尚未解析",
            )
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(cb)
            row.addStretch()
            row.addWidget(st)
            go_layout.addLayout(row)
            cb.stateChanged.connect(self._update_parse_status_labels)
            return cb

        self.openquake_parse_gq_cb = _oq_parse_row(
            "openquake_parse_gq", "GlobalQuake 全球地震预警"
        )
        gq_mag_row = QHBoxLayout()
        gq_mag_row.setContentsMargins(24, 0, 0, 0)
        gq_mag_label = QLabel("GQ 震级阈值：")
        _set_widget_style(gq_mag_label, STYLE_LABEL)
        gq_mag_row.addWidget(gq_mag_label)
        self.openquake_gq_min_magnitude_spin = QDoubleSpinBox()
        self.openquake_gq_min_magnitude_spin.setRange(0.0, 10.0)
        self.openquake_gq_min_magnitude_spin.setSingleStep(0.1)
        self.openquake_gq_min_magnitude_spin.setDecimals(1)
        self.openquake_gq_min_magnitude_spin.setValue(
            float(getattr(self.config.message_config, "openquake_gq_min_magnitude", 4.5) or 0.0)
        )
        self.openquake_gq_min_magnitude_spin.setToolTip(
            "仅作用于 GlobalQuake 地震预警；0 表示不限制。与「显示」页全局速报震级过滤相互独立。"
        )
        _set_widget_style(self.openquake_gq_min_magnitude_spin, STYLE_SPINBOX)
        gq_mag_row.addWidget(self.openquake_gq_min_magnitude_spin)
        gq_mag_hint = QLabel("（0=不限制）")
        _set_widget_style(gq_mag_hint, STYLE_HINT)
        gq_mag_row.addWidget(gq_mag_hint)
        gq_mag_row.addStretch()
        go_layout.addLayout(gq_mag_row)
        self.openquake_parse_nmefc_cb = _oq_parse_row(
            "openquake_parse_nmefc", "NMEFC 海啸预警"
        )
        self.openquake_parse_nmefc_wave_cb = _oq_parse_row(
            "openquake_parse_nmefc_wave", "NMEFC 海浪警报"
        )
        self.openquake_parse_nmefc_surge_cb = _oq_parse_row(
            "openquake_parse_nmefc_surge", "NMEFC 风暴潮警报"
        )
        self.openquake_parse_cma_cb = _oq_parse_row(
            "openquake_parse_cma", "CMA 气象预警"
        )
        self._wire_weather_source_mutex()
        self._wire_jma_report_mutex()
        ao_layout.addWidget(group_openquake)

        # 台风 HTTP（全局）
        group_typhoon = QGroupBox("台风实时与历史数据")
        _prep_groupbox(group_typhoon)
        gt_layout = QVBoxLayout(group_typhoon)
        gt_layout.setContentsMargins(*GROUP_MARGINS)
        gt_layout.setSpacing(GROUP_SPACING)
        typhoon_hint = QLabel("经 Fan Studio HTTP 轮询台风数据（全局可用）。")
        typhoon_hint.setToolTip("与主数据源提供者无关，切换提供者后仍生效。")
        _set_widget_style(typhoon_hint, STYLE_HINT)
        typhoon_hint.setWordWrap(True)
        gt_layout.addWidget(typhoon_hint)
        self._add_source_checkbox(
            group_typhoon,
            FANSTUDIO_TYPHOON_HTTP,
            "台风实时与历史数据",
            default_value=True,
            status_key=FANSTUDIO_TYPHOON_HTTP,
            status_tooltip="解析状态：本会话已解析到该源数据 / 尚未解析",
            status_connected_text="已解析",
            status_disconnected_text="未解析",
        )
        self._add_http_poll_interval_grid(gt_layout, fanstudio_http_poll_sources)

        aux_container_layout.addWidget(self.aux_panel_wolfx)
        aux_container_layout.addWidget(self.aux_panel_eqsc)
        aux_container_layout.addWidget(self.aux_panel_p2p)
        aux_container_layout.addWidget(self.aux_panel_openquake)
        scroll_layout.addWidget(self.aux_panels_container)
        scroll_layout.addWidget(group_cenc_ir)
        scroll_layout.addWidget(group_typhoon)

        provider = normalize_data_provider(
            getattr(self.config, "data_provider", DATA_PROVIDER_FANSTUDIO)
        )
        if provider == DATA_PROVIDER_WHEWS:
            self.radio_provider_whews.setChecked(True)
        elif provider == DATA_PROVIDER_JIAN:
            self.radio_provider_jian.setChecked(True)
        else:
            self.radio_provider_fanstudio.setChecked(True)

        def _update_data_provider_panels_visible():
            """切换主数据源时显示/隐藏 Fan Studio / WeJet / Jian Project 面板。"""
            self.ds_panel_fanstudio.setVisible(self.radio_provider_fanstudio.isChecked())
            self.ds_panel_whews.setVisible(self.radio_provider_whews.isChecked())
            self.ds_panel_jian.setVisible(self.radio_provider_jian.isChecked())

        def _update_aux_panels_visible():
            """辅助总开关：关闭时隐藏各分区；开启时全部展示。"""
            on = True
            if hasattr(self, "aux_sources_master_cb"):
                on = self.aux_sources_master_cb.isChecked()
            if hasattr(self, "aux_panels_container"):
                self.aux_panels_container.setVisible(on)
            if hasattr(self, "aux_panel_wolfx"):
                self.aux_panel_wolfx.setVisible(on)
            if hasattr(self, "aux_panel_eqsc"):
                self.aux_panel_eqsc.setVisible(on)
            if hasattr(self, "aux_panel_p2p"):
                self.aux_panel_p2p.setVisible(on)
            if hasattr(self, "aux_panel_openquake"):
                self.aux_panel_openquake.setVisible(on)

        self._update_aux_panels_visible = _update_aux_panels_visible

        self.radio_provider_fanstudio.toggled.connect(lambda _: _update_data_provider_panels_visible())
        self.radio_provider_whews.toggled.connect(lambda _: _update_data_provider_panels_visible())
        self.radio_provider_jian.toggled.connect(lambda _: _update_data_provider_panels_visible())
        self.aux_sources_master_cb.toggled.connect(lambda _: _update_aux_panels_visible())
        _update_data_provider_panels_visible()
        _update_aux_panels_visible()

        scroll_layout.addStretch()

        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 10, 0, 0)
        button_layout.addStretch()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setMinimumWidth(100)
        self.select_all_btn.setMinimumHeight(35)
        _set_widget_style(self.select_all_btn, STYLE_SELECT_ALL_BTN)
        self.select_all_btn.clicked.connect(self._toggle_select_all)
        button_layout.addWidget(self.select_all_btn)
        button_layout.addSpacing(10)
        save_btn = QPushButton("保存")
        save_btn.setMinimumWidth(120)
        save_btn.setMinimumHeight(35)
        _set_widget_style(save_btn, STYLE_SAVE_BTN)
        save_btn.clicked.connect(self._save_data_source_settings)
        button_layout.addWidget(save_btn)
        button_layout.addStretch()
        scroll_layout.addWidget(button_frame)

        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "数据源")
        self._update_parse_status_labels()

    def _current_whews_host_from_ui(self) -> str:
        """从设置页读取 WeJet 主机。"""
        if hasattr(self, "radio_whews_host_backup") and self.radio_whews_host_backup.isChecked():
            return WHEWS_HOST_BACKUP
        return WHEWS_HOST_PRIMARY

    def _on_whews_unified_login(self) -> None:
        """打开浏览器完成 WeJet WAuth 统一登录，自动填入 wat_ 令牌。"""
        if getattr(self, "_whews_login_worker", None) is not None:
            show_info(
                self,
                "提示",
                "正在等待浏览器完成登录。\n"
                "请确认浏览器最终跳转到本地回调页：\n"
                "http://127.0.0.1:18765/callback\n"
                "（仅登录 WeJet 个人中心不算完成统一登录）",
            )
            return
        btn = getattr(self, "whews_login_btn", None)
        status = getattr(self, "whews_login_status", None)
        if btn is not None:
            btn.setEnabled(False)
        if status is not None:
            status.setText("正在打开浏览器，请在网页中完成登录…")

        thread = QThread(self)
        worker = _WAuthLoginWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def _on_progress(msg: str) -> None:
            if status is not None and msg:
                status.setText(msg)

        def _on_finished(result) -> None:
            """登录结束后回填令牌；线程退出由 finished 信号链清理。"""
            try:
                if btn is not None:
                    btn.setEnabled(True)
                ok = bool(getattr(result, "ok", False))
                message = str(getattr(result, "message", "") or "")
                token = str(getattr(result, "api_token", "") or "").strip()
                if status is not None:
                    status.setText(message)
                if ok and token and hasattr(self, "whews_token_entry"):
                    self.whews_token_entry.setText(token)
                    self.config.ws_config.whews_token = token
                    # 登录成功后立即落盘，避免用户只点保存但令牌尚未回填
                    saved = False
                    try:
                        saved = bool(self.config.save_config())
                    except Exception as e:
                        logger.warning(f"统一登录后自动保存令牌失败: {e}")
                    if saved:
                        self._clear_settings_dirty()
                        try:
                            self.config._notify_config_changed()
                        except Exception:
                            pass
                        if status is not None:
                            status.setText(f"{message}（令牌已自动保存）")
                        show_info(
                            self,
                            "成功",
                            f"{message}\n令牌已写入并保存；将主数据源选为 WeJet 并保存后即可生效。",
                        )
                    else:
                        self._mark_settings_dirty()
                        show_info(
                            self,
                            "成功",
                            f"{message}\n令牌已填入，但自动保存失败，请再点一次「保存」。",
                        )
                elif not ok:
                    show_warning(
                        self,
                        "登录失败",
                        message
                        + "\n\n若提示 redirect_uri 无效，请在 WAuth 开发者后台为本应用登记：\n"
                        "http://127.0.0.1:18765/callback",
                    )
            finally:
                self._whews_login_worker = None
                self._whews_login_thread = None

        worker.progress.connect(_on_progress)
        worker.finished.connect(_on_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._whews_login_worker = worker
        self._whews_login_thread = thread
        thread.start()

    def _current_data_provider_from_ui(self) -> str:
        """从设置页单选框读取当前数据源提供者。"""
        if hasattr(self, "radio_provider_jian") and self.radio_provider_jian.isChecked():
            return DATA_PROVIDER_JIAN
        if hasattr(self, "radio_provider_whews") and self.radio_provider_whews.isChecked():
            return DATA_PROVIDER_WHEWS
        return DATA_PROVIDER_FANSTUDIO

    def _apply_main_provider_connection_flags(self) -> None:
        """
        按顶部主数据源三选一写入连接开关：选中者启用，另两者关闭。
        不再依赖面板内单独的 /all 勾选框。
        """
        self._update_base_urls()
        provider = self._current_data_provider_from_ui()
        self.config.data_provider = provider
        all_url = self.all_source_url
        self.config.enabled_sources[all_url] = False
        self.config.enabled_sources[WHEWS_MASTER_KEY] = False
        self.config.enabled_sources[JIAN_MASTER_KEY] = False
        for u in WHEWS_WS_URLS:
            self.config.enabled_sources[u] = False
        if hasattr(self.config, "_disable_whews_dedicated_endpoints"):
            self.config._disable_whews_dedicated_endpoints()
        if provider == DATA_PROVIDER_FANSTUDIO:
            self.config.enabled_sources[all_url] = True
        elif provider == DATA_PROVIDER_WHEWS:
            self.config.enabled_sources[WHEWS_MASTER_KEY] = True
        elif provider == DATA_PROVIDER_JIAN:
            self.config.enabled_sources[JIAN_MASTER_KEY] = True

    def _make_http_poll_spinbox(self, url: str) -> QSpinBox:
        """为 HTTP 数据源创建 Get 间隔 SpinBox（最低 1 秒）。"""
        spin = QSpinBox()
        spin.setMinimum(1)  # 轮询间隔下限 1 秒
        spin.setMaximum(2147483647)
        spin.setSuffix(" 秒")
        default_val = self.config.get_http_poll_interval(url)  # 从配置读取当前间隔
        spin.setValue(default_val)
        spin.setToolTip("HTTP 数据源 Get 轮询间隔（秒）")
        _set_widget_style(spin, "font-size: 14px; min-width: 90px;")
        self.http_poll_spinboxes[url] = spin  # 保存引用供保存时写回配置
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
        label_col_w = max(fm.width(label) for _, label in sources) + 12  # 标签列宽按最长名称对齐
        spin_col_w = 110  # 间隔输入框列宽
        hdr_style = "font-size: 14px; color: #666666; font-weight: bold;"
        hdr_name = QLabel("数据源")
        _set_widget_style(hdr_name, hdr_style)
        hdr_interval = QLabel("Get 间隔")
        _set_widget_style(hdr_interval, hdr_style)
        grid.addWidget(hdr_name, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(hdr_interval, 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
        for row, (url, label) in enumerate(sources, start=1):
            name_lbl = QLabel(label)
            _set_widget_style(name_lbl, STYLE_LABEL)
            name_lbl.setMinimumWidth(label_col_w)
            poll_spin = self._make_http_poll_spinbox(url)  # 每个 HTTP 源独立间隔控件
            poll_spin.setFixedWidth(spin_col_w)
            grid.addWidget(name_lbl, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
            grid.addWidget(poll_spin, row, 1, Qt.AlignLeft | Qt.AlignVCenter)
        grid.setColumnStretch(2, 1)  # 右侧弹性空白
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
        checkbox = QCheckBox(name, parent)  # HTTP 源连接开关
        checkbox.setChecked(initial_value)
        _set_widget_style(checkbox, STYLE_CHECKBOX_SOURCE)
        self.source_vars[url] = checkbox  # 保存引用供保存/全选时使用
        if url not in self.individual_source_urls:
            self.individual_source_urls.append(url)
        poll_spin = self._make_http_poll_spinbox(url)  # 同行展示 Get 间隔
        sk = status_key or url
        status_label = QLabel("未解析")
        _set_widget_style(status_label, STYLE_STATUS_NEUTRAL)
        status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_label.setToolTip("解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析")
        self.source_parse_labels[sk] = status_label
        self.source_status_texts[sk] = ("已解析", "未解析", "解析状态：本会话已解析到该源数据（含 initial_all；过期未上屏也算） / 尚未解析")
        row_layout = QHBoxLayout()
        row_layout.addWidget(checkbox)
        row_layout.addWidget(QLabel("Get"))
        row_layout.addWidget(poll_spin)
        row_layout.addStretch()
        row_layout.addWidget(status_label)
        if isinstance(parent.layout(), QVBoxLayout):
            parent.layout().addLayout(row_layout)
        checkbox.stateChanged.connect(self._update_parse_status_labels)  # 勾选变更时刷新状态标签

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

        checkbox = QCheckBox(name, parent)  # 数据源连接/解析开关
        checkbox.setChecked(initial_value)
        _set_widget_style(checkbox, STYLE_CHECKBOX_SOURCE)
        self.source_vars[url] = checkbox  # 以 URL 为键保存，供保存/全选时使用
        
        # 如果不是All源，记录到单项数据源列表
        if not is_all_source and url and url not in ["fanstudio_warning", "fanstudio_report"]:
            self.individual_source_urls.append(url)
            # 仅 Fan Studio WebSocket 计入 fanstudio_source_urls（台风 HTTP 为全局源）
            if url.startswith(("ws://", "wss://")) and "fanstudio.tech" in url:
                self.fanstudio_source_urls.append(url)

        if status_key:
            status_label = QLabel(status_connected_text if initial_value else status_disconnected_text)
            _set_widget_style(status_label, STYLE_STATUS_CONNECTED if initial_value else STYLE_STATUS_NEUTRAL)
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
        if hasattr(self, "aux_sources_master_cb"):
            self.aux_sources_master_cb.setChecked(True)
        if hasattr(self, "wolfx_all_connect_cb"):
            self.wolfx_all_connect_cb.setChecked(True)
        if hasattr(self, "p2pquake_connect_cb"):
            self.p2pquake_connect_cb.setChecked(True)
        for url, checkbox in self.source_vars.items():
            if url and url != self.all_source_url:  # 跳过空URL和all数据源
                checkbox.setChecked(True)
        # Fan Studio / 无界科技细粒度子源也一起全选
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
            'whews_parse_jma_eew_cb',
            'whews_parse_jma_cb',
            'whews_parse_jma_volcano_cb',
            'whews_parse_cwa_eew_cb',
            'whews_parse_sa_eew_cb',
            'whews_parse_kma_eew_cb',
            'whews_parse_cea_cb',
            'whews_parse_cea_pr_cb',
            'whews_parse_cenc_cb',
            'whews_parse_cwa_cb',
            'whews_parse_hko_cb',
            'whews_parse_usgs_cb',
            'whews_parse_emsc_cb',
            'whews_parse_bcsf_cb',
            'whews_parse_gfz_cb',
            'whews_parse_usp_cb',
            'whews_parse_kma_cb',
            'whews_parse_bmkg_cb',
            'whews_parse_geonet_cb',
            'whews_parse_tmd_cb',
            'whews_parse_ingv_cb',
            'whews_parse_nrcan_cb',
            'whews_parse_mmd_cb',
            'whews_parse_beijing_cb',
            'whews_parse_yunnan_cb',
            'whews_parse_ningxia_cb',
            'whews_parse_tsunami_cb',
            'whews_parse_ntwc_cb',
            'whews_parse_ptwc_cb',
            'whews_parse_incois_cb',
            'whews_parse_jma_tsunami_cb',
            'whews_parse_phivolcs_cb',
            'whews_parse_sgc_cb',
            'whews_parse_ga_cb',
            'whews_parse_cenais_cb',
            'whews_parse_gsras_cb',
            'whews_parse_bgs_cb',
            'whews_parse_ipma_cb',
            'whews_parse_ssn_cb',
            'whews_parse_afad_cb',
            'whews_parse_sed_cb',
            'whews_parse_noa_cb',
            'whews_parse_scsn_cb',
            'whews_parse_iag_cb',
            'whews_parse_igp_cb',
            'whews_parse_nepal_cb',
            'whews_parse_typhoon_cb',
            'whews_parse_weatheralarm_cb',
            'p2pquake_parse_551_cb',
            'p2pquake_parse_552_cb',
            'p2pquake_parse_556_cb',
            'eqsc_parse_jma_eew_cb',
            'eqsc_parse_jma_report_cb',
            'eqsc_parse_jma_tsunami_cb',
            'eqsc_parse_cenc_cb',
            'eqsc_parse_cenc_ir_cb',
            'eqsc_parse_cwa_cb',
            'eqsc_parse_hko_cb',
            'eqsc_parse_usgs_cb',
            'eqsc_parse_emsc_cb',
            'eqsc_parse_typhoon_cb',
            'eqsc_parse_volcano_cb',
            'openquake_parse_gq_cb',
            'openquake_parse_nmefc_cb',
            'openquake_parse_nmefc_wave_cb',
            'openquake_parse_nmefc_surge_cb',
            'openquake_parse_cma_cb',
            'openquake_connect_cb',
        ]:
            cb = getattr(self, attr, None)
            if cb is not None:
                cb.setChecked(True)
        for flag in JIAN_SHORT_TO_PARSE_FLAG.values():
            cb = getattr(self, f"{flag}_cb", None)
            if cb is not None:
                cb.setChecked(True)
        self._apply_jma_report_mutex_to_ui(prefer="main")
        self._update_parse_status_labels()
    
    def _restore_default_selection(self):
        """恢复默认选中状态（主数据源默认 Jian Project）。"""
        if hasattr(self, "radio_provider_jian"):
            self.radio_provider_jian.setChecked(True)
        for url, checkbox in self.source_vars.items():
            if url and url != self.all_source_url:
                checkbox.setChecked(bool(self.config.enabled_sources.get(url, False)))
        if hasattr(self, "wolfx_all_connect_cb"):
            self.wolfx_all_connect_cb.setChecked(
                wolfx_master_enabled(self.config.enabled_sources)
            )
        if hasattr(self, "aux_sources_master_cb"):
            self.aux_sources_master_cb.setChecked(
                aux_sources_enabled(self.config.enabled_sources)
            )
            if hasattr(self, "_update_aux_panels_visible"):
                self._update_aux_panels_visible()
        if hasattr(self, "p2pquake_connect_cb"):
            self.p2pquake_connect_cb.setChecked(p2pquake_master_enabled(self.config.enabled_sources))
        # Fan Studio / 无界科技细粒度子源：恢复为配置值
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
            ('whews_parse_jma_eew_cb', 'whews_parse_jma_eew'),
            ('whews_parse_jma_cb', 'whews_parse_jma'),
            ('whews_parse_jma_volcano_cb', 'whews_parse_jma_volcano'),
            ('whews_parse_cwa_eew_cb', 'whews_parse_cwa_eew'),
            ('whews_parse_sa_eew_cb', 'whews_parse_sa_eew'),
            ('whews_parse_kma_eew_cb', 'whews_parse_kma_eew'),
            ('whews_parse_cea_cb', 'whews_parse_cea'),
            ('whews_parse_cea_pr_cb', 'whews_parse_cea_pr'),
            ('whews_parse_cenc_cb', 'whews_parse_cenc'),
            ('whews_parse_cwa_cb', 'whews_parse_cwa'),
            ('whews_parse_hko_cb', 'whews_parse_hko'),
            ('whews_parse_usgs_cb', 'whews_parse_usgs'),
            ('whews_parse_emsc_cb', 'whews_parse_emsc'),
            ('whews_parse_bcsf_cb', 'whews_parse_bcsf'),
            ('whews_parse_gfz_cb', 'whews_parse_gfz'),
            ('whews_parse_usp_cb', 'whews_parse_usp'),
            ('whews_parse_kma_cb', 'whews_parse_kma'),
            ('whews_parse_bmkg_cb', 'whews_parse_bmkg'),
            ('whews_parse_geonet_cb', 'whews_parse_geonet'),
            ('whews_parse_tmd_cb', 'whews_parse_tmd'),
            ('whews_parse_ingv_cb', 'whews_parse_ingv'),
            ('whews_parse_nrcan_cb', 'whews_parse_nrcan'),
            ('whews_parse_mmd_cb', 'whews_parse_mmd'),
            ('whews_parse_beijing_cb', 'whews_parse_beijing'),
            ('whews_parse_yunnan_cb', 'whews_parse_yunnan'),
            ('whews_parse_ningxia_cb', 'whews_parse_ningxia'),
            ('whews_parse_tsunami_cb', 'whews_parse_tsunami'),
            ('whews_parse_ntwc_cb', 'whews_parse_ntwc'),
            ('whews_parse_ptwc_cb', 'whews_parse_ptwc'),
            ('whews_parse_incois_cb', 'whews_parse_incois'),
            ('whews_parse_jma_tsunami_cb', 'whews_parse_jma_tsunami'),
            ('whews_parse_phivolcs_cb', 'whews_parse_phivolcs'),
            ('whews_parse_sgc_cb', 'whews_parse_sgc'),
            ('whews_parse_ga_cb', 'whews_parse_ga'),
            ('whews_parse_cenais_cb', 'whews_parse_cenais'),
            ('whews_parse_gsras_cb', 'whews_parse_gsras'),
            ('whews_parse_bgs_cb', 'whews_parse_bgs'),
            ('whews_parse_ipma_cb', 'whews_parse_ipma'),
            ('whews_parse_ssn_cb', 'whews_parse_ssn'),
            ('whews_parse_afad_cb', 'whews_parse_afad'),
            ('whews_parse_sed_cb', 'whews_parse_sed'),
            ('whews_parse_noa_cb', 'whews_parse_noa'),
            ('whews_parse_scsn_cb', 'whews_parse_scsn'),
            ('whews_parse_iag_cb', 'whews_parse_iag'),
            ('whews_parse_igp_cb', 'whews_parse_igp'),
            ('whews_parse_nepal_cb', 'whews_parse_nepal'),
            ('whews_parse_typhoon_cb', 'whews_parse_typhoon'),
            ('whews_parse_weatheralarm_cb', 'whews_parse_weatheralarm'),
            ('p2pquake_parse_551_cb', 'p2pquake_parse_551'),
            ('p2pquake_parse_552_cb', 'p2pquake_parse_552'),
            ('p2pquake_parse_556_cb', 'p2pquake_parse_556'),
            ('eqsc_parse_jma_eew_cb', 'eqsc_parse_jma_eew'),
            ('eqsc_parse_jma_report_cb', 'eqsc_parse_jma_report'),
            ('eqsc_parse_jma_tsunami_cb', 'eqsc_parse_jma_tsunami'),
            ('eqsc_parse_cenc_cb', 'eqsc_parse_cenc'),
            ('eqsc_parse_cenc_ir_cb', 'eqsc_parse_cenc_ir'),
            ('eqsc_parse_cwa_cb', 'eqsc_parse_cwa'),
            ('eqsc_parse_hko_cb', 'eqsc_parse_hko'),
            ('eqsc_parse_usgs_cb', 'eqsc_parse_usgs'),
            ('eqsc_parse_emsc_cb', 'eqsc_parse_emsc'),
            ('eqsc_parse_typhoon_cb', 'eqsc_parse_typhoon'),
            ('eqsc_parse_volcano_cb', 'eqsc_parse_volcano'),
            ('openquake_parse_gq_cb', 'openquake_parse_gq'),
            ('openquake_parse_nmefc_cb', 'openquake_parse_nmefc'),
            ('openquake_parse_nmefc_wave_cb', 'openquake_parse_nmefc_wave'),
            ('openquake_parse_nmefc_surge_cb', 'openquake_parse_nmefc_surge'),
            ('openquake_parse_cma_cb', 'openquake_parse_cma'),
        ]:
            cb = getattr(self, attr, None)
            if cb is not None:
                default_val = getattr(self.config.message_config, cfg_name, True)
                cb.setChecked(bool(default_val))
        for flag in JIAN_SHORT_TO_PARSE_FLAG.values():
            cb = getattr(self, f"{flag}_cb", None)
            if cb is not None:
                cb.setChecked(bool(getattr(self.config.message_config, flag, True)))
        self._apply_jma_report_mutex_to_ui(prefer="main")
        if hasattr(self, "openquake_gq_min_magnitude_spin"):
            self.openquake_gq_min_magnitude_spin.setValue(
                float(getattr(self.config.message_config, "openquake_gq_min_magnitude", 4.5) or 0.0)
            )
        if hasattr(self, "openquake_connect_cb"):
            self.openquake_connect_cb.setChecked(
                openquake_master_enabled(self.config.enabled_sources)
            )
        for url, spin in self.http_poll_spinboxes.items():
            spin.setValue(self.config.get_http_poll_interval(url))
        if hasattr(self, "custom_http_poll_spinbox"):
            self.custom_http_poll_spinbox.setValue(
                self.config.get_http_poll_interval("__custom_http__")
            )
        self._update_parse_status_labels()
    
    def _create_advanced_tab(self):
        """创建高级设置标签页（地名修正、日志、自定义数据源）"""
        scroll_area = _FittingScrollArea()
        scrollable_widget = QWidget()
        _prepare_scroll_body(scrollable_widget)
        main_layout = QVBoxLayout(scrollable_widget)
        main_layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        main_layout.setSpacing(SPACING_TAB)
        
        # ---------- 1. 地名处理方式（二选一） ----------
        group_place = QGroupBox("地名处理方式")
        _prep_groupbox(group_place)
        place_layout = QVBoxLayout(group_place)
        place_layout.setContentsMargins(*GROUP_MARGINS)
        place_layout.setSpacing(GROUP_SPACING)

        mode_hint = QLabel("二选一，不可同时启用。")
        _set_widget_style(mode_hint, STYLE_HINT)
        mode_hint.setWordWrap(True)
        place_layout.addWidget(mode_hint)

        place_mode_group = QButtonGroup(scrollable_widget)

        fix_radio = QRadioButton("地名修正")
        _set_widget_style(fix_radio, STYLE_RADIO)
        place_mode_group.addButton(fix_radio, 0)
        place_layout.addWidget(fix_radio)
        fix_info = QLabel("按经纬度用 FE 区域库修正国外地名。")
        fix_info.setToolTip("CENC、CWA、JMA、HKO、P2PQuake 使用原始地名，无需 API 密钥。")
        _set_widget_style(fix_info, STYLE_HINT + " padding-left: 22px;")
        fix_info.setWordWrap(True)
        place_layout.addWidget(fix_info)

        baidu_radio = QRadioButton("百度翻译")
        _set_widget_style(baidu_radio, STYLE_RADIO)
        place_mode_group.addButton(baidu_radio, 1)
        place_layout.addWidget(baidu_radio)
        baidu_info = QLabel("将非中文地名译为中文，需 API 密钥。")
        baidu_info.setToolTip("CENC、CWA、JMA、HKO、P2PQuake 仍使用原始地名。")
        _set_widget_style(baidu_info, STYLE_HINT + " padding-left: 22px;")
        baidu_info.setWordWrap(True)
        place_layout.addWidget(baidu_info)

        tc = self.config.translation_config
        if getattr(tc, "enabled", False):
            baidu_radio.setChecked(True)
        else:
            fix_radio.setChecked(True)

        baidu_app_id_label = QLabel("百度翻译 AppID：")
        _set_widget_style(baidu_app_id_label, STYLE_LABEL)
        place_layout.addWidget(baidu_app_id_label)
        baidu_app_id_entry = QLineEdit()
        baidu_app_id_entry.setPlaceholderText("在百度翻译开放平台申请")
        baidu_app_id_entry.setText(getattr(tc, "baidu_app_id", "") or "")
        _set_widget_style(baidu_app_id_entry, STYLE_LINEEDIT)
        place_layout.addWidget(baidu_app_id_entry)
        baidu_secret_label = QLabel("百度翻译密钥：")
        _set_widget_style(baidu_secret_label, STYLE_LABEL)
        place_layout.addWidget(baidu_secret_label)
        baidu_secret_entry = QLineEdit()
        baidu_secret_entry.setPlaceholderText("与 AppID 对应的密钥")
        baidu_secret_entry.setEchoMode(QLineEdit.Password)
        baidu_secret_entry.setText(getattr(tc, "baidu_secret", "") or "")
        _set_widget_style(baidu_secret_entry, STYLE_LINEEDIT)
        place_layout.addWidget(baidu_secret_entry)

        link_label = QLabel(
            '获取 API 密钥：<a href="https://fanyi-api.baidu.com/" style="color: #3B82F6;">百度翻译开放平台</a>'
        )
        link_label.setOpenExternalLinks(True)
        _set_widget_style(link_label, STYLE_HINT + " padding-left: 22px;")
        place_layout.addWidget(link_label)

        def _update_baidu_api_visible():
            """切换翻译引擎时显示/隐藏百度 API 密钥输入区。"""
            use_baidu = baidu_radio.isChecked()
            baidu_app_id_label.setVisible(use_baidu)
            baidu_app_id_entry.setVisible(use_baidu)
            baidu_secret_label.setVisible(use_baidu)
            baidu_secret_entry.setVisible(use_baidu)
            link_label.setVisible(use_baidu)

        fix_radio.toggled.connect(lambda _: _update_baidu_api_visible())
        baidu_radio.toggled.connect(lambda _: _update_baidu_api_visible())
        _update_baidu_api_visible()
        main_layout.addWidget(group_place)

        # ---------- 2. 预警闪烁与有感提示（卡片布局，与「外观/显示」QGroupBox 风格一致） ----------
        ac = self.config.alert_config
        group_alert = QGroupBox("预警闪烁与有感提示")
        _prep_groupbox(group_alert)
        alert_outer = QVBoxLayout(group_alert)
        alert_outer.setContentsMargins(*GROUP_MARGINS)
        alert_outer.setSpacing(GROUP_SPACING)

        alert_enable_cb = QCheckBox("启用预警闪烁与有感提示")
        alert_enable_cb.setChecked(bool(getattr(ac, 'enabled', False)))
        _set_widget_style(alert_enable_cb, STYLE_CHECKBOX)
        alert_enable_cb.setToolTip(
            "收到地震预警且满足最低震级与烈度条件时，先展示带安全提示的预警全文（提示期），"
            "再切回纯预警条文；日台类源不拼接提示、不进入本序列。"
            "有感/强有感阈值：烈度小于 5 与大于等于 6（5≤烈度<6 不拼接提示）。"
        )

        _alert_enable_revert = {'active': False}

        def _on_alert_enable_toggled(on: bool) -> None:
            """首次勾选「启用预警闪烁」时弹出风险提示，取消则撤回勾选。"""
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
            apply_light_palette(dlg, "#FFFFFF")
            _set_widget_style(dlg, light_dialog_stylesheet("#FFFFFF"))
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
            _set_widget_style(sub, STYLE_HINT)
            body = QLabel()
            body.setTextFormat(Qt.RichText)
            body.setWordWrap(True)
            body.setOpenExternalLinks(False)
            body.setText(
                '<p style="margin: 0; line-height: 1.7;">'
                f'<span style="font-size: 14px; color: {COLOR_TEXT};">'
                "启用后，满足震级与烈度条件的地震预警将先展示带安全提示的全文，"
                "滚动完成后切回纯预警条文；日台类数据源不进入本序列。"
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
            _set_widget_style(ok_btn, STYLE_SAVE_BTN)
            _set_widget_style(cancel_btn, STYLE_SECONDARY_BTN)
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
            """创建告警设置卡片内的小节标题标签。"""
            h = QLabel(text)
            _set_widget_style(h, STYLE_CARD_SUBHEAD)
            return h

        _al_w = 108  # 单列纵向：标签列略宽以免截断

        def _v_field_grid() -> QGridLayout:
            """创建告警设置区单列纵向表单网格。"""
            g = QGridLayout()
            g.setContentsMargins(0, 0, 0, 0)
            g.setHorizontalSpacing(8)
            g.setVerticalSpacing(5)
            g.setColumnStretch(2, 1)
            return g

        def _v_add_row(g: QGridLayout, row: int, lbl: QLabel, w: QWidget) -> None:
            """向纵向表单网格添加一行标签与控件。"""
            lbl.setMinimumWidth(_al_w)
            g.addWidget(lbl, row, 0, Qt.AlignLeft | Qt.AlignVCenter)
            g.addWidget(w, row, 1, Qt.AlignLeft)

        # —— 触发条件（单列纵向，避免超出窗口宽度） ——
        alert_outer.addWidget(_subhead("触发条件"))
        grid_trigger = _v_field_grid()

        min_mag_label = QLabel("最低震级")
        _set_widget_style(min_mag_label, STYLE_LABEL)
        min_mag_label.setToolTip("低于该震级的预警不进入告警序列。")
        min_mag_spin = QDoubleSpinBox()
        min_mag_spin.setRange(0.0, 10.0)
        min_mag_spin.setDecimals(1)
        min_mag_spin.setSingleStep(0.1)
        min_mag_spin.setValue(float(getattr(ac, 'min_magnitude', 3.0)))
        min_mag_spin.setSuffix(" M")
        min_mag_spin.setFixedWidth(100)
        _set_widget_style(min_mag_spin, STYLE_SPINBOX)
        _v_add_row(grid_trigger, 0, min_mag_label, min_mag_spin)

        alert_outer.addLayout(grid_trigger)

        # —— 闪烁与颜色 ——
        alert_outer.addWidget(_subhead("闪烁与颜色"))
        grid_flash = _v_field_grid()

        hint_dur_label = QLabel("提示期随预警有效期；滚完一周可提前结束。")
        hint_dur_label.setToolTip("与「预警/消息更新」中的发震时间有效期（及 JMA/四川单独窗口）一致。")
        hint_dur_label.setWordWrap(True)
        _set_widget_style(hint_dur_label, STYLE_HINT)
        grid_flash.addWidget(hint_dur_label, 0, 0, 1, 2)

        int_label = QLabel("闪烁间隔")
        _set_widget_style(int_label, STYLE_LABEL)
        flash_interval_spin = QSpinBox()
        flash_interval_spin.setRange(50, 2000)
        flash_interval_spin.setSingleStep(50)
        flash_interval_spin.setValue(int(getattr(ac, 'flash_interval_ms', 400)))
        flash_interval_spin.setSuffix(" 毫秒")
        flash_interval_spin.setFixedWidth(120)
        _set_widget_style(flash_interval_spin, STYLE_SPINBOX)
        _v_add_row(grid_flash, 1, int_label, flash_interval_spin)

        color_label = QLabel("告警色")
        _set_widget_style(color_label, STYLE_LABEL)
        color_label.setToolTip("点击选择左侧标识闪烁颜色。")
        flash_color_btn = QPushButton(getattr(ac, 'flash_color', '#FF0000'))
        flash_color_btn.setFixedWidth(140)
        flash_color_btn.setCursor(Qt.PointingHandCursor)
        _set_widget_style(flash_color_btn, 
            f"QPushButton {{ background-color: {getattr(ac, 'flash_color', '#FF0000')}; "
            f"color: white; padding: 6px 10px; border-radius: 8px; font-size: 13px; border: 1px solid #E5E2DC; }}"
        )

        def _on_pick_color():
            """打开颜色对话框并更新闪烁颜色按钮样式。"""
            cur = QColor(flash_color_btn.text() or '#FF0000')
            picked = QColorDialog.getColor(cur, self, "选择闪烁颜色")
            if picked.isValid():
                hex_color = picked.name(QColor.HexRgb).upper()
                flash_color_btn.setText(hex_color)
                _set_widget_style(flash_color_btn, 
                    f"QPushButton {{ background-color: {hex_color}; "
                    f"color: white; padding: 6px 10px; border-radius: 8px; font-size: 13px; border: 1px solid #E5E2DC; }}"
                )
        flash_color_btn.clicked.connect(_on_pick_color)
        _v_add_row(grid_flash, 2, color_label, flash_color_btn)

        alert_outer.addLayout(grid_flash)

        # —— 模拟 ——
        alert_outer.addWidget(_subhead("模拟"))
        sim_btn = QPushButton("模拟预警")
        _set_widget_style(sim_btn, STYLE_SELECT_ALL_BTN)
        sim_btn.setCursor(Qt.PointingHandCursor)
        sim_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sim_btn.clicked.connect(self._simulate_alert)
        alert_outer.addWidget(sim_btn)

        main_layout.addWidget(group_alert)

        # ---------- 3. 日志设置 ----------
        group_log = QGroupBox("日志设置")
        _prep_groupbox(group_log)
        log_layout = QVBoxLayout(group_log)
        log_layout.setContentsMargins(*GROUP_MARGINS)
        log_layout.setSpacing(GROUP_SPACING)
        output_file_checkbox = QCheckBox("输出日志到文件")
        output_file_checkbox.setChecked(self.config.log_config.output_to_file)
        _set_widget_style(output_file_checkbox, STYLE_CHECKBOX_LOG)
        log_layout.addWidget(output_file_checkbox)
        output_file_desc = QLabel("保存到 log.txt")
        _set_widget_style(output_file_desc, STYLE_HINT + " padding-left: 22px;")
        output_file_desc.setWordWrap(True)
        log_layout.addWidget(output_file_desc)
        clear_log_checkbox = QCheckBox("每次程序启动前清空日志")
        clear_log_checkbox.setChecked(self.config.log_config.clear_log_on_startup)
        _set_widget_style(clear_log_checkbox, STYLE_CHECKBOX_LOG)
        log_layout.addWidget(clear_log_checkbox)
        clear_log_desc = QLabel("每次启动时清空")
        _set_widget_style(clear_log_desc, STYLE_HINT + " padding-left: 22px;")
        clear_log_desc.setWordWrap(True)
        log_layout.addWidget(clear_log_desc)
        split_date_checkbox = QCheckBox("按日期分割日志")
        split_date_checkbox.setChecked(self.config.log_config.split_by_date)
        _set_widget_style(split_date_checkbox, STYLE_CHECKBOX_LOG)
        log_layout.addWidget(split_date_checkbox)
        split_date_desc = QLabel("按日期命名（log_YYYYMMDD.txt）")
        _set_widget_style(split_date_desc, STYLE_HINT + " padding-left: 22px;")
        split_date_desc.setWordWrap(True)
        log_layout.addWidget(split_date_desc)
        log_size_layout = QHBoxLayout()
        log_size_label = QLabel("日志文件最大大小（MB）：")
        _set_widget_style(log_size_label, STYLE_LABEL)
        log_size_layout.addWidget(log_size_label)
        log_size_spinbox = QSpinBox()
        log_size_spinbox.setMinimum(1)
        log_size_spinbox.setMaximum(1000)
        log_size_spinbox.setValue(self.config.log_config.max_log_size)
        log_size_spinbox.setSuffix(" MB")
        _set_widget_style(log_size_spinbox, STYLE_SPINBOX)
        log_size_layout.addWidget(log_size_spinbox)
        log_size_layout.addStretch()
        log_layout.addLayout(log_size_layout)
        log_size_desc = QLabel("达此大小后自动备份（未按日分割时）")
        _set_widget_style(log_size_desc, STYLE_HINT)
        log_size_desc.setWordWrap(True)
        log_layout.addWidget(log_size_desc)
        main_layout.addWidget(group_log)
        
        # ---------- 4. 自定义数据源 ----------
        group_custom_src = QGroupBox("自定义数据源")
        _prep_groupbox(group_custom_src)
        custom_src_layout = QVBoxLayout(group_custom_src)
        custom_src_layout.setContentsMargins(*GROUP_MARGINS)
        custom_src_layout.setSpacing(GROUP_SPACING)
        custom_url_label = QLabel("自定义数据源 URL：")
        _set_widget_style(custom_url_label, STYLE_LABEL)
        custom_src_layout.addWidget(custom_url_label)
        custom_url_entry = QLineEdit()
        custom_url_entry.setPlaceholderText("输入 http/https/ws/wss URL，留空则关闭")
        custom_url_entry.setText(self.config.custom_data_source_url or "")
        _set_widget_style(custom_url_entry, STYLE_LINEEDIT)
        custom_src_layout.addWidget(custom_url_entry)
        custom_insecure_ssl_cb = QCheckBox("跳过 SSL 证书校验")
        custom_insecure_ssl_cb.setChecked(
            bool(getattr(self.config, 'custom_data_source_insecure_ssl', False))
        )
        _set_widget_style(custom_insecure_ssl_cb, STYLE_CHECKBOX_SMALL)
        custom_insecure_ssl_cb.setToolTip(
            "适用于自签名证书等场景；会降低 HTTPS 连接安全性，请仅在信任的数据源上开启。"
        )
        custom_src_layout.addWidget(custom_insecure_ssl_cb)
        custom_poll_layout = QHBoxLayout()
        custom_poll_label = QLabel("HTTP Get 间隔（秒）：")
        _set_widget_style(custom_poll_label, STYLE_LABEL)
        custom_poll_layout.addWidget(custom_poll_label)
        custom_http_poll_spinbox = QSpinBox()
        custom_http_poll_spinbox.setMinimum(1)
        custom_http_poll_spinbox.setMaximum(2147483647)
        custom_http_poll_spinbox.setSuffix(" 秒")
        custom_http_poll_spinbox.setValue(self.config.get_http_poll_interval("__custom_http__"))
        _set_widget_style(custom_http_poll_spinbox, STYLE_SPINBOX)
        custom_http_poll_spinbox.setToolTip("自定义 HTTP 数据源轮询间隔（仅 http/https 生效）")
        custom_poll_layout.addWidget(custom_http_poll_spinbox)
        custom_poll_layout.addStretch()
        custom_src_layout.addLayout(custom_poll_layout)
        self.custom_http_poll_spinbox = custom_http_poll_spinbox
        custom_source_status_label = QLabel("状态：—")
        _set_widget_style(custom_source_status_label, STYLE_HINT)
        custom_source_status_label.setObjectName("custom_source_status_label")
        self.custom_source_status_label = custom_source_status_label
        custom_src_layout.addWidget(custom_source_status_label)
        custom_hint = QLabel(
            "HTTP 按间隔轮询；WS 实时推送。按上方格式推送预警 JSON。"
            "发震时间超过「预警有效期」（默认约 5 分钟）的报文会被丢弃。"
            "留空关闭。"
        )
        _set_widget_style(custom_hint, STYLE_HINT)
        custom_hint.setWordWrap(True)
        custom_src_layout.addWidget(custom_hint)
        format_label = QLabel("预警源数据格式示例（二选一）：")
        _set_widget_style(format_label, STYLE_LABEL + " margin-top: 4px;")
        custom_src_layout.addWidget(format_label)
        example_flat = (
            '格式一（平铺预警，推荐）：\n'
            '{\n'
            '  "eventID": "00ee54c1-a2d8-8e93-064e-1c9c3cca630a",\n'
            '  "placeName": "offshore Chiapas, Mexico",\n'
            '  "latitude": 14.267749,\n'
            '  "longitude": -93.034294,\n'
            '  "depth": 10,\n'
            '  "reportTime": "2026/08/24 03:39:36",\n'
            '  "shockTime": "2026/08/24 03:33:59",\n'
            '  "reportNum": 14,\n'
            '  "magnitude": "4.6050143",\n'
            '  "sourceName": "GlobalQuake地震预警"\n'
            '}'
        )
        example_flat_edit = QPlainTextEdit()
        example_flat_edit.setPlainText(example_flat)
        example_flat_edit.setReadOnly(True)
        example_flat_edit.setMaximumHeight(145)
        _set_widget_style(example_flat_edit, 
            f"QPlainTextEdit {{ font-family: Consolas,Monaco,monospace; font-size: 11px; "
            f"background: {COLOR_PAGE_BG}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 8px; padding: 6px; color: {COLOR_TEXT}; }}"
        )
        custom_src_layout.addWidget(example_flat_edit)
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
        _set_widget_style(example_nested_edit, 
            f"QPlainTextEdit {{ font-family: Consolas,Monaco,monospace; font-size: 11px; "
            f"background: {COLOR_PAGE_BG}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 8px; padding: 6px; color: {COLOR_TEXT}; }}"
        )
        custom_src_layout.addWidget(example_nested_edit)
        main_layout.addWidget(group_custom_src)
        
        main_layout.addStretch()
        
        # 保存按钮
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 10, 0, 0)
        button_layout.addStretch()
        save_btn = QPushButton("保存高级设置")
        save_btn.setMinimumWidth(120)
        save_btn.setMinimumHeight(35)
        _set_widget_style(save_btn, STYLE_SAVE_BTN)
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
            'custom_insecure_ssl_cb': custom_insecure_ssl_cb,
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
                show_info(
                    self,
                    "提示",
                    "未找到主窗口接口，无法模拟预警。",
                )
                return
            try:
                self._save_alert_settings()
                self._save_audio_settings()
            except Exception:
                pass
            ok = mw.trigger_alert_simulation(
                place_name="测试地点",
                magnitude=5.0,
                epi_intensity=7.0,
            )
            if ok:
                show_info(
                    self,
                    "模拟预警",
                    "已触发模拟预警：字幕将展示带安全提示的预警全文，左侧标识会闪烁。\n"
                    "若已配置音频/TTS，应同时听到一次告警反馈。",
                )
            else:
                ac = self.config.alert_config
                adv = getattr(self, 'advanced_vars', {}) or {}
                cb = adv.get('alert_enable_cb')
                enabled = bool(cb.isChecked()) if cb is not None else bool(ac.enabled)
                min_mag = float(getattr(ac, 'min_magnitude', 3.0) or 0.0)
                if not enabled:
                    show_warning(
                        self,
                        "模拟预警",
                        "请先勾选「启用预警闪烁与有感/强有感提示」并保存高级设置，"
                        "或再次点击模拟（未启用时仍会尝试播放音频反馈，但无闪烁序列）。",
                    )
                elif 5.0 < min_mag:
                    show_warning(
                        self,
                        "模拟预警",
                        f"当前最低震级阈值为 {min_mag:.1f} M，模拟震级 5.0 未达阈值，无法进入告警序列。",
                    )
                else:
                    show_warning(
                        self,
                        "模拟预警",
                        "告警序列未能启动（可能正有其他告警进行中）。已尝试播放音频反馈。",
                    )
        except Exception as e:
            logger.error(f"模拟预警失败: {e}")

    def _save_advanced_settings(self, fix_radio, baidu_radio, output_file_checkbox, clear_log_checkbox,
                                  split_date_checkbox, log_size_spinbox, custom_url_entry,
                                  baidu_app_id_entry=None, baidu_secret_entry=None,
                                  show_message=True):
        """保存高级设置（地名处理、日志、自定义数据源）。show_message=False 时不弹成功提示（由调用方统一提示）。返回 True 表示保存成功，False 表示未保存（校验失败或异常）。"""
        try:
            if not self._apply_advanced_settings_to_config(show_url_warning=show_message):
                if show_message:
                    show_warning(self, "警告", "日志配置验证失败，请检查设置")
                return False
            self._save_audio_settings()
            if not self.config.log_config.validate():
                if show_message:
                    show_warning(self, "警告", "日志配置验证失败，请检查设置")
                return False
            self._save_config_with_data_source_toggles()
            self._clear_settings_dirty()
            self.config._notify_config_changed()
            if show_message:
                show_info(self, "成功", "高级设置已保存！\n设置已立即生效，无需重启程序。")
            logger.debug("高级设置已保存")
            return True
        except Exception as e:
            logger.error(f"保存高级设置失败: {e}")
            show_critical(self, "错误", f"保存设置失败: {e}")
            return False
    
    def _create_about_tab(self):
        """创建关于标签页"""
        scroll_area = _FittingScrollArea()
        scrollable_widget = QWidget()
        _prepare_scroll_body(scrollable_widget)
        layout = QVBoxLayout(scrollable_widget)
        layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        layout.setSpacing(SPACING_TAB)
        sep_style = f"background-color: {COLOR_BORDER}; max-height: 1px;"
        body_style = STYLE_ABOUT_ITEM + " padding-left: 10px; padding-bottom: 2px;"

        # 标题与版本（上方留白，避免贴顶）
        layout.addSpacing(12)
        title_label = QLabel("地震情报实况栏")
        _set_widget_style(title_label, f"font-size: 22px; font-weight: bold; color: {COLOR_TEXT}; padding-bottom: 2px;")
        layout.addWidget(title_label)
        version_label = QLabel(f"版本 v{APP_VERSION}")
        _set_widget_style(version_label, f"font-size: 14px; font-weight: bold; color: {COLOR_ACCENT}; padding-bottom: 6px;")
        layout.addWidget(version_label)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setFrameShadow(QFrame.Sunken)
        _set_widget_style(sep1, sep_style)
        layout.addWidget(sep1)
        layout.addSpacing(4)

        # 声明（与主窗口「更新说明」弹窗内红色声明一致）
        # 必须可水平压缩：否则最长一行 sizeHint 会把整个设置窗撑「胖」
        about_declaration = QLabel(APP_DECLARATION_TEXT)
        about_declaration.setWordWrap(True)
        about_declaration.setMinimumWidth(0)
        about_declaration.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        about_declaration.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        about_declaration.setTextInteractionFlags(Qt.TextSelectableByMouse)
        _set_widget_style(about_declaration, 
            "color: #B22222; font-weight: bold; font-size: 14px; "
            "line-height: 1.55; padding: 6px 0 2px 0; margin: 0; background: transparent;"
        )
        layout.addWidget(about_declaration)
        layout.addSpacing(SPACING_BLOCK - 8)
        sep_decl = QFrame()
        sep_decl.setFrameShape(QFrame.HLine)
        sep_decl.setFrameShadow(QFrame.Sunken)
        _set_widget_style(sep_decl, sep_style)
        layout.addWidget(sep_decl)
        layout.addSpacing(4)

        # 数据源支持（聚合平台 + 主要机构；文案宜短，避免撑宽关于页）
        data_source_label = QLabel("数据源支持")
        _set_widget_style(data_source_label, STYLE_SECTION_TITLE)
        layout.addWidget(data_source_label)
        for name in [
            "Fan Studio API",
            "无界科技 Whews API",
            "Wolfx Open API",
            "P2PQuake 地震情報",
            "Nowquake CENC 烈度速报",
            "中国地震台网中心",
            "中国气象局",
            "自然资源部海啸预警中心",
            "日本气象厅",
            "台湾气象署",
            "香港天文台",
            "美国地质调查局 USGS",
            "美国 ShakeAlert",
            "太平洋海啸预警中心 PTWC",
            "美国国家海啸预警中心 NTWC",
            "印度海啸早期预警中心 INCOIS",
            "欧洲地中海地震中心 EMSC",
            "意大利 Early-est",
            "意大利国家地球物理与火山学研究所 INGV",
            "印尼气象气候和地球物理局 BMKG",
            "新西兰 GeoNet",
            "韩国气象厅",
            "德国地学研究中心 GFZ",
            "法国中央地震研究所 BCSF",
            "巴西圣保罗大学 USP",
            "泰国地震局",
            "马来西亚气象局",
            "加拿大自然资源部",
            "菲律宾火山地震研究所",
            "哥伦比亚地质服务局",
            "澳大利亚地球科学局",
            "古巴国家地震研究中心",
        ]:
            lb = QLabel(f"• {name}")
            lb.setWordWrap(True)
            lb.setMinimumWidth(0)
            lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            _set_widget_style(lb, body_style)
            layout.addWidget(lb)
        layout.addSpacing(SPACING_BLOCK - 4)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        _set_widget_style(sep2, sep_style)
        layout.addWidget(sep2)
        layout.addSpacing(4)

        # 开发者
        developer_label = QLabel("开发者")
        _set_widget_style(developer_label, STYLE_SECTION_TITLE)
        layout.addWidget(developer_label)
        for name in ["星落"]:
            lb = QLabel(f"• {name}")
            _set_widget_style(lb, body_style)
            layout.addWidget(lb)
        layout.addSpacing(SPACING_BLOCK - 4)
        sep2b = QFrame()
        sep2b.setFrameShape(QFrame.HLine)
        sep2b.setFrameShadow(QFrame.Sunken)
        _set_widget_style(sep2b, sep_style)
        layout.addWidget(sep2b)
        layout.addSpacing(4)

        # QQ群
        qq_label = QLabel("QQ群")
        _set_widget_style(qq_label, STYLE_SECTION_TITLE)
        layout.addWidget(qq_label)
        qq_join_url = "https://qm.qq.com/q/KJUJZTdpE2"
        qq_value = QLabel(
            f'947523679　'
            f'<a href="{qq_join_url}" style="color: {COLOR_LINK};">加入群聊</a>'
        )
        _set_widget_style(qq_value, body_style)
        qq_value.setTextFormat(Qt.RichText)
        qq_value.setOpenExternalLinks(True)
        qq_value.setWordWrap(True)
        qq_value.setMinimumWidth(0)
        qq_value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(qq_value)
        layout.addSpacing(SPACING_BLOCK - 4)
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.HLine)
        sep3.setFrameShadow(QFrame.Sunken)
        _set_widget_style(sep3, sep_style)
        layout.addWidget(sep3)
        layout.addSpacing(4)

        # 项目地址（GitHub）
        github_label = QLabel("项目地址")
        _set_widget_style(github_label, STYLE_SECTION_TITLE)
        layout.addWidget(github_label)
        github_url = "https://github.com/Jian11323/Rolling-Subtitle"
        github_link = QLabel(f'<a href="{github_url}">{github_url}</a>')
        _set_widget_style(github_link, body_style)
        github_link.setOpenExternalLinks(True)
        github_link.setTextFormat(Qt.RichText)
        github_link.setWordWrap(True)
        github_link.setMinimumWidth(0)
        github_link.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(github_link)
        layout.addSpacing(SPACING_BLOCK - 4)
        sep_github = QFrame()
        sep_github.setFrameShape(QFrame.HLine)
        sep_github.setFrameShadow(QFrame.Sunken)
        _set_widget_style(sep_github, sep_style)
        layout.addWidget(sep_github)
        layout.addSpacing(4)

        # 特别致谢
        thanks_label = QLabel("特别致谢")
        _set_widget_style(thanks_label, STYLE_SECTION_TITLE)
        layout.addWidget(thanks_label)
        thanks_frame = QWidget()
        _set_widget_style(thanks_frame, 
            f"QWidget {{ background-color: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 12px; }}"
        )
        thanks_layout = QVBoxLayout(thanks_frame)
        thanks_layout.setContentsMargins(12, 10, 12, 10)
        thanks_layout.setSpacing(6)
        for text in ["感谢所有数据源提供方为地震监测事业做出的贡献。", "感谢所有用户的支持与反馈。"]:
            tl = QLabel(text)
            tl.setWordWrap(True)
            tl.setMinimumWidth(0)
            tl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            _set_widget_style(tl, STYLE_ABOUT_ITEM + " line-height: 1.4;")
            thanks_layout.addWidget(tl)
        layout.addWidget(thanks_frame)
        layout.addSpacing(SPACING_BLOCK - 4)
        sep_thanks = QFrame()
        sep_thanks.setFrameShape(QFrame.HLine)
        sep_thanks.setFrameShadow(QFrame.Sunken)
        _set_widget_style(sep_thanks, sep_style)
        layout.addWidget(sep_thanks)
        layout.addSpacing(4)

        # 支持我们（支付宝收款码 / 微信赞赏码）
        support_label = QLabel("支持我们")
        _set_widget_style(support_label, STYLE_SECTION_TITLE)
        layout.addWidget(support_label)
        support_hint = QLabel("欢迎扫码支持开发。")
        support_hint.setWordWrap(True)
        _set_widget_style(support_hint, body_style)
        layout.addWidget(support_hint)

        qr_row = QWidget()
        qr_layout = QHBoxLayout(qr_row)
        qr_layout.setContentsMargins(4, 8, 4, 4)
        qr_layout.setSpacing(16)
        qr_size = 150
        for caption, rel_path in (
            ("支付宝", "logo/donate_alipay.png"),
            ("微信赞赏", "logo/donate_wechat.png"),
        ):
            col = QVBoxLayout()
            col.setSpacing(8)
            col.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            img = QLabel()
            img.setAlignment(Qt.AlignCenter)
            img.setFixedSize(qr_size, qr_size)
            _set_widget_style(img, 
                "background-color: #FFFFFF; border: 1px solid #E5E2DC; border-radius: 12px;"
            )
            path = get_resource_path(rel_path)
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                img.setPixmap(
                    pixmap.scaled(
                        qr_size - 8,
                        qr_size - 8,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
            else:
                img.setText("图片缺失")
                _set_widget_style(img, 
                    body_style + f" background-color: {COLOR_CARD_BG}; border: 1px dashed {COLOR_BORDER};"
                )
            name_lb = QLabel(caption)
            name_lb.setAlignment(Qt.AlignCenter)
            _set_widget_style(name_lb, STYLE_ABOUT_ITEM + " font-weight: bold;")
            col.addWidget(img)
            col.addWidget(name_lb)
            qr_layout.addLayout(col)
        qr_layout.addStretch()
        layout.addWidget(qr_row)
        layout.addStretch()

        scroll_area.setWidget(scrollable_widget)
        self.notebook.addTab(scroll_area, "关于")

    def _create_data_source_status_tab(self):
        """创建数据源状态标签页（紧凑：数据源 + 状态 + 分钟条）"""
        scroll_area = _FittingScrollArea()
        _set_widget_style(scroll_area, f"QScrollArea {{ border: none; background: {COLOR_PAGE_BG}; }}")
        container = QWidget()
        _prepare_scroll_body(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(MARGIN_TAB, MARGIN_TAB, MARGIN_TAB, MARGIN_TAB)
        layout.setSpacing(12)

        title = QLabel("服务器状态")
        _set_widget_style(title, f"font-size: 20px; font-weight: bold; color: {COLOR_TEXT};")
        layout.addWidget(title)

        hint = QLabel("每分钟记录一次，最多最近 60 分钟")
        hint.setWordWrap(True)
        _set_widget_style(hint, STYLE_HINT)
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
        """将 Unix 时间戳格式化为可读日期时间字符串。"""
        try:
            ts = float(value or 0)
            if ts <= 0:
                return "-"
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "-"

    def _status_chip_text(self, connection_state: str, heartbeat_state: str) -> str:
        """根据连接与心跳状态返回状态芯片展示文案。"""
        if connection_state == "connected" and heartbeat_state != "timeout":
            return "正常"
        if connection_state == "connecting":
            return "重连中"
        # 断开/未启用优先于心跳超时，避免热停用后误报「心跳超时」
        if connection_state == "disconnected":
            return "断开"
        if connection_state == "unconnected":
            return "未连接"
        if heartbeat_state == "timeout":
            return "心跳超时"
        return "未连接"

    def _status_chip_color(self, connection_state: str, heartbeat_state: str) -> str:
        """根据连接与心跳状态返回状态芯片背景色（十六进制）。"""
        if connection_state == "connected" and heartbeat_state != "timeout":
            return "#2ECC71"
        if connection_state == "connecting":
            return "#F39C12"
        if connection_state == "unconnected":
            return "#95A5A6"
        if connection_state == "disconnected":
            return "#E74C3C"
        if heartbeat_state == "timeout":
            return "#E74C3C"
        return "#95A5A6"

    def _build_health_strip_widget(self, minute_bars: List[bool]) -> Tuple[QWidget, List[QFrame]]:
        """构建近 60 分钟健康度条带，并返回条带控件与各分钟块以便原地刷新。"""
        strip = QWidget()
        row = QHBoxLayout(strip)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        total = 60
        # 未产生历史记录的分钟显示为灰色；仅真实异常分钟显示红色
        padded: List[Any] = ([None] * max(0, total - len(minute_bars))) + minute_bars[-total:]
        bars: List[QFrame] = []
        for ok in padded:
            bar = QFrame(strip)
            bar.setFixedSize(5, 14)
            self._apply_health_bar_style(bar, ok)
            row.addWidget(bar)
            bars.append(bar)
        row.addStretch()
        return strip, bars

    @staticmethod
    def _apply_health_bar_style(bar: QFrame, ok: Any) -> None:
        """仅在状态变化时更新分钟块样式，减少无效 setStyleSheet。"""
        state = True if ok is True else (False if ok is False else None)
        if getattr(bar, "_ok_state", object()) == state:
            return
        bar._ok_state = state
        if state is True:
            _set_widget_style(bar, "background: #2ECC71; border-radius: 2px;")
        elif state is False:
            _set_widget_style(bar, "background: #E74C3C; border-radius: 2px;")
        else:
            _set_widget_style(bar, "background: #DDE2E6; border-radius: 2px;")

    def _refresh_health_strip_bars(self, bars: List[QFrame], minute_bars: List[Any]) -> None:
        """原地刷新 60 分钟健康度条带颜色。"""
        total = 60
        padded: List[Any] = ([None] * max(0, total - len(minute_bars))) + list(minute_bars)[-total:]
        for bar, ok in zip(bars, padded):
            self._apply_health_bar_style(bar, ok)

    def _compact_source_label(self, url: str, source_name: str) -> str:
        """将 WebSocket URL 压缩为设置页卡片上的短标签。"""
        low = (url or "").lower()
        if "api.p2pquake.net" in low:
            return "P2PQuake"
        if "equake.top" in low:
            return "EQSC"
        if "ws-api.wolfx.jp/all_eew" in low:
            return "Wolfx all"
        if "ws-api.wolfx.jp/cwa_eew" in low:
            return "Wolfx cwa"
        if "ws-api.wolfx.jp/cenc_eqlist" in low:
            return "Wolfx cenc"
        if "ws-api.wolfx.jp/jma_eqlist" in low:
            return "Wolfx jma list"
        if "seismicportal.eu/standing_order" in low:
            return "EMSC"
        if "nowquake.cn" in low:
            return "CENC烈度"
        if "ws.fanstudio.tech/all" in low:
            return "Fan Studio"
        if "api.2v8.cn/ws/all" in low or "api.beecld.com/ws/all" in low:
            return "WeJet all"
        return source_name or url

    def _compute_health_percent(self, connection_state: str, heartbeat_state: str, timeout_count: int, heartbeat_age: Any, timeout_threshold: float) -> float:
        """综合连接、心跳超时与心跳年龄计算 0–100 健康度百分比。"""
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
        """清空「数据源状态」页全部卡片控件。"""
        if not hasattr(self, "data_source_status_cards_layout"):
            return
        for info in list(self._status_card_by_url.values()):
            card = info.get("card")
            if card is not None:
                card.setParent(None)
                card.deleteLater()
        self._status_card_by_url.clear()
        self._status_cards_url_order = []
        if self._status_cards_empty_label is not None:
            self._status_cards_empty_label.setParent(None)
            self._status_cards_empty_label.deleteLater()
            self._status_cards_empty_label = None
        while self.data_source_status_cards_layout.count():
            item = self.data_source_status_cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._status_cards_stretch_item = None

    def _create_status_card(self, url: str, title: str, status_text: str, status_color: str, history: List[Any]) -> Dict[str, Any]:
        """创建单条数据源状态卡片（仅在 URL 集合变化时调用）。"""
        card = QFrame()
        _set_widget_style(card, 
            f"QFrame {{ background: {COLOR_CARD_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 12px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        top_row = QHBoxLayout()
        left_title = QLabel(title)
        _set_widget_style(left_title, f"font-size: 14px; color: {COLOR_TEXT}; font-weight: bold;")
        top_row.addWidget(left_title)
        top_row.addStretch()
        right_status = QLabel(f"状态：{status_text}")
        _set_widget_style(right_status, f"font-size: 13px; color: {status_color};")
        top_row.addWidget(right_status)
        card_layout.addLayout(top_row)
        strip, bars = self._build_health_strip_widget(history)
        card_layout.addWidget(strip)
        self.data_source_status_cards_layout.addWidget(card)
        return {
            "url": url,
            "card": card,
            "title_label": left_title,
            "status_label": right_status,
            "bars": bars,
            "title": title,
            "status_text": status_text,
            "status_color": status_color,
        }

    def _update_status_card_content(
        self,
        info: Dict[str, Any],
        title: str,
        status_text: str,
        status_color: str,
        history: List[Any],
    ) -> None:
        """原地更新已有卡片的标题、状态与分钟条。"""
        if info.get("title") != title:
            info["title_label"].setText(title)
            info["title"] = title
        if info.get("status_text") != status_text or info.get("status_color") != status_color:
            info["status_label"].setText(f"状态：{status_text}")
            _set_widget_style(info["status_label"], f"font-size: 13px; color: {status_color};")
            info["status_text"] = status_text
            info["status_color"] = status_color
        self._refresh_health_strip_bars(info.get("bars") or [], history)

    def _update_data_source_health_table(self):
        """刷新「数据源状态」页卡片列表（URL 集合不变时复用控件）。"""
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
            # 不展示已废弃的无界科技 cea_all / cenc 专用线
            urls = [u for u in urls if not is_whews_dedicated_endpoint(u)]

            if not urls:
                if self._status_card_by_url or self._status_cards_empty_label is None:
                    self._clear_status_cards()
                    empty_label = QLabel("暂无可展示的数据源状态")
                    _set_widget_style(empty_label, "font-size: 15px; color: #8A8A8A; padding: 8px 0;")
                    self.data_source_status_cards_layout.addWidget(empty_label)
                    self._status_cards_empty_label = empty_label
                return

            # 去掉空状态提示
            if self._status_cards_empty_label is not None:
                self._status_cards_empty_label.setParent(None)
                self._status_cards_empty_label.deleteLater()
                self._status_cards_empty_label = None

            # 移除已不存在的源
            for old_url in list(self._status_card_by_url.keys()):
                if old_url not in urls:
                    info = self._status_card_by_url.pop(old_url)
                    card = info.get("card")
                    if card is not None:
                        self.data_source_status_cards_layout.removeWidget(card)
                        card.setParent(None)
                        card.deleteLater()
            self._status_cards_url_order = [u for u in self._status_cards_url_order if u in self._status_card_by_url]

            # 结构变化（新增/顺序变化）时重建布局顺序
            need_rebuild_order = self._status_cards_url_order != urls

            for url in urls:
                health = health_map.get(url, {})
                source_name = self.config.get_source_name(url) or url
                compact_name = self._compact_source_label(url, source_name)
                connection_state = health.get("connection_state") or status_map.get(url, "unconnected")
                heartbeat_state = health.get("heartbeat_state", "unknown")
                enabled = health.get("enabled")
                if enabled is None:
                    enabled = connection_state not in ("unconnected",)

                status_text = self._status_chip_text(connection_state, heartbeat_state)
                status_color = self._status_chip_color(connection_state, heartbeat_state)
                minute_key = datetime.datetime.now().strftime("%Y%m%d%H%M")  # 按分钟去重，每分钟最多追加一条
                if self._status_last_minute_key.get(url) != minute_key:
                    history = self._status_minute_bars.setdefault(url, [])
                    if enabled and connection_state in ("connected", "connecting", "disconnected"):
                        # 仅对仍启用的源记绿/红；禁用源记灰色，避免热停用后刷红
                        is_ok = connection_state == "connected" and heartbeat_state != "timeout"
                        history.append(bool(is_ok))
                    else:
                        history.append(None)
                    if len(history) > 60:
                        del history[:-60]  # 仅保留最近 60 分钟
                    self._status_last_minute_key[url] = minute_key
                history = self._status_minute_bars.get(url, [])

                info = self._status_card_by_url.get(url)
                if info is None:
                    info = self._create_status_card(url, compact_name, status_text, status_color, history)
                    self._status_card_by_url[url] = info
                    need_rebuild_order = True
                else:
                    self._update_status_card_content(info, compact_name, status_text, status_color, history)

            if need_rebuild_order:
                # 先摘掉 stretch，再按 urls 顺序 re-add 卡片，最后补 stretch
                while self.data_source_status_cards_layout.count():
                    item = self.data_source_status_cards_layout.takeAt(0)
                    # 不 delete 卡片；仅脱离布局，稍后再 add
                    if item is not None and item.widget() is None and item.spacerItem() is not None:
                        continue
                for url in urls:
                    info = self._status_card_by_url.get(url)
                    if info and info.get("card") is not None:
                        self.data_source_status_cards_layout.addWidget(info["card"])
                self.data_source_status_cards_layout.addStretch()
                self._status_cards_url_order = list(urls)
            else:
                has_stretch = False
                for i in range(self.data_source_status_cards_layout.count()):
                    item = self.data_source_status_cards_layout.itemAt(i)
                    if item is not None and item.spacerItem() is not None:
                        has_stretch = True
                        break
                if not has_stretch:
                    self.data_source_status_cards_layout.addStretch()
        except Exception as e:
            logger.debug(f"更新数据源健康状态失败: {e}")
    
    def _create_bottom_buttons(self, main_layout):
        """创建底部按钮区域"""
        button_frame = QWidget()
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(0, 2, 0, 0)
        button_layout.setSpacing(6)
        
        restore_btn = QPushButton("恢复默认")
        _set_widget_style(restore_btn, STYLE_SECONDARY_BTN)
        restore_btn.clicked.connect(self._restore_default_and_confirm)
        button_layout.addWidget(restore_btn)
        
        button_layout.addStretch(1)

        self.auto_save_settings_cb = QCheckBox("自动保存")
        self.auto_save_settings_cb.setChecked(
            getattr(self.config.gui_config, "auto_save_settings", False)
        )
        self.auto_save_settings_cb.setToolTip(
            "修改后约 0.8 秒自动写入配置；关闭窗口时不再询问是否保存。"
        )
        _set_widget_style(self.auto_save_settings_cb, STYLE_CHECKBOX_SMALL)
        button_layout.addWidget(self.auto_save_settings_cb)

        save_tab_btn = QPushButton("保存当前页")
        _set_widget_style(save_tab_btn, STYLE_SECONDARY_BTN)
        save_tab_btn.clicked.connect(self._save_current_tab_settings)
        button_layout.addWidget(save_tab_btn)

        save_all_btn = QPushButton("保存全部")
        _set_widget_style(save_all_btn, STYLE_SAVE_BTN)
        save_all_btn.clicked.connect(lambda: self._save_all_settings())
        button_layout.addWidget(save_all_btn)
        
        cancel_btn = QPushButton("取消")
        _set_widget_style(cancel_btn, STYLE_CANCEL_BTN)
        cancel_btn.clicked.connect(self._on_cancel_clicked)
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
                        """批处理重启失败时的兜底：延迟启动新进程后退出。"""
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
            show_warning(
                self, "错误",
                f"无法自动重启程序：{e}\n\n请手动关闭程序后重新打开以使设置生效。"
            )
    
    def _restore_default_and_confirm(self):
        """恢复默认数据源选中，弹窗提供「保存」与「取消」；点保存则保存并热重载。"""
        if hasattr(self, '_restore_default_selection') and hasattr(self, 'source_vars'):
            self._restore_default_selection()
            self._is_all_selected = False
            if hasattr(self, 'select_all_btn'):
                self.select_all_btn.setText("全选")
            msg = styled_message_box(self)
            msg.setWindowTitle("提示")
            msg.setIcon(QMessageBox.Information)
            msg.setText(
                "数据源已恢复为默认选中（主数据源：Jian Project）。"
                "点击「保存」将保存并立即生效。"
            )
            save_btn = msg.addButton("保存", QMessageBox.AcceptRole)
            msg.addButton("取消", QMessageBox.RejectRole)
            msg.exec_()
            if msg.clickedButton() == save_btn:
                try:
                    self._save_data_source_settings()
                except Exception as e:
                    logger.error(f"保存数据源默认选中失败: {e}")
                    show_critical(self, "错误", f"保存失败：{e}")
        else:
            show_info(self, "提示", "当前页面无数据源选项，请切换到「数据源」标签页使用恢复默认。")

    def _save_current_tab_settings(self) -> None:
        """保存当前标签页的设置。"""
        idx = self.notebook.currentIndex()
        if idx in (
            getattr(self, '_appearance_tab_index', 0),
            getattr(self, '_display_tab_index', 1),
        ):
            self._save_appearance_settings()
        elif idx == getattr(self, '_audio_tab_index', 2):
            self._save_audio_settings_and_persist()
        elif idx == getattr(self, '_data_source_tab_index', 3):
            self._save_data_source_settings()
        elif idx == getattr(self, '_advanced_tab_index', 5):
            adv = getattr(self, 'advanced_vars', {}) or {}
            required = (
                'fix_radio', 'baidu_radio', 'output_file_checkbox', 'clear_log_checkbox',
                'split_date_checkbox', 'log_size_spinbox', 'custom_url_entry',
                'baidu_app_id_entry', 'baidu_secret_entry',
            )
            if all(k in adv for k in required):
                self._save_advanced_settings(
                    adv['fix_radio'],
                    adv['baidu_radio'],
                    adv['output_file_checkbox'],
                    adv['clear_log_checkbox'],
                    adv['split_date_checkbox'],
                    adv['log_size_spinbox'],
                    adv['custom_url_entry'],
                    adv['baidu_app_id_entry'],
                    adv['baidu_secret_entry'],
                )
            else:
                show_warning(self, "提示", "高级设置未就绪，请稍后再试。")
        else:
            show_info(self, "提示", "当前页无可保存的设置项。")

    def _apply_data_source_settings_to_config(self) -> None:
        """将数据源页控件写入内存 Config（不写盘、不重启）。"""
        self._update_base_urls()
        self._apply_main_provider_connection_flags()
        if hasattr(self, "fanstudio_api_key_entry"):
            self.config.ws_config.fanstudio_api_key = self.fanstudio_api_key_entry.text().strip()
        if hasattr(self, "eqsc_login_token_entry"):
            self.config.ws_config.eqsc_login_token = self.eqsc_login_token_entry.text().strip()
        if hasattr(self, "whews_token_entry"):
            self.config.ws_config.whews_token = self.whews_token_entry.text().strip()
        # CEA App 凭证内置，不从界面读写
        try:
            from utils.whews_cea_builtin import apply_builtin_whews_cea_credentials

            apply_builtin_whews_cea_credentials(self.config.ws_config)
        except Exception:
            pass
        if hasattr(self, "_current_whews_host_from_ui"):
            self.config.ws_config.whews_host = self._current_whews_host_from_ui()
        for flag in JIAN_SHORT_TO_PARSE_FLAG.values():
            cb = getattr(self, f"{flag}_cb", None)
            if cb is not None:
                setattr(self.config.message_config, flag, cb.isChecked())
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
            ('whews_parse_jma_eew_cb', 'whews_parse_jma_eew'),
            ('whews_parse_jma_cb', 'whews_parse_jma'),
            ('whews_parse_jma_volcano_cb', 'whews_parse_jma_volcano'),
            ('whews_parse_cwa_eew_cb', 'whews_parse_cwa_eew'),
            ('whews_parse_sa_eew_cb', 'whews_parse_sa_eew'),
            ('whews_parse_kma_eew_cb', 'whews_parse_kma_eew'),
            ('whews_parse_cea_cb', 'whews_parse_cea'),
            ('whews_parse_cea_pr_cb', 'whews_parse_cea_pr'),
            ('whews_parse_cenc_cb', 'whews_parse_cenc'),
            ('whews_parse_cwa_cb', 'whews_parse_cwa'),
            ('whews_parse_hko_cb', 'whews_parse_hko'),
            ('whews_parse_usgs_cb', 'whews_parse_usgs'),
            ('whews_parse_emsc_cb', 'whews_parse_emsc'),
            ('whews_parse_bcsf_cb', 'whews_parse_bcsf'),
            ('whews_parse_gfz_cb', 'whews_parse_gfz'),
            ('whews_parse_usp_cb', 'whews_parse_usp'),
            ('whews_parse_kma_cb', 'whews_parse_kma'),
            ('whews_parse_bmkg_cb', 'whews_parse_bmkg'),
            ('whews_parse_geonet_cb', 'whews_parse_geonet'),
            ('whews_parse_tmd_cb', 'whews_parse_tmd'),
            ('whews_parse_ingv_cb', 'whews_parse_ingv'),
            ('whews_parse_nrcan_cb', 'whews_parse_nrcan'),
            ('whews_parse_mmd_cb', 'whews_parse_mmd'),
            ('whews_parse_beijing_cb', 'whews_parse_beijing'),
            ('whews_parse_yunnan_cb', 'whews_parse_yunnan'),
            ('whews_parse_ningxia_cb', 'whews_parse_ningxia'),
            ('whews_parse_tsunami_cb', 'whews_parse_tsunami'),
            ('whews_parse_ntwc_cb', 'whews_parse_ntwc'),
            ('whews_parse_ptwc_cb', 'whews_parse_ptwc'),
            ('whews_parse_incois_cb', 'whews_parse_incois'),
            ('whews_parse_jma_tsunami_cb', 'whews_parse_jma_tsunami'),
            ('whews_parse_phivolcs_cb', 'whews_parse_phivolcs'),
            ('whews_parse_sgc_cb', 'whews_parse_sgc'),
            ('whews_parse_ga_cb', 'whews_parse_ga'),
            ('whews_parse_cenais_cb', 'whews_parse_cenais'),
            ('whews_parse_gsras_cb', 'whews_parse_gsras'),
            ('whews_parse_bgs_cb', 'whews_parse_bgs'),
            ('whews_parse_ipma_cb', 'whews_parse_ipma'),
            ('whews_parse_ssn_cb', 'whews_parse_ssn'),
            ('whews_parse_afad_cb', 'whews_parse_afad'),
            ('whews_parse_sed_cb', 'whews_parse_sed'),
            ('whews_parse_noa_cb', 'whews_parse_noa'),
            ('whews_parse_scsn_cb', 'whews_parse_scsn'),
            ('whews_parse_iag_cb', 'whews_parse_iag'),
            ('whews_parse_igp_cb', 'whews_parse_igp'),
            ('whews_parse_nepal_cb', 'whews_parse_nepal'),
            ('whews_parse_typhoon_cb', 'whews_parse_typhoon'),
            ('whews_parse_weatheralarm_cb', 'whews_parse_weatheralarm'),
            ('eqsc_parse_jma_eew_cb', 'eqsc_parse_jma_eew'),
            ('eqsc_parse_jma_report_cb', 'eqsc_parse_jma_report'),
            ('eqsc_parse_jma_tsunami_cb', 'eqsc_parse_jma_tsunami'),
            ('eqsc_parse_cenc_cb', 'eqsc_parse_cenc'),
            ('eqsc_parse_cenc_ir_cb', 'eqsc_parse_cenc_ir'),
            ('eqsc_parse_cwa_cb', 'eqsc_parse_cwa'),
            ('eqsc_parse_hko_cb', 'eqsc_parse_hko'),
            ('eqsc_parse_usgs_cb', 'eqsc_parse_usgs'),
            ('eqsc_parse_emsc_cb', 'eqsc_parse_emsc'),
            ('eqsc_parse_typhoon_cb', 'eqsc_parse_typhoon'),
            ('eqsc_parse_volcano_cb', 'eqsc_parse_volcano'),
            ('openquake_parse_gq_cb', 'openquake_parse_gq'),
            ('openquake_parse_nmefc_cb', 'openquake_parse_nmefc'),
            ('openquake_parse_nmefc_wave_cb', 'openquake_parse_nmefc_wave'),
            ('openquake_parse_nmefc_surge_cb', 'openquake_parse_nmefc_surge'),
            ('openquake_parse_cma_cb', 'openquake_parse_cma'),
        ]:
            cb = getattr(self, attr, None)
            if cb is not None:
                setattr(self.config.message_config, cfg_name, cb.isChecked())
        # JMA 情报仅走 P2PQuake：强制关闭无界科技情报解析（若配置残留）
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
        if hasattr(self, 'p2pquake_parse_556_cb'):
            self.config.message_config.p2pquake_parse_556 = self.p2pquake_parse_556_cb.isChecked()
        if hasattr(self, "openquake_gq_min_magnitude_spin"):
            self.config.message_config.openquake_gq_min_magnitude = float(
                self.openquake_gq_min_magnitude_spin.value()
            )
        enforce_weather_source_mutex(self.config.message_config)
        enforce_jma_report_mutex(self.config.message_config, prefer="main")
        self._sync_data_source_connection_switches_to_config()
        self.config.message_config.use_custom_text = self.radio_custom_text.isChecked()
        for url, spin in self.http_poll_spinboxes.items():
            self.config.http_poll_intervals[url] = max(1, int(spin.value()))
        if hasattr(self, "custom_http_poll_spinbox"):
            self.config.http_poll_intervals["__custom_http__"] = max(
                1, int(self.custom_http_poll_spinbox.value())
            )
        self.config._ensure_http_poll_interval_defaults()
        self._mark_performance_mode_custom()

    def _apply_appearance_settings_to_config(self) -> tuple:
        """将外观/显示页写入内存，返回 (timezone_changed, render_changed)。"""
        display_required = (
            'timezone', 'speed', 'font_size', 'font_family', 'font_bold', 'font_italic',
            'width', 'height', 'opacity', 'vsync_enabled', 'target_fps', 'watermark_text',
            'watermark_font_family', 'watermark_font_auto', 'watermark_font_size',
            'watermark_position', 'auto_update_check_on_startup', 'warning_min_display_seconds',
            'custom_text_return_seconds',
        )
        render_required = ('cpu_radio', 'opengl_radio')
        if not all(k in self.display_vars for k in display_required) or not all(
            k in self.render_vars for k in render_required
        ):
            return False, False

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
        timezone_changed = old_timezone != new_timezone
        old_backend = getattr(self.config.gui_config, 'render_backend', None) or (
            "opengl" if self.config.gui_config.use_gpu_rendering else "cpu"
        )
        new_backend = "opengl" if self.render_vars['opengl_radio'].isChecked() else "cpu"
        render_changed = old_backend != new_backend

        g = self.config.gui_config
        mc = self.config.message_config
        g.text_speed = self.display_vars['speed'].value() / 10.0
        g.font_size = self.display_vars['font_size'].currentData()
        g.font_family = (
            self.display_vars['font_family'].currentData()
            or self.display_vars['font_family'].currentText()
        )
        g.font_bold = self.display_vars['font_bold'].isChecked()
        g.font_italic = self.display_vars['font_italic'].isChecked()
        g.window_width = self.display_vars['width'].value()
        g.window_height = self.display_vars['height'].value()
        g.opacity = self.display_vars['opacity'].value() / 10.0
        g.vsync_enabled = self.display_vars['vsync_enabled'].isChecked()
        g.target_fps = self.display_vars['target_fps'].value()
        g.timezone = new_timezone
        g.always_on_top = self.display_vars['always_on_top'].isChecked() if 'always_on_top' in self.display_vars else False
        if 'borderless' in self.display_vars:
            g.borderless = self.display_vars['borderless'].isChecked()
        if 'background_image_path' in self.display_vars:
            g.background_image_path = (self.display_vars['background_image_path'].text() or "").strip()
        if 'background_blur_radius' in self.display_vars:
            g.background_blur_radius = int(self.display_vars['background_blur_radius'].value())
        if 'background_overlay_opacity' in self.display_vars:
            g.background_overlay_opacity = self.display_vars['background_overlay_opacity'].value() / 100.0
        if 'minimize_to_tray' in self.display_vars:
            g.minimize_to_tray = self.display_vars['minimize_to_tray'].isChecked()
        if 'toast_notifications_enabled' in self.display_vars:
            g.toast_notifications_enabled = self.display_vars['toast_notifications_enabled'].isChecked()
        if hasattr(self, "auto_save_settings_cb") and self.auto_save_settings_cb is not None:
            g.auto_save_settings = self.auto_save_settings_cb.isChecked()
        self._save_audio_settings()
        if 'min_report_magnitude' in self.display_vars:
            mc.min_report_magnitude = float(self.display_vars['min_report_magnitude'].value())
        if 'geo_filter_enabled' in self.display_vars:
            mc.geo_filter_enabled = self.display_vars['geo_filter_enabled'].isChecked()
        if 'geo_filter_latitude' in self.display_vars:
            mc.geo_filter_latitude = float(self.display_vars['geo_filter_latitude'].value())
        if 'geo_filter_longitude' in self.display_vars:
            mc.geo_filter_longitude = float(self.display_vars['geo_filter_longitude'].value())
        if 'geo_filter_radius_km' in self.display_vars:
            mc.geo_filter_radius_km = float(self.display_vars['geo_filter_radius_km'].value())
        if 'weather_region_filter_enabled' in self.display_vars:
            mc.weather_region_filter_enabled = self.display_vars['weather_region_filter_enabled'].isChecked()
        if 'weather_region_filter' in self.display_vars:
            mc.weather_region_filter = (self.display_vars['weather_region_filter'].text() or "").strip()
        if 'weather_level_filter' in self.display_vars:
            _wl = self.display_vars['weather_level_filter'].currentData()
            mc.weather_level_filter = (_wl or "none").strip().lower()
        g.auto_update_check_on_startup = self.display_vars['auto_update_check_on_startup'].isChecked()
        g.watermark_text = (self.display_vars['watermark_text'].text() or "").strip()
        wm_ff_widget = self.display_vars.get('watermark_font_family')
        if wm_ff_widget is not None:
            ff = wm_ff_widget.currentData() or wm_ff_widget.currentText() or ""
            g.watermark_font_family = (ff or "").strip() if isinstance(ff, str) else ""
        wm_auto_widget = self.display_vars.get('watermark_font_auto')
        wm_size_widget = self.display_vars.get('watermark_font_size')
        if wm_auto_widget is not None and wm_size_widget is not None:
            g.watermark_font_size = 0 if wm_auto_widget.isChecked() else max(8, wm_size_widget.value())
        wm_pos_widget = self.display_vars.get('watermark_position')
        if wm_pos_widget is not None:
            pos = wm_pos_widget.currentData() or 'diagonal'
            g.watermark_position = pos
            g.watermark_angle = "45" if pos == "diagonal" else "horizontal"
        g.render_backend = new_backend
        g.use_gpu_rendering = new_backend != "cpu"
        self._mark_performance_mode_custom()

        mc.report_color = self.current_report_color
        mc.warning_color = self.current_warning_color
        mc.custom_text_color = self.current_custom_text_color
        mc.custom_text = self.custom_text_edit.toPlainText().strip() or ""
        mc.show_one_alert_per_received = self.show_one_alert_per_received_checkbox.isChecked()
        mc.force_single_line = self.force_single_line_checkbox.isChecked()
        mc.custom_text_return_after_warning = self.custom_text_return_after_warning_checkbox.isChecked()
        cb_exp = getattr(self, "disable_warning_expiry_test_cb", None)
        if cb_exp is not None:
            mc.disable_warning_expiry_for_test = cb_exp.isChecked()
        wm_min_spin = self.display_vars.get('warning_min_display_seconds')
        if wm_min_spin is not None:
            mc.warning_min_display_seconds = max(60, wm_min_spin.value() * 60)
        ct_min_spin = self.display_vars.get('custom_text_return_seconds')
        if ct_min_spin is not None:
            mc.custom_text_return_seconds = max(60, min(3600, ct_min_spin.value() * 60))
        return timezone_changed, render_changed

    def _apply_advanced_settings_to_config(self, *, show_url_warning: bool = True) -> bool:
        """将高级页写入内存；URL 非法时保留原值，仍保存告警/日志等。"""
        adv = getattr(self, 'advanced_vars', {}) or {}
        required = (
            'fix_radio', 'baidu_radio', 'output_file_checkbox', 'clear_log_checkbox',
            'split_date_checkbox', 'log_size_spinbox', 'custom_url_entry',
            'baidu_app_id_entry', 'baidu_secret_entry',
        )
        if not all(k in adv for k in required):
            return False

        custom_url = adv['custom_url_entry'].text().strip()
        if custom_url:
            low = custom_url.lower()
            if not (
                low.startswith('http://') or low.startswith('https://')
                or low.startswith('ws://') or low.startswith('wss://')
            ):
                if show_url_warning:
                    show_warning(
                        self, "警告",
                        "自定义数据源 URL 格式不正确，已保留原 URL；其余高级设置仍将保存。"
                    )
                custom_url = self.config.custom_data_source_url or ""

        use_baidu = adv['baidu_radio'].isChecked()
        self.config.translation_config.enabled = use_baidu
        self.config.translation_config.use_place_name_fix = not use_baidu
        self.config.translation_config.baidu_app_id = adv['baidu_app_id_entry'].text().strip()
        self.config.translation_config.baidu_secret = adv['baidu_secret_entry'].text().strip()
        if use_baidu and (
            not self.config.translation_config.baidu_app_id
            or not self.config.translation_config.baidu_secret
        ):
            if show_url_warning:
                show_warning(
                    self, "警告",
                    "启用百度翻译需要 AppID 与密钥，翻译功能将保持禁用。"
                )
            self.config.translation_config.enabled = False
            self.config.translation_config.use_place_name_fix = True

        self.config.log_config.output_to_file = adv['output_file_checkbox'].isChecked()
        self.config.log_config.clear_log_on_startup = adv['clear_log_checkbox'].isChecked()
        self.config.log_config.split_by_date = adv['split_date_checkbox'].isChecked()
        self.config.log_config.max_log_size = adv['log_size_spinbox'].value()
        self.config.custom_data_source_url = custom_url
        insecure_cb = adv.get('custom_insecure_ssl_cb')
        if insecure_cb is not None:
            self.config.custom_data_source_insecure_ssl = bool(insecure_cb.isChecked())
        if hasattr(self, "custom_http_poll_spinbox"):
            self.config.http_poll_intervals["__custom_http__"] = max(
                1, int(self.custom_http_poll_spinbox.value())
            )
        try:
            self._save_alert_settings()
        except Exception as e_int:
            logger.debug(f"保存告警设置失败（忽略）: {e_int}")
        if not self.config.log_config.validate():
            return False
        self._mark_performance_mode_custom()
        return True
    
    def _save_all_settings(self, show_success_message: bool = True) -> bool:
        """保存全部标签页设置（单次写盘，全部热重载生效）。"""
        try:
            if hasattr(self, 'source_vars'):
                self._apply_data_source_settings_to_config()
            self._apply_appearance_settings_to_config()
            advanced_ok = self._apply_advanced_settings_to_config(
                show_url_warning=show_success_message
            )

            if not self._save_config_with_data_source_toggles():
                if show_success_message:
                    show_critical(self, "错误", "配置保存失败，请检查磁盘权限后重试。")
                return False

            self._clear_settings_dirty()
            self.config._notify_config_changed()

            if show_success_message:
                hint = ""
                if not advanced_ok:
                    hint = "\n部分高级设置未写入（请检查日志配置）。"
                show_info(self, "成功", f"所有设置已保存！{hint}\n设置已立即生效，无需重启。")
            logger.debug("所有设置已保存（save_all）")
            return True
        except Exception as e:
            logger.error(f"保存设置失败: {e}")
            if show_success_message:
                show_critical(self, "错误", f"保存设置失败: {e}")
            return False

    def _on_auto_update_check_clicked(self):
        """手动触发软件更新检查（成功则退出以应用更新）。"""
        try:
            from utils.app_update_check import run_interactive_update_check
            if run_interactive_update_check(self, self.config):
                os._exit(0)
        except Exception as e:
            logger.error(f"检查更新失败: {e}")
            show_critical(self, "错误", str(e))

    def _get_data_source_restart_snapshot(self):
        """采集数据源连接/解析开关快照，用于保存前后判断是否需要重启。"""
        from utils.performance_presets import _data_source_snapshot
        return _data_source_snapshot(self.config)

    def _sync_data_source_connection_switches_to_config(self):
        """将「数据源」页连接开关同步到内存，避免在其他标签页保存时覆盖用户勾选。"""
        if not hasattr(self, "source_vars"):
            return
        self._update_base_urls()  # 确保 all_source_url 与当前域名一致
        self._apply_main_provider_connection_flags()
        if hasattr(self, "fanstudio_api_key_entry"):
            self.config.ws_config.fanstudio_api_key = self.fanstudio_api_key_entry.text().strip()
        if hasattr(self, "eqsc_login_token_entry"):
            self.config.ws_config.eqsc_login_token = self.eqsc_login_token_entry.text().strip()
        if hasattr(self, "whews_token_entry"):
            self.config.ws_config.whews_token = self.whews_token_entry.text().strip()
        try:
            from utils.whews_cea_builtin import apply_builtin_whews_cea_credentials

            apply_builtin_whews_cea_credentials(self.config.ws_config)
        except Exception:
            pass
        if hasattr(self, "_current_whews_host_from_ui"):
            self.config.ws_config.whews_host = self._current_whews_host_from_ui()
        if hasattr(self, "aux_sources_master_cb"):
            self.config.enabled_sources[AUX_SOURCES_MASTER_KEY] = (
                self.aux_sources_master_cb.isChecked()
            )
        for flag in JIAN_SHORT_TO_PARSE_FLAG.values():
            cb = getattr(self, f"{flag}_cb", None)
            if cb is not None:
                setattr(self.config.message_config, flag, cb.isChecked())
        all_url = self.all_source_url
        for url, checkbox in self.source_vars.items():
            if url and url != all_url and not is_whews_url(url):
                self.config.enabled_sources[url] = checkbox.isChecked()  # 逐项同步单项源开关
        aux_on = aux_sources_enabled(self.config.enabled_sources)
        if hasattr(self, "p2pquake_connect_cb"):
            p2p_master = bool(aux_on and self.p2pquake_connect_cb.isChecked())
            self.config.enabled_sources[P2PQUAKE_WSS_URL] = p2p_master  # 总开关只控制 WSS
            for http_u in P2PQUAKE_HTTP_SOURCE_KEYS:
                # HTTP 仅启动补拉，不进入 HTTPPollingManager 持续轮询
                self.config.enabled_sources[http_u] = False
            if hasattr(self.config, "_sync_p2pquake_http_with_wss"):
                self.config._sync_p2pquake_http_with_wss()
        if hasattr(self, "wolfx_all_connect_cb"):
            wolfx_on = bool(aux_on and self.wolfx_all_connect_cb.isChecked())
            # 中国地震台网/JMA 列表经 all_eew，勾选时自动打开 Wolfx 聚合连接
            if aux_on and (
                self.config.enabled_sources.get(WOLFX_CENC_EQLIST_URL, False)
                or self.config.enabled_sources.get(WOLFX_JMA_EQLIST_URL, False)
            ):
                wolfx_on = True
                self.wolfx_all_connect_cb.setChecked(True)
            self.config.enabled_sources[WOLFX_MASTER_KEY] = wolfx_on
            self.config.enabled_sources[WOLFX_ALL_EEW_URL] = wolfx_on
            if hasattr(self.config, "_ensure_wolfx_source_defaults"):
                self.config._ensure_wolfx_source_defaults()
        if hasattr(self, "openquake_connect_cb"):
            self.config.enabled_sources[OPENQUAKE_WS_ALL_URL] = bool(
                aux_on and self.openquake_connect_cb.isChecked()
            )
        if not aux_on:
            self.config.enabled_sources[EQSC_HTTP_MASTER] = False
            self.config.enabled_sources[WOLFX_MASTER_KEY] = False
            self.config.enabled_sources[WOLFX_ALL_EEW_URL] = False
            self.config.enabled_sources[WOLFX_CWA_EEW_URL] = False
            self.config.enabled_sources[WOLFX_CENC_EQLIST_URL] = False
            self.config.enabled_sources[WOLFX_JMA_EQLIST_URL] = False
            self.config.enabled_sources[P2PQUAKE_WSS_URL] = False
            self.config.enabled_sources[OPENQUAKE_WS_ALL_URL] = False
        # EQSC：总开关 + 解析勾选 → 各 HTTP 子源；强制关闭不稳定的 WebSocket
        for attr, cfg_name in (
            ("eqsc_parse_jma_eew_cb", "eqsc_parse_jma_eew"),
            ("eqsc_parse_jma_report_cb", "eqsc_parse_jma_report"),
            ("eqsc_parse_jma_tsunami_cb", "eqsc_parse_jma_tsunami"),
            ("eqsc_parse_cenc_cb", "eqsc_parse_cenc"),
            ("eqsc_parse_cenc_ir_cb", "eqsc_parse_cenc_ir"),
            ("eqsc_parse_cwa_cb", "eqsc_parse_cwa"),
            ("eqsc_parse_hko_cb", "eqsc_parse_hko"),
            ("eqsc_parse_usgs_cb", "eqsc_parse_usgs"),
            ("eqsc_parse_emsc_cb", "eqsc_parse_emsc"),
            ("eqsc_parse_typhoon_cb", "eqsc_parse_typhoon"),
            ("eqsc_parse_volcano_cb", "eqsc_parse_volcano"),
            ("openquake_parse_gq_cb", "openquake_parse_gq"),
            ("openquake_parse_nmefc_cb", "openquake_parse_nmefc"),
            ("openquake_parse_nmefc_wave_cb", "openquake_parse_nmefc_wave"),
            ("openquake_parse_nmefc_surge_cb", "openquake_parse_nmefc_surge"),
            ("openquake_parse_cma_cb", "openquake_parse_cma"),
        ):
            cb = getattr(self, attr, None)
            if cb is not None:
                setattr(self.config.message_config, cfg_name, cb.isChecked())
        if hasattr(self, "openquake_gq_min_magnitude_spin"):
            self.config.message_config.openquake_gq_min_magnitude = float(
                self.openquake_gq_min_magnitude_spin.value()
            )
        enforce_weather_source_mutex(self.config.message_config)
        enforce_jma_report_mutex(self.config.message_config, prefer="main")
        if hasattr(self, "eqsc_connect_cb") or EQSC_HTTP_MASTER in self.source_vars:
            # EQSC 总开关来自 source_vars 勾选；辅源关闭时上面已强制 False
            pass
        if hasattr(self.config, "_sync_eqsc_http_from_parse_flags"):
            self.config._sync_eqsc_http_from_parse_flags()
        if hasattr(self.config, "_ensure_whews_source_defaults"):
            self.config._ensure_whews_source_defaults()
        removed_ws = self.config._enforce_public_ws_sources()  # 移除非公开版允许的 WS 地址
        if removed_ws:
            logger.debug(f"同步数据源连接开关时已清理非公开 WebSocket: {removed_ws}")
        self.config.ws_urls = self.config._build_ws_urls_ordered()  # 按启用状态重建 WS 连接列表

    def _save_config_with_data_source_toggles(self) -> bool:
        """保存配置前同步数据源连接开关，防止跨标签页保存把旧开关写回文件。"""
        self._sync_data_source_connection_switches_to_config()
        return bool(self.config.save_config())
    
    def _save_data_source_settings(self, silent_restart=False):
        """保存数据源设置并热重载。silent_restart 参数已废弃，保留仅为兼容调用。"""
        try:
            _ = silent_restart
            self._apply_data_source_settings_to_config()
            logger.info(
                f"已更新ws_urls，包含{len(self.config.ws_urls)}个WebSocket数据源: {self.config.ws_urls}"
            )

            if not self._save_config_with_data_source_toggles():
                show_critical(self, "错误", "数据源设置保存失败")
                return

            self._clear_settings_dirty()
            self.config._notify_config_changed()
            logger.debug("数据源设置已保存")
            show_info(
                self,
                "成功",
                "数据源设置已保存！\n设置已立即生效，无需重启程序。",
            )
            return
            
        except Exception as e:
            logger.error(f"保存数据源设置失败: {e}")
            show_critical(self, "错误", f"保存设置失败: {e}")
    
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
            show_critical(self, "错误", f"打开颜色选择器失败: {e}")
    
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
                _set_widget_style(self.report_color_preview, 
                    f"background-color: {color_upper}; "
                    "border: 1px solid #000; "
                    "border-radius: 3px;"
                )
                self.report_color_label.setText(color_upper)
            elif color_type == 'warning':
                self.current_warning_color = color_upper
                _set_widget_style(self.warning_color_preview, 
                    f"background-color: {color_upper}; "
                    "border: 1px solid #000; "
                    "border-radius: 3px;"
                )
                self.warning_color_label.setText(color_upper)
            elif color_type == 'custom_text':
                self.current_custom_text_color = color_upper
                _set_widget_style(self.custom_text_color_preview, 
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
                _set_widget_style(self.report_color_preview, 
                    f"background-color: {default_color}; "
                    "border: 1px solid #000; "
                    "border-radius: 3px;"
                )
                self.report_color_label.setText(default_color)
            elif color_type == 'warning':
                default_color = '#FF0000'  # 默认红色
                self.current_warning_color = default_color
                _set_widget_style(self.warning_color_preview, 
                    f"background-color: {default_color}; "
                    "border: 1px solid #000; "
                    "border-radius: 3px;"
                )
                self.warning_color_label.setText(default_color)
            elif color_type == 'custom_text':
                default_color = '#01FF00'  # 默认绿色
                self.current_custom_text_color = default_color
                _set_widget_style(self.custom_text_color_preview, 
                    f"background-color: {default_color}; "
                    "border: 1px solid #000; "
                    "border-radius: 3px;"
                )
                self.custom_text_color_label.setText(default_color)
            
            logger.debug(f"颜色已恢复默认: {color_type} -> {default_color}")
            
        except Exception as e:
            logger.error(f"恢复默认颜色失败: {e}")
    
    def _mark_performance_mode_custom(self) -> None:
        """手动保存单项设置后，标记为不再跟随性能预设。"""
        self.config.gui_config.performance_mode = PERFORMANCE_MODE_CUSTOM
        combo = getattr(self, 'performance_vars', {}) or {}
        widget = combo.get('performance_mode_combo')
        if widget is not None:
            idx = widget.findData(PERFORMANCE_MODE_CUSTOM)
            if idx >= 0:
                widget.setCurrentIndex(idx)

    @staticmethod
    def _backgrounds_dir():
        from pathlib import Path
        return Path.home() / "AppData" / "Roaming" / "subtitl" / "backgrounds"

    def _resolve_custom_background_source(self) -> str:
        """返回保留的原图路径（供再次裁切）；无原图时回退到当前展示图。"""
        from utils.builtin_backgrounds import resolve_background_image_file
        bg_dir = self._backgrounds_dir()
        if bg_dir.is_dir():
            for p in sorted(bg_dir.glob("custom_bg_source.*")):
                if p.is_file():
                    return str(p)
        cur = ""
        if "background_image_path" in getattr(self, "display_vars", {}):
            cur = (self.display_vars["background_image_path"].text() or "").strip()
        if not cur:
            cur = str(getattr(self.config.gui_config, "background_image_path", "") or "").strip()
        return resolve_background_image_file(cur)

    def _subtitle_window_size_for_crop(self):
        """
        裁切目标尺寸：绑定当前字幕窗口。
        优先设置页宽高（可能尚未应用），其次主窗口实时尺寸，最后配置值。
        """
        aw = ah = 0
        # 1) 设置页上的窗口宽高
        try:
            dv = getattr(self, "display_vars", {}) or {}
            for wkey in ("width", "window_width"):
                if wkey in dv:
                    aw = int(dv[wkey].value())
                    break
            for hkey in ("height", "window_height"):
                if hkey in dv:
                    ah = int(dv[hkey].value())
                    break
        except Exception:
            aw = ah = 0
        # 2) 主窗口实时尺寸（用户拖拽改过后最准）
        if aw < 50 or ah < 20:
            try:
                parent = self.parent()
                if parent is not None:
                    pw, ph = int(parent.width()), int(parent.height())
                    if pw >= 50 and ph >= 20:
                        aw, ah = pw, ph
            except Exception:
                pass
        # 3) 配置兜底
        if aw < 50 or ah < 20:
            try:
                aw = int(getattr(self.config.gui_config, "window_width", 1000) or 1000)
                ah = int(getattr(self.config.gui_config, "window_height", 100) or 100)
            except (TypeError, ValueError):
                aw, ah = 1000, 100
        aw = max(50, min(20000, int(aw)))
        ah = max(20, min(5000, int(ah)))
        return aw, ah

    def _crop_background_image(self, src_path: str):
        """弹出裁切对话框，按当前字幕窗口尺寸裁切并缩放到该像素大小；取消返回 None。"""
        from PyQt5.QtCore import Qt

        aw, ah = self._subtitle_window_size_for_crop()
        img = ImageCropDialog.crop_file(self, src_path, aspect_w=aw, aspect_h=ah)
        if img is None or img.isNull():
            return None
        # 输出像素与窗口一致，避免后续铺满时二次取景偏移
        if img.width() != aw or img.height() != ah:
            img = img.scaled(aw, ah, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        if img is None or img.isNull():
            return None
        return img.copy()

    def _store_background_image(
        self,
        src_path: str = "",
        qimage=None,
        keep_source: bool = False,
    ) -> str:
        """
        将用户选择/裁切后的背景图写入 AppData/subtitl/backgrounds/。
        - qimage：裁切后的展示图，存为 custom_bg.png
        - src_path：上传原图，另存为 custom_bg_source.* 供再次裁切
        - keep_source=True：仅更新展示图，不改动原图缓存
        """
        try:
            import shutil
            from pathlib import Path
            from PyQt5.QtGui import QImage

            bg_dir = self._backgrounds_dir()
            bg_dir.mkdir(parents=True, exist_ok=True)

            if src_path and not keep_source:
                src = Path(src_path)
                if src.is_file():
                    ext = src.suffix.lower() or ".png"
                    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
                        ext = ".png"
                    for old in bg_dir.glob("custom_bg_source.*"):
                        try:
                            old.unlink()
                        except OSError:
                            pass
                    shutil.copy2(str(src), str(bg_dir / f"custom_bg_source{ext}"))

            if qimage is not None and isinstance(qimage, QImage) and not qimage.isNull():
                dest_name = "custom_bg.png"
                dest = bg_dir / dest_name
                for old in bg_dir.glob("custom_bg.*"):
                    # 勿误删 custom_bg_source.*
                    if old.stem != "custom_bg" or old.name == dest_name:
                        continue
                    try:
                        old.unlink()
                    except OSError:
                        pass
                if not qimage.save(str(dest), "PNG"):
                    show_critical(self, "错误", "保存裁切后的背景图失败")
                    return ""
                logger.info(f"已保存自定义背景(裁切): {dest}")
                return dest_name

            src = Path(src_path or "")
            if not src.is_file():
                show_critical(self, "错误", "所选文件不存在")
                return ""
            ext = src.suffix.lower() or ".png"
            if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
                ext = ".png"
            dest_name = f"custom_bg{ext}"
            dest = bg_dir / dest_name
            for old in bg_dir.glob("custom_bg.*"):
                if old.stem != "custom_bg" or old.name == dest_name:
                    continue
                try:
                    old.unlink()
                except OSError:
                    pass
            shutil.copy2(str(src), str(dest))
            logger.info(f"已保存自定义背景: {dest}")
            return dest_name
        except Exception as e:
            logger.error(f"保存背景图失败: {e}")
            show_critical(self, "错误", f"保存背景图失败: {e}")
            return ""

    def _apply_performance_preset(self) -> None:
        """应用所选低/中/高/极致性能模式。"""
        perf = getattr(self, 'performance_vars', {}) or {}
        combo = perf.get('performance_mode_combo')
        if combo is None:
            return
        mode = combo.currentData()
        if mode in (None, PERFORMANCE_MODE_CUSTOM):
            show_info(
                self,
                "提示",
                "请在下拉框中选择「低性能模式」「中性能模式」「高性能模式」或「极致模式」后再点击应用。",
            )
            return
        if mode == PERFORMANCE_MODE_EXTREME:
            hint = performance_mode_budget_hint(PERFORMANCE_MODE_EXTREME)
            msg = styled_message_box(self)
            msg.setWindowTitle("开启极致模式")
            msg.setIcon(QMessageBox.Warning)
            msg.setText(
                "极致模式将显著提高 CPU 与内存占用，以换取最佳渲染与数据处理能力。"
            )
            msg.setInformativeText(
                f"目标资源上限：{hint}。\n\n"
                "若本机配置较低，可能出现卡顿或内存不足。是否继续开启？"
            )
            confirm_btn = msg.addButton("开启极致模式", QMessageBox.AcceptRole)
            msg.addButton("取消", QMessageBox.RejectRole)
            msg.exec_()
            if msg.clickedButton() != confirm_btn:
                return
        try:
            result = self.config.apply_performance_preset(mode)
            self._reload_controls_from_config()
            self._save_config_with_data_source_toggles()
            self.config._notify_config_changed()
            label = PERFORMANCE_MODE_LABELS.get(mode, mode)
            show_info(
                self,
                "成功",
                f"已应用{label}，相关设置已保存并立即生效。",
            )
            logger.info(
                "用户已应用性能模式: %s (render_changed=%s, sources_changed=%s)",
                mode,
                result.get("render_backend_changed"),
                result.get("sources_changed"),
            )
        except Exception as e:
            logger.error(f"应用性能模式失败: {e}", exc_info=True)
            show_critical(self, "错误", f"应用性能模式失败：{e}")

    def _save_display_settings(self):
        """保存显示设置"""
        try:
            required = ('timezone', 'speed', 'font_size', 'font_family', 'font_bold', 'font_italic', 'width', 'height', 'opacity', 'vsync_enabled', 'target_fps', 'watermark_text', 'watermark_font_family', 'watermark_font_auto', 'watermark_font_size', 'watermark_position')
            if not all(k in self.display_vars for k in required):
                logger.warning("显示设置未就绪，请先打开「外观」或「显示」页")
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
            self._mark_performance_mode_custom()
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
            if 'borderless' in self.display_vars:
                self.config.gui_config.borderless = self.display_vars['borderless'].isChecked()
            if 'background_image_path' in self.display_vars:
                self.config.gui_config.background_image_path = (
                    self.display_vars['background_image_path'].text() or ""
                ).strip()
            if 'background_blur_radius' in self.display_vars:
                self.config.gui_config.background_blur_radius = int(
                    self.display_vars['background_blur_radius'].value()
                )
            if 'background_overlay_opacity' in self.display_vars:
                self.config.gui_config.background_overlay_opacity = (
                    self.display_vars['background_overlay_opacity'].value() / 100.0
                )

            # 保存到文件
            self._save_config_with_data_source_toggles()

            # 通知主窗口更新（热更新，立即生效）
            self.config._notify_config_changed()

            show_info(self, "成功", "显示设置已保存！\n设置已立即生效，无需重启程序。")
            logger.debug("显示设置已保存（热更新）")
            
        except Exception as e:
            logger.error(f"保存显示设置失败: {e}")
            show_critical(self, "错误", f"保存设置失败: {e}")

    def _save_render_settings(self):
        """保存渲染方式设置（仅渲染方式页使用）"""
        try:
            render_required = ('cpu_radio', 'opengl_radio')
            if not all(k in self.render_vars for k in render_required):
                logger.warning("渲染设置未就绪，请先打开「外观」或「显示」页")
                return
            if self.render_vars['opengl_radio'].isChecked():
                new_backend = "opengl"
            else:
                new_backend = "cpu"
            self.config.gui_config.render_backend = new_backend
            self.config.gui_config.use_gpu_rendering = (new_backend != "cpu")
            self._mark_performance_mode_custom()
            self._save_config_with_data_source_toggles()
            self.config._notify_config_changed()
            show_info(self, "成功", "渲染方式已保存！\n设置已立即生效，无需重启程序。")
            logger.debug("渲染方式已保存（热更新）")
        except Exception as e:
            logger.error(f"保存渲染方式失败: {e}")
            show_critical(self, "错误", f"保存设置失败: {e}")
    
    def _save_color_settings(self):
        """保存字体颜色设置"""
        try:
            # 更新颜色配置
            self.config.message_config.report_color = self.current_report_color
            self.config.message_config.warning_color = self.current_warning_color
            self.config.message_config.custom_text_color = self.current_custom_text_color
            
            # 保存到文件
            self._save_config_with_data_source_toggles()
            
            # 通知主窗口更新（热更新，立即生效）
            self.config._notify_config_changed()
            
            show_info(self, "成功", "字体颜色设置已保存！\n设置已立即生效，无需重启程序。")
            logger.debug("字体颜色设置已保存（热更新）")
            
        except Exception as e:
            logger.error(f"保存字体颜色设置失败: {e}")
            show_critical(self, "错误", f"保存设置失败: {e}")

    def _on_custom_text_return_after_warning_toggled(self, checked: bool, minutes_spin):
        """勾选「预警后限时显示速报再回自定义（beta版）」时弹出二次确认；取消则恢复未勾选。"""
        minutes_spin.setEnabled(checked)
        if not checked:
            return
        warning_text = (
            "功能仅为 Beta 测试版本，仅供测试与评估使用，不建议在直播场景中使用；"
            "开发者不提供任何明示或默示的适用性、稳定性保证，由此产生的一切后果及相关责任均由用户自行承担！"
        )
        msg = styled_message_box(self)
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
        """保存「外观」+「显示」页全部设置，保存后热重载生效。"""
        try:
            display_required = ('timezone', 'speed', 'font_size', 'font_family', 'font_bold', 'font_italic', 'width', 'height', 'opacity', 'vsync_enabled', 'target_fps', 'watermark_text', 'watermark_font_family', 'watermark_font_auto', 'watermark_font_size', 'watermark_position', 'auto_update_check_on_startup', 'warning_min_display_seconds', 'custom_text_return_seconds')
            render_required = ('cpu_radio', 'opengl_radio')
            if not all(k in self.display_vars for k in display_required) or not all(k in self.render_vars for k in render_required):
                logger.warning("外观/显示设置未就绪，请先打开「外观」或「显示」页")
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
            if 'borderless' in self.display_vars:
                self.config.gui_config.borderless = self.display_vars['borderless'].isChecked()
            if 'background_image_path' in self.display_vars:
                self.config.gui_config.background_image_path = (
                    self.display_vars['background_image_path'].text() or ""
                ).strip()
            if 'background_blur_radius' in self.display_vars:
                self.config.gui_config.background_blur_radius = int(
                    self.display_vars['background_blur_radius'].value()
                )
            if 'background_overlay_opacity' in self.display_vars:
                self.config.gui_config.background_overlay_opacity = (
                    self.display_vars['background_overlay_opacity'].value() / 100.0
                )
            if 'minimize_to_tray' in self.display_vars:
                self.config.gui_config.minimize_to_tray = self.display_vars['minimize_to_tray'].isChecked()
            if 'toast_notifications_enabled' in self.display_vars:
                self.config.gui_config.toast_notifications_enabled = self.display_vars['toast_notifications_enabled'].isChecked()
            if hasattr(self, "auto_save_settings_cb") and self.auto_save_settings_cb is not None:
                self.config.gui_config.auto_save_settings = self.auto_save_settings_cb.isChecked()
            self._save_audio_settings()
            if 'min_report_magnitude' in self.display_vars:
                self.config.message_config.min_report_magnitude = float(
                    self.display_vars['min_report_magnitude'].value()
                )
            if 'geo_filter_enabled' in self.display_vars:
                self.config.message_config.geo_filter_enabled = self.display_vars['geo_filter_enabled'].isChecked()
            if 'geo_filter_latitude' in self.display_vars:
                self.config.message_config.geo_filter_latitude = float(
                    self.display_vars['geo_filter_latitude'].value()
                )
            if 'geo_filter_longitude' in self.display_vars:
                self.config.message_config.geo_filter_longitude = float(
                    self.display_vars['geo_filter_longitude'].value()
                )
            if 'geo_filter_radius_km' in self.display_vars:
                self.config.message_config.geo_filter_radius_km = float(
                    self.display_vars['geo_filter_radius_km'].value()
                )
            if 'weather_region_filter_enabled' in self.display_vars:
                self.config.message_config.weather_region_filter_enabled = (
                    self.display_vars['weather_region_filter_enabled'].isChecked()
                )
            if 'weather_region_filter' in self.display_vars:
                self.config.message_config.weather_region_filter = (
                    self.display_vars['weather_region_filter'].text() or ""
                ).strip()
            if 'weather_level_filter' in self.display_vars:
                _wl = self.display_vars['weather_level_filter'].currentData()
                self.config.message_config.weather_level_filter = (_wl or "none").strip().lower()
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

            self._mark_performance_mode_custom()

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

            self._save_config_with_data_source_toggles()
            self.config._notify_config_changed()
            self._clear_settings_dirty()
            
            show_info(self, "成功", "设置已保存！\n设置已立即生效，无需重启程序。")
            logger.debug("外观/显示设置已保存")
        except Exception as e:
            logger.error(f"保存外观/显示设置失败: {e}")
            show_critical(self, "错误", f"保存设置失败: {e}")
    
    def update_weather_image(self, weather_data: Dict[str, Any]):
        """
        更新气象预警图片显示（已移除，不再在设置页面显示）
        
        Args:
            weather_data: 气象预警数据字典
        """
        # 不再在设置页面显示气象预警图片
        pass
