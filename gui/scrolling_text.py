#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
滚动文本组件
使用QPainter实现高性能滚动，自动处理刷新，解决窗口静止时卡顿问题
"""

from PyQt5.QtWidgets import QOpenGLWidget, QWidget, QApplication
from PyQt5.QtCore import QTimer, Qt, QRectF, pyqtSignal, QElapsedTimer, QThread
from PyQt5.QtGui import QPainter, QFont, QColor, QPixmap, QImage, QFontMetrics, QSurfaceFormat, QOpenGLContext, QFontDatabase
from collections import OrderedDict
from typing import Optional, Dict, Tuple, Any, List
from pathlib import Path
import math
import threading
import time
import urllib.request
import ssl

from utils.logger import get_logger

logger = get_logger()


# 中文名 -> 英文系统名，用于 exactMatch 时系统仅注册英文名（如 KaiTi）的情况
FONT_FAMILY_ALIASES = {
    "楷体": "KaiTi",
    "黑体": "SimHei",
    "仿宋": "FangSong",
    "微软雅黑": "Microsoft YaHei",
}


def _resolve_font_family(family_name: str, point_size: int) -> str:
    """
    解析字体族名：先尝试别名映射，再尝试前缀/子串变体；仅当请求为宋体/SimSun 且仍无法匹配时才回退到宋体。
    返回最终应使用的 family 字符串。
    """
    if not family_name or not family_name.strip():
        return "SimSun"
    family_name = family_name.strip()
    test_font = QFont(family_name, point_size)
    if test_font.exactMatch():
        return family_name
    # 尝试中文 -> 英文别名
    if family_name in FONT_FAMILY_ALIASES:
        alias = FONT_FAMILY_ALIASES[family_name]
        test_font.setFamily(alias)
        if test_font.exactMatch():
            logger.debug(f"字体解析: 请求「{family_name}」通过别名「{alias}」匹配")
            return alias
    # 尝试前缀/子串变体（如 楷体_GB2312、华文琥珀 中）
    db = QFontDatabase()
    for f in db.families():
        if f == family_name:
            continue
        if f.startswith(family_name) or family_name.startswith(f):
            test_font.setFamily(f)
            if test_font.exactMatch():
                logger.debug(f"字体解析: 请求「{family_name}」通过变体「{f}」匹配")
                return f
    # 仅当用户选的就是宋体/SimSun 时才回退到宋体
    if family_name in ("宋体", "SimSun"):
        logger.warning("字体解析: 请求宋体/SimSun 无法 exactMatch，已回退到宋体")
        return "宋体"
    # 其他情况保持请求名，交给 Qt 回退
    return family_name


class _ScrollingTextMixin:
    """滚动文本逻辑混入（与 QOpenGLWidget 或 QWidget 组合使用）"""
    scroll_completed = pyqtSignal()

    def _init_scrolling(self, config):
        """初始化滚动组件状态（由 ScrollingText / ScrollingTextCPU 的 __init__ 调用）"""
        self.config = config
        self.x_position = 0.0
        self.current_text = ""
        self.current_color = QColor('#01FF00')
        # 阶段一/二：预警正文与提示语分段异色绘制 [(文本, QColor, advance宽度)]
        self._text_segment_paint: Optional[List[Tuple[str, QColor, int]]] = None
        self.current_message_type = None
        self.current_parsed_data = None
        self.current_image_path = None
        self.current_image = None
        self.current_text_image = None
        self._watermark_45_pixmap: Optional[QPixmap] = None
        self._watermark_45_cache_key: Optional[Tuple] = None
        font_family = getattr(config.gui_config, 'font_family', None) or "SimSun"
        resolved_family = _resolve_font_family(font_family, config.gui_config.font_size)
        self.font = QFont(resolved_family, config.gui_config.font_size)
        self.font.setBold(getattr(config.gui_config, 'font_bold', False))
        self.font.setItalic(getattr(config.gui_config, 'font_italic', False))
        self.font.setStyleStrategy(QFont.PreferAntialias)
        if hasattr(QFont, 'PreferNoHinting'):
            self.font.setHintingPreference(QFont.PreferNoHinting)
        elif hasattr(QFont, 'HintingPreference') and hasattr(QFont.HintingPreference, 'PreferNoHinting'):
            self.font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        logger.info(f"使用字体: {self.font.family()}, 大小: {config.gui_config.font_size}pt, 加粗: {self.font.bold()}, 倾斜: {self.font.italic()}")
        # 实际绘制字体：默认与 self.font 一致；若当前字体不支持中文则整句回退，避免时间与正文显示成两套字形
        self._render_font = QFont(self.font)
        self._image_cache: Dict[str, QPixmap] = {}
        self._image_cache_lock = threading.Lock()
        self._text_texture_cache: OrderedDict[Tuple[str, str, int], QPixmap] = OrderedDict()
        self._text_texture_cache_lock = threading.Lock()
        self._pil_font_cache: Dict[int, Any] = {}
        self._pil_font_cache_lock = threading.Lock()
        self._current_load_task_id = 0
        self._cached_text_width = 0
        self._cached_image_width = 0
        self._image_after_text = False  # True 时图片在文字后绘制（CMT 沙滩球在消息末尾）
        self._last_scroll_time = time.time()
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._is_loading = False
        self._loading_lock = threading.Lock()
        self._is_scrolling = False
        self._scrolling_lock = threading.Lock()

        # 有感/强有感红屏背景闪烁状态（整栏背景交替）
        self._alert_flash_enabled = False
        self._alert_flash_on = False
        self._alert_flash_color = QColor('#FF0000')
        self._alert_flash_timer = QTimer(self)
        self._alert_flash_timer.setTimerType(Qt.PreciseTimer)
        self._alert_flash_timer.timeout.connect(self._on_alert_flash_timeout)

        # 左侧固定「地震预警」红底白字条闪烁（与整栏红闪互斥）
        self._lead_badge_enabled = False
        self._lead_badge_on = False
        self._lead_badge_flash_color = QColor("#FF0000")
        self._lead_badge_dim_color = QColor("#8B0000")
        self._lead_badge_timer = QTimer(self)
        self._lead_badge_timer.setTimerType(Qt.PreciseTimer)
        self._lead_badge_timer.timeout.connect(self._on_lead_badge_timeout)

        self.timer = QTimer()
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._scroll)
        target_fps = config.gui_config.target_fps
        timer_interval = max(1, int(1000 / target_fps))
        self.timer.start(timer_interval)
        logger.info(f"定时器间隔设置为: {timer_interval}ms (PreciseTimer, 目标帧率: {target_fps}fps, VSync: {'开启' if config.gui_config.vsync_enabled else '关闭'})")
        self._timer_interval = timer_interval
        self.setStyleSheet(f"background-color: {config.gui_config.bg_color};")

    def _contains_cjk(self, text: str) -> bool:
        for ch in text or "":
            cp = ord(ch)
            if (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or (0xF900 <= cp <= 0xFAFF):
                return True
        return False

    def _font_supports_text(self, font: QFont, text: str) -> bool:
        if not text:
            return True
        fm = QFontMetrics(font)
        for ch in text:
            cp = ord(ch)
            if (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or (0xF900 <= cp <= 0xFAFF):
                if not fm.inFontUcs4(cp):
                    return False
        return True

    def _resolve_render_font_for_text(self, text: str) -> QFont:
        base = QFont(self.font)
        if not self._contains_cjk(text):
            return base
        if self._font_supports_text(base, text):
            return base
        fallback_family = _resolve_font_family("微软雅黑", base.pointSize())
        fallback = QFont(base)
        fallback.setFamily(fallback_family)
        if self._font_supports_text(fallback, text):
            logger.info(f"文本含中文且当前字体不支持，已整句回退到: {fallback.family()}")
            return fallback
        fallback2 = QFont(base)
        fallback2.setFamily("SimSun")
        logger.info(f"文本含中文且字体支持不足，已整句回退到: {fallback2.family()}")
        return fallback2

    def _build_watermark_45_pixmap(self, w: int, h: int, watermark_text: str, wm_font: QFont, wm_color: QColor) -> QPixmap:
        """
        将 45° 斜向整面平铺的水印预渲染到一张 Pixmap 上，避免每帧在 QPainter 上做大量 drawText。
        """
        if w <= 0 or h <= 0 or not watermark_text:
            pix = QPixmap(1, 1)
            pix.fill(Qt.transparent)
            return pix
        pixmap = QPixmap(w, h)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            p.setFont(wm_font)
            p.setPen(wm_color)
            cx, cy = w / 2.0, h / 2.0
            p.translate(cx, cy)
            p.rotate(-45)
            diag = (w * w + h * h) ** 0.5
            fm = QFontMetrics(wm_font)
            tw = fm.horizontalAdvance(watermark_text)
            th = fm.height()
            step_x = max(tw + 80, 120)
            step_y = max(int(th * 2.2), 60)
            n = int(diag / min(step_x, step_y)) + 2
            for i in range(-n, n + 1):
                for j in range(-n, n + 1):
                    x, y = i * step_x, j * step_y
                    wr = QRectF(x - tw / 2 - 20, y - th / 2, tw + 40, th + 4)
                    p.drawText(wr, Qt.AlignCenter | Qt.TextSingleLine, watermark_text)
        finally:
            p.end()
        return pixmap

    def _clear_lead_badge_if_not_alert_hint_content(self) -> None:
        """
        左侧红条仅服务于 AlertController 的「分段提示期」正文。
        其它任意字幕（含速报/气象/海啸等）不得保留红条，避免模拟预警后轮播提前 return 未清状态。
        """
        try:
            if getattr(self, "_text_segment_paint", None):
                return
            if self.current_message_type != "warning":
                self.set_lead_earthquake_badge_flashing(False)
        except Exception:
            pass

    def _get_lead_badge_width(self) -> int:
        """左侧「地震预警」红条宽度；未启用时返回 0。"""
        if not getattr(self, "_lead_badge_enabled", False):
            return 0
        try:
            bf = QFont(self.font)
            bf.setBold(True)
            fm = QFontMetrics(bf)
            return max(fm.horizontalAdvance("地震预警") + 28, 88)
        except Exception:
            return 120

    def _paint_content(self, painter: QPainter):
        """统一的绘制逻辑（供 paintGL / paintEvent 调用）。使用浮点坐标与原生 drawText，避免取整卡顿与位图插值模糊/闪烁。"""
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            base_bg = QColor(self.config.gui_config.bg_color)
            lead_w = self._get_lead_badge_width()

            if lead_w > 0:
                painter.fillRect(self.rect(), base_bg)
                bright = QColor(self._lead_badge_flash_color)
                if not bright.isValid():
                    bright = QColor("#FF0000")
                dim = QColor(self._lead_badge_dim_color)
                if not dim.isValid():
                    dim = QColor("#7A0000")
                strip = bright if self._lead_badge_on else dim
                painter.fillRect(0, 0, lead_w, self.height(), strip)
                bf = QFont(self.font)
                bf.setBold(True)
                painter.setFont(bf)
                painter.setPen(QColor("#FFFFFF"))
                painter.setRenderHint(QPainter.TextAntialiasing)
                painter.drawText(
                    QRectF(0, 0, lead_w, self.height()),
                    Qt.AlignCenter | Qt.TextSingleLine,
                    "地震预警",
                )
                self._draw_background_watermark(painter, base_bg)
            else:
                if getattr(self, "_alert_flash_enabled", False):
                    bg_color = self._alert_flash_color if self._alert_flash_on else base_bg
                else:
                    bg_color = base_bg
                painter.fillRect(self.rect(), bg_color)
                self._draw_background_watermark(painter, bg_color)

            if not self.current_text:
                return

            center_y = self.height() / 2.0
            base_x = self.x_position + lead_w
            text_x = base_x
            image_x = base_x
            if self.current_image:
                if getattr(self, '_image_after_text', False):
                    text_x = base_x
                    image_x = base_x + self._cached_text_width + 10
                else:
                    image_x = base_x
                    text_x = base_x + self._cached_image_width

            if lead_w > 0:
                painter.save()
                cr = QRectF(
                    float(lead_w),
                    0.0,
                    max(1.0, float(self.width() - lead_w)),
                    float(self.height()),
                )
                painter.setClipRect(cr)

            painter.setFont(self._render_font)
            painter.setRenderHint(QPainter.TextAntialiasing)
            seg_paint = getattr(self, "_text_segment_paint", None)
            if seg_paint:
                x_draw = text_x
                for piece, qcol, _adv in seg_paint:
                    painter.setPen(qcol)
                    if x_draw + _adv > 0 and x_draw < self.width():
                        painter.drawText(
                            QRectF(x_draw, 0, float(_adv + 2), float(self.height())),
                            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine,
                            piece,
                        )
                    x_draw += float(_adv)
            else:
                painter.setPen(self.current_color)
                if text_x < self.width() and text_x + self._cached_text_width > 0:
                    text_rect = QRectF(text_x, 0, self._cached_text_width, self.height())
                    painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, self.current_text)
            if self.current_image:
                pm = self.current_image
                w, h = pm.width(), pm.height()
                image_y = center_y - h / 2.0
                painter.drawPixmap(QRectF(image_x, image_y, w, h), pm, QRectF(0, 0, w, h))

            if lead_w > 0:
                painter.restore()
        except Exception as e:
            logger.error(f"绘制失败: {e}")
            import traceback
            logger.exception("详细错误信息:")

    def _draw_background_watermark(self, painter: QPainter, bg_color: QColor) -> None:
        """
        绘制背景水印：支持横向与斜向 45 度，以及四角单行水印。
        横向/四角：每帧一次 drawText；
        斜向 45 度：预渲染整面平铺到 QPixmap 并缓存，帧内仅 drawPixmap 一次。
        """
        try:
            watermark_text = (getattr(self.config.gui_config, 'watermark_text', '') or '').strip()
            if not watermark_text:
                return
            position = getattr(self.config.gui_config, 'watermark_position', 'diagonal') or 'diagonal'

            base_color = QColor('#FFFFFF')
            if bg_color.isValid():
                lum = 0.299 * bg_color.red() + 0.587 * bg_color.green() + 0.114 * bg_color.blue()
                if lum > 180:
                    base_color = QColor(0, 0, 0)
                else:
                    base_color = QColor(255, 255, 255)
            watermark_color = QColor(base_color)
            watermark_color.setAlpha(80)

            wm_family = getattr(self.config.gui_config, 'watermark_font_family', '') or ''
            wm_size = int(getattr(self.config.gui_config, 'watermark_font_size', 0) or 0)
            base_size = getattr(self.config.gui_config, 'font_size', 40)
            target_pt = wm_size if wm_size > 0 else max(8, int(base_size * 0.7))
            if wm_family:
                font = QFont(wm_family, target_pt)
            else:
                font = QFont(self.font)
                font.setPointSize(target_pt)

            w = max(1, self.width())
            h = max(1, self.height())

            if position == "diagonal":
                key = (w, h, watermark_text, watermark_color.name(), font.family(), font.pointSize())
                pix = None
                if (
                    self._watermark_45_cache_key == key
                    and self._watermark_45_pixmap is not None
                    and not self._watermark_45_pixmap.isNull()
                ):
                    pix = self._watermark_45_pixmap
                else:
                    pix = self._build_watermark_45_pixmap(w, h, watermark_text, font, watermark_color)
                    self._watermark_45_pixmap = pix
                    self._watermark_45_cache_key = key
                if pix is None or pix.isNull():
                    return
                painter.save()
                painter.drawPixmap(0, 0, pix)
                painter.restore()
                return

            painter.save()
            painter.setPen(watermark_color)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            text_w = metrics.horizontalAdvance(watermark_text) if hasattr(metrics, 'horizontalAdvance') else metrics.width(watermark_text)
            text_h = metrics.height()
            margin = max(8, int(min(w, h) * 0.02))

            if position == "top_left":
                rect = QRectF(margin, margin, text_w + 4, text_h + 4)
            elif position == "top_right":
                rect = QRectF(w - text_w - margin - 4, margin, text_w + 4, text_h + 4)
            elif position == "bottom_left":
                rect = QRectF(margin, h - text_h - margin - 4, text_w + 4, text_h + 4)
            elif position == "bottom_right":
                rect = QRectF(w - text_w - margin - 4, h - text_h - margin - 4, text_w + 4, text_h + 4)
            else:
                rect = self.rect()

            painter.drawText(rect, Qt.AlignCenter, watermark_text)
            painter.restore()
        except Exception as e:
            logger.debug(f"绘制背景水印失败: {e}")

    def _render_text_to_image(self, text: str, color: QColor) -> Optional[QPixmap]:
        """
        将文本预渲染为图片（纹理缓存），供 ScrollingText / ScrollingTextCPU 共用。
        """
        if not text:
            return None
        cache_key = (text, color.name(), self.config.gui_config.font_size)
        with self._text_texture_cache_lock:
            if cache_key in self._text_texture_cache:
                self._text_texture_cache.move_to_end(cache_key)
                return self._text_texture_cache[cache_key]
        try:
            from PIL import Image, ImageDraw, ImageFont
            font_size = self.config.gui_config.font_size
            pil_font = None
            with self._pil_font_cache_lock:
                if font_size in self._pil_font_cache:
                    pil_font = self._pil_font_cache[font_size]
                else:
                    try:
                        import platform
                        if platform.system() == "Windows":
                            simsun_fonts = [
                                ("C:/Windows/Fonts/simsun.ttc", 0),
                                ("C:/Windows/Fonts/simsun.ttc", 1),
                                ("C:/Windows/Fonts/simsun.ttf", 0),
                            ]
                            for font_path, font_index in simsun_fonts:
                                if Path(font_path).exists():
                                    try:
                                        pil_font = ImageFont.truetype(font_path, font_size, index=font_index)
                                        break
                                    except (OSError, IndexError):
                                        try:
                                            pil_font = ImageFont.truetype(font_path, font_size)
                                            break
                                        except Exception:
                                            continue
                                    except Exception:
                                        continue
                        if pil_font is None:
                            pil_font = ImageFont.load_default()
                            logger.warning("PIL无法加载宋体，使用默认字体")
                    except Exception as e:
                        logger.warning(f"加载PIL字体时出错: {e}，使用默认字体")
                        pil_font = ImageFont.load_default()
                    self._pil_font_cache[font_size] = pil_font
            if hasattr(pil_font, 'getbbox'):
                bbox = pil_font.getbbox(text)
            else:
                temp_img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
                temp_draw = ImageDraw.Draw(temp_img)
                bbox = temp_draw.textbbox((0, 0), text, font=pil_font)
            pad_h = max(20, int(font_size * 0.6))
            pad_v = max(20, int(font_size * 0.5))
            text_width = bbox[2] - bbox[0] + pad_h
            text_height = bbox[3] - bbox[1] + pad_v
            img = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            rgb = (color.red(), color.green(), color.blue())
            draw.text((pad_h // 2, pad_v // 2), text, fill=rgb, font=pil_font)
            img_bytes = img.tobytes("raw", "RGBA")
            qimg = QImage(img_bytes, text_width, text_height, QImage.Format_RGBA8888)
            pixmap = QPixmap.fromImage(qimg)
            with self._text_texture_cache_lock:
                self._text_texture_cache[cache_key] = pixmap
                if len(self._text_texture_cache) > 50:
                    self._text_texture_cache.popitem(last=False)
            self._cached_text_width = text_width
            return pixmap
        except ImportError:
            logger.warning("PIL库未安装，无法使用文本预渲染优化")
            return None
        except Exception as e:
            logger.error(f"文本预渲染失败: {e}")
            return None

    def is_scrolling(self) -> bool:
        """检查是否正在滚动（供 ScrollingText / ScrollingTextCPU 共用）"""
        with self._scrolling_lock:
            return self._is_scrolling

    def _ensure_timer_stopped(self):
        """窗口不可见或无内容时停止定时器（供 ScrollingText / ScrollingTextCPU 共用）"""
        try:
            if self.timer.isActive():
                self.timer.stop()
                logger.debug("定时器已暂停（无内容或不可见）")
        except RuntimeError:
            pass

    def _ensure_timer_running(self):
        """有内容且可见时确保定时器运行（供 ScrollingText / ScrollingTextCPU 共用）"""
        try:
            if self.current_text and self.isVisible() and not self.timer.isActive():
                self.timer.start(self._timer_interval)
                logger.debug("定时器已恢复运行")
        except RuntimeError:
            pass

    def showEvent(self, event):
        """窗口显示时恢复定时器（供 ScrollingText / ScrollingTextCPU 共用）"""
        QWidget.showEvent(self, event)
        self.update()  # 确保显示时至少重绘一次（解决 CPU 渲染窗口不显示）
        if self.current_text:
            self._ensure_timer_running()

    def hideEvent(self, event):
        """窗口隐藏/最小化时暂停定时器（供 ScrollingText / ScrollingTextCPU 共用）"""
        self._ensure_timer_stopped()
        QWidget.hideEvent(self, event)

    def _scroll(self):
        """滚动动画（由 QTimer 调用，供 ScrollingText / ScrollingTextCPU 共用）"""
        if not self.isVisible():
            self._ensure_timer_stopped()
            return
        if not self.current_text:
            with self._scrolling_lock:
                self._is_scrolling = False
            self._ensure_timer_stopped()
            return
        delta_time = self._elapsed.elapsed() / 1000.0
        self._elapsed.restart()
        if delta_time > 0.1:
            delta_time = 0.1
        pixels_per_second = self.config.gui_config.text_speed * 60.0
        move_distance = -pixels_per_second * delta_time
        self.x_position += move_distance
        total_width = 0
        if getattr(self, '_image_after_text', False) and self.current_image and self.current_text:
            total_width = self._cached_text_width + 10 + self._cached_image_width
        else:
            if self.current_image:
                total_width += self._cached_image_width
            if self.current_text:
                total_width += self._cached_text_width
        lead_w = self._get_lead_badge_width()
        if total_width > 0 and self.x_position + lead_w + total_width < 0:
            with self._scrolling_lock:
                self._is_scrolling = False
            self.scroll_completed.emit()
            return
        getattr(self, '_refresh_offscreen_image', lambda: None)()
        self.update()

    def show_loading_message(self):
        """显示加载提示消息（供 ScrollingText / ScrollingTextCPU 共用）"""
        try:
            loading_text = "正在加载数据，请稍后......"
            loading_color = '#01FF00'
            self.set_loading(True)
            self.update_text(loading_text, loading_color, None, force=True)
            logger.info("显示加载提示：正在加载数据，请稍后......")
        except Exception as e:
            logger.error(f"显示加载提示失败: {e}")

    def set_loading(self, loading: bool):
        """设置加载状态（供 ScrollingText / ScrollingTextCPU 共用）"""
        with self._loading_lock:
            self._is_loading = loading

    def is_loading(self) -> bool:
        """检查是否正在加载（供 ScrollingText / ScrollingTextCPU 共用）"""
        with self._loading_lock:
            return self._is_loading

    def _get_color_for_message_type(self, message_type: Optional[str], parsed_data: Optional[Dict[str, Any]] = None) -> QColor:
        """根据消息类型获取文本颜色（供 ScrollingText / ScrollingTextCPU 共用）"""
        try:
            if message_type == 'weather':
                if parsed_data:
                    from utils.message_processor import MessageProcessor
                    processor = MessageProcessor()
                    color_str = processor.get_message_color('weather', parsed_data)
                    return self._get_validated_color(color_str, message_type)
                if self.current_color.isValid() and self.current_color.name().upper() != self.config.gui_config.bg_color.upper():
                    return self.current_color
                return self._get_validated_color('#FFF500', message_type)
            elif message_type == 'report':
                return self._get_validated_color(self.config.message_config.report_color, message_type)
            elif message_type == 'warning':
                return self._get_validated_color(self.config.message_config.warning_color, message_type)
            elif message_type == 'custom_text':
                color_str = getattr(self.config.message_config, 'custom_text_color', None) or '#01FF00'
                return self._get_validated_color(color_str, message_type)
            else:
                return self._get_validated_color('#01FF00', message_type)
        except Exception as e:
            logger.error(f"获取消息颜色失败: {e}", exc_info=True)
            if message_type == 'weather':
                if self.current_color.isValid() and self.current_color.name().upper() != self.config.gui_config.bg_color.upper():
                    return self.current_color
                return self._get_validated_color('#FFF500', message_type)
            elif message_type == 'report':
                return self._get_validated_color(self.config.message_config.report_color, message_type)
            elif message_type == 'warning':
                return self._get_validated_color(self.config.message_config.warning_color, message_type)
            elif message_type == 'custom_text':
                return self._get_validated_color(getattr(self.config.message_config, 'custom_text_color', None) or '#01FF00', message_type)
            return self._get_validated_color('#01FF00', message_type)

    def _get_validated_color(self, color_str: str, message_type: Optional[str] = None) -> QColor:
        """验证并修正颜色（供 ScrollingText / ScrollingTextCPU 共用）"""
        try:
            color = QColor(color_str)
            if not color.isValid():
                color = QColor('#01FF00')
            bg_color_str = self.config.gui_config.bg_color
            bg_color = QColor(bg_color_str)
            if color.rgb() == bg_color.rgb():
                if message_type == 'report':
                    color = QColor(self.config.message_config.report_color)
                elif message_type == 'warning':
                    color = QColor(self.config.message_config.warning_color)
                elif message_type == 'weather':
                    color = QColor('#FFF500')
                elif message_type == 'custom_text':
                    color = QColor(getattr(self.config.message_config, 'custom_text_color', None) or '#01FF00')
                else:
                    color = QColor('#01FF00')
                if color.rgb() == bg_color.rgb():
                    color = QColor('#FFFFFF') if bg_color_str.upper() in ('BLACK', '#000000', 'BLACK') else QColor('#FFFF00')
            return color
        except Exception as e:
            logger.error(f"验证颜色失败: {e}", exc_info=True)
            return QColor('#FFFFFF')

    def _on_alert_flash_timeout(self):
        """红色背景闪烁计时器回调，仅切换背景开关并请求重绘。"""
        try:
            if not self._alert_flash_enabled:
                return
            self._alert_flash_on = not self._alert_flash_on
            self.update()
        except Exception as e:
            logger.debug(f"更新红屏闪烁状态失败: {e}")

    def _on_lead_badge_timeout(self):
        """左侧「地震预警」红条明暗交替闪烁。"""
        try:
            if not self._lead_badge_enabled:
                return
            self._lead_badge_on = not self._lead_badge_on
            self.update()
            try:
                self.repaint()
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"更新地震预警条闪烁状态失败: {e}")

    def set_lead_earthquake_badge_flashing(
        self,
        enabled: bool,
        interval_ms: int = 400,
        flash_color: str = "#FF0000",
    ) -> None:
        """
        启用/关闭左侧固定「地震预警」红底白字闪烁条（与整栏 set_alert_flashing 互斥）。

        启用时主滚动内容从红条右侧开始，不遮挡红条。
        """
        try:
            self._lead_badge_enabled = bool(enabled)
            if not self._lead_badge_enabled:
                self._lead_badge_on = False
                if self._lead_badge_timer.isActive():
                    self._lead_badge_timer.stop()
                self.update()
                return

            c = QColor(flash_color or "#FF0000")
            if not c.isValid():
                c = QColor("#FF0000")
            self._lead_badge_flash_color = c
            # 暗相与亮红拉开差距，否则两态都像「整红条」看不出在闪
            dim = QColor("#120000")
            dim.setAlpha(255)
            self._lead_badge_dim_color = dim

            if self._alert_flash_enabled:
                self._alert_flash_enabled = False
                self._alert_flash_on = False
                if self._alert_flash_timer.isActive():
                    self._alert_flash_timer.stop()

            interval = max(50, min(2000, int(interval_ms or 400)))
            self._lead_badge_timer.setInterval(interval)
            self._lead_badge_on = True
            self._lead_badge_timer.stop()
            self._lead_badge_timer.start()
            self.update()
            try:
                self.repaint()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"设置地震预警条闪烁失败: {e}")

    def set_alert_flashing(self, enabled: bool, color: str = '#FF0000', interval_ms: int = 400):
        """
        启用/关闭红色背景闪烁（仅背景闪烁，文字颜色不变）。

        Args:
            enabled: 是否启用闪烁
            color: 背景闪烁使用的颜色
            interval_ms: 闪烁间隔（毫秒）
        """
        try:
            if enabled and getattr(self, "_lead_badge_enabled", False):
                self.set_lead_earthquake_badge_flashing(False)
            self._alert_flash_enabled = bool(enabled)
            if not self._alert_flash_enabled:
                self._alert_flash_on = False
                if self._alert_flash_timer.isActive():
                    self._alert_flash_timer.stop()
                self.update()
                return

            c = QColor(color)
            if not c.isValid():
                c = QColor('#FF0000')
            self._alert_flash_color = c

            interval = max(50, min(2000, int(interval_ms or 400)))
            self._alert_flash_timer.setInterval(interval)
            if not self._alert_flash_timer.isActive():
                self._alert_flash_on = True
                self._alert_flash_timer.start()
            self.update()
        except Exception as e:
            logger.error(f"设置红屏闪烁失败: {e}")

    def apply_config_changes(self):
        """应用配置变更（热修改），供 ScrollingText / ScrollingTextCPU 共用。OpenGL 仅在有 format/setFormat 时更新 VSync。"""
        try:
            logger.debug("开始应用滚动文本组件配置热修改...")
            new_text_speed = self.config.gui_config.text_speed
            logger.info(f"滚动速度已更新（配置热修改）: {new_text_speed:.1f}")
            new_font_size = self.config.gui_config.font_size
            new_font_family = getattr(self.config.gui_config, 'font_family', None) or "SimSun"
            new_font_bold = getattr(self.config.gui_config, 'font_bold', False)
            new_font_italic = getattr(self.config.gui_config, 'font_italic', False)
            font_changed = (
                self.font.pointSize() != new_font_size
                or self.font.family() != new_font_family
                or self.font.bold() != new_font_bold
                or self.font.italic() != new_font_italic
            )
            if font_changed:
                logger.debug(f"字体热更新: 请求字体「{new_font_family}」")
                resolved_family = _resolve_font_family(new_font_family, new_font_size)
                self.font.setPointSize(new_font_size)
                self.font.setFamily(resolved_family)
                self.font.setBold(new_font_bold)
                self.font.setItalic(new_font_italic)
                self.font.setStyleStrategy(QFont.PreferAntialias)
                logger.info(f"字体已更新: {self.font.family()}, {self.font.pointSize()}pt, 加粗: {self.font.bold()}, 倾斜: {self.font.italic()}")
                with self._text_texture_cache_lock:
                    self._text_texture_cache.clear()
                with self._pil_font_cache_lock:
                    self._pil_font_cache.clear()
                if self.current_text:
                    self._render_font = self._resolve_render_font_for_text(self.current_text)
                    self._cached_text_width = QFontMetrics(self._render_font).horizontalAdvance(self.current_text)
            # 仅 OpenGL 控件有 format/setFormat，ScrollingTextCPU 跳过
            if hasattr(self, 'setFormat') and callable(getattr(self, 'format', None)):
                try:
                    fmt = self.format()
                    new_vsync = 1 if self.config.gui_config.vsync_enabled else 0
                    if fmt.swapInterval() != new_vsync:
                        fmt.setSwapInterval(new_vsync)
                        self.setFormat(fmt)
                        logger.info(f"VSync已更新: {'开启' if new_vsync == 1 else '关闭'}")
                except Exception as e:
                    logger.debug(f"更新 VSync 失败（非 OpenGL 控件可忽略）: {e}")
            new_target_fps = self.config.gui_config.target_fps
            new_timer_interval = max(1, int(1000 / new_target_fps))
            self._timer_interval = new_timer_interval
            try:
                if self.timer.interval() != new_timer_interval:
                    self.timer.setInterval(new_timer_interval)
                    logger.info(f"定时器间隔已更新 -> {new_timer_interval}ms (目标帧率: {new_target_fps}fps)")
            except RuntimeError:
                pass
            new_bg_color = self.config.gui_config.bg_color
            self.setStyleSheet(f"background-color: {new_bg_color};")
            if self.current_text and self.current_message_type:
                old_color = self.current_color.name().upper()
                if self.current_message_type == 'weather':
                    new_color_obj = self.current_color
                else:
                    new_color_obj = self._get_color_for_message_type(self.current_message_type, None)
                new_color_str = new_color_obj.name().upper()
                color_updated = (old_color != new_color_str)
                if color_updated:
                    self.current_color = new_color_obj
                self.current_text_image = None
                with self._text_texture_cache_lock:
                    self._text_texture_cache.clear()
                with self._pil_font_cache_lock:
                    self._pil_font_cache.clear()
                if self.current_text:
                    self._render_font = self._resolve_render_font_for_text(self.current_text)
                    self._cached_text_width = QFontMetrics(self._render_font).horizontalAdvance(self.current_text)
                    self.update()
            logger.debug("滚动文本组件配置热修改应用完成")
        except Exception as e:
            logger.error(f"应用滚动文本组件配置热修改失败: {e}")
            import traceback
            logger.exception("详细错误信息:")
        self._last_scroll_time = time.time()
        self.update()

    def reset_position(self):
        """重置文本位置到右侧（供 ScrollingText / ScrollingTextCPU 共用）"""
        w = float(self.width() if self.width() > 1 else self.config.gui_config.window_width)
        self.x_position = w - float(self._get_lead_badge_width())

    def _is_image_url(self, image_path: str) -> bool:
        """判断是否为远程图片 URL"""
        return isinstance(image_path, str) and image_path.startswith(('http://', 'https://'))

    def _fetch_image_bytes_from_url(self, url: str, timeout: int = 12, max_retries: int = 3, retry_delay: float = 2.0) -> Optional[bytes]:
        """
        带重试的远程图片拉取函数：用于 NMC 等气象预警图片的预加载与展示加载。
        使用与现有逻辑一致的 User-Agent 与 SSL 配置，仅在网络/服务抖动时进行有限次重试。
        """
        if not url or not isinstance(url, str):
            return None
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        last_exc: Optional[BaseException] = None
        for attempt in range(1, max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
                    return resp.read()
            except Exception as e:  # 包含超时、连接错误、HTTPError 等
                last_exc = e
                logger.warning(
                    f"从 URL 加载图片失败(第{attempt}次): {url[:60]}..., {type(e).__name__}: {e}"
                )
                if attempt < max_retries:
                    try:
                        time.sleep(retry_delay)
                    except Exception:
                        pass
        if last_exc is not None:
            logger.warning(
                f"从 URL 加载图片失败(已重试 {max_retries} 次): {url[:60]}..., {type(last_exc).__name__}: {last_exc}"
            )
        return None

    def preload_image_url(self, url: str) -> None:
        """
        预加载远程图片 URL 到缓存（仅写入缓存，不刷新界面）。
        收到气象预警且图片为 NMC URL 时调用，轮播到该条时即可命中缓存并立即显示图标。
        """
        if not self._is_image_url(url):
            return

        def start():
            window_height = self.height() if self.height() > 10 else self.config.gui_config.window_height
            cache_key = f"{url}_{window_height}"
            with self._image_cache_lock:
                if cache_key in self._image_cache:
                    return
                for offset in range(-20, 21, 5):
                    h = window_height + offset
                    if h > 0 and f"{url}_{h}" in self._image_cache:
                        return
            logger.info(f"气象预警 NMC 图片预加载已启动: {url[:60]}...")
            threading.Thread(
                target=self._do_preload_url,
                args=(url, window_height),
                daemon=True,
                name="PreloadImageUrl"
            ).start()

        app = QApplication.instance()
        if app and QThread.currentThread() == app.thread():
            start()
        else:
            QTimer.singleShot(0, start)

    def _do_preload_url(self, url: str, window_height: int) -> None:
        """后台线程：请求 URL、缩放、写入 _image_cache，不刷新界面。"""
        try:
            data = self._fetch_image_bytes_from_url(url, timeout=12, max_retries=3, retry_delay=2.0)
            if not data:
                logger.warning(f"气象预警图片预加载失败(已重试 3 次): {url}")
                return
            pixmap = QPixmap()
            if not pixmap.loadFromData(data):
                logger.warning(f"预加载图片数据解析失败: {url}")
                return
            target_height = int(window_height * 0.8)
            if pixmap.height() > target_height:
                ratio = target_height / pixmap.height()
                new_width = int(pixmap.width() * ratio)
                pixmap = pixmap.scaled(new_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            cache_key = f"{url}_{window_height}"
            with self._image_cache_lock:
                self._image_cache[cache_key] = pixmap
                if len(self._image_cache) > 200:
                    oldest_key = next(iter(self._image_cache))
                    del self._image_cache[oldest_key]
            logger.info(f"气象预警图片预加载完成: {url}")
        except Exception as e:
            logger.warning(f"气象预警图片预加载失败: {url}, {e}")

    def _load_image_async(self, image_path: str, task_id: int):
        """异步加载图片（支持本地路径或 http(s) URL）"""
        try:
            logger.info(f"开始异步加载图片: {image_path}, task_id: {task_id}")

            is_url = self._is_image_url(image_path)
            if is_url:
                img_path_resolved = image_path
            else:
                img_path = Path(image_path)
                if not img_path.exists():
                    logger.error(f"图片文件不存在: {image_path}")
                    self.set_loading(False)
                    return
                img_path_resolved = str(img_path.resolve())

            # 与预加载一致：高度不足时用 config，确保能命中预加载写入的 key
            current_height = self.height() if self.height() > 10 else self.config.gui_config.window_height
            cache_key = f"{img_path_resolved}_{current_height}"

            # 检查缓存
            found_pixmap = None
            found_key = None
            with self._image_cache_lock:
                if cache_key in self._image_cache:
                    found_pixmap = self._image_cache[cache_key]
                    found_key = cache_key
                else:
                    for offset in range(-20, 21, 5):
                        test_height = current_height + offset
                        if test_height > 0:
                            test_key = f"{img_path_resolved}_{test_height}"
                            if test_key in self._image_cache:
                                found_pixmap = self._image_cache[test_key]
                                found_key = test_key
                                logger.debug(f"找到附近高度的缓存: {test_key} (当前高度: {current_height})")
                                break

            if found_pixmap:
                logger.info(f"从缓存中获取图片: {found_key}, task_id: {task_id}, current_task_id: {self._current_load_task_id}")
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, lambda: self._update_image_display(found_pixmap, task_id))
                return

            # 加载图片：URL 用 urllib + loadFromData，本地用 QPixmap(path)
            if is_url:
                data = self._fetch_image_bytes_from_url(image_path, timeout=12, max_retries=3, retry_delay=2.0)
                if not data:
                    logger.error(f"从 URL 加载图片失败(已重试 3 次): {image_path}")
                    self.set_loading(False)
                    return
                pixmap = QPixmap()
                if not pixmap.loadFromData(data):
                    logger.error(f"图片数据加载失败: {image_path}")
                    self.set_loading(False)
                    return
            else:
                pixmap = QPixmap(image_path)
                if pixmap.isNull():
                    logger.error(f"图片加载失败: {image_path}")
                    self.set_loading(False)
                    return

            logger.debug(f"图片加载成功: {pixmap.width()}x{pixmap.height()}")

            target_height = int(self.height() * 0.8)
            if pixmap.height() > target_height:
                ratio = target_height / pixmap.height()
                new_width = int(pixmap.width() * ratio)
                pixmap = pixmap.scaled(new_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                logger.debug(f"图片已缩放: {pixmap.width()}x{pixmap.height()}")

            cache_key = f"{img_path_resolved}_{self.height()}"
            with self._image_cache_lock:
                self._image_cache[cache_key] = pixmap
                logger.debug(f"图片已缓存: {cache_key}")
                if len(self._image_cache) > 200:
                    oldest_key = next(iter(self._image_cache))
                    del self._image_cache[oldest_key]

            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._update_image_display(pixmap, task_id))

        except Exception as e:
            logger.error(f"异步加载图片失败: {e}")
            self.set_loading(False)
    
    def _update_image_display(self, pixmap: QPixmap, task_id: int):
        """更新图片显示（在主线程中执行）"""
        logger.debug(f"尝试更新图片显示: task_id={task_id}, current_task_id={self._current_load_task_id}")
        if task_id != self._current_load_task_id:
            logger.warning(f"任务已过期，忽略图片显示更新: task_id={task_id}, current_task_id={self._current_load_task_id}")
            self.set_loading(False)
            return
        
        try:
            self.current_image = pixmap
            self._cached_image_width = pixmap.width() + 10
            self.set_loading(False)
            self.update()  # 触发重绘
            logger.info(f"✓ 气象预警图片已显示，宽度: {pixmap.width()}px, 高度: {pixmap.height()}px")
        except Exception as e:
            logger.error(f"更新图片显示失败: {e}")
            self.set_loading(False)
    
    def update_text(self, text: str, color: str, image_path: Optional[str] = None, force: bool = False, message_type: Optional[str] = None, parsed_data: Optional[Dict[str, Any]] = None, fallback_image_path: Optional[str] = None, image_after_text: bool = False, text_color_segments: Optional[List[Tuple[str, str]]] = None):
        """
        更新文本和颜色，可选显示图片（异步加载）

        Args:
            text: 文本内容
            color: 文本颜色
            image_path: 图片路径（可选）
            force: 是否强制更新（即使正在滚动），用于预警消息
            message_type: 消息类型（可选），用于配置热修改时重新获取颜色
            parsed_data: 解析后的数据字典（可选），用于气象预警颜色计算和热修改
            fallback_image_path: 保留参数以兼容调用方；气象预警已改为仅在线图标，不再使用本地回退
            image_after_text: True 时图片在文字后绘制（如 CMT 沙滩球在消息末尾）
            text_color_segments: 非空时按 (片段, #RRGGBB) 分段着色；``text`` 须与各片段拼接一致（用于告警阶段一/二）
        """
        # 如果正在滚动且不是强制更新，则忽略
        with self._scrolling_lock:
            if self._is_scrolling and not force:
                logger.debug(f"当前正在滚动，忽略新消息: {text} (force={force})")
                return False
        
        self.set_loading(True)

        self._text_segment_paint = None
        force_sl = getattr(self.config.message_config, 'force_single_line', True)

        if text_color_segments:
            norm: List[Tuple[str, str]] = []
            for p, c in text_color_segments:
                s = (p or "")
                if force_sl:
                    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
                norm.append((s, c or "#FFFFFF"))
            text = "".join(p for p, _ in norm).strip()
            self.current_text = text
            self.current_message_type = None
            self.current_color = self._get_validated_color("#FFFFFF", None)
            self._render_font = self._resolve_render_font_for_text(text)
            metrics = QFontMetrics(self._render_font)
            self._text_segment_paint = []
            total_adv = 0
            for piece, col in norm:
                if not piece:
                    continue
                qc = self._get_validated_color(col, None)
                adv = metrics.horizontalAdvance(piece)
                self._text_segment_paint.append((piece, qc, adv))
                total_adv += adv
            self._cached_text_width = total_adv
            logger.info(
                f"update_text: 分段着色 {len(self._text_segment_paint)} 段, 总宽 {self._cached_text_width}"
            )
        else:
            # 强制单行显示：仅当配置开启时将换行符替换为空格，否则保留原文
            text = (text or "").strip()
            if force_sl:
                text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
            self.current_text = text
            # 如果提供了message_type，优先从配置中获取颜色（确保使用最新配置）
            # 否则使用传入的color参数
            if message_type and message_type in ('report', 'warning', 'custom_text'):
                # 从配置中获取颜色（确保使用最新配置）
                config_color = self._get_color_for_message_type(message_type, parsed_data)
                self.current_color = config_color
                logger.info(f"update_text: 使用配置中的颜色 - 消息类型: {message_type}, 颜色: {config_color.name().upper()}")
            else:
                # 验证并设置颜色（确保颜色有效且不与背景颜色相同）
                self.current_color = self._get_validated_color(color, message_type)
            self.current_message_type = message_type  # 存储消息类型
        self.current_parsed_data = parsed_data  # 存储解析数据（用于热修改时重新计算气象预警颜色）
        self.current_image_path = image_path
        self._image_after_text = image_after_text

        # 调试日志
        logger.info(f"更新文本: {text}, 颜色: {color}, 图片路径: {image_path if image_path else '无'}, 窗口尺寸: {self.width()}x{self.height()}, 初始X位置: {self.width() if self.width() > 1 else self.config.gui_config.window_width}")
        
        # 更新位置 - 从窗口右侧开始（左侧「地震预警」条占用 lead_w 时，内容仍从视口右缘入场）
        initial_x = float(self.width() if self.width() > 1 else self.config.gui_config.window_width)
        lead_w = self._get_lead_badge_width()
        self.x_position = initial_x - float(lead_w)
        self._last_scroll_time = time.time()
        logger.info(f"文本初始位置设置为: {self.x_position}")
        
        # 清除旧图片
        self.current_image = None
        self.current_text_image = None
        self._cached_image_width = 0
        
        # 设置滚动状态
        with self._scrolling_lock:
            self._is_scrolling = True
        
        # 生成新的任务ID
        self._current_load_task_id += 1
        current_task_id = self._current_load_task_id
        
        # 统一使用 QFontMetrics 计算文本宽度；分段着色时在分支内已算好宽度
        if not self._text_segment_paint:
            self._render_font = self._resolve_render_font_for_text(text)
            metrics = QFontMetrics(self._render_font)
            self._cached_text_width = metrics.horizontalAdvance(text)
            logger.debug(f"文本宽度（QFontMetrics）: {self._cached_text_width}")

        self._clear_lead_badge_if_not_alert_hint_content()
        
        # 如果没有图片，取消加载状态
        if not image_path:
            self.set_loading(False)
        else:
            # 先检查缓存，如果图片在缓存中，立即显示
            # URL 直接用作 cache key；本地路径使用 resolve 后的绝对路径
            try:
                if self._is_image_url(image_path):
                    img_path_resolved = image_path
                else:
                    img_path = Path(image_path)
                    try:
                        img_path_resolved = str(img_path.resolve())
                    except (OSError, PermissionError) as e:
                        logger.debug(f"解析图片路径时出错（非阻塞）: {e}")
                        img_path_resolved = str(image_path)

                # 与预加载一致：高度不足时用 config，确保能命中预加载写入的 key
                current_height = self.height() if self.height() > 10 else self.config.gui_config.window_height
                cache_key = f"{img_path_resolved}_{current_height}"
                
                # 尝试多个可能的高度（因为窗口高度可能变化）
                # 检查当前高度，以及附近的高度（±20px范围内）
                found_pixmap = None
                found_key = None
                with self._image_cache_lock:
                    # 先检查精确匹配
                    if cache_key in self._image_cache:
                        found_pixmap = self._image_cache[cache_key]
                        found_key = cache_key
                    else:
                        # 尝试查找附近高度的缓存（±20px范围内）
                        for offset in range(-20, 21, 5):  # 每5px检查一次
                            test_height = current_height + offset
                            if test_height > 0:
                                test_key = f"{img_path_resolved}_{test_height}"
                                if test_key in self._image_cache:
                                    found_pixmap = self._image_cache[test_key]
                                    found_key = test_key
                                    logger.debug(f"找到附近高度的缓存: {test_key} (当前高度: {current_height})")
                                    break
                
                if found_pixmap:
                    logger.info(f"图片已在缓存中，立即显示: {found_key}")
                    self.current_image = found_pixmap
                    self._cached_image_width = found_pixmap.width() + 10
                    self.set_loading(False)
                    self._ensure_timer_running()
                    self._clear_lead_badge_if_not_alert_hint_content()
                    self.update()  # 触发重绘
                    logger.info(f"✓ 气象预警图片已立即显示，宽度: {found_pixmap.width()}px, 高度: {found_pixmap.height()}px")
                    return True
                else:
                    logger.info(f"图片不在缓存中，开始异步加载: {image_path}")
            except Exception as e:
                logger.warning(f"检查图片缓存时出错: {e}")
            
            # 本地图片直接在主线程加载（稳定性优先，避免子线程 QTimer 回主线程失效导致“只打印开始加载不显示”）
            if not self._is_image_url(image_path):
                try:
                    pixmap = QPixmap(image_path)
                    if pixmap.isNull():
                        logger.error(f"本地图片加载失败: {image_path}")
                        self.set_loading(False)
                        self._clear_lead_badge_if_not_alert_hint_content()
                        return True
                    target_height = int((self.height() if self.height() > 10 else self.config.gui_config.window_height) * 0.8)
                    if pixmap.height() > target_height:
                        ratio = target_height / pixmap.height()
                        new_width = int(pixmap.width() * ratio)
                        pixmap = pixmap.scaled(new_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    cache_key_local = f"{str(Path(image_path).resolve())}_{self.height() if self.height() > 10 else self.config.gui_config.window_height}"
                    with self._image_cache_lock:
                        self._image_cache[cache_key_local] = pixmap
                        if len(self._image_cache) > 200:
                            oldest_key = next(iter(self._image_cache))
                            del self._image_cache[oldest_key]
                    self.current_image = pixmap
                    self._cached_image_width = pixmap.width() + 10
                    self.set_loading(False)
                    self._clear_lead_badge_if_not_alert_hint_content()
                    self.update()
                    logger.info(f"✓ 本地图片已显示，宽度: {pixmap.width()}px, 高度: {pixmap.height()}px")
                    return True
                except Exception as e:
                    logger.error(f"主线程加载本地图片失败: {e}")
                    self.set_loading(False)
                    self._clear_lead_badge_if_not_alert_hint_content()
                    return True

            # URL 图片走异步加载
            logger.info(f"启动异步图片加载线程: {image_path}, task_id: {current_task_id}")
            thread = threading.Thread(
                target=self._load_image_async,
                args=(image_path, current_task_id),
                daemon=True,
                name="ImageLoader"
            )
            thread.start()
        
        self._ensure_timer_running()
        self.update()  # 触发重绘
        return True


class ScrollingText(QOpenGLWidget, _ScrollingTextMixin):
    """滚动文本组件（GPU/OpenGL 渲染）"""
    
    def __init__(self, config):
        fmt = QSurfaceFormat()
        swap_interval = 1 if config.gui_config.vsync_enabled else 0
        fmt.setSwapInterval(swap_interval)
        fmt.setRenderableType(QSurfaceFormat.OpenGL)
        fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
        fmt.setVersion(2, 1)
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)
        fmt.setSamples(4)  # 多重采样，改善 OpenGL 下文字抗锯齿
        fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
        fmt.setOption(QSurfaceFormat.DeprecatedFunctions, False)
        super().__init__()
        self.setFormat(fmt)
        self._init_scrolling(config)
        logger.info(f"滚动组件使用 QOpenGLWidget 硬件加速（VSync: {'开启' if config.gui_config.vsync_enabled else '关闭'}）")
    
    def initializeGL(self):
        """OpenGL初始化（QOpenGLWidget要求），并校验垂直同步与硬件加速是否生效"""
        try:
            context = QOpenGLContext.currentContext()
            if context:
                surface = context.surface()
                if surface:
                    fmt = surface.format()
                    vsync_status = "开启" if fmt.swapInterval() > 0 else "关闭"
                    logger.info(f"OpenGL 上下文已就绪 | 垂直同步: {vsync_status} | 渲染类型: OpenGL（硬件加速）")
                else:
                    logger.warning("无法获取 OpenGL 表面，渲染可能降级")
            else:
                logger.warning("无法获取 OpenGL 上下文，将使用软件渲染")
        except Exception as e:
            logger.error(f"OpenGL 初始化失败: {e}")
            import traceback
            logger.exception("详细错误信息:")
    
    def resizeGL(self, width: int, height: int):
        """OpenGL窗口大小改变时调用（QOpenGLWidget要求）"""
        # OpenGL视口会自动更新，无需手动设置
        pass
    
    def paintGL(self):
        """OpenGL绘制方法（QOpenGLWidget要求，替代paintEvent）"""
        painter = QPainter(self)
        self._paint_content(painter)


class ScrollingTextCPU(_ScrollingTextMixin, QWidget):
    """滚动文本组件（CPU/软件 渲染）"""
    
    def __init__(self, config):
        super().__init__()
        # 由本控件完全负责绘制，避免系统/样式清屏导致窗口不显示
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self._init_scrolling(config)
        logger.info("滚动组件使用 QWidget 软件渲染（CPU）")

    def paintEvent(self, event):
        """软件绘制（QWidget）"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self._paint_content(painter)
