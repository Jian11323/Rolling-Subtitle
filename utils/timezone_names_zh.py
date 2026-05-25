# -*- coding: utf-8 -*-
"""
时区显示：每档 UTC 偏移对应一个代表城市，格式如 UTC+8 北京、UTC+9 东京
列表项为 (显示文本, IANA 时区 ID)
"""

# 按 UTC 偏移从负到正排列，每档一个著名城市
TZ_OFFSET_CITY = [
    ("UTC-12 贝克岛", "Pacific/Baker"),
    ("UTC-11 萨摩亚", "Pacific/Pago_Pago"),
    ("UTC-10 火奴鲁鲁", "Pacific/Honolulu"),
    ("UTC-9 安克雷奇", "America/Anchorage"),
    ("UTC-8 洛杉矶", "America/Los_Angeles"),
    ("UTC-7 丹佛", "America/Denver"),
    ("UTC-6 芝加哥", "America/Chicago"),
    ("UTC-5 纽约", "America/New_York"),
    ("UTC-4 圣地亚哥", "America/Santiago"),
    ("UTC-3 圣保罗", "America/Sao_Paulo"),
    ("UTC-2 努瓦克肖特", "Africa/Nouakchott"),
    ("UTC-1 亚速尔", "Atlantic/Azores"),
    ("UTC+0 伦敦", "Europe/London"),
    ("UTC+1 巴黎", "Europe/Paris"),
    ("UTC+2 开罗", "Africa/Cairo"),
    ("UTC+3 莫斯科", "Europe/Moscow"),
    ("UTC+4 迪拜", "Asia/Dubai"),
    ("UTC+5 卡拉奇", "Asia/Karachi"),
    ("UTC+5:30 新德里", "Asia/Kolkata"),
    ("UTC+6 达卡", "Asia/Dhaka"),
    ("UTC+7 曼谷", "Asia/Bangkok"),
    ("UTC+8 北京", "Asia/Shanghai"),
    ("UTC+9 东京", "Asia/Tokyo"),
    ("UTC+10 悉尼", "Australia/Sydney"),
    ("UTC+11 所罗门群岛", "Pacific/Guadalcanal"),
    ("UTC+12 奥克兰", "Pacific/Auckland"),
    ("UTC+13 汤加", "Pacific/Tongatapu"),
    ("UTC+14 莱恩群岛", "Pacific/Kiritimati"),
]


def get_tz_options():
    """返回 [(显示文本, IANA ID), ...]，供下拉框使用。"""
    return list(TZ_OFFSET_CITY)


def iana_to_display(iana_id: str) -> str:
    """
    若 iana_id 在 TZ_OFFSET_CITY 中，返回对应显示文本；否则根据当前偏移匹配「UTC±N 城市」。
    用于兼容旧配置（如保存了 Asia/Hong_Kong）时在下拉框中选中对应偏移项。
    """
    for display, tid in TZ_OFFSET_CITY:
        if tid == iana_id:
            return display
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        z = ZoneInfo(iana_id)
        dt = datetime.now(z)
        off = dt.utcoffset()
        if off is None:
            return "UTC+0 伦敦"
        sec = int(off.total_seconds())
        if sec >= 0:
            h, r = divmod(sec, 3600)
            m = r // 60
            utc_str = f"UTC+{h}" if m == 0 else f"UTC+{h}:{m:02d}"
        else:
            h, r = divmod(-sec, 3600)
            m = r // 60
            utc_str = f"UTC-{h}" if m == 0 else f"UTC-{h}:{m:02d}"
        # 在已知列表中找同一偏移的显示名（用「UTC±N 」前缀匹配，避免 UTC+5 与 UTC+5:30 混淆）
        prefix = utc_str + " "
        for display, tid in TZ_OFFSET_CITY:
            if display.startswith(prefix):
                return display
        return f"{utc_str}（{iana_id}）"
    except Exception:
        return "UTC+8 北京"
