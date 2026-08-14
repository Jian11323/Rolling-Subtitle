#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自定义背景图裁切对话框：拖动选择区域，按字幕窗比例裁切。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt5.QtCore import Qt, QPoint, QRect
from PyQt5.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
    QMouseEvent,
    QPaintEvent,
    QKeySequence,
)
from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
    QSizePolicy,
    QShortcut,
)

from gui.qt_light_theme import apply_light_palette, light_dialog_stylesheet


class _CropCanvas(QWidget):
    """在缩放后的预览图上绘制可拖动裁切框（固定宽高比）。"""

    def __init__(self, image: QImage, aspect: float, parent=None):
        super().__init__(parent)
        self._src = image
        self._aspect = max(0.05, float(aspect) if aspect and aspect > 0 else 10.0)
        self._display = QPixmap()
        self._img_rect = QRect()  # 预览图在控件内的位置
        self._scale = 1.0  # 原图像素 → 预览像素
        # 裁切框：原图坐标系
        self._crop = QRect()
        self._drag_offset = QPoint()
        self._dragging = False
        self.setMinimumSize(480, 280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._init_crop()

    def _init_crop(self) -> None:
        w, h = self._src.width(), self._src.height()
        if w <= 0 or h <= 0:
            self._crop = QRect()
            return
        # 尽量大的居中框，保持目标宽高比且不超出原图
        if w / h >= self._aspect:
            ch = h
            cw = int(round(ch * self._aspect))
            if cw > w:
                cw = w
                ch = int(round(cw / self._aspect))
        else:
            cw = w
            ch = int(round(cw / self._aspect))
            if ch > h:
                ch = h
                cw = int(round(ch * self._aspect))
        cw = max(1, min(w, cw))
        ch = max(1, min(h, ch))
        x = (w - cw) // 2
        y = (h - ch) // 2
        self._crop = QRect(x, y, cw, ch)

    def reset_crop(self) -> None:
        self._init_crop()
        self.update()

    def crop_rect(self) -> QRect:
        return QRect(self._crop)

    def cropped_image(self) -> Optional[QImage]:
        r = self._crop.intersected(QRect(0, 0, self._src.width(), self._src.height()))
        if r.width() < 1 or r.height() < 1:
            return None
        return self._src.copy(r)

    def _rebuild_display(self) -> None:
        aw, ah = self.width(), self.height()
        if aw < 2 or ah < 2 or self._src.isNull():
            return
        # 留边距给边框
        pad = 8
        max_w, max_h = max(1, aw - pad * 2), max(1, ah - pad * 2)
        scaled = QPixmap.fromImage(self._src).scaled(
            max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._display = scaled
        self._scale = scaled.width() / self._src.width() if self._src.width() else 1.0
        x = (aw - scaled.width()) // 2
        y = (ah - scaled.height()) // 2
        self._img_rect = QRect(x, y, scaled.width(), scaled.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild_display()

    def showEvent(self, event):
        super().showEvent(event)
        self._rebuild_display()

    def _src_to_view(self, r: QRect) -> QRect:
        if self._scale <= 0:
            return QRect()
        return QRect(
            self._img_rect.x() + int(round(r.x() * self._scale)),
            self._img_rect.y() + int(round(r.y() * self._scale)),
            max(1, int(round(r.width() * self._scale))),
            max(1, int(round(r.height() * self._scale))),
        )

    def _view_to_src_point(self, p: QPoint) -> QPoint:
        if self._scale <= 0:
            return QPoint(0, 0)
        return QPoint(
            int(round((p.x() - self._img_rect.x()) / self._scale)),
            int(round((p.y() - self._img_rect.y()) / self._scale)),
        )

    def _clamp_crop(self) -> None:
        w, h = self._src.width(), self._src.height()
        cw = max(1, min(self._crop.width(), w))
        ch = max(1, min(self._crop.height(), h))
        # 保持比例
        if cw / ch > self._aspect:
            cw = max(1, int(round(ch * self._aspect)))
        else:
            ch = max(1, int(round(cw / self._aspect)))
        cw = max(1, min(cw, w))
        ch = max(1, min(ch, h))
        x = max(0, min(self._crop.x(), w - cw))
        y = max(0, min(self._crop.y(), h - ch))
        self._crop = QRect(x, y, cw, ch)

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#2A2A2A"))
        if self._display.isNull() or self._img_rect.isEmpty():
            return
        painter.drawPixmap(self._img_rect, self._display)

        view_crop = self._src_to_view(self._crop)
        # 遮罩：裁切区外半透明
        dim = QColor(0, 0, 0, 140)
        ir = self._img_rect
        # 上
        painter.fillRect(QRect(ir.left(), ir.top(), ir.width(), max(0, view_crop.top() - ir.top())), dim)
        # 下
        painter.fillRect(
            QRect(ir.left(), view_crop.bottom() + 1, ir.width(), max(0, ir.bottom() - view_crop.bottom())),
            dim,
        )
        # 左
        mid_h = max(0, view_crop.height())
        painter.fillRect(
            QRect(ir.left(), view_crop.top(), max(0, view_crop.left() - ir.left()), mid_h),
            dim,
        )
        # 右
        painter.fillRect(
            QRect(view_crop.right() + 1, view_crop.top(), max(0, ir.right() - view_crop.right()), mid_h),
            dim,
        )

        pen = QPen(QColor("#42A5F5"), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(view_crop.adjusted(0, 0, -1, -1))
        # 角点
        hs = 6
        painter.setBrush(QColor("#42A5F5"))
        for cx, cy in (
            (view_crop.left(), view_crop.top()),
            (view_crop.right(), view_crop.top()),
            (view_crop.left(), view_crop.bottom()),
            (view_crop.right(), view_crop.bottom()),
        ):
            painter.drawRect(cx - hs // 2, cy - hs // 2, hs, hs)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return
        view_crop = self._src_to_view(self._crop)
        if view_crop.contains(event.pos()):
            self._dragging = True
            src_pt = self._view_to_src_point(event.pos())
            self._drag_offset = QPoint(src_pt.x() - self._crop.x(), src_pt.y() - self._crop.y())
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        view_crop = self._src_to_view(self._crop)
        if self._dragging:
            src_pt = self._view_to_src_point(event.pos())
            self._crop.moveTo(src_pt.x() - self._drag_offset.x(), src_pt.y() - self._drag_offset.y())
            self._clamp_crop()
            self.update()
        else:
            if view_crop.contains(event.pos()):
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            view_crop = self._src_to_view(self._crop)
            self.setCursor(Qt.OpenHandCursor if view_crop.contains(event.pos()) else Qt.ArrowCursor)

    def wheelEvent(self, event: QWheelEvent):
        """滚轮缩放裁切框（保持比例，中心尽量不变）。"""
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.08 if delta > 0 else 1 / 1.08
        cx = self._crop.center().x()
        cy = self._crop.center().y()
        nw = max(8, int(round(self._crop.width() * factor)))
        nh = max(8, int(round(nw / self._aspect)))
        w, h = self._src.width(), self._src.height()
        if nw > w or nh > h:
            if w / h >= self._aspect:
                nh = h
                nw = int(round(nh * self._aspect))
            else:
                nw = w
                nh = int(round(nw / self._aspect))
        nw = max(1, min(nw, w))
        nh = max(1, min(nh, h))
        x = int(round(cx - nw / 2))
        y = int(round(cy - nh / 2))
        self._crop = QRect(x, y, nw, nh)
        self._clamp_crop()
        self.update()
        event.accept()


class ImageCropDialog(QDialog):
    """选择图片裁切区域；确定后可通过 cropped_image() 取结果。"""

    def __init__(
        self,
        image_path: str,
        aspect_w: int = 1000,
        aspect_h: int = 100,
        parent=None,
        preloaded_image: Optional[QImage] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("裁切背景图")
        self.setModal(True)
        self.setMinimumSize(720, 520)
        self.resize(860, 600)
        apply_light_palette(self, "#FFFFFF")
        self.setStyleSheet(light_dialog_stylesheet("#FFFFFF"))

        self._result: Optional[QImage] = None

        if preloaded_image is not None and not preloaded_image.isNull():
            img = preloaded_image
        else:
            from utils.safe_image import load_qimage_capped

            img = load_qimage_capped(image_path) or QImage()
        if img.isNull():
            # 占位：后续 exec 前可检测
            self._canvas = None
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel("无法加载图片"))
            btn = QPushButton("关闭")
            btn.clicked.connect(self.reject)
            layout.addWidget(btn)
            return

        aw = max(1, int(aspect_w or 1000))
        ah = max(1, int(aspect_h or 100))
        aspect = aw / ah

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        tip = QLabel(
            f"拖动亮区选择要显示的部分；滚轮调整裁切框大小。"
            f"裁切比例与输出尺寸均绑定当前字幕窗口（{aw}×{ah}）。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("font-size: 13px; color: #616161;")
        root.addWidget(tip)

        self._canvas = _CropCanvas(img, aspect, self)
        root.addWidget(self._canvas, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        reset_btn = QPushButton("重置居中")
        reset_btn.setMinimumHeight(36)
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 6px 14px; "
            "background: #F5F5F5; color: #333333; border: 1px solid #BDBDBD; border-radius: 6px; }"
            "QPushButton:hover { background: #EEEEEE; }"
        )
        reset_btn.clicked.connect(self._canvas.reset_crop)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)

        cancel_btn = QPushButton("取消")
        ok_btn = QPushButton("确认裁切")
        for b in (cancel_btn, ok_btn):
            b.setMinimumHeight(36)
            b.setCursor(Qt.PointingHandCursor)
        cancel_btn.setMinimumWidth(96)
        ok_btn.setMinimumWidth(120)
        ok_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 6px 16px; "
            "background: #1565C0; color: white; border: none; border-radius: 6px; }"
            "QPushButton:hover { background: #1976D2; }"
            "QPushButton:pressed { background: #0D47A1; }"
        )
        cancel_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 6px 16px; "
            "background: #F5F5F5; color: #333333; border: 1px solid #BDBDBD; border-radius: 6px; }"
            "QPushButton:hover { background: #EEEEEE; }"
        )
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        root.addLayout(btn_row)

        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.activated.connect(self.reject)

    def _on_accept(self) -> None:
        if self._canvas is None:
            self.reject()
            return
        out = self._canvas.cropped_image()
        if out is None or out.isNull():
            self.reject()
            return
        self._result = out
        self.accept()

    def cropped_image(self) -> Optional[QImage]:
        return self._result

    @staticmethod
    def crop_file(
        parent,
        image_path: str,
        aspect_w: int = 1000,
        aspect_h: int = 100,
    ) -> Optional[QImage]:
        """打开裁切对话框；取消或失败返回 None。大图在后台解码，避免卡住设置页。"""
        import threading
        from PyQt5.QtCore import QObject, pyqtSignal, QEventLoop
        from PyQt5.QtWidgets import QProgressDialog

        class _Done(QObject):
            finished = pyqtSignal()

        holder: Dict[str, Any] = {"img": None, "err": None}
        loop = QEventLoop()
        bridge = _Done()
        bridge.finished.connect(loop.quit)

        def _load() -> None:
            try:
                from utils.safe_image import load_qimage_capped

                img = load_qimage_capped(image_path)
                holder["img"] = img if img is not None and not img.isNull() else None
            except Exception as e:
                holder["err"] = e
            finally:
                bridge.finished.emit()

        progress = QProgressDialog("正在加载图片…", None, 0, 0, parent)
        progress.setWindowTitle("请稍候")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(120)
        progress.setCancelButton(None)
        progress.show()

        threading.Thread(target=_load, daemon=True, name="CropImageLoader").start()
        loop.exec_()
        progress.close()

        if holder["err"] is not None or holder["img"] is None:
            return None
        dlg = ImageCropDialog(
            image_path,
            aspect_w=aspect_w,
            aspect_h=aspect_h,
            parent=parent,
            preloaded_image=holder["img"],
        )
        if dlg.exec_() != QDialog.Accepted:
            return None
        return dlg.cropped_image()
