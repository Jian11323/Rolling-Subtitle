#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
事件历史窗口
按数据源展示最近一条事件记录。
"""

from typing import Dict, Any

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QLabel,
)
from PyQt5.QtCore import Qt, QTimer

from utils.logger import get_logger

logger = get_logger()


class HistoryWindow(QDialog):
    """事件历史窗口（每个 source_name 保留最新一条）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("事件历史")
        self.resize(980, 520)
        self.setModal(False)
        self.setStyleSheet("QDialog { background: #FFFFFF; }")
        self._setup_ui()
        # 自动刷新（可见时每 2 秒刷新一次）
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(2000)
        self._auto_refresh_timer.timeout.connect(self.refresh_history)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hint = QLabel("按数据源保留最新一条事件。")
        hint.setStyleSheet("color: #666666; font-size: 13px; background: #FFFFFF;")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            ["数据源", "类型", "事件时间", "内容"]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(False)
        self.table.setStyleSheet(
            """
            QTableWidget {
                background: #FFFFFF;
                color: #222222;
                gridline-color: #E6E6E6;
                border: 1px solid #DDDDDD;
                selection-background-color: #EAF3FF;
                selection-color: #222222;
            }
            QHeaderView::section {
                background: #F5F7FA;
                color: #222222;
                border: 1px solid #E6E6E6;
                padding: 6px;
            }
            QHeaderView {
                background: #F5F7FA;
            }
            QTableCornerButton::section {
                background: #F5F7FA;
                border: 1px solid #E6E6E6;
            }
            QAbstractScrollArea::corner {
                background: #F5F7FA;
                border: 1px solid #E6E6E6;
            }
            QScrollBar:vertical {
                background: #F2F2F2;
                width: 12px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #C8CDD4;
                min-height: 30px;
                border-radius: 5px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: #F2F2F2;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
                background: transparent;
                border: none;
            }
            QScrollBar:horizontal {
                background: #F2F2F2;
                height: 12px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #C8CDD4;
                min-width: 30px;
                border-radius: 5px;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: #F2F2F2;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
                background: transparent;
                border: none;
            }
            """
        )
        self._apply_scrollbar_styles()
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(
            "QPushButton { background: #28A745; color: white; border: none; border-radius: 4px; padding: 6px 14px; }"
            "QPushButton:hover { background: #218838; }"
        )
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _apply_scrollbar_styles(self):
        """为表格滚动条单独设置样式，避免刷新后被全局样式覆盖。"""
        bar_style = """
            QScrollBar {
                border: none;
                background: #F2F2F2;
            }
            QScrollBar:vertical {
                width: 12px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #C8CDD4;
                min-height: 30px;
                border-radius: 5px;
                border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: #F2F2F2;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
                background: transparent;
                border: none;
            }
            QScrollBar:horizontal {
                height: 12px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #C8CDD4;
                min-width: 30px;
                border-radius: 5px;
                border: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: #F2F2F2;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
                background: transparent;
                border: none;
            }
        """
        self.table.verticalScrollBar().setStyleSheet(bar_style)
        self.table.horizontalScrollBar().setStyleSheet(bar_style)

    def _fit_last_column_width(self):
        """让最后一列吃满可视宽度，避免右上角出现未覆盖区域。"""
        try:
            col_count = self.table.columnCount()
            if col_count <= 0:
                return
            last_col = col_count - 1
            viewport_w = self.table.viewport().width()
            used_w = 0
            for i in range(last_col):
                used_w += self.table.columnWidth(i)
            # 预留一点边距，防止触发水平滚动条
            target = max(240, viewport_w - used_w - 4)
            if target > self.table.columnWidth(last_col):
                self.table.setColumnWidth(last_col, target)
        except Exception as e:
            logger.debug(f"自适应最后一列宽度失败: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_history()
        if not self._auto_refresh_timer.isActive():
            self._auto_refresh_timer.start()

    def hideEvent(self, event):
        if self._auto_refresh_timer.isActive():
            self._auto_refresh_timer.stop()
        super().hideEvent(event)

    def refresh_history(self):
        """从主窗口读取快照并刷新表格。"""
        try:
            parent = self.parent()
            if parent is None or not hasattr(parent, "get_event_history_snapshot"):
                self.table.setRowCount(0)
                return
            data: Dict[str, Dict[str, Any]] = parent.get_event_history_snapshot() or {}
            rows = sorted(
                data.values(),
                key=lambda x: x.get("received_at", ""),
                reverse=True,
            )
            self.table.setRowCount(len(rows))
            for row_idx, item in enumerate(rows):
                self._set_item(row_idx, 0, item.get("source_name", ""))
                self._set_item(row_idx, 1, item.get("message_type", ""))
                self._set_item(row_idx, 2, item.get("event_time", ""))
                self._set_item(row_idx, 3, item.get("message_text", ""))
            self.table.resizeColumnsToContents()
            self._fit_last_column_width()
            self._apply_scrollbar_styles()
            if not rows:
                self.table.setRowCount(1)
                self._set_item(0, 0, "暂无事件记录")
                for col in range(1, 4):
                    self._set_item(0, col, "")
        except Exception as e:
            logger.error(f"刷新事件历史失败: {e}")

    def clear_history(self):
        """清空历史缓存并刷新显示。"""
        try:
            parent = self.parent()
            if parent is not None and hasattr(parent, "clear_event_history"):
                parent.clear_event_history()
            self.refresh_history()
        except Exception as e:
            logger.error(f"清空事件历史失败: {e}")

    def _set_item(self, row: int, col: int, value: str):
        text = "" if value is None else str(value)
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setItem(row, col, item)
