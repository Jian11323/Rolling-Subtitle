#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安全加载本地/内存图片：限制文件体积与边长，避免超大图 OOM。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PyQt5.QtGui import QImage, QImageReader

from utils.logger import get_logger

logger = get_logger()

# 解码上限：边长与原始字节（裁剪/背景/气象图共用）
MAX_IMAGE_EDGE_PX = 8192
MAX_IMAGE_BYTES = 40 * 1024 * 1024


def _apply_scaled_size(reader: QImageReader, max_edge: int) -> None:
    """若原图任一边超过 max_edge，按比例缩小后再解码。"""
    size = reader.size()
    if not size.isValid():
        return
    w, h = int(size.width()), int(size.height())
    if w <= 0 or h <= 0:
        return
    longest = max(w, h)
    if longest <= max_edge:
        return
    scale = max_edge / float(longest)
    reader.setScaledSize(QSize(max(1, int(w * scale)), max(1, int(h * scale))))


def load_qimage_capped(
    path: str,
    *,
    max_edge: int = MAX_IMAGE_EDGE_PX,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> Optional[QImage]:
    """从文件路径加载 QImage；超限则拒绝或缩放到上限内。"""
    try:
        p = Path(path)
        if not p.is_file():
            return None
        size_b = p.stat().st_size
        if size_b > max_bytes:
            logger.warning(
                f"图片过大已跳过 ({size_b / (1024 * 1024):.1f}MB > {max_bytes // (1024 * 1024)}MB): {path}"
            )
            return None
        reader = QImageReader(str(p))
        reader.setAutoTransform(True)
        _apply_scaled_size(reader, max_edge)
        img = reader.read()
        if img is None or img.isNull():
            err = reader.errorString() if reader else ""
            logger.debug(f"图片解码失败: {path} {err}")
            return None
        return img
    except Exception as e:
        logger.warning(f"加载图片失败: {path}: {e}")
        return None


def load_qimage_from_bytes_capped(
    data: bytes,
    *,
    max_edge: int = MAX_IMAGE_EDGE_PX,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> Optional[QImage]:
    """从内存字节加载 QImage；超限则拒绝或缩放到上限内。"""
    try:
        if not data:
            return None
        if len(data) > max_bytes:
            logger.warning(
                f"图片数据过大已跳过 ({len(data) / (1024 * 1024):.1f}MB > {max_bytes // (1024 * 1024)}MB)"
            )
            return None
        ba = QByteArray(data)
        buf = QBuffer(ba)
        if not buf.open(QIODevice.ReadOnly):
            return None
        reader = QImageReader(buf)
        reader.setAutoTransform(True)
        _apply_scaled_size(reader, max_edge)
        img = reader.read()
        buf.close()
        if img is None or img.isNull():
            return None
        return img
    except Exception as e:
        logger.warning(f"从内存解码图片失败: {e}")
        return None
