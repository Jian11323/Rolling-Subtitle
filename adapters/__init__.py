#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源适配器模块
提供各种数据源的适配器实现
"""

from .base_adapter import BaseAdapter
from .fanstudio_adapter import FanStudioAdapter
from .fanstudio_http_adapter import FanStudioHttpAdapter
from .p2pquake_adapter import P2PQuakeAdapter
from .p2pquake_tsunami_adapter import P2PQuakeTsunamiAdapter
from .p2pquake_ws_adapter import P2PQuakeWebSocketAdapter
from .custom_adapter import CustomAdapter
from .wolfx_adapter import WolfxAdapter

__all__ = [
    'BaseAdapter',
    'FanStudioAdapter',
    'FanStudioHttpAdapter',
    'P2PQuakeAdapter',
    'P2PQuakeTsunamiAdapter',
    'P2PQuakeWebSocketAdapter',
    'CustomAdapter',
    'WolfxAdapter',
]
