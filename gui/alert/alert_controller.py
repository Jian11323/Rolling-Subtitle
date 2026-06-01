#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
告警序列状态机控制器。

状态：``IDLE -> HINT（带安全提示的预警全文）-> FINAL（纯预警条文）-> IDLE``。
提示期结束条件：优先在提示期字幕**完整滚过一周**后结束（与左侧「地震预警」闪烁同步消失）；
兜底定时器时长按当前报文**发震时间有效期**剩余时间（与 ``MessageProcessor`` 入口校验同源），
无发震时间时用 ``warning_shock_validity_seconds`` 整窗；关闭「关闭预警有效期（测试）」时视为极长。
日台类源不拼接提示、不进入本序列。

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

import math
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, QTimer, Qt, QThread, QCoreApplication, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QApplication

from utils.logger import get_logger
from utils.message_processor import (
    warning_shock_validity_max_seconds,
    warning_shock_validity_remaining_seconds,
)
from utils.epi_intensity_estimate import (
    SOURCE_TW_JP_ALERT_EXCLUDE,
    effective_epi_for_alert,
)

logger = get_logger()


class AlertState(IntEnum):
    IDLE = 0
    HINT = 1
    FINAL = 2


# 等级整数权重，用于跨事件抢占判断；与 AlertConfig 中两个阈值无关，仅做大小比较。
_LEVEL_WEIGHT = {
    "none": 0,
    "alert": 1,
    "flash": 2,
}

# 有感 / 强有感白字提示（烈度标量：I<6 用有感提示，I≥6 用强有感提示；含原 5≤I<6 空白带）
_HINT_ALERT = "现正发生有感地震。请注意安全"
_HINT_FLASH = (
    "现正发生强有感地震，请保持冷静，注意保护头部并远离掉落物。"
)


