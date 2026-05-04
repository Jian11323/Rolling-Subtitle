#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
告警序列状态机控制器。

状态：``IDLE -> STAGE1 -> STAGE2 -> STAGE3 -> IDLE``。

并发规则：
- 同 ``event_id`` 重复 trigger -> 忽略（防止 Fan Studio /all 聚合源把同事件再投一次）
- 不同 ``event_id``：仅当 ``new_level > current_level`` 才抢占；否则忽略，避免连发预警相互打断。
- 任意阶段收到 ``cancel(event_id)`` 取消报 -> 立即停止序列、关闭左侧闪烁、不再覆盖文本。
- ``dispose()`` 主动释放，关闭定时器与左侧闪烁（主窗口关闭时调用）。

对外信号：
- ``sequence_started(event_id, level)``
- ``sequence_finished(event_id)``
- 其它（如 stage 变化）目前不需要，主窗口只关心是否进行中（``alert_sequence_active()``）。
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, QTimer, Qt, QThread, QCoreApplication, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QApplication

from utils.logger import get_logger

logger = get_logger()


class AlertState(IntEnum):
    IDLE = 0
    STAGE1 = 1
    STAGE2 = 2
    STAGE3 = 3


# 等级整数权重，用于跨事件抢占判断；与 AlertConfig 中两个阈值无关，仅做大小比较。
_LEVEL_WEIGHT = {
    "none": 0,
    "alert": 1,
    "flash": 2,
}

# 阶段一、二白字提示（与实时预警条文间隔拼接）
_HINT_ALERT = "现正发生有感地震。请注意安全"
_HINT_FLASH = (
    "现正发生强有感地震，请保持冷静，注意保护头部并远离掉落物。"
)

# 日本气象厅 / 台湾中央气象署类预警：用报文「震度」与 4 比较；含 Fan Studio 与 Wolfx 子源。
_JP_TW_HINT_SOURCE_TYPES = frozenset(
    {"jma", "cwa-eew", "wolfx_jma_eew", "wolfx_cwa_eew"}
)

# 主窗口在无站点估算时注入的合成 provider，其整数烈度不应用于日台震度文案判断。
_SYNTHETIC_INTENSITY_PROVIDERS = frozenset(
    {"no_site_fallback", "expiry_test_synthetic"}
)


