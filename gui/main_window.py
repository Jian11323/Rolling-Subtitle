#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口模块
负责GUI界面的创建和管理
"""

import sys
import os
import asyncio
import threading
import time
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QMenu, QApplication, QMessageBox,
    QDialog, QLabel, QScrollArea, QPushButton, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt5.QtGui import QIcon
from typing import Dict, Any, Optional, Union

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config, APP_VERSION, CHANGELOG_TEXT
from data_sources import WebSocketManager, HTTPPollingManager
from utils.message_processor import MessageProcessor
from utils.logger import get_logger
from utils import timezone_utils

from .scrolling_text import ScrollingText, ScrollingTextCPU
from .message_manager import MessageQueue, MessageBuffer, MessageItem

logger = get_logger()


class MainWindow(QMainWindow):
    """地震预警及情报实况栏主窗口"""
    
    # 定义信号：用于在主线程中更新设置窗口的气象预警图片
    weather_image_update = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.message_processor = MessageProcessor()
        self.message_queue = MessageQueue(maxsize=100)
        self.message_buffer = MessageBuffer(max_size=20)
        # 分别存储预警和速报消息
        self.warning_buffer = MessageBuffer(max_size=20, use_priority=True)
        self.report_buffer = MessageBuffer(max_size=20, use_priority=True)
        self.scrolling_text: Optional[Union[ScrollingText, ScrollingTextCPU]] = None
        self.data_sources: Dict[str, Any] = {}
        self.ws_manager: Optional[WebSocketManager] = None  # WebSocket管理器引用

        # 状态标志
        self.running = True
        self.initialized = False
        self.current_display_type = None
        self._switching_to_report = False
        # 当前正在显示的消息（用于检查更新）
        self._current_displaying_message: Optional[MessageItem] = None
        # 待更新的消息（如果当前显示的消息收到更新，等滚动完成后替换）
        self._pending_update_message: Optional[MessageItem] = None
        
        # 设置窗口引用
        self.settings_window = None
        
        # 右键菜单缓存（避免每次右键点击时重新创建）
        self.context_menu = None
        
        # 连接信号到槽函数
        self.weather_image_update.connect(self._update_settings_weather_image)
        
        # 注册配置变更回调（支持热修改）
        self.config.add_config_callback(self._on_config_changed)
        
        # 初始化UI
        self._setup_ui()
        
        # 延迟启动后台任务
        QTimer.singleShot(100, self._delayed_startup)
        
        self.initialized = True
        logger.debug("主窗口初始化完成")
    
    def _delayed_startup(self):
        """延迟启动后台任务"""
        try:
            # 自定义文本模式：向 report_buffer 注入一条合成消息，非预警时显示
            if getattr(self.config.message_config, 'use_custom_text', False):
                custom_text = self.config.message_config.custom_text or '系统运行中，等待最新地震信息...'
                custom_color = getattr(self.config.message_config, 'custom_text_color', None) or '#01FF00'
                custom_msg = MessageItem(
                    text=custom_text,
                    color=custom_color,
                    timestamp=time.time(),
                    message_type='custom_text',
                    source='__custom_text__',
                )
                self.report_buffer.add(custom_msg)
                logger.info("已注入自定义文本到 report_buffer（自定义文本模式）")
            self._start_message_processing()
            self._start_data_sources()
            logger.info("后台任务已启动")
            # 预弹一次右键菜单（离屏并立即隐藏），消化首次 popup 的初始化，避免用户第一次右键时卡顿
            QTimer.singleShot(300, self._warm_up_context_menu)
            # 后台预创建设置窗口，避免首次打开时构建复杂UI导致明显卡顿
            QTimer.singleShot(1000, self._precreate_settings_window)
            # 更新说明弹窗（每个版本仅展示一次，延后到预创建之后避免被抢焦点）
            QTimer.singleShot(1500, self._show_changelog_if_needed)
        except Exception as e:
            logger.error(f"延迟启动后台任务失败: {e}")
    
    def _setup_ui(self):
        """设置用户界面"""
        try:
            # 窗口基本属性
            self.setWindowTitle("地震预警及情报实况栏")
            
            # 设置窗口图标（用于窗口标题栏）
            try:
                from utils.message_processor import get_resource_path
                icon_path = get_resource_path("logo/icon.ico")
                if icon_path.exists():
                    self.setWindowIcon(QIcon(str(icon_path)))
                    logger.info(f"已设置窗口图标: {icon_path}")
                else:
                    # 如果打包后找不到，尝试开发环境路径
                    dev_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logo', 'icon.ico')
                    if os.path.exists(dev_icon_path):
                        self.setWindowIcon(QIcon(dev_icon_path))
                        logger.info(f"已设置窗口图标（开发环境）: {dev_icon_path}")
            except Exception as e:
                logger.warning(f"设置窗口图标失败: {e}")
            
            self.setGeometry(100, 100, 
                           self.config.gui_config.window_width,
                           self.config.gui_config.window_height)
            
            # 设置窗口最小高度为100像素
            self.setMinimumHeight(100)
            
            # 设置窗口属性（不再强制置顶）
            # 移除透明背景属性，因为现在有窗口边框了
            # self.setAttribute(Qt.WA_TranslucentBackground)
            
            # 创建中央部件
            central_widget = QWidget()
            self.setCentralWidget(central_widget)
            
            # 创建布局
            layout = QVBoxLayout(central_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            
            # 创建滚动文本组件（按配置选择 CPU 或 GPU 渲染）
            if self.config.gui_config.use_gpu_rendering:
                self.scrolling_text = ScrollingText(self.config)
            else:
                self.scrolling_text = ScrollingTextCPU(self.config)
            self.scrolling_text.scroll_completed.connect(self._on_scroll_completed)
            layout.addWidget(self.scrolling_text)
            
            # 设置样式
            self.setStyleSheet(f"background-color: {self.config.gui_config.bg_color};")
            
            # 窗口居中
            self._center_window()
            
            # 创建右键菜单（绑定到主窗口和滚动文本组件）
            self._create_context_menu()
            # 同时为滚动文本组件绑定右键菜单（使用 lambda 确保坐标正确映射）
            self.scrolling_text.setContextMenuPolicy(Qt.CustomContextMenu)
            self.scrolling_text.customContextMenuRequested.connect(
                lambda pos: self._show_context_menu(pos, self.scrolling_text)
            )
            
            logger.debug("用户界面初始化完成")
            
        except Exception as e:
            logger.error(f"用户界面初始化失败: {e}")
            raise
    
    def _center_window(self):
        """窗口居中"""
        try:
            screen = QApplication.desktop().screenGeometry()
            window = self.geometry()
            x = (screen.width() - window.width()) // 2
            y = (screen.height() - window.height()) // 2
            self.move(x, y)
        except Exception as e:
            logger.error(f"窗口居中失败: {e}")
    
    def _create_context_menu(self):
        """创建右键菜单（在初始化时立即创建，避免第一次点击时的延迟）"""
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        if not getattr(self, '_context_menu_connected', False):
            self.customContextMenuRequested.connect(
                lambda pos: self._show_context_menu(pos, self)
            )
            self._context_menu_connected = True
        
        # 立即创建菜单对象，避免第一次点击时的延迟
        self.context_menu = QMenu(self)
        # 设置菜单样式（使用轻量级样式，确保白色背景）
        self.context_menu.setStyleSheet("""
            QMenu {
                background-color: white;
                color: black;
                border: 1px solid #ccc;
            }
            QMenu::item {
                padding: 5px 20px 5px 20px;
            }
            QMenu::item:selected {
                background-color: #e0e0e0;
            }
        """)
        
        # 设置菜单项
        settings_action = self.context_menu.addAction("设置")
        settings_action.triggered.connect(self._open_settings)
        
        # 退出菜单项
        exit_action = self.context_menu.addAction("退出")
        exit_action.triggered.connect(self.close)
        
        logger.debug("右键菜单已创建")
    
    def _precreate_settings_window(self):
        """后台预创建设置窗口，减少首次打开时的卡顿"""
        try:
            if self.settings_window is None:
                from .settings_window import SettingsWindow
                self.settings_window = SettingsWindow(self)
                self.settings_window.hide()
                logger.info("设置窗口已在后台预创建完成")
        except Exception as e:
            logger.debug(f"预创建设置窗口失败（可忽略）: {e}")
    
    def _warm_up_context_menu(self):
        """预弹右键菜单一次（离屏并立即隐藏），使首次 popup 的初始化在后台完成，避免用户第一次右键时卡顿"""
        try:
            if self.context_menu is None:
                return
            self.context_menu.popup(QPoint(-10000, -10000))
            QTimer.singleShot(0, self.context_menu.hide)
        except Exception as e:
            logger.debug(f"右键菜单预弹失败（可忽略）: {e}")
    
    def _show_context_menu(self, position, source_widget=None):
        """显示右键菜单（使用缓存的菜单对象，优化性能）
        
        Args:
            position: 点击位置（相对于 source_widget 的坐标）
            source_widget: 发出信号的控件，用于正确映射全局坐标；若为 None 则使用 self
        """
        # 确保菜单已创建（如果还没创建，立即创建）
        if self.context_menu is None:
            self._create_context_menu()
        
        # 使用发出信号的控件映射全局坐标，确保菜单位置正确
        widget = source_widget if source_widget is not None else self
        global_pos = widget.mapToGlobal(position)
        self.context_menu.popup(global_pos)
    
    def _update_settings_weather_image(self, weather_data: Dict[str, Any]):
        """更新设置窗口的气象预警图片（在主线程中执行）"""
        try:
            if self.settings_window and self.settings_window.isVisible():
                self.settings_window.update_weather_image(weather_data)
        except Exception as e:
            logger.error(f"更新设置窗口气象预警图片失败: {e}")
    
    def _on_config_changed(self):
        """配置变更回调（支持热修改）"""
        try:
            logger.info("检测到配置变更，开始应用热修改...")
            
            # 更新窗口大小（但不再强制重新居中，避免每次保存设置都把窗口拉回初始位置）
            new_width = self.config.gui_config.window_width
            new_height = self.config.gui_config.window_height
            current_width = self.width()
            current_height = self.height()
            
            if current_width != new_width or current_height != new_height:
                self.resize(new_width, new_height)
                logger.info(f"窗口大小已更新: {current_width}x{current_height} -> {new_width}x{new_height}")
            
            # 更新窗口透明度
            current_opacity = self.windowOpacity()
            new_opacity = self.config.gui_config.opacity
            if abs(current_opacity - new_opacity) > 0.01:  # 避免浮点数精度问题
                self.setWindowOpacity(new_opacity)
                logger.info(f"窗口透明度已更新: {current_opacity:.2f} -> {new_opacity:.2f}")
            
            # 更新背景颜色
            new_bg_color = self.config.gui_config.bg_color
            self.setStyleSheet(f"background-color: {new_bg_color};")
            logger.info(f"背景颜色已更新: {new_bg_color}")
            
            # 更新滚动文本组件的配置（包括字体大小、VSync、目标帧率、滚动速度、消息颜色等）
            if self.scrolling_text:
                logger.debug("开始更新滚动文本组件配置...")
                # 如果当前有显示的消息，确保消息类型已传递（用于颜色热修改）
                if self._current_displaying_message and self._current_displaying_message.message_type:
                    # 如果scrolling_text没有消息类型，从当前显示的消息中获取
                    if not self.scrolling_text.current_message_type:
                        self.scrolling_text.current_message_type = self._current_displaying_message.message_type
                        logger.debug(f"从当前显示消息中获取消息类型: {self._current_displaying_message.message_type}")
                
                try:
                    self.scrolling_text.apply_config_changes()
                    logger.info("滚动文本组件配置已更新（字体大小、VSync、目标帧率、滚动速度、消息颜色等）")
                except Exception as e:
                    logger.error(f"更新滚动文本组件配置时出错: {e}")
                    import traceback
                    logger.exception("详细错误信息:")
            else:
                logger.warning("滚动文本组件不存在，跳过配置更新")
            
            # 自定义文本热更新：若为自定义文本模式，更新 report_buffer 中 __custom_text__ 消息（文本与颜色）并刷新显示
            if getattr(self.config.message_config, 'use_custom_text', False):
                new_text = self.config.message_config.custom_text or ""
                custom_color = getattr(self.config.message_config, 'custom_text_color', None) or '#01FF00'
                with self.report_buffer._lock:
                    for msg in self.report_buffer.buffer:
                        if msg.source == '__custom_text__':
                            msg.text = new_text
                            msg.color = custom_color
                            break
                if (self._current_displaying_message and 
                    self._current_displaying_message.source == '__custom_text__' and 
                    self.scrolling_text):
                    self.scrolling_text.update_text(
                        new_text,
                        custom_color,
                        None,
                        force=True,
                        message_type='custom_text',
                    )
                    self._current_displaying_message.text = new_text
                    self._current_displaying_message.color = custom_color
                    logger.info("自定义文本已热更新到当前显示")
            
            logger.info("配置热修改应用完成")
            
        except Exception as e:
            logger.error(f"应用配置热修改失败: {e}")
            import traceback
            logger.exception("详细错误信息:")
    
    def _show_changelog_if_needed(self):
        """若当前版本未读过更新说明，则弹窗展示一次，关闭后记录已读版本并保存配置"""
        try:
            last_seen = getattr(self.config.gui_config, 'last_seen_changelog_version', '') or ''
            if last_seen == APP_VERSION:
                return
            dlg = QDialog(None)
            dlg.setWindowTitle("更新说明")
            dlg.setWindowModality(Qt.ApplicationModal)
            dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowStaysOnTopHint)
            dlg.setMinimumSize(380, 200)
            dlg.resize(420, 260)
            layout = QVBoxLayout(dlg)
            layout.setSpacing(10)
            layout.setContentsMargins(18, 12, 18, 12)
            title = QLabel(f"更新说明  v{APP_VERSION}")
            title.setStyleSheet("font-size: 16px; font-weight: bold; color: #333333; padding-bottom: 4px;")
            layout.addWidget(title)
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            line.setStyleSheet("background-color: #e0e0e0; max-height: 1px;")
            layout.addWidget(line)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            content = QLabel(CHANGELOG_TEXT)
            content.setWordWrap(True)
            content.setStyleSheet(
                "font-size: 13px; color: #333333; line-height: 1.5; padding: 4px 0; background: transparent;"
            )
            content.setTextInteractionFlags(Qt.TextSelectableByMouse)
            scroll.setWidget(content)
            layout.addWidget(scroll)
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            ok_btn = QPushButton("确定")
            ok_btn.setMinimumWidth(88)
            ok_btn.setMinimumHeight(32)
            ok_btn.setStyleSheet("""
                QPushButton { background-color: #4A90E2; color: white; border: none; border-radius: 4px; font-size: 13px; }
                QPushButton:hover { background-color: #357ABD; }
                QPushButton:pressed { background-color: #2E5F8F; }
            """)
            ok_btn.clicked.connect(dlg.accept)
            btn_layout.addWidget(ok_btn)
            btn_layout.addStretch()
            layout.addLayout(btn_layout)
            dlg.setStyleSheet("QDialog { background-color: #f5f5f5; }")
            dlg.exec_()
            self.config.gui_config.last_seen_changelog_version = APP_VERSION
            self.config.save_config()
            logger.debug(f"已记录更新说明已读版本: {APP_VERSION}")
        except Exception as e:
            logger.error(f"显示更新说明失败: {e}")
    
    def _open_settings(self):
        """打开设置窗口（尽量复用预创建实例，减少每次打开的卡顿）"""
        def _do_open_settings():
            try:
                from .settings_window import SettingsWindow
                if self.settings_window is None:
                    # 如果预创建失败或尚未完成，按需创建一次
                    self.settings_window = SettingsWindow(self)
                self.settings_window.show()
                self.settings_window.raise_()
                self.settings_window.activateWindow()
            except Exception as e:
                logger.error(f"打开设置窗口失败: {e}")
        # 不再额外延迟，直接在下一事件循环打开（菜单点击已结束）
        QTimer.singleShot(0, _do_open_settings)
    
    def _on_scroll_completed(self):
        """滚动完成回调"""
        try:
            # 优先检查是否有预警消息
            if self.warning_buffer.size() > 0:
                # 清理过期的预警消息
                self._clean_expired_warnings()
                
                # 如果清理后预警缓冲区为空，切换到速报模式
                if self.warning_buffer.size() == 0:
                    if self.report_buffer.size() > 0 and not self._switching_to_report:
                        self._switch_to_report_mode()
                        logger.info("预警缓冲区已空（清理过期消息后），切换到速报轮播模式")
                    return
                
                next_msg = self.warning_buffer.get_next()
                if next_msg:
                    # 首先检查预警消息是否仍然有效（无论是否是同一条消息）
                    if not self._is_warning_still_valid(next_msg):
                        # 预警消息已过期，移除并切换到速报模式
                        logger.info(f"预警消息已过期，移除并切换到速报模式: {next_msg.text[:50]}...")
                        with self.warning_buffer._lock:
                            # 从缓冲区中移除这条消息
                            self.warning_buffer.buffer = [msg for msg in self.warning_buffer.buffer 
                                                         if not msg.is_same_event(next_msg)]
                            self.warning_buffer.current_index = 0
                        
                        # 再次清理过期预警，确保所有过期消息都被移除
                        self._clean_expired_warnings()
                        
                        # 如果清理后预警缓冲区为空，切换到速报模式
                        if self.warning_buffer.size() == 0:
                            if self.report_buffer.size() > 0 and not self._switching_to_report:
                                self._switch_to_report_mode()
                            return
                        else:
                            # 如果还有有效预警，继续获取下一条
                            next_msg = self.warning_buffer.get_next()
                            if not next_msg or not self._is_warning_still_valid(next_msg):
                                # 如果下一条也过期或不存在，切换到速报
                                if self.report_buffer.size() > 0 and not self._switching_to_report:
                                    self._switch_to_report_mode()
                                return
                    
                    # 预警消息在当前滚动完成后进入播放
                    prev_msg = self._current_displaying_message
                    success = self.scrolling_text.update_text(
                        next_msg.text,
                        next_msg.color,
                        next_msg.image_path,
                        force=False,
                        message_type=next_msg.message_type,
                        parsed_data=next_msg.parsed_data
                    )
                    if success:
                        self.current_display_type = 'warning'
                        self._current_displaying_message = next_msg
                        if next_msg.message_type == 'warning' and next_msg.first_displayed_at is None:
                            next_msg.first_displayed_at = time.time()
                        self._pending_update_message = None  # 清除待更新消息
                        msg_preview = next_msg.text[:80] + "..." if len(next_msg.text) > 80 else next_msg.text
                        logger.info(f"【当前显示-预警】{msg_preview} | 预警缓冲区: {self.warning_buffer.size()}")
                        # 仅在实际切屏时记录（同一事件轮播回同一条不记录，避免刷屏）
                        prev_source = prev_msg.source if prev_msg else 'None'
                        prev_type = prev_msg.message_type if prev_msg else 'None'
                        prev_event = prev_msg.event_id if prev_msg else ''
                        is_same_item = (
                            prev_source == next_msg.source
                            and prev_event == (next_msg.event_id or '')
                        )
                        if not is_same_item:
                            logger.warning(
                                f"[切屏-预警-轮播] from source={prev_source}, type={prev_type}, event_id={prev_event} "
                                f"to source={next_msg.source}, type={next_msg.message_type}, event_id={next_msg.event_id}"
                            )
            elif self.report_buffer.size() > 0:
                # 检查是否有待更新的消息（当前数据源的消息收到更新）
                if self._pending_update_message:
                    # 使用待更新的消息（当前数据源的最新消息）
                    next_msg = self._pending_update_message
                    self._pending_update_message = None
                    # 从缓冲区中获取该数据源的最新消息（确保使用最新的）
                    updated_msg = self.report_buffer.find_by_source(next_msg.source)
                    if updated_msg:
                        next_msg = updated_msg
                        # 更新缓冲区的索引，找到这条更新后的消息在缓冲区中的位置
                        # 尽量减少锁的持有时间
                        found = False
                        with self.report_buffer._lock:
                            for i, msg in enumerate(self.report_buffer.buffer):
                                # 通过数据源匹配，找到更新后的消息
                                if msg.source == next_msg.source:
                                    # 确保使用缓冲区中的消息（最新版本）
                                    next_msg = msg
                                    self.report_buffer.current_index = i
                                    self.report_buffer._current_displaying_msg_id = id(msg)
                                    found = True
                                    logger.debug(f"找到待更新数据源【{next_msg.source}】在缓冲区中的位置: 索引={i}")
                                    break
                        
                        if not found:
                            logger.warning(f"待更新数据源【{next_msg.source}】未在缓冲区中找到")
                    else:
                        logger.warning(f"无法在缓冲区中找到数据源【{next_msg.source}】的最新消息")
                    logger.info(f"使用待更新的数据源【{next_msg.source}】消息: {next_msg.text[:50]}...")
                else:
                    # 轮播速报消息（不强制，确保上一条滚动完）
                    next_msg = self.report_buffer.get_next()
                
                if next_msg:
                    # 滚动完成后，应该立即显示下一条消息
                    if next_msg.message_type == 'weather':
                        logger.info(f"准备显示气象预警: 数据源={next_msg.source}, 图片路径={next_msg.image_path if next_msg.image_path else '无'}")
                    prev_msg = self._current_displaying_message
                    success = self.scrolling_text.update_text(
                        next_msg.text,
                        next_msg.color,
                        next_msg.image_path,
                        force=False,
                        message_type=next_msg.message_type,
                        parsed_data=next_msg.parsed_data
                    )
                    if success:
                        self.current_display_type = 'report'
                        self._current_displaying_message = next_msg
                        msg_preview = next_msg.text[:80] + "..." if len(next_msg.text) > 80 else next_msg.text
                        logger.info(f"【当前轮播】{msg_preview} | 数据源: {next_msg.source} | 缓冲区大小: {self.report_buffer.size()}")
                        # 仅在实际切屏时记录（首次显示无上一条，不记录）
                        if prev_msg:
                            prev_source = prev_msg.source
                            prev_type = prev_msg.message_type
                            prev_event = prev_msg.event_id or ''
                            logger.warning(
                                f"[切屏-速报-轮播] from source={prev_source}, type={prev_type}, event_id={prev_event} "
                                f"to source={next_msg.source}, type={next_msg.message_type}, event_id={next_msg.event_id}"
                            )
                    else:
                        logger.warning(f"速报消息更新失败: {next_msg.source} - {next_msg.text[:50]}...")
            
            # 如果当前显示的是预警，但预警缓冲区已空，立即切换到速报模式
            if self.current_display_type == 'warning' and self.warning_buffer.size() == 0:
                if self.report_buffer.size() > 0 and not self._switching_to_report:
                    logger.info("预警缓冲区已空，立即切换到速报轮播模式")
                    self._switch_to_report_mode()
                elif self.report_buffer.size() == 0:
                    # 如果速报缓冲区也为空，保持当前显示但记录日志
                    logger.debug("预警和速报缓冲区都为空，保持当前显示")
        except Exception as e:
            logger.error(f"处理滚动完成事件失败: {e}")
    
    def _update_message_image_path(self, message: MessageItem, image_path: str):
        """
        更新消息的图片路径（在主线程中执行）
        
        Args:
            message: 消息项
            image_path: 图片路径
        """
        try:
            # 更新消息的图片路径
            message.image_path = image_path
            
            # 如果当前正在显示该消息，更新显示
            if (self._current_displaying_message and 
                self._current_displaying_message.source == message.source and
                self._current_displaying_message.message_type == message.message_type):
                # 当前正在显示该消息，更新图片
                if self.scrolling_text:
                    # 更新滚动文本的图片
                    self.scrolling_text.current_image_path = image_path
                    # 如果图片在缓存中，立即显示
                    # 直接检查缓存，避免文件系统操作导致的阻塞
                    if image_path:
                        from pathlib import Path
                        try:
                            img_path = Path(image_path)
                            # 尝试解析路径（使用try-except避免阻塞）
                            try:
                                img_path_resolved = str(img_path.resolve())
                            except (OSError, PermissionError) as e:
                                logger.debug(f"解析图片路径时出错（非阻塞）: {e}")
                                img_path_resolved = str(image_path)  # 使用原始路径
                            
                            current_height = self.scrolling_text.height()
                            cache_key = f"{img_path_resolved}_{current_height}"
                            
                            with self.scrolling_text._image_cache_lock:
                                if cache_key in self.scrolling_text._image_cache:
                                    found_pixmap = self.scrolling_text._image_cache[cache_key]
                                    self.scrolling_text.current_image = found_pixmap
                                    self.scrolling_text._cached_image_width = found_pixmap.width() + 10
                                    self.scrolling_text.set_loading(False)
                                    self.scrolling_text.update()
                                    logger.info(f"已更新当前显示消息的图片: {image_path}")
                                    return
                            
                            # 如果不在缓存中，异步加载
                            self.scrolling_text._current_load_task_id += 1
                            current_task_id = self.scrolling_text._current_load_task_id
                            thread = threading.Thread(
                                target=self.scrolling_text._load_image_async,
                                args=(image_path, current_task_id),
                                daemon=True,
                                name="ImageLoader"
                            )
                            thread.start()
                        except Exception as e:
                            logger.debug(f"检查图片缓存时出错（非阻塞）: {e}")
                            logger.info(f"已触发当前显示消息的图片异步加载: {image_path}")
            
            # 更新缓冲区中的消息图片路径
            # 对于速报缓冲区
            with self.report_buffer._lock:
                for msg in self.report_buffer.buffer:
                    if (msg.source == message.source and 
                        msg.message_type == message.message_type):
                        msg.image_path = image_path
                        logger.debug(f"已更新缓冲区中消息的图片路径: {message.source}")
                        break
            
            logger.debug(f"已更新消息图片路径: {message.source} -> {image_path}")
        except Exception as e:
            logger.error(f"更新消息图片路径失败: {e}")
    
    def _switch_to_warning_mode(self, message: MessageItem, force_interrupt: bool = False):
        """
        切换到预警模式
        
        Args:
            message: 要显示的预警消息
            force_interrupt: 是否强制打断当前滚动（速报模式下收到预警时使用，不加入缓冲区）
        """
        try:
            if self.scrolling_text and message:
                # 确保加载状态被清除（如果没有图片）
                if not message.image_path:
                    self.scrolling_text.set_loading(False)
                
                # 更新缓冲区的当前显示消息索引（供 get_next 轮播使用；速报打断时消息已先加入缓冲区）
                found_index = -1
                with self.warning_buffer._lock:
                    for i, msg in enumerate(self.warning_buffer.buffer):
                        if id(msg) == id(message) or msg.is_same_event(message):
                            found_index = i
                            break
                    
                    if found_index >= 0:
                        self.warning_buffer.current_index = found_index
                        self.warning_buffer._current_displaying_msg_id = id(self.warning_buffer.buffer[found_index])
                        logger.debug(f"更新预警缓冲区当前显示消息: 索引={found_index}, 数据源={message.source}")
                    else:
                        self.warning_buffer._current_displaying_msg_id = id(message)
                        logger.debug(f"预警消息未在缓冲区中找到，已更新当前显示消息ID: 数据源={message.source}")
                
                # force_interrupt：立即打断当前滚动；否则等待当前滚动结束
                prev_msg = self._current_displaying_message
                success = self.scrolling_text.update_text(
                    message.text,
                    message.color,
                    message.image_path,
                    force=force_interrupt,
                    message_type=message.message_type,
                    parsed_data=message.parsed_data
                )
                if success:
                    self.current_display_type = 'warning'
                    self._current_displaying_message = message
                    if message.message_type == 'warning' and message.first_displayed_at is None:
                        message.first_displayed_at = time.time()
                    self._pending_update_message = None  # 清除待更新消息
                    msg_preview = message.text[:80] + "..." if len(message.text) > 80 else message.text
                    logger.info(f"【当前显示-预警】{msg_preview} | 预警缓冲区: {self.warning_buffer.size()}")
                    # 使用WARNING级别记录切屏日志，便于长期追踪上古bug（会写入日志文件）
                    prev_source = prev_msg.source if prev_msg else 'None'
                    prev_type = prev_msg.message_type if prev_msg else 'None'
                    prev_event = prev_msg.event_id if prev_msg else ''
                    logger.warning(
                        f"[切屏-预警] from source={prev_source}, type={prev_type}, event_id={prev_event} "
                        f"to source={message.source}, type={message.message_type}, event_id={message.event_id}"
                    )
                else:
                    # 即使更新失败，也记录日志，但保持状态
                    logger.warning(f"预警消息更新失败（可能正在滚动）: {message.text[:50]}...，将在下次滚动完成时重试")
                    # 确保状态正确，即使更新失败
                    self.current_display_type = 'warning'
                    self._current_displaying_message = message
        except Exception as e:
            logger.error(f"切换到预警模式失败: {e}", exc_info=True)
    
    def _switch_to_report_mode(self):
        """切换到轮播模式"""
        try:
            if self.current_display_type == 'warning':
                # 从预警模式切换到速报模式，应该从第一条消息开始
                # 防止重复调用
                if self._switching_to_report:
                    logger.debug("正在切换到速报模式，忽略重复调用")
                    return
                
                if self.report_buffer.size() > 0:
                    if self.scrolling_text and not self.scrolling_text.is_scrolling():
                        self._switching_to_report = True
                        try:
                            # 尽量减少锁的持有时间
                            current_msg = None
                            with self.report_buffer._lock:
                                if self.report_buffer.buffer:
                                    # 从预警切换到速报，重置索引为0
                                    self.report_buffer.current_index = 0
                                    current_msg = self.report_buffer.buffer[0]
                            
                            # 在锁外调用可能阻塞的操作
                            if current_msg and self.scrolling_text:
                                self._do_switch_to_report(current_msg)
                            else:
                                self._switching_to_report = False
                        except Exception as e:
                            logger.error(f"获取速报消息失败: {e}", exc_info=True)
                            self._switching_to_report = False
                else:
                    self._switching_to_report = False
                return
            
            if self._switching_to_report:
                return
            
            if self.report_buffer.size() > 0:
                # 只有在当前没有滚动时才切换，否则等待滚动完成
                if self.scrolling_text and self.scrolling_text.is_scrolling():
                    logger.debug("当前正在滚动，等待滚动完成后再切换速报消息")
                    self._switching_to_report = False
                    return
                
                # 已经在速报模式，不需要重置索引，继续轮播
                # 索引会在 get_next() 中自动更新
                self._switching_to_report = False
            else:
                self._switching_to_report = False
        except Exception as e:
            logger.error(f"切换到速报模式失败: {e}", exc_info=True)
            self._switching_to_report = False
    
    def _do_switch_to_report(self, current_msg: MessageItem):
        """实际执行切换到轮播模式"""
        try:
            if current_msg and self.scrolling_text:
                # 确保加载状态被清除
                self.scrolling_text.set_loading(False)
                # 速报消息不强制，确保上一条滚动完
                # 但如果当前没有滚动，应该可以立即显示
                is_scrolling = self.scrolling_text.is_scrolling()
                logger.info(f"切换到速报模式，图片路径: {current_msg.image_path if current_msg.image_path else '无'}, 消息类型: {current_msg.message_type}")
                prev_msg = self._current_displaying_message
                success = self.scrolling_text.update_text(
                    current_msg.text,
                    current_msg.color,
                    current_msg.image_path,
                    force=not is_scrolling,
                    message_type=current_msg.message_type,
                    parsed_data=current_msg.parsed_data
                )
                if success:
                    self.current_display_type = 'report'
                    self._current_displaying_message = current_msg
                    self._pending_update_message = None  # 清除待更新消息
                    # 显示当前正在轮播的数据
                    msg_preview = current_msg.text[:80] + "..." if len(current_msg.text) > 80 else current_msg.text
                    logger.info(f"【当前轮播】{msg_preview} | 数据源: {current_msg.source} | 缓冲区大小: {self.report_buffer.size()}")
                    # 记录速报模式下的切屏行为（从预警或上一条速报切到当前速报）
                    prev_source = prev_msg.source if prev_msg else 'None'
                    prev_type = prev_msg.message_type if prev_msg else 'None'
                    prev_event = prev_msg.event_id if prev_msg else ''
                    logger.warning(
                        f"[切屏-速报] from source={prev_source}, type={prev_type}, event_id={prev_event} "
                        f"to source={current_msg.source}, type={current_msg.message_type}, event_id={current_msg.event_id}"
                    )
                else:
                    logger.warning(f"速报消息更新失败: {current_msg.source} - {current_msg.text[:50]}... (正在滚动: {is_scrolling})")
        except Exception as e:
            logger.error(f"更新滚动文本失败: {e}")
        finally:
            self._switching_to_report = False

    def _show_cancellation_notice(self, source_name: str, cancelled_message: Optional[MessageItem] = None):
        """
        立即展示取消报通知，并撤回当前预警
        """
        if not self.scrolling_text:
            return
        
        try:
            # 获取原消息前缀，保持显示一致
            prefix = None
            if cancelled_message and cancelled_message.text:
                text = cancelled_message.text
                if '】' in text:
                    prefix = text.split('】', 1)[0] + '】'
            if not prefix:
                prefix = f"【{source_name}预警】"
            
            notice_text = f"{prefix}收到取消报，撤回当前预警信息"
            notice_color = self.config.message_config.warning_color
            
            logger.info(f"展示取消报通知: {notice_text}")
            self.scrolling_text.update_text(
                notice_text,
                notice_color,
                image_path=None,
                force=True,
                message_type='warning',
                parsed_data=None
            )
            
            # 当前显示内容已撤回
            self._current_displaying_message = None
            self._pending_update_message = None
            self.current_display_type = 'warning'
        except Exception as e:
            logger.error(f"展示取消报通知失败: {e}")
    
    def on_message_received(self, source_name: str, parsed_data: Dict[str, Any]):
        """接收到消息时的回调"""
        try:
            message_type = parsed_data.get('type', 'report')
            
            # JMA数据特殊处理：检查cancel字段，如果为true，从预警缓冲区移除对应事件
            if message_type == 'warning' and source_name == 'jma':
                is_cancel = parsed_data.get('cancel', False)
                if is_cancel:
                    event_id = parsed_data.get('event_id', '')
                    if event_id:
                        # 检查当前显示的消息是否会被移除
                        current_msg_will_be_removed = (
                            self._current_displaying_message and 
                            self._current_displaying_message.source == 'jma' and 
                            self._current_displaying_message.event_id == event_id
                        )
                        
                        # 从预警缓冲区移除对应event_id的JMA消息
                        with self.warning_buffer._lock:
                            original_size = len(self.warning_buffer.buffer)
                            # 移除所有匹配event_id和source的JMA消息
                            self.warning_buffer.buffer = [
                                msg for msg in self.warning_buffer.buffer
                                if not (msg.source == 'jma' and msg.event_id == event_id)
                            ]
                            removed_count = original_size - len(self.warning_buffer.buffer)
                            
                            if removed_count > 0:
                                logger.info(f"JMA取消报：已从预警缓冲区移除 {removed_count} 条消息（event_id={event_id}）")
                            else:
                                logger.debug(f"JMA取消报：未找到对应消息（event_id={event_id}）")
                            
                            # 重置索引，避免索引越界
                            if self.warning_buffer.current_index >= len(self.warning_buffer.buffer):
                                self.warning_buffer.current_index = 0
                        
                        # 如果当前显示的消息被移除，需要立即切换显示
                        if current_msg_will_be_removed:
                            logger.info(f"JMA取消报：当前显示的消息已被移除")
                            self._show_cancellation_notice(source_name, self._current_displaying_message)
                            
                            # 如果预警缓冲区为空，切换到速报模式
                            if self.warning_buffer.size() == 0:
                                if self.report_buffer.size() > 0 and not self._switching_to_report:
                                    self._switch_to_report_mode()
                                    logger.info("JMA取消报：预警缓冲区已空，切换到速报轮播模式")
                            elif self.warning_buffer.size() > 0:
                                # 如果还有预警消息，切换到下一条
                                next_msg = self.warning_buffer.get_next()
                                if next_msg:
                                    if self.scrolling_text and not self.scrolling_text.is_scrolling():
                                        self._switch_to_warning_mode(next_msg)
                                    else:
                                        logger.info("JMA取消报：已有内容正在滚动，新预警将在当前滚动结束后显示")
                    
                    # cancel消息不进入队列，直接返回
                    return
            
            # 对于预警消息，先检查是否过期，避免将过期消息误报为格式化失败
            if message_type == 'warning':
                logger.info(f"收到预警消息: source={source_name}, place_name={parsed_data.get('place_name')}, magnitude={parsed_data.get('magnitude')}, source_type={parsed_data.get('source_type')}")
                if not self.message_processor._is_warning_valid(parsed_data):
                    # 消息已过期，静默忽略（format_message中已记录日志）
                    logger.warning(f"预警消息已过期，忽略: source={source_name}, place_name={parsed_data.get('place_name')}")
                    return
            
            message = self.message_processor.format_message(parsed_data)
            if not message:
                # 只有在消息未过期但格式化失败时才记录警告
                logger.warning(f"[{source_name}] 消息格式化失败: {message_type}, parsed_data keys: {list(parsed_data.keys())}")
                return
            
            # 对于预警消息，记录格式化成功的信息
            if message_type == 'warning':
                logger.info(f"预警消息格式化成功: {message[:100]}...")
            
            # 对于气象预警，传递parsed_data以提取预警颜色
            color = self.message_processor.get_message_color(message_type, parsed_data if message_type == 'weather' else None)
            # 图片路径不在on_message_received中同步获取，避免阻塞主线程
            # 图片路径将在消息处理循环中异步获取
            image_path = None
            if message_type == 'weather':
                # 尝试快速获取图片路径（如果已经在缓存中或路径已知）
                # 如果获取失败，将在消息处理循环中异步获取
                try:
                    image_path = self.message_processor.get_weather_image_path(parsed_data)
                    if image_path:
                        logger.info(f"✓ 气象预警图片路径已获取: {image_path}")
                    else:
                        logger.debug(f"气象预警图片路径未找到，将在消息处理循环中异步获取")
                except Exception as e:
                    logger.warning(f"快速获取气象预警图片路径失败（将在消息处理循环中异步获取）: {e}")
                    image_path = None
                
                # 延迟通知设置窗口更新气象预警图片（使用信号确保线程安全）
                # 使用QTimer.singleShot延迟执行，避免阻塞
                try:
                    raw_data = parsed_data.get('raw_data', {})
                    if raw_data:
                        QTimer.singleShot(0, lambda: self.weather_image_update.emit(raw_data))
                except Exception as e:
                    logger.error(f"延迟通知设置窗口更新气象预警图片失败: {e}")
            
            # 获取event_id（用于识别同一条地震事件的更新）
            event_id = parsed_data.get('event_id', '')
            # 获取发震时间（用于预警消息有效期检查）
            shock_time = parsed_data.get('shock_time', '')
            
            msg_item = MessageItem(
                text=message,
                color=color,
                timestamp=time.time(),
                message_type=message_type,
                source=source_name,
                image_path=image_path,
                event_id=event_id,
                shock_time=shock_time if message_type == 'warning' else None,  # 只保存预警消息的发震时间
                parsed_data=parsed_data if message_type == 'weather' else None  # 只保存气象预警的parsed_data（用于热修改时重新计算颜色和异步获取图片路径）
            )
            
            # 对于气象预警，记录图片路径信息
            if message_type == 'weather':
                logger.info(f"创建气象预警MessageItem: 数据源={source_name}, 图片路径={image_path if image_path else '无'}, parsed_data={'有' if parsed_data else '无'}")
            
            if self.message_queue.put(msg_item, block=False):
                # 只保留“新预警”的日志；速报(report)的“收到新消息”日志不再输出
                if message_type == 'warning':
                    logger.info(f"收到新预警消息 【{source_name}】: {message[:50]}...")
                elif message_type == 'weather':
                    logger.info(f"收到新气象预警消息 【{source_name}】: {message[:50]}...")
            else:
                logger.warning("消息队列已满，丢弃消息")
        except Exception as e:
            logger.error(f"处理消息时出错: {e}")
    
    def _start_message_processing(self):
        """启动消息处理循环"""
        def process_messages():
            if not self.running:
                return
            
            try:
                new_messages = []
                max_batch_size = 5  # 增加批量大小，减少处理频率
                count = 0
                while count < max_batch_size:
                    try:
                        msg = self.message_queue.get(block=False)
                        if msg is None:
                            break
                        new_messages.append(msg)
                        count += 1
                    except Exception:
                        # 队列为空或其他异常，退出循环
                        break
                
                if new_messages:
                    logger.info(f"开始处理 {len(new_messages)} 条新消息")
                    
                    # 分类消息
                    warning_messages = []
                    weather_messages = []
                    report_messages = []
                    
                    for msg in new_messages:
                        if msg.message_type == 'warning':
                            warning_messages.append(msg)
                        elif msg.message_type == 'weather':
                            weather_messages.append(msg)
                        else:
                            report_messages.append(msg)
                    
                    will_update_text = False
                    
                    # 处理预警消息
                    if warning_messages:
                        # 【速报/初始状态下收到预警】立即切换，且必须加入缓冲区，否则滚动完成后会因 buffer 为空而切回速报
                        if self.current_display_type in ('report', None):
                            from .message_manager import get_source_priority
                            # 先加入缓冲区，确保滚动完成后能继续显示预警（而非切回速报）
                            self.warning_buffer.batch_replace_by_source(warning_messages)
                            first_warning = sorted(warning_messages, key=lambda m: get_source_priority(m.source))[0]
                            if self.scrolling_text and first_warning:
                                self._switch_to_warning_mode(first_warning, force_interrupt=True)
                                logger.info(
                                    f"[速报-打断] 收到预警立即切换: {first_warning.source} | {first_warning.text[:50]}..."
                                )
                        else:
                            # 【预警模式下】保持原有逻辑：加入缓冲区，按轮播规则切换
                            results = self.warning_buffer.batch_replace_by_source(warning_messages)
                            for i, msg in enumerate(warning_messages):
                                if results[i] if i < len(results) else False:
                                    logger.debug(f"预警数据源【{msg.source}】消息已更新: {msg.text[:50]}...")
                                else:
                                    logger.debug(f"新增预警数据源【{msg.source}】消息: {msg.text[:50]}...")
                            
                            # 预警消息的“update 更新报”不应打断当前正在滚动的同一事件
                            if self.scrolling_text:
                                need_switch = False
                                if (self._current_displaying_message is None or
                                    self._current_displaying_message.message_type != 'warning'):
                                    need_switch = True
                                else:
                                    current_warning = self._current_displaying_message
                                    for msg in warning_messages:
                                        if not msg.is_same_event(current_warning):
                                            need_switch = True
                                            break
                                
                                if need_switch:
                                    first_warning = None
                                    with self.warning_buffer._lock:
                                        if self.warning_buffer.buffer:
                                            first_warning = self.warning_buffer.buffer[0]
                                    
                                    if first_warning:
                                        if not self.scrolling_text.is_scrolling():
                                            self._switch_to_warning_mode(first_warning)
                                            self.current_display_type = 'warning'
                                            logger.info(
                                                f"收到 {len(warning_messages)} 条预警消息，开始播放排序后的第一条预警"
                                            )
                                        else:
                                            logger.info(
                                                f"收到 {len(warning_messages)} 条预警消息，已有内容正在滚动，新预警已加入缓冲区等待当前滚动结束"
                                            )
                                    else:
                                        logger.warning("预警缓冲区为空，无法切换显示")
                                else:
                                    logger.info(
                                        f"收到 {len(warning_messages)} 条预警更新报（同一事件），已后台替换缓冲区，不打断当前正在滚动的内容"
                                    )
                        will_update_text = True
                    
                    # 处理气象预警和速报消息（自定义文本模式下不写入 report_buffer，仅显示自定义文本）
                    if (weather_messages or report_messages) and not getattr(self.config.message_config, 'use_custom_text', False):
                        all_messages = weather_messages + report_messages
                        
                        # 对于气象预警消息，检查图片路径并异步获取（如果需要）
                        for msg in all_messages:
                            if msg.message_type == 'weather':
                                logger.info(f"处理气象预警消息: 数据源={msg.source}, 图片路径={msg.image_path if msg.image_path else '无'}, parsed_data={'有' if msg.parsed_data else '无'}")
                            
                            if msg.message_type == 'weather' and not msg.image_path and msg.parsed_data:
                                # 在后台线程中异步获取图片路径
                                def get_image_path_async(msg_item=msg):
                                    try:
                                        image_path = self.message_processor.get_weather_image_path(msg_item.parsed_data)
                                        if image_path:
                                            # 在主线程中更新图片路径
                                            QTimer.singleShot(0, lambda path=image_path, m=msg_item: self._update_message_image_path(m, path))
                                            logger.debug(f"异步获取气象预警图片路径成功: {image_path}")
                                    except Exception as e:
                                        logger.error(f"异步获取气象预警图片路径失败: {e}")
                                
                                # 使用线程异步执行，避免阻塞
                                thread = threading.Thread(target=get_image_path_async, daemon=True, name="WeatherImagePathLoader")
                                thread.start()
                        
                        # 检查是否正在滚动
                        is_scrolling = self.scrolling_text and self.scrolling_text.is_scrolling()
                        
                        # 按数据源批量替换消息（每个数据源只保留一条最新消息），静默更新
                        update_results = self.report_buffer.batch_replace_by_source(all_messages)
                        
                        # 检查是否有消息更新，并处理当前正在显示的数据源
                        for i, msg in enumerate(all_messages):
                            if update_results[i]:
                                logger.info(f"收到数据源更新 【{msg.source}】: {msg.text[:50]}...")
                                
                                # 对于气象预警，确保图片已匹配（如果已获取）
                                if msg.message_type == 'weather':
                                    # 从缓冲区中获取实际的消息（因为batch_replace_by_source可能已经替换了）
                                    buffer_msg = self.report_buffer.find_by_source(msg.source)
                                    if buffer_msg:
                                        logger.info(f"气象预警缓冲区消息: 数据源={buffer_msg.source}, 图片路径={buffer_msg.image_path if buffer_msg.image_path else '无'}")
                                    if msg.image_path:
                                        logger.info(f"气象预警更新消息已包含图片路径: {msg.image_path}")
                                    else:
                                        logger.debug(f"气象预警更新消息图片路径正在异步获取中...")
                                
                                # 检查当前正在显示的消息是否来自同一数据源
                                is_currently_displaying_source = (self._current_displaying_message and 
                                                                  self._current_displaying_message.source == msg.source)
                                
                                if is_currently_displaying_source:
                                    # 如果当前正在显示该数据源的消息
                                    # 从缓冲区中获取更新后的消息（因为已经替换了）
                                    updated_msg = self.report_buffer.find_by_source(msg.source)
                                    if updated_msg:
                                        # 标记为待更新，等待当前数据源轮播完成后替换
                                        self._pending_update_message = updated_msg
                                        logger.debug(f"[{msg.source}] 等待轮播完成后更新")
                                    else:
                                        logger.warning(f"无法在缓冲区中找到更新后的消息: {msg.source}")
                                else:
                                    # 如果不在显示该数据源的消息，已静默更新缓冲区，不打断当前轮播
                                    logger.debug(f"数据源【{msg.source}】不在显示，已静默更新缓冲区，不打断当前轮播")
                        
                        if not warning_messages:
                            # 只有在当前没有滚动时才切换，否则等待滚动完成
                            if not is_scrolling:
                                # 延迟执行，避免阻塞UI
                                QTimer.singleShot(100, self._switch_to_report_mode)
                            else:
                                logger.debug("当前正在滚动，等待滚动完成后再切换速报消息")
                        will_update_text = True
                        
                        # 记录添加到缓冲区的消息
                        sources = [msg.source for msg in all_messages]
                        logger.info(f"已添加 {len(all_messages)} 条消息到速报缓冲区: {sources}")
                        logger.info(f"当前速报缓冲区大小: {self.report_buffer.size()}")
                    
                    logger.debug(f"处理了{len(new_messages)}条消息")
            
            except Exception as e:
                logger.error(f"处理消息时出错: {e}", exc_info=True)
            
            # 继续处理（增加延迟，减少CPU占用）
            if self.running:
                QTimer.singleShot(100, process_messages)
        
        # 延迟启动，避免初始化时阻塞
        QTimer.singleShot(500, process_messages)
    
    def _start_data_sources(self):
        """启动数据源连接"""
        try:
            # 显示加载提示
            if self.scrolling_text:
                self.scrolling_text.show_loading_message()
            
            # 启动WebSocket管理器
            ws_manager = WebSocketManager(self.on_message_received)
            self.ws_manager = ws_manager  # 保存引用，用于发送消息
            
            # 在单独线程中运行WebSocket连接
            def ws_thread():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(ws_manager.start_all_connections())
                except Exception as e:
                    logger.error(f"WebSocket连接失败: {e}")
                finally:
                    loop.close()
            
            thread = threading.Thread(target=ws_thread, daemon=True, name="WebSocketThread")
            thread.start()
            logger.debug("WebSocket连接线程已启动")
            
            # 启动HTTP轮询管理器
            http_manager = HTTPPollingManager(self.on_message_received)
            http_manager.start_all_connections()
            self.data_sources['http_polling'] = http_manager
            logger.debug("HTTP轮询管理器已启动")
            
        except Exception as e:
            logger.error(f"启动数据源失败: {e}")
    
    def _clean_expired_warnings(self) -> bool:
        """
        清理过期的预警消息
        
        Returns:
            bool: 如果清理后预警缓冲区为空且需要切换到速报模式，返回True；否则返回False
        """
        try:
            import time
            
            expired_count = 0
            current_msg_expired = False
            
            with self.warning_buffer._lock:
                valid_messages = []
                for msg in self.warning_buffer.buffer:
                    if self._is_warning_still_valid(msg):
                        valid_messages.append(msg)
                    else:
                        expired_count += 1
                        logger.debug(f"移除过期预警消息: {msg.text[:50]}...")
                        # 检查当前显示的消息是否过期
                        if (self._current_displaying_message and 
                            msg.is_same_event(self._current_displaying_message)):
                            current_msg_expired = True
                
                if expired_count > 0:
                    self.warning_buffer.buffer = valid_messages
                    # 重置索引
                    if self.warning_buffer.current_index >= len(self.warning_buffer.buffer):
                        self.warning_buffer.current_index = 0
                    logger.info(f"清理了 {expired_count} 条过期预警消息，剩余: {len(self.warning_buffer.buffer)}")
                    
                    # 如果当前显示的消息已过期，标记需要切换
                    if current_msg_expired:
                        logger.info("当前显示的预警消息已过期，需要切换到速报模式")
                    
                    # 如果清理后预警缓冲区为空，且当前显示的是预警，需要切换到速报
                    if len(self.warning_buffer.buffer) == 0 and self.current_display_type == 'warning':
                        logger.info("清理过期预警后，预警缓冲区已空，准备切换到速报模式")
                        return True
            
            return False
        except Exception as e:
            logger.error(f"清理过期预警消息失败: {e}")
            return False
    
    def _is_warning_still_valid(self, message: MessageItem) -> bool:
        """
        检查预警消息是否仍然有效（展示侧：最少展示时长 + 最多展示时长）。
        1) 若已首次展示且未满 warning_min_display_seconds（默认 5 分钟），一律视为有效。
        2) 若已首次展示且已满 5 分钟，一律视为过期并移除（所有数据源统一，从展示到结束滚动为 5 分钟）。
        3) 未设置首次展示时间时，按发震时间判断（入队侧逻辑不变）。
        
        Args:
            message: 消息项
            
        Returns:
            True表示有效，False表示已过期
        """
        try:
            min_display = self.config.message_config.warning_min_display_seconds
            # 保证最少展示时长：自首次显示起未满 min_display 秒则仍有效
            if message.first_displayed_at is not None:
                displayed_seconds = time.time() - message.first_displayed_at
                if displayed_seconds < min_display:
                    logger.debug(f"预警仍在最少展示期内: 已展示 {displayed_seconds:.0f}秒")
                    return True
                # 最多展示时长：自首次展示满 5 分钟后一律视为过期（所有数据源统一）
                logger.debug(f"预警已展示满 {min_display} 秒，视为过期: 已展示 {displayed_seconds:.0f}秒")
                return False
            
            # 优先使用保存的发震时间
            shock_time_str = message.shock_time
            if not shock_time_str:
                # 如果没有保存的发震时间，尝试从消息文本中提取
                import re
                # 匹配时间格式：2026-02-05 01:17:51 或 2026/02/05 01:17:51
                # 支持多种格式：可能在逗号后面，也可能直接在开头
                time_patterns = [
                    r'，(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{1,2}:\d{1,2})',  # 逗号后的时间
                    r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{1,2}:\d{1,2})',  # 任意位置的时间
                ]
                
                for pattern in time_patterns:
                    match = re.search(pattern, message.text)
                    if match:
                        shock_time_str = match.group(1)
                        break
                
                if not shock_time_str:
                    # 无法提取时间，默认有效（避免误删除）
                    logger.debug(f"无法提取预警消息的发震时间，默认有效: {message.text[:50]}...")
                    return True
            
            # 解析发震时间（显示时区下的时间）
            shock_time = timezone_utils.parse_display_time(shock_time_str)
            if shock_time is None:
                logger.debug(f"预警消息时间格式不匹配，默认有效: {shock_time_str}")
                return True
            
            # 计算时间差（秒），与显示时区当前时间比较
            time_diff = (timezone_utils.now_in_display_tz() - shock_time).total_seconds()
            
            msg_cfg = self.config.message_config
            max_seconds = msg_cfg.warning_shock_validity_seconds
            is_valid = time_diff <= max_seconds
            if not is_valid:
                logger.info(f"预警消息已过期: {shock_time_str}, 时间差: {time_diff:.0f}秒 ({time_diff/60:.1f}分钟)")
            else:
                logger.debug(f"预警消息仍然有效: {shock_time_str}, 剩余时间: {max_seconds - time_diff:.0f}秒")
            
            return is_valid
        except Exception as e:
            logger.error(f"检查预警有效性失败: {e}")
            # 出错时默认有效，避免误删除
            return True
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        try:
            self.running = False
            
            # 停止HTTP轮询管理器
            if 'http_polling' in self.data_sources:
                try:
                    self.data_sources['http_polling'].stop_all()
                except Exception as e:
                    logger.error(f"停止HTTP轮询管理器失败: {e}")
            
            logger.info("程序正在关闭...")
            event.accept()
        except Exception as e:
            logger.error(f"关闭窗口时出错: {e}")
            event.accept()
    
    def send_websocket_message(self, url: str, message: str) -> bool:
        """
        发送消息到WebSocket连接
        
        Args:
            url: WebSocket URL
            message: 要发送的消息（字符串或JSON字符串）
            
        Returns:
            bool: 是否发送成功
        """
        try:
            if not self.ws_manager:
                logger.warning("WebSocket管理器未初始化")
                return False
            
            return self.ws_manager.send_message(url, message)
        except Exception as e:
            logger.error(f"发送WebSocket消息失败: {e}")
            return False