def _hint_text_for_warning(parsed_data: Dict[str, Any]) -> str:
    """
    尾部白字提示：基于报文或经验估算的震中烈度标量（日台类源不拼接）。
    有感：烈度 < 5；强有感：烈度 ≥ 6。
    """
    st = (parsed_data.get("source_type") or "").strip().lower()
    if st in SOURCE_TW_JP_ALERT_EXCLUDE:
        return ""
    val = effective_epi_for_alert(parsed_data or {})
    if val is None or val <= 0:
        return ""
    if val >= 6.0:
        return _HINT_FLASH
    return _HINT_ALERT


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
    与告警「提示期」相同的「正文 + 白字安全提示」分段。

    用于缓冲区轮播、切屏等不经过 ``AlertController.trigger`` 的路径，避免只有
    首个成功触发序列的数据源才出现白字提示。
    """
    ac = getattr(config, "alert_config", None)
    if ac is None or not getattr(ac, "enabled", False):
        return None
    live = (live_text or "").replace("\n", " ").replace("\r", "").strip()
    if not live:
        return None
    _ = intensity_result  # 保留参数以兼容旧调用；提示仅依据报文
    hint = _hint_text_for_warning(parsed_data or {})
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
    告警序列控制器：先展示带安全提示的预警全文（提示期），再切回纯预警条文。

    有感 / 强有感序列驱动字幕条左侧「地震预警」标识闪烁（见 ``set_lead_earthquake_badge_flashing``），
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

        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self._enter_final_phase)

        # 跨线程 trigger：BlockingQueued 保证在消息入队/切屏前完成，避免 QTimer 在非主线程启动
        self._pending_cross_thread_trigger: Optional[Tuple[Any, Any, str, str]] = None
        self._cross_thread_trigger_result: bool = False

        self._cancel_requested.connect(self._cancel_impl, Qt.QueuedConnection)
        self._blocking_trigger_run.connect(
            self._run_pending_trigger, Qt.BlockingQueuedConnection
        )

    def alert_sequence_active(self) -> bool:
        """告警状态机是否在运行（提示期或纯条文切换阶段）。勿用 ``is_active`` 名以免与 Qt 动态属性冲突。"""
        return self._state != AlertState.IDLE

    def consume_scroll_completed_for_hint_phase(self) -> bool:
        """
        由主窗口在 ``scroll_completed`` 时调用。

        若当前处于提示期（HINT），视为本条提示期字幕已完整滚过一周：结束闪烁、
        切回纯预警条文并结束序列；返回 True 表示已消费本轮滚动完成事件（主窗口
        应跳过后续轮播逻辑，避免再次用分段提示覆盖刚切回的纯条文）。
        """
        if self._state != AlertState.HINT:
            return False
        self._enter_final_phase()
        return True

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

        ``intensity_result`` 已废弃，请传 ``None``；阈值与提示仅依据 ``parsed_data`` 报文。

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

            self._current_event_id = event_id
            self._current_level = level
            _ei = effective_epi_for_alert(parsed_data or {})
            self._current_intensity = int(round(_ei)) if _ei is not None else 0
            self._formatted_text = formatted_text or ""
            self._formatted_color = formatted_color or "#FF0000"

            self._enter_hint_phase(parsed_data)
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
        _ = intensity_result
        pd = parsed_data or {}
        try:
            magnitude = float(pd.get("magnitude") or 0.0)
        except (TypeError, ValueError):
            return "none"

        if magnitude < float(getattr(alert_config, "min_magnitude", 3.0) or 0.0):
            logger.debug(
                f"AlertController: 震级 {magnitude} 未达最低阈值，忽略"
            )
            return "none"

        st = (pd.get("source_type") or "").strip().lower()
        if st in SOURCE_TW_JP_ALERT_EXCLUDE:
            return "none"

        val = effective_epi_for_alert(pd)
        if val is None or val <= 0:
            return "none"

        if val >= 6.0:
            return "flash"
        return "alert"

    def _enter_hint_phase(self, parsed_data: Dict[str, Any]) -> None:
        self._state = AlertState.HINT
        ac = self._config.alert_config

        # 有感 / 强有感均显示左侧「地震预警」条闪烁（仅强有感时历史上曾独占，现统一为有告警序列即闪）
        if self._current_level in ("flash", "alert"):
            self._start_flash(ac)

        live = (self._formatted_text or "").strip()
        hint = _hint_text_for_warning(parsed_data or {})
        # 提示期为「全文｜ 提示 ｜」（无提示时与纯条文相同，仍按时长切换）
        self._hint_phase_text = _suffix_hint_after_live(live, hint)
        warn_col = str(
            getattr(self._config.message_config, "warning_color", None) or "#FF0000"
        )
        self._hint_phase_segments = _suffix_hint_segments(
            live, hint, live_color=warn_col, hint_color="#FFFFFF"
        )

        logger.info(
            f"AlertController: 进入提示期 event_id={self._current_event_id} "
            f"level={self._current_level} intensity={self._current_intensity}"
        )
        self._safe_update_text(
            self._hint_phase_text,
            "#FFFFFF",
            message_type=None,
            text_color_segments=self._hint_phase_segments,
        )
        try:
            self.sequence_started.emit(self._current_event_id, self._current_level)
        except Exception:
            pass

        msg_cfg = getattr(self._config, "message_config", None)
        hint_ms = 300_000
        if msg_cfg is not None:
            rem = warning_shock_validity_remaining_seconds(parsed_data or {}, msg_cfg)
            if rem is None:
                hint_ms = int(warning_shock_validity_max_seconds(
                    (parsed_data or {}).get("source_type", "") or "", msg_cfg
                ) * 1000)
            elif math.isinf(rem):
                hint_ms = 86_400_000
            else:
                hint_ms = int(max(0.0, rem) * 1000)
        _cap = 86_400_000
        self._hint_timer.setInterval(max(100, min(hint_ms, _cap)))
        self._hint_timer.start()

    def _enter_final_phase(self) -> None:
        if self._state != AlertState.HINT:
            return
        self._stop_timers()
        self._state = AlertState.FINAL
        logger.info(
            f"AlertController: 切换为纯预警条文 event_id={self._current_event_id}"
        )
        finished_id = self._current_event_id
        text = self._formatted_text
        color = self._formatted_color

        self._stop_flash()

        if text:
            self._safe_update_text(text, color, message_type="warning")

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
        ``text_color_segments`` 非空时按段着色（提示期：预警正文 + 白字提示）；
        ``message_type='warning'`` 时与主流程一致，从配置取预警色（纯预警条文）。
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

    def _stop_flash(self) -> None:
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
            if self._hint_timer.isActive():
                self._hint_timer.stop()
        except Exception:
            pass

    def _reset_state(self) -> None:
        self._state = AlertState.IDLE
        self._current_event_id = ""
        self._current_level = "none"
        self._current_intensity = 0
        self._formatted_text = ""
        self._formatted_color = "#FF0000"