def _normalize_shindo_token(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    t = t.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    for prefix in ("震度", "予想震度", "预估震度", "最大震度", "予報震度", "予測震度"):
        if t.startswith(prefix):
            t = t[len(prefix) :].strip()
    return t.strip()


def _shindo_text_to_score(value: Any) -> Optional[float]:
    """将 JMA 式震度（含 5弱/5強 等）转为可比较标量；>4 视为应显示强有感提示。"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            x = float(value)
        except (TypeError, ValueError):
            return None
        return x if x > 0 else None
    t = _normalize_shindo_token(str(value))
    if not t:
        return None
    # 常见 API 写法
    precise = {
        "1": 1.0,
        "2": 2.0,
        "3": 3.0,
        "4": 4.0,
        "5-": 4.5,
        "5弱": 4.5,
        "5−": 4.5,
        "5+": 5.5,
        "5強": 5.5,
        "6-": 6.5,
        "6弱": 6.5,
        "6−": 6.5,
        "6+": 7.5,
        "6強": 7.5,
        "7": 8.5,
    }
    if t in precise:
        return precise[t]
    try:
        return float(t)
    except (TypeError, ValueError):
        return None


def _max_warn_area_shindo_score(parsed_data: Dict[str, Any]) -> Optional[float]:
    rows = parsed_data.get("wolfx_warn_areas")
    if not isinstance(rows, list):
        return None
    best: Optional[float] = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        for k in ("shindo1", "shindo2"):
            sc = _shindo_text_to_score(row.get(k))
            if sc is not None and (best is None or sc > best):
                best = sc
    return best


def _pick_epi_intensity_candidate(parsed_data: Dict[str, Any]) -> Any:
    """从解析结果或 raw_data 中取预报震度/震度栏位（日台）。"""
    for key in ("intensity", "max_intensity", "epiIntensity", "epi_intensity", "maxIntensity", "MaxIntensity"):
        v = parsed_data.get(key)
        if v is not None and str(v).strip():
            return v
    raw = parsed_data.get("raw_data")
    if isinstance(raw, dict):
        for key in ("epiIntensity", "maxIntensity", "MaxIntensity", "epi_intensity", "Intensity", "intensity"):
            v = raw.get(key)
            if v is not None and str(v).strip():
                return v
    return None


def _reported_jma_cwa_shindo_score(parsed_data: Dict[str, Any]) -> Optional[float]:
    sc = _shindo_text_to_score(_pick_epi_intensity_candidate(parsed_data))
    if sc is not None:
        return sc
    return _max_warn_area_shindo_score(parsed_data)


def _hint_text_for_warning(
    parsed_data: Dict[str, Any],
    site_intensity_level: int,
    site_intensity_trusted: bool,
) -> str:
    """
    阶段一/二尾部白字提示。
    - 日台类源：优先报文「震度」；震度 >4 用强有感，否则有感。无震度且站点烈度不可信（合成兜底）时有感。
    - 其它源：站点估算烈度 >7 强有感，否则有感。
    """
    st = (parsed_data.get("source_type") or "").strip().lower()
    if st in _JP_TW_HINT_SOURCE_TYPES:
        score = _reported_jma_cwa_shindo_score(parsed_data)
        if score is not None:
            return _HINT_FLASH if score > 4.0 else _HINT_ALERT
        if not site_intensity_trusted:
            return _HINT_ALERT
        try:
            i = int(site_intensity_level)
        except (TypeError, ValueError):
            i = 0
        return _HINT_FLASH if i > 7 else _HINT_ALERT
    try:
        i = int(site_intensity_level)
    except (TypeError, ValueError):
        i = 0
    return _HINT_FLASH if i > 7 else _HINT_ALERT


# 正文末尾若尚无句读，补「。」再接「｜ 提示 ｜」，与各数据源预警串格式一致。
_SENTENCE_END_CHARS = frozenset("。！？.!?…」）)'\"】］")


def _ensure_sentence_ending(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    if s[-1] not in _SENTENCE_END_CHARS:
        return s + "。"
    return s


def _suffix_hint_after_live(live: str, hint: str) -> str:
    """预警全文 + 「｜ 提示语 ｜」，不在正文中间插入提示（避免拆开日期/震级）。"""
    live = (live or "").replace("\n", " ").replace("\r", "").strip()
    hint = (hint or "").strip()
    if not hint:
        return live or ""
    if not live:
        return f"｜ {hint} ｜"
    body = _ensure_sentence_ending(live)
    return f"{body}｜ {hint} ｜"


def _suffix_hint_segments(
    live: str,
    hint: str,
    live_color: str,
    hint_color: str,
) -> List[Tuple[str, str]]:
    """与 ``_suffix_hint_after_live`` 一致，供分段着色（正文预警色 + 提示白字）。"""
    live = (live or "").replace("\n", " ").replace("\r", "").strip()
    hint = (hint or "").strip()
    if not hint:
        return [(live, live_color)] if live else []
    if not live:
        return [(f"｜ {hint} ｜", hint_color)]
    body = _ensure_sentence_ending(live)
    return [(body, live_color), (f"｜ {hint} ｜", hint_color)]


def build_warning_hint_segments(
    config: Any,
    parsed_data: Dict[str, Any],
    intensity_result: Optional[Any],
    live_text: str,
) -> Optional[List[Tuple[str, str]]]:
    """
    与告警阶段一/二相同的「正文 + 白字安全提示」分段。

    用于缓冲区轮播、切屏等不经过 ``AlertController.trigger`` 的路径，避免只有
    首个成功触发序列的数据源才出现白字提示。
    """
    ac = getattr(config, "alert_config", None)
    if ac is None or not getattr(ac, "enabled", False):
        return None
    live = (live_text or "").replace("\n", " ").replace("\r", "").strip()
    if not live:
        return None
    site_level = 0
    trusted = True
    if intensity_result is not None:
        try:
            site_level = int(getattr(intensity_result, "intensity_level", 0) or 0)
        except (TypeError, ValueError):
            site_level = 0
        pn = str(getattr(intensity_result, "provider_name", "") or "")
        trusted = pn not in _SYNTHETIC_INTENSITY_PROVIDERS
    hint = _hint_text_for_warning(parsed_data or {}, site_level, trusted)
    hint = (hint or "").strip()
    if not hint:
        return None
    warn_col = str(
        getattr(getattr(config, "message_config", None), "warning_color", None)
        or "#FF0000"
    )
    segs = _suffix_hint_segments(live, hint, live_color=warn_col, hint_color="#FFFFFF")
    return segs if segs else None


class AlertController(QObject):
    """
    告警序列控制器：编排 stage1 -> stage2 -> stage3 三阶段。

    有感 / 强有感告警序列均驱动字幕条左侧「地震预警」标识闪烁（见 ``set_lead_earthquake_badge_flashing``），
    不再使用主窗口四边叠加层。
    """

    sequence_started = pyqtSignal(str, str)
    sequence_finished = pyqtSignal(str)

    # 从数据源线程投递到主线程的取消请求（非阻塞排队）
    _cancel_requested = pyqtSignal(object)
    # 无参信号 + BlockingQueued：比 QMetaObject.invokeMethod 更可靠（PyQt5 下 invoke 常失败）
    _blocking_trigger_run = pyqtSignal()

    def __init__(
        self,
        scrolling_text: Any,
        config: Any,
        parent: Optional[QObject] = None,
        edge_flash: Optional[Any] = None,
    ):
        super().__init__(parent)
        self._scrolling_text = scrolling_text
        self._config = config
        # 保留 edge_flash 形参以兼容旧调用；主窗口四边闪烁已移除，始终不使用
        _ = edge_flash

        self._state: AlertState = AlertState.IDLE
        self._current_event_id: str = ""
        self._current_level: str = "none"
        self._current_intensity: int = 0
        self._formatted_text: str = ""
        self._formatted_color: str = "#FF0000"
        # 站点烈度是否来自真实估算（合成兜底时日台提示只看震度栏位，不看整数烈度）
        self._site_intensity_trusted_for_hint: bool = True

        self._stage1_timer = QTimer(self)
        self._stage1_timer.setSingleShot(True)
        self._stage1_timer.timeout.connect(self._enter_stage2)

        self._stage2_timer = QTimer(self)
        self._stage2_timer.setSingleShot(True)
        self._stage2_timer.timeout.connect(self._enter_stage3)

        self._pending_stop_flash_on_scroll: bool = False
        self._post_stage3_flash_event_id: str = ""

        # 跨线程 trigger：BlockingQueued 保证在消息入队/切屏前完成，避免 QTimer 在非主线程启动
        self._pending_cross_thread_trigger: Optional[Tuple[Any, Any, str, str]] = None
        self._cross_thread_trigger_result: bool = False

        self._cancel_requested.connect(self._cancel_impl, Qt.QueuedConnection)
        self._blocking_trigger_run.connect(
            self._run_pending_trigger, Qt.BlockingQueuedConnection
        )

    def alert_sequence_active(self) -> bool:
        """告警状态机是否在运行（阶段一至三任一）。勿用 ``is_active`` 名以免与 Qt 动态属性冲突。"""
        return self._state != AlertState.IDLE

    def _main_app_thread(self) -> Optional[QThread]:
        app = QApplication.instance() or QCoreApplication.instance()
        if app is None:
            return None
        return app.thread()

    def trigger(
        self,
        parsed_data: Dict[str, Any],
        intensity_result: Any,
        formatted_text: str,
        formatted_color: str = "#FF0000",
    ) -> bool:
        """
        基于解析结果与 ``AlertConfig`` 决定是否触发；返回 True 表示已启动序列。

        若在非 GUI 线程调用，会通过 BlockingQueuedConnection 切到主线程执行
        （否则 ``QTimer.start`` 会报错且左侧条不会闪烁）。

        调用方应在 trigger 返回 False 时按正常流程展示 ``formatted_text`` 与警告色。
        """
        main_th = self._main_app_thread()
        if main_th is not None and QThread.currentThread() != main_th:
            self._pending_cross_thread_trigger = (
                parsed_data,
                intensity_result,
                formatted_text or "",
                formatted_color or "#FF0000",
            )
            self._cross_thread_trigger_result = False
            try:
                self._blocking_trigger_run.emit()
            except Exception as e:
                logger.warning(f"AlertController.trigger: 主线程排队执行失败: {e}")
                return False
            return bool(self._cross_thread_trigger_result)

        return self._trigger_impl(
            parsed_data, intensity_result, formatted_text, formatted_color
        )

    @pyqtSlot()
    def _run_pending_trigger(self) -> None:
        """在主线程执行跨线程排队的 ``trigger`` 逻辑。"""
        t = self._pending_cross_thread_trigger
        self._pending_cross_thread_trigger = None
        if t is None:
            self._cross_thread_trigger_result = False
            return
        pd, ir, ft, fc = t
        self._cross_thread_trigger_result = self._trigger_impl(pd, ir, ft, fc)

    def _trigger_impl(
        self,
        parsed_data: Dict[str, Any],
        intensity_result: Any,
        formatted_text: str,
        formatted_color: str = "#FF0000",
    ) -> bool:
        try:
            ac = getattr(self._config, "alert_config", None)
            if ac is None or not getattr(ac, "enabled", False):
                return False

            level = self._evaluate_level(parsed_data, intensity_result, ac)
            if level == "none":
                return False

            event_id = (parsed_data.get("event_id") or "").strip()

            # 新序列开始前结束「等滚完再关闪」的残留，避免与下一条叠闪
            if self._pending_stop_flash_on_scroll:
                self._stop_flash()

            if event_id and event_id == self._current_event_id and self._state != AlertState.IDLE:
                logger.debug(
                    f"AlertController: 同事件重复触发，忽略 event_id={event_id}"
                )
                return False

            if self._state != AlertState.IDLE:
                cur_w = _LEVEL_WEIGHT.get(self._current_level, 0)
                new_w = _LEVEL_WEIGHT.get(level, 0)
                if new_w <= cur_w:
                    logger.debug(
                        f"AlertController: 抢占失败（新等级未超过当前），忽略 "
                        f"new={level} cur={self._current_level}"
                    )
                    return False
                logger.info(
                    f"AlertController: 抢占当前序列 cur_event={self._current_event_id} "
                    f"-> new_event={event_id} level {self._current_level}->{level}"
                )
                self._stop_timers()
                self._stop_flash()

            try:
                intensity_level = int(getattr(intensity_result, "intensity_level", 0) or 0)
            except (TypeError, ValueError):
                intensity_level = 0

            self._current_event_id = event_id
            self._current_level = level
            self._current_intensity = intensity_level
            self._formatted_text = formatted_text or ""
            self._formatted_color = formatted_color or "#FF0000"
            pn = str(getattr(intensity_result, "provider_name", "") or "")
            self._site_intensity_trusted_for_hint = (
                pn not in _SYNTHETIC_INTENSITY_PROVIDERS
            )

            self._enter_stage1(parsed_data)
            return True
        except Exception as e:
            logger.error(f"AlertController.trigger 失败: {e}")
            self.dispose()
            return False

    def cancel(self, event_id: Optional[str] = None) -> None:
        """
        取消当前序列。``event_id`` 非空时仅在匹配时取消，否则无条件取消。
        """
        main_th = self._main_app_thread()
        if main_th is not None and QThread.currentThread() != main_th:
            self._cancel_requested.emit(event_id)
            return
        self._cancel_impl(event_id)

    @pyqtSlot(object)
    def _cancel_impl(self, event_id_obj: object) -> None:
        """在主线程执行取消（亦由 ``_cancel_requested`` 排队调用）。"""
        event_id: Optional[str]
        if event_id_obj is None or isinstance(event_id_obj, str):
            event_id = event_id_obj  # type: ignore[assignment]
        else:
            event_id = str(event_id_obj)
        try:
            if self._state == AlertState.IDLE:
                if self._pending_stop_flash_on_scroll:
                    eid = (event_id or "").strip()
                    if not eid or eid == self._post_stage3_flash_event_id:
                        self._stop_flash()
                return
            if event_id is not None and event_id and event_id != self._current_event_id:
                return
            logger.info(
                f"AlertController: 取消序列 event_id={self._current_event_id}"
            )
            self._stop_timers()
            self._stop_flash()
            finished_id = self._current_event_id
            self._reset_state()
            try:
                self.sequence_finished.emit(finished_id)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"AlertController.cancel 失败: {e}")

    def dispose(self) -> None:
        """主窗口关闭时调用：停止全部定时器与左侧闪烁。"""
        try:
            self._stop_timers()
            self._stop_flash()
            self._reset_state()
        except Exception as e:
            logger.debug(f"AlertController.dispose 失败: {e}")

    def _evaluate_level(
        self,
        parsed_data: Dict[str, Any],
        intensity_result: Any,
        alert_config: Any,
    ) -> str:
        if intensity_result is None:
            return "none"
        try:
            magnitude = float(getattr(intensity_result, "magnitude", 0.0) or 0.0)
            distance_km = float(getattr(intensity_result, "distance_km", 0.0) or 0.0)
            intensity_level = int(getattr(intensity_result, "intensity_level", 0) or 0)
        except (TypeError, ValueError):
            return "none"

        if magnitude < float(getattr(alert_config, "min_magnitude", 3.0) or 0.0):
            logger.debug(
                f"AlertController: 震级 {magnitude} 未达最低阈值，忽略"
            )
            return "none"
        max_dist = float(getattr(alert_config, "max_distance_km", 800.0) or 0.0)
        if max_dist > 0 and distance_km > max_dist:
            logger.debug(
                f"AlertController: 震中距 {distance_km:.0f}km 超过最大值 {max_dist:.0f}km，忽略"
            )
            return "none"

        flash_th = int(getattr(alert_config, "min_intensity_to_flash", 6) or 6)
        alert_th = int(getattr(alert_config, "min_intensity_to_alert", 4) or 4)
        if intensity_level >= flash_th:
            return "flash"
        if intensity_level >= alert_th:
            return "alert"
        return "none"

    def _enter_stage1(self, parsed_data: Dict[str, Any]) -> None:
        self._state = AlertState.STAGE1
        ac = self._config.alert_config

        # 有感 / 强有感均显示左侧「地震预警」条闪烁（仅强有感时历史上曾独占，现统一为有告警序列即闪）
        if self._current_level in ("flash", "alert"):
            self._start_flash(ac)

        live = (self._formatted_text or "").strip()
        hint = _hint_text_for_warning(
            parsed_data,
            self._current_intensity,
            self._site_intensity_trusted_for_hint,
        )
        # 阶段一/二均为「全文｜ 提示 ｜」，仅停留时长不同；数据源无关。
        self._stage1_text = _suffix_hint_after_live(live, hint)
        self._stage2_text = self._stage1_text
        warn_col = str(
            getattr(self._config.message_config, "warning_color", None) or "#FF0000"
        )
        self._stage1_segments = _suffix_hint_segments(
            live, hint, live_color=warn_col, hint_color="#FFFFFF"
        )
        self._stage2_segments = list(self._stage1_segments)

        logger.info(
            f"AlertController: 进入 STAGE1 event_id={self._current_event_id} "
            f"level={self._current_level} intensity={self._current_intensity}"
        )
        self._safe_update_text(
            self._stage1_text,
            "#FFFFFF",
            message_type=None,
            text_color_segments=self._stage1_segments,
        )
        try:
            self.sequence_started.emit(self._current_event_id, self._current_level)
        except Exception:
            pass

        self._stage1_timer.setInterval(max(100, int(ac.stage1_ms or 1500)))
        self._stage1_timer.start()

    def _enter_stage2(self) -> None:
        if self._state != AlertState.STAGE1:
            return
        self._state = AlertState.STAGE2
        ac = self._config.alert_config
        logger.info(
            f"AlertController: 进入 STAGE2 event_id={self._current_event_id}"
        )
        self._safe_update_text(
            self._stage2_text,
            "#FFFFFF",
            message_type=None,
            text_color_segments=self._stage2_segments,
        )
        self._stage2_timer.setInterval(max(100, int(ac.stage2_ms or 2500)))
        self._stage2_timer.start()

    def _enter_stage3(self) -> None:
        if self._state not in (AlertState.STAGE2, AlertState.STAGE1):
            return
        self._state = AlertState.STAGE3
        ac = self._config.alert_config
        keep_flash = bool(getattr(ac, "flash_during_stage3_warning", True))
        had_visual_flash = self._current_level in ("flash", "alert")
        logger.info(
            f"AlertController: 进入 STAGE3 event_id={self._current_event_id}"
        )
        finished_id = self._current_event_id
        text = self._formatted_text
        color = self._formatted_color

        if not (keep_flash and had_visual_flash):
            self._stop_flash()
        elif not (text or "").strip():
            self._stop_flash()

        if text:
            self._safe_update_text(text, color, message_type="warning")
            if keep_flash and had_visual_flash:
                self._arm_stop_flash_when_scroll_done(finished_id)

        self._reset_state()
        try:
            self.sequence_finished.emit(finished_id)
        except Exception:
            pass

    def _safe_update_text(
        self,
        text: str,
        color: str,
        message_type: Optional[str] = "warning",
        text_color_segments: Optional[List[Tuple[str, str]]] = None,
    ) -> None:
        """
        更新滚动条文案。
        ``text_color_segments`` 非空时按段着色（阶段一/二：预警正文 + 白字提示）；
        ``message_type='warning'`` 时与主流程一致，从配置取预警色（阶段三）。
        """
        try:
            if self._scrolling_text is None:
                return
            updater: Optional[Callable[..., Any]] = getattr(
                self._scrolling_text, "update_text", None
            )
            if updater is None:
                return
            kwargs: Dict[str, Any] = dict(
                image_path=None,
                force=True,
                message_type=message_type,
                parsed_data=None,
            )
            if text_color_segments is not None:
                kwargs["text_color_segments"] = text_color_segments
            updater(text, color, **kwargs)
        except Exception as e:
            logger.debug(f"AlertController 更新滚动文本失败: {e}")

    def _start_flash(self, ac: Any) -> None:
        try:
            if self._scrolling_text is not None:
                badge_fn = getattr(
                    self._scrolling_text, "set_lead_earthquake_badge_flashing", None
                )
                if badge_fn is not None:
                    badge_fn(
                        True,
                        interval_ms=int(ac.flash_interval_ms or 400),
                        flash_color=ac.flash_color or "#FF0000",
                    )
        except Exception as e:
            logger.debug(f"AlertController 启动闪烁失败: {e}")

    def _disconnect_flash_scroll_hook(self) -> None:
        self._pending_stop_flash_on_scroll = False
        st = self._scrolling_text
        if st is None:
            return
        try:
            st.scroll_completed.disconnect(self._on_scroll_completed_stop_flash)
        except (TypeError, RuntimeError):
            pass

    def _on_scroll_completed_stop_flash(self) -> None:
        if not self._pending_stop_flash_on_scroll:
            return
        self._stop_flash()

    def _arm_stop_flash_when_scroll_done(self, finished_id: str) -> None:
        self._disconnect_flash_scroll_hook()
        self._post_stage3_flash_event_id = (finished_id or "").strip()
        self._pending_stop_flash_on_scroll = True
        st = self._scrolling_text
        if st is None:
            return
        try:
            st.scroll_completed.connect(
                self._on_scroll_completed_stop_flash,
                type=Qt.UniqueConnection,
            )
        except TypeError:
            st.scroll_completed.connect(self._on_scroll_completed_stop_flash)

    def _stop_flash(self) -> None:
        self._disconnect_flash_scroll_hook()
        self._post_stage3_flash_event_id = ""
        try:
            if self._scrolling_text is not None:
                bfn = getattr(
                    self._scrolling_text, "set_lead_earthquake_badge_flashing", None
                )
                if bfn is not None:
                    bfn(False)
                fn = getattr(self._scrolling_text, "set_alert_flashing", None)
                if fn is not None:
                    fn(False)
        except Exception:
            pass

    def _stop_timers(self) -> None:
        try:
            if self._stage1_timer.isActive():
                self._stage1_timer.stop()
            if self._stage2_timer.isActive():
                self._stage2_timer.stop()
        except Exception:
            pass

    def _reset_state(self) -> None:
        self._state = AlertState.IDLE
        self._current_event_id = ""
        self._current_level = "none"
        self._current_intensity = 0
        self._formatted_text = ""
        self._formatted_color = "#FF0000"
        self._site_intensity_trusted_for_hint = True
