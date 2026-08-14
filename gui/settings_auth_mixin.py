#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设置窗 Fan Studio / EQSC 鉴权相关逻辑（从 settings_window 拆出以降低单文件体积）。"""

from __future__ import annotations

import threading
from typing import Any


class SettingsAuthMixin:
    """依赖 SettingsWindow 上的 config / 控件 / 信号 / _mark_settings_dirty。"""

    def _auth_set_widget_style(self, widget: Any, style: str) -> None:
        """延迟导入，避免与 settings_window 循环依赖。"""
        from gui.settings_window import _set_widget_style

        _set_widget_style(widget, style)

    def _on_fanstudio_auth_test_clicked(self):
        """测试 Fan Studio API Key：连接 /all 发送 auth，等待 auth_success 或 error。"""
        from gui.qt_light_theme import show_warning

        api_key = ""
        if hasattr(self, "fanstudio_api_key_entry"):
            api_key = self.fanstudio_api_key_entry.text().strip()
        if not api_key:
            show_warning(self, "提示", "请先填写 Fan Studio API Key（sk- 开头）。")
            return
        if getattr(self, "_fanstudio_auth_testing", False):
            return

        self._fanstudio_auth_testing = True
        if hasattr(self, "fanstudio_auth_btn"):
            self.fanstudio_auth_btn.setEnabled(False)
        if hasattr(self, "fanstudio_auth_status_label"):
            self.fanstudio_auth_status_label.setText("正在连接并鉴权…")
            self._auth_set_widget_style(
                self.fanstudio_auth_status_label, "color: #666666; font-size: 14px;"
            )

        from utils.fanstudio_credentials import test_fanstudio_auth

        def _worker():
            try:
                ok, message = test_fanstudio_auth(api_key)
            except Exception as e:
                ok, message = False, f"鉴权异常: {e}"
            self.fanstudio_auth_test_finished.emit(bool(ok), str(message or ""), api_key)

        threading.Thread(target=_worker, daemon=True, name="FanStudioAuthTest").start()

    def _on_fanstudio_auth_test_finished(self, ok: bool, message: str, api_key: str):
        """鉴权测试完成后更新 UI；成功则写入配置并对主连接热鉴权（无需重启）。"""
        from gui.qt_light_theme import show_info, show_warning

        self._fanstudio_auth_testing = False
        if hasattr(self, "fanstudio_auth_btn"):
            self.fanstudio_auth_btn.setEnabled(True)
        if ok:
            self.config.ws_config.fanstudio_api_key = api_key
            live_applied = self._hot_apply_fanstudio_auth(api_key)
            self._mark_settings_dirty()
            status = message or "鉴权成功，已接入数据流。"
            if live_applied:
                status = status + " 已对当前连接生效，完整数据流将自动下发。"
            else:
                status = status + " Key 已保存，Fan Studio 下次建连时将自动鉴权。"
            if hasattr(self, "fanstudio_auth_status_label"):
                self.fanstudio_auth_status_label.setText(status)
                self._auth_set_widget_style(
                    self.fanstudio_auth_status_label, "color: #2E7D32; font-size: 14px;"
                )
            show_info(self, "鉴权成功", status)
        else:
            if hasattr(self, "fanstudio_auth_status_label"):
                self.fanstudio_auth_status_label.setText(message or "鉴权失败")
                self._auth_set_widget_style(
                    self.fanstudio_auth_status_label, "color: #C62828; font-size: 14px;"
                )
            show_warning(self, "鉴权失败", message or "鉴权失败，请检查 API Key。")
        self._refresh_fanstudio_auth_status_label(force=False)

    def _fanstudio_api_key_text(self) -> str:
        """读取设置页当前填写的 Fan Studio API Key。"""
        if hasattr(self, "fanstudio_api_key_entry") and self.fanstudio_api_key_entry is not None:
            return (self.fanstudio_api_key_entry.text() or "").strip()
        return (getattr(self.config.ws_config, "fanstudio_api_key", "") or "").strip()

    def _set_fanstudio_auth_status_text(self, text: str, color: str = "#888888") -> None:
        """设置鉴权状态行文案（始终非空）。"""
        if not hasattr(self, "fanstudio_auth_status_label") or self.fanstudio_auth_status_label is None:
            return
        msg = (text or "").strip() or "请输入 Key"
        self.fanstudio_auth_status_label.setText(msg)
        self._auth_set_widget_style(
            self.fanstudio_auth_status_label, f"color: {color}; font-size: 14px;"
        )

    def _refresh_fanstudio_auth_status_label(self, force: bool = False) -> None:
        """
        刷新 API Key 下方状态行，保证始终有可见文案。
        优先级：测试进行中 > 主连接鉴权结果 > 是否已填写 Key。
        """
        if not hasattr(self, "fanstudio_auth_status_label") or self.fanstudio_auth_status_label is None:
            return
        if getattr(self, "_fanstudio_auth_testing", False) and not force:
            self._set_fanstudio_auth_status_text("正在连接并鉴权…", "#666666")
            return

        key = self._fanstudio_api_key_text()
        if not key:
            self._set_fanstudio_auth_status_text("请输入 Key", "#888888")
            return

        parent = self.parent()
        getter = getattr(parent, "get_fanstudio_auth_status", None) if parent is not None else None
        state, message = "none", ""
        if callable(getter):
            try:
                state, message = getter()
            except Exception:
                state, message = "none", ""
        state = str(state or "none").strip().lower()
        message = str(message or "").strip()
        current = (self.fanstudio_auth_status_label.text() or "").strip()

        if state == "ok":
            text = message or "鉴权成功，已接入数据流。"
            if force or current.startswith("正在连接并鉴权") or not current or current in (
                "请输入 Key",
                "已填写，点击「连接」进行鉴权",
            ) or "鉴权成功" in current:
                self._set_fanstudio_auth_status_text(text, "#2E7D32")
            return
        if state == "pending":
            self._set_fanstudio_auth_status_text(message or "正在连接并鉴权…", "#666666")
            return
        if state == "failed":
            if force or current.startswith("正在连接并鉴权") or "鉴权失败" in current or current in (
                "请输入 Key",
                "已填写，点击「连接」进行鉴权",
                "",
            ):
                self._set_fanstudio_auth_status_text(message or "鉴权失败", "#C62828")
            return

        if current and current not in ("请输入 Key",) and (
            "鉴权成功" in current or "鉴权失败" in current or current.startswith("正在连接并鉴权")
        ):
            return
        self._set_fanstudio_auth_status_text("已填写，点击「连接」进行鉴权", "#666666")

    def _sync_fanstudio_auth_status_label(self, force: bool = False) -> None:
        """兼容旧调用：转交到统一刷新逻辑。"""
        self._refresh_fanstudio_auth_status_label(force=force)

    def _hot_apply_fanstudio_auth(self, api_key: str) -> bool:
        """向主窗口已连接的 Fan Studio /all 热发送鉴权；返回是否已发出。"""
        parent = self.parent()
        if parent is None:
            return False
        apply_fn = getattr(parent, "apply_fanstudio_api_key", None)
        if not callable(apply_fn):
            ws_manager = getattr(parent, "ws_manager", None)
            if ws_manager is None or not hasattr(ws_manager, "send_fanstudio_auth"):
                return False
            self.config.ws_config.fanstudio_api_key = (api_key or "").strip()
            return bool(ws_manager.send_fanstudio_auth(api_key))
        return bool(apply_fn(api_key))

    def _on_eqsc_auth_test_clicked(self):
        """测试 EQSC 登录密钥：换取 AccessToken。"""
        from gui.qt_light_theme import show_warning

        login_token = ""
        if hasattr(self, "eqsc_login_token_entry"):
            login_token = self.eqsc_login_token_entry.text().strip()
        if not login_token:
            show_warning(self, "提示", "请先填写 EQSC 登录密钥（在 equake.top/auth 申请）。")
            return
        if getattr(self, "_eqsc_auth_testing", False):
            return

        self._eqsc_auth_testing = True
        if hasattr(self, "eqsc_auth_btn"):
            self.eqsc_auth_btn.setEnabled(False)
        if hasattr(self, "eqsc_auth_status_label"):
            self.eqsc_auth_status_label.setText("正在换取 AccessToken…")
            self._auth_set_widget_style(
                self.eqsc_auth_status_label, "color: #666666; font-size: 14px;"
            )

        from utils.eqsc_credentials import test_eqsc_auth

        def _worker():
            try:
                ok, message = test_eqsc_auth(login_token)
            except Exception as e:
                ok, message = False, f"鉴权异常: {e}"
            self.eqsc_auth_test_finished.emit(bool(ok), str(message or ""), login_token)

        threading.Thread(target=_worker, daemon=True, name="EqscAuthTest").start()

    def _on_eqsc_auth_test_finished(self, ok: bool, message: str, login_token: str):
        """EQSC 鉴权完成后更新 UI；成功则写入登录密钥。"""
        from gui.qt_light_theme import show_info, show_warning

        self._eqsc_auth_testing = False
        if hasattr(self, "eqsc_auth_btn"):
            self.eqsc_auth_btn.setEnabled(True)
        if ok:
            self.config.ws_config.eqsc_login_token = login_token
            self._mark_settings_dirty()
            status = message or "鉴权成功，已换取 AccessToken。"
            if hasattr(self, "eqsc_auth_status_label"):
                self.eqsc_auth_status_label.setText(status)
                self._auth_set_widget_style(
                    self.eqsc_auth_status_label, "color: #2E7D32; font-size: 14px;"
                )
            show_info(self, "鉴权成功", status)
        else:
            if hasattr(self, "eqsc_auth_status_label"):
                self.eqsc_auth_status_label.setText(message or "鉴权失败")
                self._auth_set_widget_style(
                    self.eqsc_auth_status_label, "color: #C62828; font-size: 14px;"
                )
            show_warning(self, "鉴权失败", message or "鉴权失败，请检查登录密钥。")
        self._refresh_eqsc_auth_status_label(force=False)

    def _eqsc_login_token_text(self) -> str:
        """读取设置页当前填写的 EQSC 登录密钥。"""
        if hasattr(self, "eqsc_login_token_entry") and self.eqsc_login_token_entry is not None:
            return (self.eqsc_login_token_entry.text() or "").strip()
        return (getattr(self.config.ws_config, "eqsc_login_token", "") or "").strip()

    def _set_eqsc_auth_status_text(self, text: str, color: str = "#888888") -> None:
        """设置 EQSC 鉴权状态行文案（始终非空）。"""
        if not hasattr(self, "eqsc_auth_status_label") or self.eqsc_auth_status_label is None:
            return
        msg = (text or "").strip() or "请输入登录密钥"
        self.eqsc_auth_status_label.setText(msg)
        self._auth_set_widget_style(
            self.eqsc_auth_status_label, f"color: {color}; font-size: 14px;"
        )

    def _refresh_eqsc_auth_status_label(self, force: bool = False) -> None:
        """刷新 EQSC 登录密钥下方状态行（测试中 / 主连接鉴权 / 是否已填写）。"""
        if not hasattr(self, "eqsc_auth_status_label") or self.eqsc_auth_status_label is None:
            return
        if getattr(self, "_eqsc_auth_testing", False) and not force:
            self._set_eqsc_auth_status_text("正在换取 AccessToken…", "#666666")
            return

        key = self._eqsc_login_token_text()
        if not key:
            self._set_eqsc_auth_status_text("请输入登录密钥", "#888888")
            return

        parent = self.parent()
        getter = getattr(parent, "get_eqsc_auth_status", None) if parent is not None else None
        if not callable(getter) and parent is not None:
            ws_manager = getattr(parent, "ws_manager", None)
            getter = getattr(ws_manager, "get_eqsc_auth_status", None) if ws_manager is not None else None
        state, message = "none", ""
        if callable(getter):
            try:
                state, message = getter()
            except Exception:
                state, message = "none", ""
        state = str(state or "none").strip().lower()
        message = str(message or "").strip()
        current = (self.eqsc_auth_status_label.text() or "").strip()

        if state == "ok":
            text = message or "鉴权成功，已换取 AccessToken。"
            if force or current.startswith("正在换取") or not current or current in (
                "请输入登录密钥",
                "已填写，点击「连接」进行鉴权",
                "已保存登录密钥，点击「连接」可重新验证",
            ) or "鉴权成功" in current:
                self._set_eqsc_auth_status_text(text, "#2E7D32")
            return
        if state == "pending":
            self._set_eqsc_auth_status_text(message or "正在换取 AccessToken…", "#666666")
            return
        if state == "failed":
            if force or current.startswith("正在换取") or "鉴权失败" in current or current in (
                "请输入登录密钥",
                "已填写，点击「连接」进行鉴权",
                "已保存登录密钥，点击「连接」可重新验证",
                "",
            ):
                self._set_eqsc_auth_status_text(message or "鉴权失败", "#C62828")
            return

        if current and current not in ("请输入登录密钥",) and (
            "鉴权成功" in current or "鉴权失败" in current or current.startswith("正在换取")
        ):
            return
        saved = (getattr(self.config.ws_config, "eqsc_login_token", "") or "").strip()
        if saved and saved == key:
            self._set_eqsc_auth_status_text("已保存登录密钥，点击「连接」可重新验证", "#2E7D32")
            return
        self._set_eqsc_auth_status_text("已填写，点击「连接」进行鉴权", "#666666")

    def _sync_eqsc_auth_status_label(self, force: bool = False) -> None:
        """兼容调用：转交到 EQSC 状态刷新。"""
        self._refresh_eqsc_auth_status_label(force=force)
