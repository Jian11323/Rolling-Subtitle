#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据源适配器模块
提供各种数据源的适配器实现
"""

from .base_adapter import BaseAdapter
from .fanstudio_adapter import FanStudioAdapter
from .p2pquake_adapter import P2PQuakeAdapter
from .p2pquake_tsunami_adapter import P2PQuakeTsunamiAdapter
from .wolfx_adapter import WolfxAdapter
from .nied_adapter import NiedAdapter

__all__ = [
    'BaseAdapter',
    'FanStudioAdapter',
    'P2PQuakeAdapter',
    'P2PQuakeTsunamiAdapter',
    'WolfxAdapter',
    'NiedAdapter',
]
