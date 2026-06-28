#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事件历史环形缓冲与导出。"""

import csv
import json
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger()


class EventHistoryStore:
    """线程安全的环形事件历史。"""

    def __init__(self, max_entries: int = 500):
        """初始化环形缓冲，max_entries 最小为 50。"""
        self._max_entries = max(50, int(max_entries or 500))
        self._entries: Deque[Dict[str, Any]] = deque(maxlen=self._max_entries)
        self._lock = threading.Lock()
        # 各数据源最新一条记录的快照（用于轮播展示）
        self._per_source_latest: Dict[str, Dict[str, Any]] = {}

    def set_max_entries(self, max_entries: int) -> None:
        """调整缓冲上限，超出部分从队首丢弃。"""
        with self._lock:
            self._max_entries = max(50, int(max_entries or 500))
            while len(self._entries) > self._max_entries:
                self._entries.popleft()

    def append(
        self,
        source_name: str,
        message_type: str,
        message_text: str,
        parsed_data: Optional[Dict[str, Any]],
        *,
        source_display: str = "",
        type_display: str = "",
        event_time: str = "",
        scroll_text: str = "",
    ) -> None:
        """追加一条事件记录，同时更新该数据源的最新快照。"""
        now_iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        entry = {
            "source_name": source_name,
            "source_display": source_display or source_name,
            "message_type": message_type,
            "type_display": type_display or message_type,
            "event_time": event_time,
            "message_text": message_text,
            "scroll_text": scroll_text or message_text,
            "received_at": now_iso,
            "received_at_ts": time.time(),
            "parsed_data": dict(parsed_data) if isinstance(parsed_data, dict) else {},
            "merged_sources": [source_name],
        }
        with self._lock:
            self._entries.append(entry)  # 环形缓冲自动丢弃最旧项
            self._per_source_latest[source_name] = dict(entry)  # 更新该源最新快照

    def update_entry(self, index: int, entry: Dict[str, Any]) -> None:
        """按索引替换已有条目（如同震跨源合并时更新 merged_sources）。"""
        with self._lock:
            if 0 <= index < len(self._entries):
                self._entries[index] = entry
                sn = entry.get("source_name")
                if sn:
                    self._per_source_latest[sn] = dict(entry)

    def find_index_from_end(self, predicate) -> Optional[int]:
        """从最新向最旧查找满足 predicate 的条目索引。"""
        with self._lock:
            items = list(self._entries)
        for i in range(len(items) - 1, -1, -1):
            if predicate(items[i]):
                return i
        return None

    def get_entries_snapshot(self) -> List[Dict[str, Any]]:
        """返回全部历史条目的深拷贝列表。"""
        with self._lock:
            return [dict(e) for e in self._entries]

    def get_per_source_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """返回各数据源最新一条记录的深拷贝字典。"""
        with self._lock:
            return {k: dict(v) for k, v in self._per_source_latest.items()}

    def clear(self) -> None:
        """清空全部历史与 per-source 快照。"""
        with self._lock:
            self._entries.clear()
            self._per_source_latest.clear()

    def export_csv(self, path: str) -> bool:
        """导出为 UTF-8 BOM CSV，列：接收时间、数据源、类型、事件时间、震级、地点、内容。"""
        rows = self.get_entries_snapshot()
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["received_at", "source", "type", "event_time", "magnitude", "place", "content"]
                )
                for r in rows:
                    pd = r.get("parsed_data") or {}
                    writer.writerow([
                        r.get("received_at", ""),
                        r.get("source_display", r.get("source_name", "")),
                        r.get("type_display", r.get("message_type", "")),
                        r.get("event_time", ""),
                        pd.get("magnitude", ""),
                        pd.get("place_name", ""),
                        r.get("message_text", ""),
                    ])
            return True
        except Exception as e:
            logger.error(f"导出 CSV 失败: {e}")
            return False

    def export_json(self, path: str) -> bool:
        """导出为 UTF-8 JSON 数组，包含完整 parsed_data。"""
        rows = self.get_entries_snapshot()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2, default=str)
            return True
        except Exception as e:
            logger.error(f"导出 JSON 失败: {e}")
            return False
