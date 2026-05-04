#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动时或手动「检查更新」：拉取 manifest.json，比对版本，必要时下载并由独立 bat 静默安装/解压后启动新版本。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, Optional, Tuple

import requests
from packaging.version import parse as parse_version

from config import APP_VERSION, AUTO_UPDATE_MANIFEST_URL_DEFAULT
from utils.logger import get_logger
from utils.resource_path import get_executable_path

logger = get_logger()

USER_AGENT = f"EarthquakeScroller/{APP_VERSION}"

# 与 build_lite.spec 中 onedir 名称一致（空格 + V + 版本号）
def portable_dist_folder_name(version: str) -> str:
    return f"地震预警及情报实况栏 V{version.strip()}"


def portable_exe_basename(version: str) -> str:
    return f"地震预警及情报实况栏 V{version.strip()}.exe"


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _fetch_manifest(url: str, timeout: float) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(
            url.strip(),
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            return None
        return data
    except Exception as e:
        logger.warning(f"拉取更新清单失败: {e}")
        return None


def _remote_newer(
    local_ver: str, remote_ver: str, upgrade_only: bool
) -> Tuple[bool, str]:
    """返回 (是否需要更新, 说明文本)。"""
    try:
        lv = parse_version((local_ver or "").strip())
        rv = parse_version((remote_ver or "").strip())
    except Exception as e:
        logger.warning(f"版本号解析失败: {e}")
        return False, "版本号格式无效，已跳过更新。"
    if lv == rv:
        return False, ""
    if upgrade_only:
        if rv > lv:
            return True, ""
        return False, ""
    return lv != rv, ""


def _pick_asset(
    manifest: Dict[str, Any], package_kind: str
) -> Tuple[Optional[str], Optional[str], str]:
    """返回 (url, sha256_hex_or_empty, kind_label)。"""
    kind = (package_kind or "installer").strip().lower()
    if kind == "zip":
        z = manifest.get("zip")
        if isinstance(z, dict):
            u = (z.get("url") or "").strip()
            h = (z.get("sha256") or "").strip()
            if u:
                return u, h, "zip"
        return None, None, "zip"
    inst = manifest.get("installer")
    if isinstance(inst, dict):
        u = (inst.get("url") or "").strip()
        h = (inst.get("sha256") or "").strip()
        if u:
            return u, h, "installer"
    return None, None, "installer"


def _download_file(
    url: str,
    dest: str,
    timeout: float,
    progress_cb=None,
) -> bool:
    try:
        with requests.get(
            url,
            stream=True,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        ) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb and total > 0:
                        progress_cb(min(99, int(done * 100 / total)))
        if progress_cb:
            progress_cb(100)
        return True
    except Exception as e:
        logger.warning(f"下载更新文件失败: {e}")
        try:
            if os.path.isfile(dest):
                os.remove(dest)
        except OSError:
            pass
        return False


def _write_installer_bat(setup_exe_abs: str) -> str:
    """静默安装 Inno 包，结束后尝试启动安装目录下的 Rolling Subtitle.exe（与 installer.iss 一致）。"""
    fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="rolling_upd_")
    os.close(fd)
    bat_encoding = "gbk" if os.name == "nt" else "utf-8"
    setup_exe_abs = os.path.normpath(setup_exe_abs)
    lines = [
        "@echo off",
        "setlocal",
        f'set "SETUP={setup_exe_abs}"',
        "ping 127.0.0.1 -n 5 >nul",
        'if not exist "%SETUP%" goto :eof',
        '"%SETUP%" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /SP-',
        'set "L1=%ProgramFiles%\\Rolling Subtitle\\Rolling Subtitle.exe"',
        'set "L2=%LocalAppData%\\Programs\\Rolling Subtitle\\Rolling Subtitle.exe"',
        'if exist "%L1%" (start "" "%L1%" & goto :done)',
        'if exist "%L2%" (start "" "%L2%" & goto :done)',
        ":done",
        'del "%~f0"',
    ]
    with open(bat_path, "w", encoding=bat_encoding, newline="\r\n") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return bat_path


