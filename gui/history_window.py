#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
事件历史窗口
展示环形缓冲中的事件记录，支持导出。
"""

from typing import Dict, Any, List

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QAbstractItemView,
    QLabel,
    QFileDialog,
)
from PyQt5.QtCore import Qt, QTimer

from gui.qt_light_theme import (
    apply_light_palette,
    light_dialog_stylesheet,
    LIGHT_SCROLLBAR_QSS,
    show_info,
)
from utils.logger import get_logger

logger = get_logger()


class HistoryWindow(QDialog):
    """事件历史窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("事件历史")
        self.resize(980, 520)
        self.setModal(False)
        apply_light_palette(self, "#FFFFFF")
        self.setStyleSheet(light_dialog_stylesheet("#FFFFFF"))
        self._setup_ui()
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(2000)
        self._auto_refresh_timer.timeout.connect(self.refresh_history)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hint = QLabel("展示最近收到的事件（环形缓冲）；同震跨源去重时会合并数据源。")
        hint.setStyleSheet("color: #666666; font-size: 13px; background: #FFFFFF;")
        layout.addWidget(hint)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            ["接收时间", "数据源", "类型", "事件时间", "内容"]
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
            """
            + LIGHT_SCROLLBAR_QSS
        )
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        export_csv_btn = QPushButton("导出 CSV")
        export_csv_btn.clicked.connect(self._export_csv)
        export_json_btn = QPushButton("导出 JSON")
        export_json_btn.clicked.connect(self._export_json)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_history)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        for b, style in (
            (export_csv_btn, "#1565C0"),
            (export_json_btn, "#1565C0"),
            (clear_btn, "#6C757D"),
            (close_btn, "#28A745"),
        ):
            b.setStyleSheet(
                f"QPushButton {{ background: {style}; color: white; border: none; "
                f"border-radius: 4px; padding: 6px 14px; }}"
            )
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _parent_main(self):
        p = self.parent()
        return p if p is not None else None

    def _get_rows(self) -> List[Dict[str, Any]]:
        parent = self._parent_main()
        if parent is None:
            return []
        if hasattr(parent, "get_full_event_history"):
            return parent.get_full_event_history() or []
        if hasattr(parent, "get_event_history_snapshot"):
            snap = parent.get_event_history_snapshot() or {}
            return list(snap.values())
        return []

    def refresh_history(self):
        try:
            rows = self._get_rows()
            rows = sorted(rows, key=lambda x: x.get("received_at", ""), reverse=True)
            self.table.setRowCount(len(rows))
            for row_idx, item in enumerate(rows):
                merged = item.get("merged_sources") or []
                if isinstance(merged, list) and len(merged) > 1:
                    src = " / ".join(str(s) for s in merged)
                else:
                    src = item.get("source_display") or item.get("source_name", "")
                self._set_item(row_idx, 0, item.get("received_at", ""))
                self._set_item(row_idx, 1, src)
                self._set_item(row_idx, 2, item.get("type_display") or item.get("message_type", ""))
                self._set_item(row_idx, 3, item.get("event_time", ""))
                self._set_item(row_idx, 4, item.get("message_text", ""))
            self.table.resizeColumnsToContents()
            if not rows:
                self.table.setRowCount(1)
                self._set_item(0, 0, "暂无事件记录")
                for col in range(1, 5):
                    self._set_item(0, col, "")
        except Exception as e:
            logger.error(f"刷新事件历史失败: {e}")

    def _export_csv(self):
        parent = self._parent_main()
        if parent is None or not hasattr(parent, "export_event_history_csv"):
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 CSV", "event_history.csv", "CSV (*.csv)")
        if not path:
            return
        ok = parent.export_event_history_csv(path)
        show_info(self, "导出", "导出成功" if ok else "导出失败")

    def _export_json(self):
        parent = self._parent_main()
        if parent is None or not hasattr(parent, "export_event_history_json"):
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 JSON", "event_history.json", "JSON (*.json)")
        if not path:
            return
        ok = parent.export_event_history_json(path)
        show_info(self, "导出", "导出成功" if ok else "导出失败")

    def _clear_history(self):
        parent = self._parent_main()
        if parent is not None and hasattr(parent, "clear_event_history"):
            parent.clear_event_history()
        self.refresh_history()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_history()
        if not self._auto_refresh_timer.isActive():
            self._auto_refresh_timer.start()

    def hideEvent(self, event):
        if self._auto_refresh_timer.isActive():
            self._auto_refresh_timer.stop()
        super().hideEvent(event)

    def _set_item(self, row: int, col: int, value: str):
        text = "" if value is None else str(value)
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setItem(row, col, item)
