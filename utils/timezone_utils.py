#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时区工具模块
将各数据源时间统一转换为用户在 GUI 中配置的显示时区（``Config.gui_config.timezone``），
并提供解析/比较接口供有效期判断使用。适配器出口侧的 ``shock_time`` 等展示字段应在此转换后再入队。
"""

from datetime import datetime, timezone
from typing import Optional, Union

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

# 延迟导入 config，避免循环依赖
def _get_config():
    """延迟加载 Config 单例，避免模块导入时的循环依赖。"""
    from config import Config
    return Config()


def get_display_zone():
    """返回当前配置的显示时区 ZoneInfo，异常时退回 Asia/Shanghai。"""
    try:
        tz_name = _get_config().gui_config.timezone
        if not tz_name:  # 未配置时默认上海时区
            return ZoneInfo("Asia/Shanghai")
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("Asia/Shanghai")


def utc_to_display(utc_time_str: str) -> str:
    """
    将 UTC 时间字符串（ISO 8601 / 带 Z）转为显示时区后格式化为 YYYY-MM-DD HH:MM:SS。
    """
    try:
        if not utc_time_str:
            return ""
        s = utc_time_str.strip().replace("Z", "+00:00").replace("z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return utc_time_str
        if dt.tzinfo is None:  # 无时区信息则视为 UTC
            dt = dt.replace(tzinfo=timezone.utc)
        display_dt = dt.astimezone(get_display_zone())
        return display_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return utc_time_str


def jst_to_display(jst_time_str: str) -> str:
    """
    将日本时间（JST, UTC+9）字符串解析后转为显示时区，格式化为 YYYY-MM-DD HH:MM:SS。
    """
    try:
        if not jst_time_str:
            return ""
        jst = ZoneInfo("Asia/Tokyo")
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",  # JMA 速报 time 无秒
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y%m%d%H%M%S",
        ]
        dt = None
        for fmt in formats:
            try:
                dt = datetime.strptime(jst_time_str.strip(), fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return jst_time_str
        dt = dt.replace(tzinfo=jst)
        display_dt = dt.astimezone(get_display_zone())
        return display_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return jst_time_str


def cst_to_display(cst_time_str: str) -> str:
    """
    将北京时间（CST, UTC+8）字符串解析后转为显示时区，格式化为 YYYY-MM-DD HH:MM:SS。
    支持格式：YYYY-MM-DD HH:MM:SS, YYYY/MM/DD HH:MM:SS, YYYYMMDDHHMMSS 等。
    """
    try:
        if not cst_time_str:
            return ""
        s = cst_time_str.strip()
        cst = ZoneInfo("Asia/Shanghai")
        formats = [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y%m%d%H%M%S",
            "%Y%m%d%H%M",
        ]
        dt = None
        for fmt in formats:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return cst_time_str
        dt = dt.replace(tzinfo=cst)
        display_dt = dt.astimezone(get_display_zone())
        return display_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return cst_time_str


def timestamp_to_display(ts: int) -> str:
    """
    将时间戳（秒或毫秒）按 UTC 解释后转为显示时区，格式化为 YYYY-MM-DD HH:MM:SS。
    """
    try:
        if ts is None:
            return ""
        t = int(ts)
        if t > 10000000000:  # 毫秒时间戳转为秒
            t = t // 1000
        dt = datetime.fromtimestamp(t, tz=timezone.utc)
        display_dt = dt.astimezone(get_display_zone())
        return display_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def parse_display_time(time_str: str) -> Optional[datetime]:
    """
    将显示用时间字符串按当前显示时区解析为 naive datetime（用于与 now_in_display_tz 做差）。
    """
    try:
        if not time_str or not time_str.strip():
            return None
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str.strip(), fmt)
                return dt
            except ValueError:
                continue
        return None
    except Exception:
        return None


def now_in_display_tz() -> datetime:
    """当前时刻在显示时区下的 naive datetime，用于与 parse_display_time 的结果做差。"""
    return datetime.now(get_display_zone()).replace(tzinfo=None)


def now_display_str() -> str:
    """当前时刻在显示时区下的格式化字符串 YYYY-MM-DD HH:MM:%S。"""
    return now_in_display_tz().strftime("%Y-%m-%d %H:%M:%S")


def ms_timestamp_utc_to_display(ms: Union[int, float]) -> str:
    """
    Fan Studio 等数据源常用的 Unix 毫秒时间戳（按 UTC）→ 当前显示时区 YYYY-MM-DD HH:MM:SS。
    """
    try:
        t = float(ms) / 1000.0
        dt = datetime.fromtimestamp(t, tz=timezone.utc)
        return dt.astimezone(get_display_zone()).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def flexible_time_to_display(time_str: str) -> str:
    """
    气象预警等混合格式：优先解析带时区偏移的 ISO8601（含 Z），否则按北京时间朴素串解析。
    """
    s = (time_str or "").strip()
    if not s:  # 空字符串直接返回
        return ""
    s_iso = s.replace("Z", "+00:00").replace("z", "+00:00")
    if "T" in s_iso:
        try:
            dt = datetime.fromisoformat(s_iso)
            if dt.tzinfo is not None:
                return dt.astimezone(get_display_zone()).strftime("%Y-%m-%d %H:%M:%S")
            head = s_iso.replace("T", " ", 1)
            if len(head) >= 19:
                head = head[:19]
            return cst_to_display(head)
        except ValueError:
            pass
    return cst_to_display(s)