def _write_zip_bat(
    zip_abs: str,
    extract_root: str,
    inner_folder: str,
    dest_parent: str,
    launch_exe_abs: str,
) -> str:
    fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="rolling_upd_zip_")
    os.close(fd)
    bat_encoding = "gbk" if os.name == "nt" else "utf-8"
    zip_abs = os.path.normpath(zip_abs)
    extract_root = os.path.normpath(extract_root)
    inner_folder = inner_folder.rstrip("\\/")
    dest_parent = os.path.normpath(dest_parent)
    launch_exe_abs = os.path.normpath(launch_exe_abs)
    inner_src = os.path.join(extract_root, inner_folder)
    inner_dest = os.path.join(dest_parent, inner_folder)
    ps_extract = (
        f'powershell -NoProfile -ExecutionPolicy Bypass -Command '
        f'"Expand-Archive -LiteralPath \'{zip_abs}\' -DestinationPath \'{extract_root}\' -Force"'
    )
    lines = [
        "@echo off",
        "setlocal",
        "ping 127.0.0.1 -n 5 >nul",
        ps_extract,
        f'if exist "{inner_src}" robocopy "{inner_src}" "{inner_dest}" /E /NFL /NDL /NJH /NJS /IS /IT',
        f'if exist "{launch_exe_abs}" start "" "{launch_exe_abs}"',
        'del "%~f0"',
    ]
    with open(bat_path, "w", encoding=bat_encoding, newline="\r\n") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return bat_path


def _spawn_detached_bat(bat_path: str) -> bool:
    try:
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        return True
    except Exception as e:
        logger.error(f"启动更新脚本失败: {e}")
        return False


def _verify_sha256(path: str, expected: str) -> bool:
    if not expected:
        return True
    actual = _sha256_file(path).lower()
    return actual == expected.strip().lower()


def run_startup_auto_update(app, config) -> bool:
    """
    打包版启动时检查更新；若已触发安装流程则返回 True，调用方应 sys.exit(0) 且不再创建主窗口。
    """
    if not getattr(sys, "frozen", False):
        return False
    if not getattr(config.gui_config, "auto_update_check_on_startup", True):
        return False
    return _run_update_flow(app, config, parent=None, force_prompt_if_newer=True)


def run_interactive_update_check(parent, config) -> bool:
    """设置-关于：手动检查更新。若已启动安装流程返回 True，调用方可 os._exit(0)。"""
    from PyQt5.QtWidgets import QMessageBox

    if not getattr(sys, "frozen", False):
        QMessageBox.information(
            parent,
            "检查更新",
            "当前为源码/解释器运行模式，不支持自动下载安装。\n请使用打包后的 exe 或自行从发布页获取安装包。",
        )
        return False
    return _run_update_flow(app=None, config=config, parent=parent, force_prompt_if_newer=False)


