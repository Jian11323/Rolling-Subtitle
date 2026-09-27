#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
滚动文本组件
使用QPainter实现高性能滚动，自动处理刷新，解决窗口静止时卡顿问题
"""

from PyQt5.QtWidgets import QOpenGLWidget, QWidget, QApplication
from PyQt5.QtCore import QTimer, Qt, QRectF, pyqtSignal, QElapsedTimer, QThread, QObject
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


class _AsyncRasterBridge(QObject):
    """
    工作线程 → 主线程投递栅格结果（QueuedConnection）。
    避免在工作线程创建 QPixmap，也比跨线程 QTimer.singleShot 更稳。
    """
    commit_image = pyqtSignal(object, str, object)  # QImage, cache_key, task_id|None
    show_cached = pyqtSignal(str, int)  # cache_key, task_id
    commit_bg = pyqtSignal(int, object, object)  # generation, key, QImage|None
    load_failed = pyqtSignal()  # 清除 loading 状态


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
        self._watermark_pending_key: Optional[Tuple] = None
        self._watermark_pending_build: Optional[Tuple] = None
        self._watermark_debounce_timer = QTimer(self)
        self._watermark_debounce_timer.setSingleShot(True)
        self._watermark_debounce_timer.setInterval(120)
        self._watermark_debounce_timer.timeout.connect(self._rebuild_watermark_deferred)
        self._screen_change_bound_handle = None
        self._last_screen_name: Optional[str] = None
        self._last_screen_hz: float = 0.0
        self._last_dpr_q: int = 100
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
        gc = config.gui_config
        self._image_cache_max = max(4, int(getattr(gc, "image_cache_max", 16) or 16))
        self._text_texture_cache: OrderedDict[Tuple[str, str, int], QPixmap] = OrderedDict()
        self._text_texture_cache_lock = threading.Lock()
        self._text_texture_cache_max = max(4, int(getattr(gc, "text_texture_cache_max", 10) or 10))
        self._pil_font_cache: Dict[int, Any] = {}
        self._pil_font_cache_lock = threading.Lock()
        self._current_load_task_id = 0
        self._cached_text_width = 0
        self._cached_image_width = 0
        self._image_after_text = False  # 为 True 时图片绘制在文字之后（如 CMT 沙滩球在消息末尾）
        self._last_scroll_time = time.time()
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._is_loading = False
        self._loading_lock = threading.Lock()
        self._is_scrolling = False
        self._scrolling_lock = threading.Lock()
        # 自定义背景缓存：(resolved_path, w, h, blur_radius) -> QPixmap；构建在后台线程完成
        self._bg_pixmap_cache: Optional[QPixmap] = None
        self._bg_pixmap_cache_key: Optional[Tuple] = None
        self._bg_load_generation = 0
        self._bg_pending_key: Optional[Tuple] = None
        self._bg_loading_key: Optional[Tuple] = None
        self._bg_debounce_timer = QTimer(self)
        self._bg_debounce_timer.setSingleShot(True)
        # 略加长防抖：跨屏 DPI/尺寸抖动时合并多次 resize，避免后台线程堆积
        self._bg_debounce_timer.setInterval(150)
        self._bg_debounce_timer.timeout.connect(self._start_pending_background_load)

        # 跨线程栅格投递（图片 / 背景）
        self._raster_bridge = _AsyncRasterBridge(self)
        self._raster_bridge.commit_image.connect(self._commit_loaded_qimage)
        self._raster_bridge.show_cached.connect(self._update_image_display_from_cache)
        self._raster_bridge.commit_bg.connect(self._commit_background_qimage)
        self._raster_bridge.load_failed.connect(lambda: self.set_loading(False))

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

        self.timer = QTimer(self)
        # 滚动流畅优先：PreciseTimer 保证帧间隔稳定；占用由性能档的 target_fps/缓存等控制
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._scroll)
        self._timer_interval = self._compute_timer_interval()
        self.timer.start(self._timer_interval)
        logger.info(
            f"定时器间隔设置为: {self._timer_interval}ms (PreciseTimer, "
            f"目标帧率: {max(1, int(config.gui_config.target_fps or 30))}fps, "
            f"VSync: {'开启' if config.gui_config.vsync_enabled else '关闭'})"
        )
        self.setStyleSheet(f"background-color: {config.gui_config.bg_color};")
        # 启动后尽快预取背景，避免首帧才开始防抖等待
        QTimer.singleShot(0, self._prefetch_background_if_needed)
        QTimer.singleShot(0, self._bind_screen_change_handler)

    @staticmethod
    def _quantize_dim(value: int, step: int = 8) -> int:
        """将宽/高量化到 step 的倍数，吸收主副屏 DPI 切换时的 ±1~数 px 抖动。"""
        v = max(1, int(value))
        s = max(1, int(step))
        return max(s, ((v + s // 2) // s) * s)

    def _device_pixel_ratio_q(self) -> int:
        """设备像素比 ×100（整数，便于作缓存键）。"""
        try:
            dpr = float(self.devicePixelRatioF()) if hasattr(self, "devicePixelRatioF") else float(self.devicePixelRatio())
            if dpr <= 0:
                dpr = 1.0
            return max(50, min(400, int(round(dpr * 100))))
        except Exception:
            return 100

    def _cache_wh(self) -> Tuple[int, int]:
        """背景/水印缓存用的量化宽高。"""
        return self._quantize_dim(self.width()), self._quantize_dim(self.height())

    def _image_cache_height(self) -> int:
        """图标缓存用高度（量化，减轻跨屏高度抖动产生多份解码）。"""
        h = self.height() if self.height() > 10 else int(getattr(self.config.gui_config, "window_height", 100) or 100)
        return self._quantize_dim(h, step=8)

    def _screen_refresh_hz(self) -> float:
        """
        读取窗口所在屏刷新率；Windows/部分驱动上 refreshRate() 可能为 0，
        依次回退到 windowHandle → 控件中心命中屏 → primaryScreen → 任意有效屏。
        """
        candidates = []
        try:
            handle = self.windowHandle()
            if handle is not None and handle.screen() is not None:
                candidates.append(handle.screen())
        except Exception:
            pass
        try:
            app = QApplication.instance()
            if app is not None:
                try:
                    center = self.mapToGlobal(self.rect().center())
                    hit = app.screenAt(center)
                    if hit is not None:
                        candidates.append(hit)
                except Exception:
                    pass
                try:
                    primary = app.primaryScreen()
                    if primary is not None:
                        candidates.append(primary)
                except Exception:
                    pass
                try:
                    for s in app.screens() or []:
                        if s is not None:
                            candidates.append(s)
                except Exception:
                    pass
        except Exception:
            pass
        seen = set()
        for screen in candidates:
            try:
                sid = id(screen)
                if sid in seen:
                    continue
                seen.add(sid)
                hz = float(screen.refreshRate() or 0.0)
                if hz >= 20.0:
                    return hz
            except Exception:
                continue
        return 0.0

    def _compute_timer_interval(self) -> int:
        """
        按配置目标帧率与当前屏刷新率取较低者，避免副屏高刷时定时器仍按主屏/过高 FPS 空转。
        下限约 60fps（16ms），与既有逻辑一致。
        """
        target_fps = max(1, int(getattr(self.config.gui_config, "target_fps", 30) or 30))
        screen_hz = self._screen_refresh_hz()
        if screen_hz >= 20.0:
            # 不超过显示器刷新；仍尊重用户目标 fps
            effective = min(target_fps, int(round(screen_hz)))
        else:
            effective = target_fps
        effective = max(1, effective)
        return max(16, int(1000 / effective))

    def _sync_timer_to_screen(self, *, force_log: bool = False) -> None:
        """根据当前屏刷新率与目标 fps 更新定时器间隔。"""
        new_interval = self._compute_timer_interval()
        old = getattr(self, "_timer_interval", None)
        self._timer_interval = new_interval
        try:
            if self.timer.isActive() and self.timer.interval() != new_interval:
                self.timer.setInterval(new_interval)
            elif not self.timer.isActive():
                pass
            if force_log or old != new_interval:
                hz = self._screen_refresh_hz()
                logger.info(
                    f"滚动定时器已按当前屏同步: interval={new_interval}ms "
                    f"(target_fps={getattr(self.config.gui_config, 'target_fps', 30)}, screen_hz≈{hz:.1f})"
                )
        except RuntimeError:
            pass

    def _bind_screen_change_handler(self) -> None:
        """监听窗口所在屏变化（分辨率/刷新率/DPI），只重建一次缓存而非每帧抖动。"""
        try:
            handle = self.windowHandle()
            if handle is None:
                # 尚未有原生窗口时稍后再试
                QTimer.singleShot(200, self._bind_screen_change_handler)
                return
            if getattr(self, "_screen_change_bound_handle", None) is handle:
                return
            old = getattr(self, "_screen_change_bound_handle", None)
            if old is not None:
                try:
                    old.screenChanged.disconnect(self._on_window_screen_changed)
                except Exception:
                    pass
            handle.screenChanged.connect(self._on_window_screen_changed)
            self._screen_change_bound_handle = handle
            self._on_window_screen_changed(handle.screen())
        except Exception as e:
            logger.debug(f"绑定 screenChanged 失败（可忽略）: {e}")

    def _on_window_screen_changed(self, screen) -> None:
        """切换主/副屏：同步刷新率定时器，作废尺寸敏感缓存（保留旧图拉伸过渡）。"""
        try:
            name = ""
            hz = 0.0
            if screen is not None:
                try:
                    name = str(screen.name() or "")
                except Exception:
                    name = ""
                try:
                    hz = float(screen.refreshRate() or 0.0)
                except Exception:
                    hz = 0.0
            if hz < 20.0:
                hz = self._screen_refresh_hz()
            dpr_q = self._device_pixel_ratio_q()
            changed = (
                name != getattr(self, "_last_screen_name", None)
                or abs(hz - getattr(self, "_last_screen_hz", 0.0)) >= 0.5
                or dpr_q != getattr(self, "_last_dpr_q", 100)
            )
            self._last_screen_name = name
            self._last_screen_hz = hz
            self._last_dpr_q = dpr_q
            self._sync_timer_to_screen(force_log=changed)
            if not changed:
                return
            logger.info(
                f"窗口已切换显示器: name={name or '?'}, refresh≈{hz:.1f}Hz, dpr={dpr_q / 100.0:.2f}"
            )
            # 作废背景加载队列，但保留旧 pixmap 拉伸，避免闪纯色与反复堆线程
            self._invalidate_background_cache(clear_pixmap=False)
            self._watermark_45_cache_key = None
            self._watermark_pending_key = None
            self._watermark_pending_build = None
            path = self._resolve_background_image_file()
            if path:
                wq, hq = self._cache_wh()
                blur = int(getattr(self.config.gui_config, "background_blur_radius", 0) or 0)
                self._schedule_background_load((path, wq, hq, blur, dpr_q))
            self.update()
        except Exception as e:
            logger.debug(f"处理 screenChanged 失败: {e}")

    def _prefetch_background_if_needed(self) -> None:
        """主线程：若配置了背景图则尽早排队异步构建。"""
        try:
            path = self._resolve_background_image_file()
            if not path:
                return
            wq, hq = self._cache_wh()
            if self.width() <= 1:
                wq = self._quantize_dim(int(getattr(self.config.gui_config, "window_width", 800) or 800))
            if self.height() <= 1:
                hq = self._quantize_dim(int(getattr(self.config.gui_config, "window_height", 100) or 100))
            blur = int(getattr(self.config.gui_config, "background_blur_radius", 0) or 0)
            self._bg_pending_key = (path, wq, hq, blur, self._device_pixel_ratio_q())
            self._start_pending_background_load()
        except Exception as e:
            logger.debug(f"预取背景图失败（可忽略）: {e}")

    def _contains_cjk(self, text: str) -> bool:
        """判断文本是否包含中日韩统一表意文字（CJK）字符。"""
        for ch in text or "":
            cp = ord(ch)
            if (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) or (0xF900 <= cp <= 0xFAFF):
                return True
        return False

    def _font_supports_text(self, font: QFont, text: str) -> bool:
        """检查字体是否包含文本中全部 CJK 码位（via inFontUcs4）。"""
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
        """为含中文的文本选择整句可用的绘制字体（必要时回退微软雅黑/宋体）。"""
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

    def _resolve_background_image_file(self) -> str:
        """解析配置中的背景图路径（内置 / AppData / 绝对路径）。"""
        from utils.builtin_backgrounds import resolve_background_image_file
        raw = str(getattr(self.config.gui_config, "background_image_path", "") or "").strip()
        return resolve_background_image_file(raw)

    def _invalidate_background_cache(self, clear_pixmap: bool = True) -> None:
        """作废进行中的背景加载；可选清空已缓存 pixmap。"""
        self._bg_load_generation += 1
        self._bg_pending_key = None
        self._bg_loading_key = None
        try:
            if self._bg_debounce_timer.isActive():
                self._bg_debounce_timer.stop()
        except RuntimeError:
            pass
        if clear_pixmap:
            self._bg_pixmap_cache = None
            self._bg_pixmap_cache_key = None

    @staticmethod
    def _build_background_qimage(w: int, h: int, path: str, blur_radius: int) -> Optional[QImage]:
        """加载、裁剪缩放并可选模糊背景图（可在工作线程调用，仅返回 QImage）。"""
        if w <= 0 or h <= 0 or not path:
            return None
        try:
            from utils.safe_image import load_qimage_capped

            src = load_qimage_capped(path)
            if src is None or src.isNull():
                return None
            # Cover 裁剪：保持比例铺满
            scaled = src.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            if scaled.width() > w or scaled.height() > h:
                x = max(0, (scaled.width() - w) // 2)
                y = max(0, (scaled.height() - h) // 2)
                scaled = scaled.copy(x, y, w, h)
            if blur_radius > 0:
                try:
                    from PIL import Image, ImageFilter
                    img = scaled.convertToFormat(QImage.Format_RGBA8888)
                    ptr = img.bits()
                    nbytes = img.byteCount() if hasattr(img, "byteCount") else img.sizeInBytes()
                    ptr.setsize(nbytes)
                    pil = Image.frombytes(
                        "RGBA", (img.width(), img.height()), bytes(ptr)
                    )
                    pil = pil.filter(ImageFilter.GaussianBlur(radius=max(1, blur_radius)))
                    data = pil.tobytes("raw", "RGBA")
                    out = QImage(data, pil.width, pil.height, QImage.Format_RGBA8888)
                    return out.copy()
                except Exception as e_blur:
                    logger.debug(f"背景模糊失败，使用原图: {e_blur}")
            return scaled.copy()
        except Exception as e:
            logger.warning(f"加载背景图失败: {e}")
            return None

    def _schedule_background_load(self, key: Tuple) -> None:
        """防抖后异步构建背景（避免拖拽改尺寸/跨屏 DPI 抖动时连续同步模糊卡顿）。"""
        if self._bg_loading_key == key:
            return
        if self._bg_pending_key == key and self._bg_debounce_timer.isActive():
            return
        self._bg_pending_key = key
        try:
            self._bg_debounce_timer.start()
        except RuntimeError:
            self._start_pending_background_load()

    def _start_pending_background_load(self) -> None:
        """主线程：启动后台线程构建当前待加载背景 key（同时仅允许一路加载）。"""
        key = self._bg_pending_key
        if not key:
            return
        if self._bg_pixmap_cache is not None and self._bg_pixmap_cache_key == key:
            self._bg_pending_key = None
            return
        if self._bg_loading_key == key:
            return
        # 已有一路加载在跑：只保留最新 pending，等当前完成后在 commit 里再排
        if self._bg_loading_key is not None:
            return
        path, w, h, blur = key[0], key[1], key[2], key[3]
        if w <= 0 or h <= 0 or not path:
            self._bg_pending_key = None
            return
        gen = self._bg_load_generation
        self._bg_loading_key = key
        self._bg_pending_key = None
        logger.debug(
            f"异步加载背景图: {path}, {w}x{h}, blur={blur}, "
            f"dpr_q={key[4] if len(key) > 4 else '?'}"
        )
        threading.Thread(
            target=self._load_background_async,
            args=(gen, key),
            daemon=True,
            name="BackgroundLoader",
        ).start()

    def _load_background_async(self, generation: int, key: Tuple) -> None:
        """工作线程：解码/缩放/模糊背景，经信号回主线程提交。"""
        try:
            path, w, h, blur = key[0], int(key[1]), int(key[2]), int(key[3])
            image = self._build_background_qimage(w, h, path, blur)
            img_copy = image.copy() if image is not None and not image.isNull() else None
            self._raster_bridge.commit_bg.emit(generation, key, img_copy)
        except Exception as e:
            logger.warning(f"异步加载背景图失败: {e}")
            self._raster_bridge.commit_bg.emit(generation, key, None)

    def _current_background_key(self) -> Optional[Tuple]:
        path = self._resolve_background_image_file()
        wq, hq = self._cache_wh()
        if not path or wq <= 0 or hq <= 0:
            return None
        blur = int(getattr(self.config.gui_config, "background_blur_radius", 0) or 0)
        return (path, wq, hq, blur, self._device_pixel_ratio_q())

    @staticmethod
    def _bg_keys_compatible(a: Optional[Tuple], b: Optional[Tuple]) -> bool:
        """量化键相同或仅差极小尺寸时视为可复用（拉伸绘制即可）。"""
        if not a or not b or len(a) < 4 or len(b) < 4:
            return False
        if a[0] != b[0] or int(a[3]) != int(b[3]):
            return False
        if len(a) > 4 and len(b) > 4 and a[4] != b[4]:
            return False
        return abs(int(a[1]) - int(b[1])) <= 8 and abs(int(a[2]) - int(b[2])) <= 8

    def _commit_background_qimage(
        self,
        generation: int,
        key: Tuple,
        image: Optional[QImage],
    ) -> None:
        """主线程：接收后台背景 QImage，写入 QPixmap 缓存并刷新。"""
        if generation != self._bg_load_generation:
            if self._bg_loading_key == key:
                self._bg_loading_key = None
            if self._bg_pending_key and self._bg_loading_key is None:
                self._start_pending_background_load()
            return
        if self._bg_loading_key == key:
            self._bg_loading_key = None

        current_key = self._current_background_key()
        if current_key != key and not self._bg_keys_compatible(current_key, key):
            if self._bg_pending_key is None and current_key:
                self._schedule_background_load(current_key)
            elif self._bg_pending_key is not None:
                self._start_pending_background_load()
            return
        if image is None or image.isNull():
            if self._bg_pending_key is not None:
                self._start_pending_background_load()
            return
        try:
            pix = QPixmap.fromImage(image)
            if pix.isNull():
                return
            self._bg_pixmap_cache = pix
            self._bg_pixmap_cache_key = current_key or key
            self.update()
            logger.debug(
                f"背景图异步就绪: {self._bg_pixmap_cache_key[0]}, "
                f"{self._bg_pixmap_cache_key[1]}x{self._bg_pixmap_cache_key[2]}"
            )
        except Exception as e:
            logger.warning(f"提交背景图到主线程失败: {e}")
        if self._bg_pending_key is not None and self._bg_loading_key is None:
            self._start_pending_background_load()

    def _get_cached_background_pixmap(self) -> Optional[QPixmap]:
        """
        取缓存背景；未命中时异步构建，不在绘制路径同步加载/模糊。
        同路径旧缓存可先拉伸绘制，避免等待期间闪回纯色。
        """
        path = self._resolve_background_image_file()
        if not path:
            if self._bg_pixmap_cache is not None or self._bg_pixmap_cache_key is not None:
                self._invalidate_background_cache(clear_pixmap=True)
            return None
        key = self._current_background_key()
        if key is None:
            return self._bg_pixmap_cache
        if self._bg_pixmap_cache is not None and (
            self._bg_pixmap_cache_key == key
            or self._bg_keys_compatible(self._bg_pixmap_cache_key, key)
        ):
            return self._bg_pixmap_cache
        self._schedule_background_load(key)
        if (
            self._bg_pixmap_cache is not None
            and self._bg_pixmap_cache_key is not None
            and self._bg_pixmap_cache_key[0] == path
            and not self._bg_pixmap_cache.isNull()
        ):
            return self._bg_pixmap_cache
        return None

    def _paint_window_background(self, painter: QPainter, base_bg: QColor) -> None:
        """绘制纯色或自定义背景（含毛玻璃遮罩与预警闪烁叠色）。"""
        rect = self.rect()
        bg_pix = self._get_cached_background_pixmap()
        if bg_pix is not None and not bg_pix.isNull():
            if bg_pix.width() == rect.width() and bg_pix.height() == rect.height():
                painter.drawPixmap(0, 0, bg_pix)
            else:
                # 异步新尺寸未就绪时，拉伸旧缓存，避免闪纯色
                painter.drawPixmap(rect, bg_pix)
            # 半透明遮罩（液态玻璃可读性）
            try:
                ov = float(getattr(self.config.gui_config, "background_overlay_opacity", 0.35) or 0.0)
            except (TypeError, ValueError):
                ov = 0.35
            ov = max(0.0, min(0.9, ov))
            if ov > 0.001:
                overlay = QColor(0, 0, 0)
                overlay.setAlphaF(ov)
                painter.fillRect(rect, overlay)
            # 预警闪烁：叠半透明色，不盖死背景图
            if getattr(self, "_alert_flash_enabled", False) and getattr(self, "_alert_flash_on", False):
                flash = QColor(self._alert_flash_color)
                if flash.isValid():
                    flash.setAlpha(110)
                    painter.fillRect(rect, flash)
        else:
            if getattr(self, "_alert_flash_enabled", False):
                bg_color = self._alert_flash_color if self._alert_flash_on else base_bg
            else:
                bg_color = base_bg
            painter.fillRect(rect, bg_color)

    def _paint_content(self, painter: QPainter):
        """统一的绘制逻辑（供 paintGL / paintEvent 调用）。使用浮点坐标与原生 drawText，避免取整卡顿与位图插值模糊/闪烁。"""
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            base_bg = QColor(self.config.gui_config.bg_color)
            lead_w = self._get_lead_badge_width()

            if lead_w > 0:
                self._paint_window_background(painter, base_bg)
                bright = QColor(self._lead_badge_flash_color)  # 左侧红条亮色
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
                self._paint_window_background(painter, base_bg)
                self._draw_background_watermark(painter, base_bg)

            if not self.current_text:
                return  # 没有文本时只绘制背景与水印

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
        斜向 45 度：预渲染整面平铺到 QPixmap 并缓存；尺寸变化时防抖重建，绘制路径不分配大图。
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
            wq, hq = self._cache_wh()

            if position == "diagonal":
                key = (
                    wq,
                    hq,
                    watermark_text,
                    watermark_color.name(),
                    font.family(),
                    font.pointSize(),
                    self._device_pixel_ratio_q(),
                )
                pix = None
                if (
                    self._watermark_45_cache_key == key
                    and self._watermark_45_pixmap is not None
                    and not self._watermark_45_pixmap.isNull()
                ):
                    pix = self._watermark_45_pixmap
                else:
                    # 不在 paint 路径同步重建整屏 pixmap（副屏 DPI 抖动会瞬间打满内存）
                    self._watermark_pending_key = key
                    self._watermark_pending_build = (
                        watermark_text,
                        QFont(font),
                        QColor(watermark_color),
                        wq,
                        hq,
                    )
                    try:
                        if not self._watermark_debounce_timer.isActive():
                            self._watermark_debounce_timer.start()
                    except RuntimeError:
                        self._rebuild_watermark_deferred()
                    if (
                        self._watermark_45_pixmap is not None
                        and not self._watermark_45_pixmap.isNull()
                    ):
                        pix = self._watermark_45_pixmap
                if pix is None or pix.isNull():
                    return
                painter.save()
                if pix.width() == w and pix.height() == h:
                    painter.drawPixmap(0, 0, pix)
                else:
                    painter.drawPixmap(self.rect(), pix)
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

    def _rebuild_watermark_deferred(self) -> None:
        """防抖后重建斜向水印（主线程，避开 paint 热路径）。"""
        try:
            key = getattr(self, "_watermark_pending_key", None)
            build = getattr(self, "_watermark_pending_build", None)
            if not key or not build:
                return
            watermark_text, font, watermark_color, wq, hq = build
            # 若等待期间又变了目标键，丢弃本次（定时器会再次触发或下帧重排）
            if key != self._watermark_pending_key:
                return
            pix = self._build_watermark_45_pixmap(
                int(wq), int(hq), watermark_text, font, watermark_color
            )
            self._watermark_45_pixmap = pix
            self._watermark_45_cache_key = key
            self._watermark_pending_build = None
            self.update()
        except Exception as e:
            logger.debug(f"延迟重建水印失败: {e}")

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
                max_tex = int(getattr(self, "_text_texture_cache_max", 12) or 12)
                while len(self._text_texture_cache) > max_tex:
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
        self._bind_screen_change_handler()
        self._sync_timer_to_screen()
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
        # 宽度为 0 时也必须完成一轮，否则永远不 emit → 黑屏卡住
        if total_width <= 0 or self.x_position + lead_w + total_width < 0:
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
                if parsed_data and parsed_data.get('is_tsunami'):
                    from utils.message_processor import MessageProcessor
                    processor = MessageProcessor()
                    color_str = processor.get_message_color('report', parsed_data)
                    return self._get_validated_color(color_str, message_type)
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
            self._sync_timer_to_screen(force_log=True)
            gc = self.config.gui_config
            self._image_cache_max = max(4, int(getattr(gc, "image_cache_max", 16) or 16))
            self._text_texture_cache_max = max(
                4, int(getattr(gc, "text_texture_cache_max", 10) or 10)
            )
            # 水印相关配置变更：作废缓存，由绘制路径防抖重建
            self._watermark_45_cache_key = None
            self._watermark_pending_key = None
            self._watermark_pending_build = None
            new_bg_color = self.config.gui_config.bg_color
            self.setStyleSheet(f"background-color: {new_bg_color};")
            # 背景变更：作废进行中加载；有新路径时保留旧图作过渡，避免闪纯色
            new_bg_path = self._resolve_background_image_file()
            if not new_bg_path:
                self._invalidate_background_cache(clear_pixmap=True)
            else:
                old_key = self._bg_pixmap_cache_key
                self._invalidate_background_cache(clear_pixmap=False)
                if old_key is not None and old_key[0] != new_bg_path:
                    self._bg_pixmap_cache = None
                    self._bg_pixmap_cache_key = None
            self.update()
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
        带重试的远程图片拉取：优先校验证书；仅在 SSL 失败时回退到不校验（兼容部分气象图源）。
        """
        if not url or not isinstance(url, str):
            return None
        from utils.safe_image import MAX_IMAGE_BYTES

        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        verify_ctx = ssl.create_default_context()
        insecure_ctx = ssl.create_default_context()
        insecure_ctx.check_hostname = False
        insecure_ctx.verify_mode = ssl.CERT_NONE

        last_exc: Optional[BaseException] = None
        for attempt in range(1, max_retries + 1):
            # 先严格校验，再对 SSL 错误回退 insecure（同一次尝试内）
            for use_insecure in (False, True):
                ctx = insecure_ctx if use_insecure else verify_ctx
                try:
                    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                        # 限制读取体积，避免超大图占满内存
                        chunks: List[bytes] = []
                        total = 0
                        while True:
                            chunk = resp.read(1024 * 256)
                            if not chunk:
                                break
                            total += len(chunk)
                            if total > MAX_IMAGE_BYTES:
                                logger.warning(
                                    f"远程图片超过大小上限已中止: {url[:60]}... ({total} bytes)"
                                )
                                return None
                            chunks.append(chunk)
                        if use_insecure:
                            logger.debug(f"远程图片 SSL 回退为不校验: {url[:60]}...")
                        return b"".join(chunks)
                except ssl.SSLError as e:
                    last_exc = e
                    if not use_insecure:
                        continue  # 同一次 attempt 再试 insecure
                    break
                except Exception as e:  # 超时、连接错误、HTTPError 等
                    last_exc = e
                    break
            logger.warning(
                f"从 URL 加载图片失败(第{attempt}次): {url[:60]}..., {type(last_exc).__name__}: {last_exc}"
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

    @staticmethod
    def _scale_qimage_to_height(image: QImage, target_height: int) -> QImage:
        """按目标高度等比缩放 QImage（可在工作线程调用）。"""
        if image.isNull() or target_height <= 0 or image.height() <= target_height:
            return image
        ratio = target_height / image.height()
        new_width = max(1, int(image.width() * ratio))
        return image.scaled(new_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _put_pixmap_in_image_cache(self, cache_key: str, pixmap: QPixmap) -> None:
        """主线程写入图片缓存并按条数淘汰最旧项。"""
        with self._image_cache_lock:
            self._image_cache[cache_key] = pixmap
            max_img = int(getattr(self, "_image_cache_max", 24) or 24)
            while len(self._image_cache) > max_img:
                oldest_key = next(iter(self._image_cache))
                del self._image_cache[oldest_key]

    def _commit_loaded_qimage(
        self,
        image: QImage,
        cache_key: str,
        task_id: Optional[int] = None,
    ) -> None:
        """主线程：QImage → QPixmap，写入缓存；若带 task_id 则刷新显示。"""
        try:
            if image is None or image.isNull():
                if task_id is not None:
                    self.set_loading(False)
                return
            pixmap = QPixmap.fromImage(image)
            if pixmap.isNull():
                if task_id is not None:
                    self.set_loading(False)
                return
            self._put_pixmap_in_image_cache(cache_key, pixmap)
            if task_id is not None:
                self._update_image_display(pixmap, task_id)
            else:
                logger.info(f"气象预警图片预加载完成: {cache_key[:80]}")
        except Exception as e:
            logger.warning(f"提交加载图片到主线程失败: {e}")
            if task_id is not None:
                self.set_loading(False)

    def _update_image_display_from_cache(self, cache_key: str, task_id: int) -> None:
        """主线程：按 cache_key 取 QPixmap 并显示（避免工作线程触碰 QPixmap）。"""
        pixmap = None
        with self._image_cache_lock:
            pixmap = self._image_cache.get(cache_key)
        if pixmap is None:
            self.set_loading(False)
            return
        self._update_image_display(pixmap, task_id)

    def preload_image_url(self, url: str) -> None:
        """
        预加载远程图片 URL 到缓存（仅写入缓存，不刷新界面）。
        收到气象预警且图片为 NMC URL 时调用，轮播到该条时即可命中缓存并立即显示图标。
        """
        if not self._is_image_url(url):
            return

        def start():
            """在主线程安全启动图片预加载后台线程。"""
            window_height = self._image_cache_height()
            cache_key = f"{url}_{window_height}"
            with self._image_cache_lock:
                if cache_key in self._image_cache:
                    return
                for offset in (-16, -8, 8, 16):
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
        """后台线程：请求 URL，用 QImage 解码/缩放，回主线程写入 QPixmap 缓存。"""
        try:
            from utils.safe_image import load_qimage_from_bytes_capped

            data = self._fetch_image_bytes_from_url(url, timeout=12, max_retries=3, retry_delay=2.0)
            if not data:
                logger.warning(f"气象预警图片预加载失败(已重试 3 次): {url}")
                return
            image = load_qimage_from_bytes_capped(data)
            if image is None or image.isNull():
                logger.warning(f"预加载图片数据解析失败: {url}")
                return
            target_height = int(window_height * 0.8)
            image = self._scale_qimage_to_height(image, target_height)
            cache_key = f"{url}_{window_height}"
            img_copy = image.copy()
            self._raster_bridge.commit_image.emit(img_copy, cache_key, None)
        except Exception as e:
            logger.warning(f"气象预警图片预加载失败: {url}, {e}")

    def _load_image_async(self, image_path: str, task_id: int, window_height: Optional[int] = None):
        """异步加载图片（支持本地路径或 http(s) URL）。工作线程仅用 QImage。"""
        try:
            logger.info(f"开始异步加载图片: {image_path}, task_id: {task_id}")

            is_url = self._is_image_url(image_path)
            if is_url:
                img_path_resolved = image_path
            else:
                img_path = Path(image_path)
                if not img_path.exists():
                    logger.error(f"图片文件不存在: {image_path}")
                    self._raster_bridge.load_failed.emit()
                    return
                img_path_resolved = str(img_path.resolve())

            # window_height 由主线程传入，避免工作线程读取 QWidget.height()
            try:
                current_height = int(window_height or 0)
            except (TypeError, ValueError):
                current_height = 0
            if current_height <= 10:
                current_height = int(self.config.gui_config.window_height or 100)
            cache_key = f"{img_path_resolved}_{current_height}"

            found_key = None
            with self._image_cache_lock:
                if cache_key in self._image_cache:
                    found_key = cache_key
                else:
                    for offset in range(-20, 21, 5):
                        test_height = current_height + offset
                        if test_height > 0:
                            test_key = f"{img_path_resolved}_{test_height}"
                            if test_key in self._image_cache:
                                found_key = test_key
                                logger.debug(f"找到附近高度的缓存: {test_key} (当前高度: {current_height})")
                                break

            if found_key:
                logger.info(f"从缓存中获取图片: {found_key}, task_id: {task_id}, current_task_id: {self._current_load_task_id}")
                self._raster_bridge.show_cached.emit(found_key, task_id)
                return

            if is_url:
                from utils.safe_image import load_qimage_from_bytes_capped

                data = self._fetch_image_bytes_from_url(image_path, timeout=12, max_retries=3, retry_delay=2.0)
                if not data:
                    logger.error(f"从 URL 加载图片失败(已重试 3 次): {image_path}")
                    self._raster_bridge.load_failed.emit()
                    return
                image = load_qimage_from_bytes_capped(data)
                if image is None or image.isNull():
                    logger.error(f"图片数据加载失败: {image_path}")
                    self._raster_bridge.load_failed.emit()
                    return
            else:
                from utils.safe_image import load_qimage_capped

                image = load_qimage_capped(image_path)
                if image is None or image.isNull():
                    logger.error(f"图片加载失败: {image_path}")
                    self._raster_bridge.load_failed.emit()
                    return

            logger.debug(f"图片加载成功: {image.width()}x{image.height()}")
            target_height = int(current_height * 0.8)
            image = self._scale_qimage_to_height(image, target_height)
            logger.debug(f"图片已缩放: {image.width()}x{image.height()}")

            cache_key = f"{img_path_resolved}_{current_height}"
            img_copy = image.copy()
            self._raster_bridge.commit_image.emit(img_copy, cache_key, task_id)

        except Exception as e:
            logger.error(f"异步加载图片失败: {e}")
            self._raster_bridge.load_failed.emit()
    
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
            # 远程 URL 直接作为 cache key；本地路径使用 resolve 后的绝对路径
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

                # 与预加载一致：高度量化，避免主副屏高度抖动产生多份缓存
                current_height = self._image_cache_height()
                cache_key = f"{img_path_resolved}_{current_height}"
                
                # 尝试多个可能的高度（因为窗口高度可能变化）
                # 检查当前高度，以及附近的量化高度
                found_pixmap = None
                found_key = None
                with self._image_cache_lock:
                    # 先检查精确匹配
                    if cache_key in self._image_cache:
                        found_pixmap = self._image_cache[cache_key]
                        found_key = cache_key
                    else:
                        for offset in (-16, -8, 8, 16):
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
            
            # 本地与远程统一异步加载（工作线程 QImage，主线程经信号转 QPixmap）
            load_height = self._image_cache_height()
            logger.info(f"启动异步图片加载线程: {image_path}, task_id: {current_task_id}")
            thread = threading.Thread(
                target=self._load_image_async,
                args=(image_path, current_task_id, load_height),
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
        """初始化 OpenGL 硬件加速滚动组件并配置 VSync/抗锯齿。"""
        fmt = QSurfaceFormat()
        swap_interval = 1 if config.gui_config.vsync_enabled else 0
        fmt.setSwapInterval(swap_interval)
        fmt.setRenderableType(QSurfaceFormat.OpenGL)
        fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
        fmt.setVersion(2, 1)
        # 2D 滚动字幕不需要深度/模板缓冲，可明显降低显存占用
        fmt.setDepthBufferSize(0)
        fmt.setStencilBufferSize(0)
        try:
            msaa = int(getattr(config.gui_config, "opengl_msaa_samples", 0) or 0)
        except (TypeError, ValueError):
            msaa = 0
        if msaa not in (0, 2, 4, 8):
            msaa = 0
        fmt.setSamples(msaa)
        fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
        fmt.setOption(QSurfaceFormat.DeprecatedFunctions, False)
        super().__init__()
        self.setFormat(fmt)
        self._init_scrolling(config)
        logger.info(
            f"滚动组件使用 QOpenGLWidget 硬件加速"
            f"（VSync: {'开启' if config.gui_config.vsync_enabled else '关闭'}, MSAA: {msaa}x）"
        ) 
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
        # OpenGL 视口会随 resizeGL 自动更新，此处无需手动设置
        pass
    
    def paintGL(self):
        """OpenGL绘制方法（QOpenGLWidget要求，替代paintEvent）"""
        painter = QPainter(self)
        self._paint_content(painter)


class ScrollingTextCPU(_ScrollingTextMixin, QWidget):
    """滚动文本组件（CPU/软件 渲染）"""
    
    def __init__(self, config):
        """初始化 CPU 软件渲染滚动组件（低配/无 OpenGL 时使用）。"""
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
