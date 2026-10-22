#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""官方通知中心：每 15 秒拉取远端生效通知，本地维护已读。"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import requests

from config import APP_VERSION
from utils.logger import get_logger
from utils.timezone_utils import utc_to_display

logger = get_logger()

POLL_INTERVAL_MS = 15_000
FETCH_URL = "https://api.sismotide.top/api/v1/notifications/updates"
USER_AGENT = f"EarthquakeScroller/{APP_VERSION}"

TYPE_LABEL = {
    "UPDATE": "更新通知",
    "BUGFIX": "修复通知",
    "NOTICE": "公告通知",
    "SECURITY": "安全通知",
    "TEST": "测试通知",
    "INFO": "公告通知",
}


def _read_path() -> Path:
    return Path.home() / "AppData" / "Roaming" / "subtitl" / "notifications_read.json"


def type_label(code: str) -> str:
    return TYPE_LABEL.get((code or "").upper(), "其他通知")


def load_read_ids() -> Set[int]:
    path = _read_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        ids = raw.get("read_ids") if isinstance(raw, dict) else None
        if isinstance(ids, list):
            out: Set[int] = set()
            for x in ids:
                try:
                    out.add(int(x))
                except (TypeError, ValueError):
                    continue
            return out
    except Exception:
        pass
    return set()


def save_read_ids(ids: Set[int]) -> None:
    path = _read_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"read_ids": sorted(ids)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug(f"保存通知已读状态失败: {e}")


def fetch_notices(timeout: float = 10.0) -> List[Dict[str, Any]]:
    """拉取生效通知列表（按 created_at / id 倒序）。"""
    url = f"{FETCH_URL}?client_version={APP_VERSION}"
    r = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
    )
    r.raise_for_status()
    data = json.loads(r.content.decode("utf-8-sig"))
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("is_active") is not True:
            continue
        try:
            nid = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "")
        if nid < 1 or not title:
            continue
        raw_created = str(item.get("created_at") or "")
        raw_updated = str(item.get("updated_at") or "")
        out.append(
            {
                "id": nid,
                "title": title,
                "content": content,
                "content_format": str(item.get("content_format") or "text"),
                "type": str(item.get("type") or "NOTICE").upper(),
                # 远端为 UTC ISO；展示统一转为配置时区（默认 Asia/Shanghai = UTC+8）
                "created_at": utc_to_display(raw_created) if raw_created else "",
                "updated_at": utc_to_display(raw_updated) if raw_updated else "",
                "created_at_raw": raw_created,
                "is_active": True,
            }
        )
    # 排序用原始 UTC，避免展示串与原始串混排
    out.sort(
        key=lambda x: (x.get("created_at_raw") or x.get("created_at") or "", x.get("id") or 0),
        reverse=True,
    )
    return out


class OfficialNoticeController:
    """主窗口持有：轮询、已读、弹窗队列。"""

    def __init__(self, on_updated: Optional[Callable[[], None]] = None):
        self._lock = threading.Lock()
        self.items: List[Dict[str, Any]] = []
        self.read_ids: Set[int] = load_read_ids()
        self.popup_queue: List[Dict[str, Any]] = []
        self._fetching = False
        self._on_updated = on_updated
        self._cold = True

    def unread_count(self) -> int:
        with self._lock:
            return sum(1 for n in self.items if int(n["id"]) not in self.read_ids)

    def is_read(self, nid: int) -> bool:
        with self._lock:
            return int(nid) in self.read_ids

    def mark_read(self, nid: int) -> None:
        with self._lock:
            nid = int(nid)
            self.read_ids.add(nid)
            self.popup_queue = [x for x in self.popup_queue if int(x["id"]) != nid]
            save_read_ids(self.read_ids)

    def mark_all_read(self) -> None:
        with self._lock:
            for n in self.items:
                self.read_ids.add(int(n["id"]))
            self.popup_queue.clear()
            save_read_ids(self.read_ids)

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(x) for x in self.items]

    def pop_popup(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self.popup_queue:
                return None
            return dict(self.popup_queue[0])

    def apply_fetched(self, items: List[Dict[str, Any]]) -> None:
        with self._lock:
            prev_ids = {int(x["id"]) for x in self.items}
            alive = {int(x["id"]) for x in items}
            self.read_ids = {i for i in self.read_ids if i in alive}
            cold = self._cold
            self._cold = False
            self.items = items
            if cold:
                if items:
                    latest = items[0]
                    lid = int(latest["id"])
                    if lid not in self.read_ids and not any(
                        int(x["id"]) == lid for x in self.popup_queue
                    ):
                        self.popup_queue.append(dict(latest))
            else:
                for n in items:
                    nid = int(n["id"])
                    if nid in prev_ids or nid in self.read_ids:
                        continue
                    if any(int(x["id"]) == nid for x in self.popup_queue):
                        continue
                    self.popup_queue.append(dict(n))
            save_read_ids(self.read_ids)
        if self._on_updated:
            try:
                self._on_updated()
            except Exception:
                pass

    def start_fetch_async(self) -> None:
        with self._lock:
            if self._fetching:
                return
            self._fetching = True

        def _run() -> None:
            try:
                items = fetch_notices()
                self.apply_fetched(items)
            except Exception as e:
                logger.debug(f"官方通知拉取失败: {e}")
            finally:
                with self._lock:
                    self._fetching = False

        threading.Thread(target=_run, name="official-notice", daemon=True).start()