def _run_update_flow(app, config, parent, force_prompt_if_newer: bool) -> bool:
    from PyQt5.QtWidgets import QApplication, QMessageBox, QProgressDialog
    from PyQt5.QtCore import Qt

    url = (getattr(config.gui_config, "auto_update_manifest_url", "") or "").strip()
    if not url:
        url = (AUTO_UPDATE_MANIFEST_URL_DEFAULT or "").strip()
    if not url:
        return False
    timeout = float(getattr(config.gui_config, "auto_update_timeout_seconds", 15) or 15)
    timeout = max(5.0, min(120.0, timeout))
    upgrade_only = bool(getattr(config.gui_config, "auto_update_upgrade_only", True))
    package_kind = (getattr(config.gui_config, "auto_update_package_kind", "installer") or "installer").strip().lower()

    manifest = _fetch_manifest(url, timeout)
    if not manifest:
        if parent is not None:
            QMessageBox.warning(parent, "检查更新", "无法获取更新清单，请检查网络或稍后再试。")
        else:
            logger.info("启动时检查更新：无法获取清单，跳过。")
        return False

    remote_ver = (manifest.get("latest_version") or "").strip()
    if not remote_ver:
        if parent is not None:
            QMessageBox.warning(parent, "检查更新", "清单中缺少 latest_version 字段。")
        else:
            logger.info("启动时检查更新：清单缺少 latest_version，跳过。")
        return False

    need, _ = _remote_newer(APP_VERSION, remote_ver, upgrade_only)
    if not need:
        if parent is not None:
            QMessageBox.information(
                parent,
                "检查更新",
                f"当前版本 v{APP_VERSION} 已是最新（或高于服务器版本）。\n服务器最新：v{remote_ver}",
            )
        return False

    msg_parent = parent if parent is not None else None
    if force_prompt_if_newer or parent is not None:
        r = QMessageBox.question(
            msg_parent,
            "发现新版本",
            f"发现新版本 v{remote_ver}（当前 v{APP_VERSION}）。\n是否下载并安装？\n\n安装完成后将自动启动新版本。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if r != QMessageBox.Yes:
            return False

    asset_url, sha256_expected, kind_label = _pick_asset(manifest, package_kind)
    if not asset_url:
        QMessageBox.warning(
            msg_parent,
            "检查更新",
            f"清单中未找到可用的 {kind_label} 下载地址（installer / zip）。",
        )
        return False

    staging = tempfile.mkdtemp(prefix="rolling_upd_dl_")
    try:
        if package_kind == "zip":
            local_file = os.path.join(staging, "update.zip")
        else:
            local_file = os.path.join(staging, "setup_update.exe")

        prog = QProgressDialog("正在下载更新…", "取消", 0, 100, msg_parent)
        prog.setWindowTitle("更新")
        prog.setWindowModality(Qt.ApplicationModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        prog.show()

        cancelled = {"v": False}

        def cb(pct):
            if prog.wasCanceled():
                cancelled["v"] = True
                return
            prog.setValue(pct)
            qa = QApplication.instance()
            if qa:
                qa.processEvents()

        ok = _download_file(asset_url, local_file, timeout, progress_cb=cb)
        prog.close()
        if cancelled["v"] or not ok:
            QMessageBox.information(msg_parent, "检查更新", "下载已取消或失败。")
            return False

        if not _verify_sha256(local_file, sha256_expected or ""):
            QMessageBox.critical(msg_parent, "检查更新", "文件校验失败（SHA256 不一致），已中止更新。")
            return False

        if package_kind == "zip":
            exe_path = get_executable_path()
            exe_dir = os.path.dirname(exe_path)
            portable_parent = os.path.dirname(exe_dir)
            inner = portable_dist_folder_name(remote_ver)
            extract_root = os.path.join(staging, "extract")
            os.makedirs(extract_root, exist_ok=True)
            launch_exe = os.path.join(portable_parent, inner, portable_exe_basename(remote_ver))
            bat = _write_zip_bat(local_file, extract_root, inner, portable_parent, launch_exe)
        else:
            bat = _write_installer_bat(local_file)

        # 必须先让用户点「确定」并尽快退出进程，再启动 bat。
        # 若先 spawn bat，ping 结束后安装程序会在本进程仍存活（阻塞在下方对话框）时运行，文件被占用会导致静默安装失败并陷入「永远 v 旧版 → 又提示更新」。
        QMessageBox.information(
            msg_parent,
            "准备安装更新",
            "安装包已下载完毕。\n\n请点击「确定」：本程序将立即退出，几秒后自动开始静默安装；完成后将尝试启动新版本。\n\n"
            "若您是从便携文件夹内的旧 exe 启动，而安装版写入「开始菜单」目录，更新后请从开始菜单或安装目录打开新版本，勿再运行旧路径下的 exe。",
        )
        qa = QApplication.instance()
        if qa:
            qa.processEvents()

        if not _spawn_detached_bat(bat):
            QMessageBox.critical(msg_parent, "检查更新", "无法启动安装脚本。")
            return False

        return True
    finally:
        try:
            # staging 中的 zip/setup 仍可能被 bat 使用，仅删除失败时忽略；由 bat 后无法删 — 保留在 Temp 由系统清理
            pass
        except Exception:
            pass

