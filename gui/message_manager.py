#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息管理模块
负责消息队列和缓冲区的管理
"""

import queue
import threading
import time
import re
from typing import Optional, List, Dict
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger()

# 数据源优先级定义（数字越小越靠前）
# 预警仍为 0（进 warning 缓冲）；速报轮播对齐 Jian /all 快照键序（见 api/all.php）
# /all：weather → nmefc-tsunami → cea… → … → jma-volcano → usgs-volcano → usgs-tsunami
# 台风不在 /all，放队尾

# Jian /all 全数据流顺序（短名 → 已映射为内部 source_type）
_ALL_STREAM_ORDER: List[str] = [
    # 灾害/气象（报告缓冲）
    "weatheralarm",  # weather
    "tsunami",  # nmefc-tsunami
    # 地震预警（warning 缓冲，priority=0）
    "cea",
    "cwa-eew",
    "jma",  # jma-eew
    "sa",
    "kma-eew",
    "early_est",  # early-est
    # 国内/地区速报
    "cenc",
    "ningxia",
    "yunnan",
    "shanxi",
    "beijing",
    "cwa",
    "cwa_tsunami",
    "jma_eq",  # jma
    "jma_tsunami",
    "hko",
    # 国际速报（与 /all 键序一致）
    "tmd",
    "mmd",
    "bmkg",
    "geonet",
    "usgs",
    "emsc",
    "gfz",
    "bcsf",
    "ingv",
    "usp",
    "nrcan",
    "afad",
    "ipma",
    "noa",
    "sed",
    "scsn",
    "ipgp",
    "infp",
    "isc",
    "knmi",
    "ncedc",
    "lmu",
    "kma",
    "koeri",
    "gsras",
    "csn",
    "phivolcs",
    "ssn",
    "ga",
    "igepn",
    "peru",
    "jma_volcano",
    "usgs_volcano",
    "usgs_tsunami",
]

# 不在 /all、但客户端会播的源：插在语义相邻位置，或队尾
_ALL_STREAM_EXTRAS: List[str] = [
    "海啸信息", "ntwc", "ptwc", "incois", "cat_tsunami", "eqsc_jma_tsunami",
    "cenc-ir", "wolfx_cenc", "eqsc_cenc", "eqsc_cenc_ir",
    "guangxi", "fujian", "sichuan", "shaanxi", "hubei",
    "eqsc_cwa",
    "p2pquake", "wolfx_jma_eqlist", "eqsc_jma_report", "p2pquake_tsunami",
    "eqsc_volcano",
    "eqsc_hko", "eqsc_usgs", "eqsc_emsc",
    "sgc", "cenais",
    "fssn", "fssn-cmt",
    "cmt_usgs", "cmt_emsc", "cmt_cenc", "cmt_ingv",
    # 台风：不在 /all，放最后
    "jian_typhoon", "eqsc_typhoon", "whews_typhoon",
]

_WARNING_SOURCES = frozenset({
    "cea", "cea-pr", "cwa-eew", "jma", "sa", "kma-eew", "early_est",
    "wolfx_jma_eew", "wolfx_sc_eew", "wolfx_fj_eew", "wolfx_cenc_eew",
    "wolfx_cq_eew", "wolfx_cwa_eew", "eqsc_jma_eew", "p2pquake_eew",
})


def _build_all_stream_priority_and_order() -> tuple:
    """由 /all 键序生成 SOURCE_PRIORITY 与 SOURCE_FIXED_ORDER。"""
    fixed: List[str] = []
    # 预警先列（缓冲分离，顺序仅作同组稳定）
    for s in (
        "cea", "cea-pr", "cwa-eew", "jma", "sa", "kma-eew", "early_est",
        "wolfx_jma_eew", "wolfx_sc_eew", "wolfx_fj_eew", "wolfx_cenc_eew",
        "wolfx_cq_eew", "wolfx_cwa_eew", "eqsc_jma_eew", "p2pquake_eew",
    ):
        if s not in fixed:
            fixed.append(s)

    # /all 正文序（跳过已在预警区的）
    for s in _ALL_STREAM_ORDER:
        if s not in fixed:
            fixed.append(s)

    # 邻近插入：cenc-ir 紧跟 cenc；省局跟在北京后；p2p 跟 jma_eq 等
    def _insert_after(anchor: str, item: str) -> None:
        if item in fixed:
            return
        if anchor in fixed:
            fixed.insert(fixed.index(anchor) + 1, item)
        else:
            fixed.append(item)

    _insert_after("tsunami", "海啸信息")
    _insert_after("海啸信息", "ntwc")
    _insert_after("ntwc", "ptwc")
    _insert_after("ptwc", "incois")
    _insert_after("incois", "cat_tsunami")
    _insert_after("jma_tsunami", "eqsc_jma_tsunami")
    _insert_after("jma_tsunami", "p2pquake_tsunami")
    _insert_after("cenc", "cenc-ir")
    _insert_after("cenc-ir", "wolfx_cenc")
    _insert_after("wolfx_cenc", "eqsc_cenc")
    _insert_after("eqsc_cenc", "eqsc_cenc_ir")
    _insert_after("beijing", "guangxi")
    _insert_after("guangxi", "fujian")
    _insert_after("fujian", "sichuan")
    _insert_after("sichuan", "shaanxi")
    _insert_after("shaanxi", "hubei")
    _insert_after("cwa", "eqsc_cwa")
    _insert_after("jma_eq", "p2pquake")
    _insert_after("p2pquake", "wolfx_jma_eqlist")
    _insert_after("wolfx_jma_eqlist", "eqsc_jma_report")
    _insert_after("hko", "eqsc_hko")
    _insert_after("usgs", "eqsc_usgs")
    _insert_after("emsc", "eqsc_emsc")
    _insert_after("usgs_volcano", "eqsc_volcano")
    _insert_after("phivolcs", "sgc")
    _insert_after("ga", "cenais")

    for s in _ALL_STREAM_EXTRAS:
        if s not in fixed:
            fixed.append(s)

    priority: Dict[str, int] = {}
    report_rank = 1
    for s in fixed:
        if s in _WARNING_SOURCES:
            priority[s] = 0
        else:
            priority[s] = report_rank
            report_rank += 1
    priority["default"] = 999
    return priority, fixed


SOURCE_PRIORITY, SOURCE_FIXED_ORDER = _build_all_stream_priority_and_order()
SOURCE_FIXED_ORDER_INDEX: Dict[str, int] = {
    source: idx for idx, source in enumerate(SOURCE_FIXED_ORDER)
}

# 淘汰缓冲时的优先级覆盖（越小越不易被挤掉）。台风播最后，但尽量留在缓冲里。
_EVICT_PRIORITY_OVERRIDE: Dict[str, int] = {
    "jian_typhoon": 20,
    "eqsc_typhoon": 20,
    "whews_typhoon": 20,
    "weatheralarm": 1,
    "tsunami": 2,
    "海啸信息": 2,
}


def get_source_priority(source: str) -> int:
    """
    获取数据源优先级
    
    Args:
        source: 数据源名称
        
    Returns:
        优先级数字（越小优先级越高）
    """
    return SOURCE_PRIORITY.get(source, SOURCE_PRIORITY['default'])


@dataclass
class MessageItem:
    """消息项"""
    text: str
    color: str
    timestamp: float
    message_type: str = "report"  # 消息类型：'warning'（预警）、'report'（速报）、'weather'（气象预警）
    source: str = ""
    image_path: Optional[str] = None  # 图片路径（用于气象预警）
    fallback_image_path: Optional[str] = None  # 保留字段；气象预警图标已改为仅 NMC 在线，不再使用本地回退
    event_id: str = ""  # 事件唯一ID，用于识别同一条地震事件的更新
    shock_time: Optional[str] = None  # 发震时间（用于预警消息有效期检查）
    parsed_data: Optional[Dict] = None  # 气象：颜色/图片热更新；预警：轮播时白字提示与烈度需保留解析字段
    first_displayed_at: Optional[float] = None  # 首次在窗口显示的时间（用于预警至少展示5分钟）
    image_after_text: bool = False  # 为 True 时图片绘制在文字之后（如 CMT 沙滩球在消息末尾）

    def __post_init__(self):
        """dataclass 初始化后补全 timestamp 默认值。"""
        if not hasattr(self, 'timestamp') or self.timestamp is None:
            self.timestamp = time.time()
    
    def inherit_display_meta_from(self, existing: "MessageItem") -> None:
        """更新报替换时保留首次上屏时间，避免展示计时被重置。"""
        if (
            existing is not None
            and existing.first_displayed_at is not None
            and self.first_displayed_at is None
        ):
            self.first_displayed_at = existing.first_displayed_at

    def is_same_event(self, other: 'MessageItem') -> bool:
        """
        判断是否是同一条地震事件的更新
        
        Args:
            other: 另一个消息项
            
        Returns:
            True表示是同一条事件，False表示不是
        """
        # 必须来自同一个数据源
        if self.source != other.source:
            return False
        
        # 如果有event_id，使用event_id匹配
        if self.event_id and other.event_id:
            return self.event_id == other.event_id
        
        # 如果没有event_id（如气象预警），使用文本内容的前50个字符和时间戳作为唯一标识
        # 这样可以避免完全相同的消息被重复添加
        if not self.event_id and not other.event_id:
            normalized_self = _normalize_warning_text(self.text)
            normalized_other = _normalize_warning_text(other.text)
            if normalized_self and normalized_self == normalized_other:
                return True
            
            if self.shock_time and other.shock_time and self.shock_time == other.shock_time:
                return True
            
            if normalized_self and normalized_other:
                time_diff = abs(self.timestamp - other.timestamp)
                if time_diff < 30.0 and normalized_self[:80] == normalized_other[:80]:
                    return True
        
        return False


class MessageQueue:
    """线程安全的消息队列"""
    
    def __init__(self, maxsize: int = 100):
        """
        初始化消息队列
        
        Args:
            maxsize: 队列最大容量
        """
        self._maxsize = max(10, int(maxsize or 10))
        self.queue = queue.Queue(maxsize=self._maxsize)
        self._lock = threading.Lock()

    @property
    def maxsize(self) -> int:
        return self._maxsize

    def rebuild_with_maxsize(self, new_max: int) -> "MessageQueue":
        """按新容量重建队列，尽量保留已有消息（从新到旧截断）。"""
        new_max = max(10, int(new_max or 10))
        if new_max == self._maxsize:
            return self
        kept: List[MessageItem] = []
        try:
            while True:
                kept.append(self.queue.get_nowait())
        except queue.Empty:
            pass
        if len(kept) > new_max:
            kept = kept[-new_max:]
        rebuilt = MessageQueue(maxsize=new_max)
        for item in kept:
            rebuilt.put(item, block=False)
        return rebuilt
        
    def put(self, item: MessageItem, block: bool = True, timeout: Optional[float] = None) -> bool:
        """
        添加消息
        
        Args:
            item: 消息项
            block: 是否阻塞
            timeout: 超时时间
            
        Returns:
            bool: 是否成功添加
        """
        try:
            self.queue.put(item, block=block, timeout=timeout)
            return True
        except queue.Full:
            try:
                # 优先保留更高优先级消息，低优先级消息先被丢弃
                oldest_item = None
                with self.queue.mutex:
                    if len(self.queue.queue) > 0:
                        oldest_item = self.queue.queue[0]
                if isinstance(oldest_item, MessageItem) and isinstance(item, MessageItem):
                    oldest_priority = get_source_priority(oldest_item.source)
                    incoming_priority = get_source_priority(item.source)
                    if incoming_priority >= oldest_priority:
                        logger.warning("消息队列已满，丢弃新消息")
                        return False
                logger.warning("消息队列已满，丢弃最旧低优先级消息")
                self.queue.get_nowait()  # 移除最旧消息
                self.queue.put(item, block=False)  # 添加新消息
                return True
            except queue.Empty:
                return False
    
    def get(self, block: bool = True, timeout: Optional[float] = None) -> Optional[MessageItem]:
        """
        获取消息
        
        Args:
            block: 是否阻塞
            timeout: 超时时间
            
        Returns:
            MessageItem或None
        """
        try:
            return self.queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None
    
    def get_all(self) -> List[MessageItem]:
        """获取所有消息"""
        messages = []
        with self._lock:
            while not self.queue.empty():
                try:
                    messages.append(self.queue.get_nowait())
                except queue.Empty:
                    break
        return messages
    
    def clear(self):
        """清空队列"""
        with self._lock:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break
    
    def qsize(self) -> int:
        """获取队列大小"""
        return self.queue.qsize()


class MessageBuffer:
    """消息缓冲区，用于循环显示消息，支持按优先级排序和轮播"""
    
    def __init__(self, max_size: int = 40, use_priority: bool = True):
        """
        初始化消息缓冲区
        
        Args:
            max_size: 缓冲区最大容量
            use_priority: 是否使用优先级排序
        """
        self.buffer: List[MessageItem] = []
        self.max_size = max_size
        self.current_index = 0
        self.use_priority = use_priority
        self._lock = threading.Lock()
        self._priority_group_index: Dict[int, int] = {}
        # 用于记录消息的添加顺序，确保相同优先级内的消息按添加顺序排序
        self._add_order_counter = 0
        # 记录每个消息的添加顺序（使用消息对象的内存地址作为键）
        self._message_add_order: Dict[int, int] = {}
        # 记录当前正在显示的消息ID，用于排序后重新定位
        self._current_displaying_msg_id: Optional[int] = None
        # 本轮已播过的 source：中途插入的更高优先级（如气象）不会被跳到下一轮才播
        self._shown_sources_this_round: set = set()

    def set_max_size(self, new_max: int) -> None:
        """热调整缓冲上限，并剔除超出容量的低优先级项。"""
        new_max = max(4, int(new_max or 4))
        with self._lock:
            self.max_size = new_max
            while len(self.buffer) > self.max_size:
                self._remove_lowest_priority_message()
            if self.buffer and self.current_index >= len(self.buffer):
                self.current_index = 0
    
    def add(self, message: MessageItem):
        """
        添加消息到缓冲区，如果启用优先级，会自动排序
        
        Args:
            message: 消息项
        """
        with self._lock:
            # 限制缓冲区大小
            if len(self.buffer) >= self.max_size:
                self._remove_lowest_priority_message()
            
            # 记录消息的添加顺序
            msg_id = id(message)
            self._add_order_counter += 1
            self._message_add_order[msg_id] = self._add_order_counter
            
            self.buffer.append(message)
            
            # 如果启用优先级，按优先级和添加顺序排序
            if self.use_priority:
                self._sort_by_priority()
    
    def replace_or_add(self, message: MessageItem) -> bool:
        """
        替换或添加消息到缓冲区
        如果找到同一条事件的消息（通过event_id和source匹配），则替换；否则添加
        
        Args:
            message: 消息项
            
        Returns:
            True表示替换了已有消息，False表示添加了新消息
        """
        with self._lock:
            # 查找是否有同一条事件的消息
            for i, existing_msg in enumerate(self.buffer):
                if message.is_same_event(existing_msg):
                    # 如果内容完全一致，则认为是重复更新，忽略它，避免重复轮播相同内容
                    if message.text == existing_msg.text and message.image_path == existing_msg.image_path:
                        logger.debug(f"忽略重复更新消息: {message.source} / {message.event_id}")
                        return False  # 内容完全一致则不重复入缓冲
                    # 找到同一条事件，替换
                    message.inherit_display_meta_from(existing_msg)
                    old_msg_id = id(existing_msg)
                    new_msg_id = id(message)
                    # 保持原有的添加顺序
                    if old_msg_id in self._message_add_order:
                        self._message_add_order[new_msg_id] = self._message_add_order[old_msg_id]
                        del self._message_add_order[old_msg_id]
                    else:
                        # 如果没有原有顺序，使用当前计数器
                        self._add_order_counter += 1
                        self._message_add_order[new_msg_id] = self._add_order_counter
                    
                    self.buffer[i] = message
                    self._retarget_displaying_id_if_needed(old_msg_id, new_msg_id)
                    # 如果启用优先级，重新排序
                    if self.use_priority:
                        self._sort_by_priority()
                    return True
            
            # 没有找到同一条事件，添加新消息
            if len(self.buffer) >= self.max_size:
                self._remove_lowest_priority_message()
            
            # 记录消息的添加顺序
            msg_id = id(message)
            self._add_order_counter += 1
            self._message_add_order[msg_id] = self._add_order_counter
            
            self.buffer.append(message)
            
            # 如果启用优先级，按优先级和添加顺序排序
            if self.use_priority:
                self._sort_by_priority()
            
            return False
    
    def batch_replace_or_add(self, messages: List[MessageItem]) -> List[bool]:
        """
        批量替换或添加消息到缓冲区
        如果找到同一条事件的消息（通过event_id和source匹配），则替换；否则添加
        批量操作完成后统一排序，确保顺序稳定
        同时处理批量消息列表中的重复项
        
        Args:
            messages: 消息项列表
            
        Returns:
            结果列表，True表示替换了已有消息，False表示添加了新消息
        """
        results = []
        with self._lock:
            # 先对批量消息列表去重（避免同一条消息在列表中重复）
            seen_in_batch = {}  # 用于记录本次批量中已处理的消息 {msg_key: unique_index}
            unique_messages = []
            message_index_map = []  # 记录原始消息索引到去重后消息索引的映射
            
            for idx, message in enumerate(messages):
                # 生成唯一标识（event_id + source）
                msg_key = (message.event_id, message.source)
                if msg_key not in seen_in_batch:
                    unique_index = len(unique_messages)
                    seen_in_batch[msg_key] = unique_index
                    unique_messages.append(message)
                    message_index_map.append(unique_index)
                else:
                    # 跳过重复的消息，记录为已处理（使用之前消息的索引）
                    logger.debug(f"跳过批量消息列表中的重复消息: {message.source} - {message.event_id}")
                    message_index_map.append(seen_in_batch[msg_key])
            
            # 处理去重后的消息
            unique_results = []
            for message in unique_messages:
                replaced = False
                # 查找是否有同一条事件的消息（在缓冲区中）
                for i, existing_msg in enumerate(self.buffer):
                    if message.is_same_event(existing_msg):
                        # 如果内容完全一致，则认为是重复更新，忽略它，避免重复轮播相同内容
                        if message.text == existing_msg.text and message.image_path == existing_msg.image_path:
                            logger.debug(f"忽略重复更新消息: {message.source} / {message.event_id}")
                            unique_results.append(False)
                            replaced = True
                            break
                        # 找到同一条事件，替换
                        message.inherit_display_meta_from(existing_msg)
                        old_msg_id = id(existing_msg)
                        new_msg_id = id(message)
                        # 保持原有的添加顺序
                        if old_msg_id in self._message_add_order:
                            self._message_add_order[new_msg_id] = self._message_add_order[old_msg_id]
                            del self._message_add_order[old_msg_id]
                        else:
                            # 如果没有原有顺序，使用当前计数器
                            self._add_order_counter += 1
                            self._message_add_order[new_msg_id] = self._add_order_counter
                        
                        self.buffer[i] = message
                        self._retarget_displaying_id_if_needed(old_msg_id, new_msg_id)
                        unique_results.append(True)
                        replaced = True
                        break
                
                if not replaced:
                    # 没有找到同一条事件，添加新消息
                    if len(self.buffer) >= self.max_size:
                        self._remove_lowest_priority_message()
                    
                    # 记录消息的添加顺序
                    msg_id = id(message)
                    self._add_order_counter += 1
                    self._message_add_order[msg_id] = self._add_order_counter
                    
                    self.buffer.append(message)
                    unique_results.append(False)
            
            # 根据映射关系构建结果列表（保持与输入消息列表长度一致）
            results = [unique_results[message_index_map[i]] for i in range(len(messages))]
            
            # 批量操作完成后统一排序
            if self.use_priority:
                self._sort_by_priority()
        
        return results
    
    def find_by_event_id(self, event_id: str, source: str) -> Optional[MessageItem]:
        """
        根据event_id和source查找消息
        
        Args:
            event_id: 事件ID
            source: 数据源名称
            
        Returns:
            找到的消息项，如果未找到返回None
        """
        with self._lock:
            for msg in self.buffer:
                if msg.event_id == event_id and msg.source == source:
                    return msg
            return None
    
    def replace_by_source(self, message: MessageItem) -> bool:
        """
        按数据源替换消息（每个数据源只保留一条最新消息）
        如果找到相同数据源的消息，则替换；否则添加
        静默替换，不打断当前轮播顺序
        
        Args:
            message: 消息项
            
        Returns:
            True表示替换了已有消息，False表示添加了新消息
        """
        with self._lock:
            # 查找是否有相同数据源的消息
            for i, existing_msg in enumerate(self.buffer):
                if message.source == existing_msg.source:
                    # 如果内容完全一致，则认为是重复更新，忽略它，避免重复轮播相同内容
                    if message.text == existing_msg.text and message.image_path == existing_msg.image_path:
                        logger.debug(f"忽略重复更新消息: {message.source}")
                        return False
                    # 找到相同数据源，替换
                    message.inherit_display_meta_from(existing_msg)
                    old_msg_id = id(existing_msg)
                    new_msg_id = id(message)
                    # 保持原有的添加顺序，确保轮播顺序不变
                    if old_msg_id in self._message_add_order:
                        self._message_add_order[new_msg_id] = self._message_add_order[old_msg_id]
                        del self._message_add_order[old_msg_id]
                    else:
                        # 如果没有原有顺序，使用当前计数器
                        self._add_order_counter += 1
                        self._message_add_order[new_msg_id] = self._add_order_counter
                    
                    # 静默替换：直接替换缓冲区中的消息，不改变位置
                    self.buffer[i] = message
                    self._retarget_displaying_id_if_needed(old_msg_id, new_msg_id)
                    # 如果启用优先级，重新排序（但保持当前显示的消息位置）
                    if self.use_priority:
                        self._sort_by_priority()
                    return True
            
            # 没有找到相同数据源，添加新消息
            if len(self.buffer) >= self.max_size:
                self._remove_lowest_priority_message()
            
            # 记录消息的添加顺序
            msg_id = id(message)
            self._add_order_counter += 1
            self._message_add_order[msg_id] = self._add_order_counter
            
            self.buffer.append(message)
            
            # 如果启用优先级，按优先级和添加顺序排序
            if self.use_priority:
                self._sort_by_priority()
            
            return False
    
    def batch_replace_by_source(self, messages: List[MessageItem]) -> List[bool]:
        """
        批量按数据源替换消息（每个数据源只保留一条最新消息）
        批量操作完成后统一排序，确保顺序稳定
        同时处理批量消息列表中的重复数据源（只保留最新的）
        
        Args:
            messages: 消息项列表
            
        Returns:
            结果列表，True表示替换了已有消息，False表示添加了新消息
        """
        results = []
        with self._lock:
            # 先对批量消息列表按数据源去重（每个数据源只保留最新的消息）
            source_to_latest_msg = {}  # {source: message}
            message_source_map = []  # 记录原始消息索引到数据源的映射
            
            for idx, message in enumerate(messages):
                source = message.source
                # 如果该数据源已有消息，比较时间戳，保留最新的
                if source in source_to_latest_msg:
                    existing_msg = source_to_latest_msg[source]
                    # 确定性规则：先比时间戳，再比 event_id，再比文本，避免同时间戳顺序抖动
                    new_rank = (
                        float(message.timestamp or 0.0),
                        str(message.event_id or ''),
                        str(message.text or ''),
                    )
                    old_rank = (
                        float(existing_msg.timestamp or 0.0),
                        str(existing_msg.event_id or ''),
                        str(existing_msg.text or ''),
                    )
                    if new_rank > old_rank:
                        source_to_latest_msg[source] = message
                    message_source_map.append(source)
                else:
                    source_to_latest_msg[source] = message
                    message_source_map.append(source)
            
            # 处理去重后的消息（每个数据源一条）
            unique_messages = list(source_to_latest_msg.values())
            unique_results = []
            
            for message in unique_messages:
                replaced = False
                # 查找是否有相同数据源的消息（在缓冲区中）
                for i, existing_msg in enumerate(self.buffer):
                    if message.source == existing_msg.source:
                        # 如果内容完全一致，则认为是重复更新，忽略它，避免重复轮播相同内容
                        if message.text == existing_msg.text and message.image_path == existing_msg.image_path:
                            logger.debug(f"忽略重复更新消息: {message.source}")
                            unique_results.append(False)
                            replaced = True
                            break
                        # 找到相同数据源，替换
                        message.inherit_display_meta_from(existing_msg)
                        old_msg_id = id(existing_msg)
                        new_msg_id = id(message)
                        # 保持原有的添加顺序
                        if old_msg_id in self._message_add_order:
                            self._message_add_order[new_msg_id] = self._message_add_order[old_msg_id]
                            del self._message_add_order[old_msg_id]
                        else:
                            # 如果没有原有顺序，使用当前计数器
                            self._add_order_counter += 1
                            self._message_add_order[new_msg_id] = self._add_order_counter
                        
                        # 对于气象预警消息，如果新消息没有图片路径但旧消息有，保留旧消息的图片路径
                        # 这样可以避免图片路径丢失
                        if (message.message_type == 'weather' and 
                            not message.image_path and 
                            existing_msg.image_path):
                            message.image_path = existing_msg.image_path
                            logger.debug(f"保留旧消息的图片路径: {message.source} -> {existing_msg.image_path}")
                        
                        # 静默替换：直接替换缓冲区中的消息
                        self.buffer[i] = message
                        self._retarget_displaying_id_if_needed(old_msg_id, new_msg_id)
                        unique_results.append(True)
                        replaced = True
                        break
                
                if not replaced:
                    # 没有找到相同数据源，添加新消息
                    if len(self.buffer) >= self.max_size:
                        self._remove_lowest_priority_message()
                    
                    # 记录消息的添加顺序
                    msg_id = id(message)
                    self._add_order_counter += 1
                    self._message_add_order[msg_id] = self._add_order_counter
                    
                    self.buffer.append(message)
                    unique_results.append(False)
            
            # 根据映射关系构建结果列表（保持与输入消息列表长度一致）
            # 对于同一数据源的多个消息，结果相同
            source_to_result = {msg.source: unique_results[i] for i, msg in enumerate(unique_messages)}
            results = [source_to_result[message_source_map[i]] for i in range(len(messages))]
            
            # 批量操作完成后统一排序
            if self.use_priority:
                self._sort_by_priority()
        
        return results
    
    def find_by_source(self, source: str) -> Optional[MessageItem]:
        """
        根据数据源查找消息
        
        Args:
            source: 数据源名称
            
        Returns:
            找到的消息项，如果未找到返回None
        """
        with self._lock:
            for msg in self.buffer:
                if msg.source == source:
                    return msg
            return None
    
    def remove_by_event_id(self, event_id: str, source: str) -> bool:
        """
        根据event_id和source移除消息
        
        Args:
            event_id: 事件ID
            source: 数据源名称
            
        Returns:
            True表示成功移除，False表示未找到
        """
        with self._lock:
            for i, msg in enumerate(self.buffer):
                if msg.event_id == event_id and msg.source == source:
                    # 移除消息
                    removed_msg = self.buffer.pop(i)
                    # 清理被移除消息的添加顺序记录
                    msg_id = id(removed_msg)
                    if msg_id in self._message_add_order:
                        del self._message_add_order[msg_id]
                    
                    # 调整当前索引
                    if self.current_index > i:
                        self.current_index -= 1
                    elif self.current_index == i:
                        # 如果移除的是当前显示的消息，重置索引
                        if self.current_index >= len(self.buffer):
                            self.current_index = 0
                        self._current_displaying_msg_id = None
                    
                    # 如果启用优先级，重新排序
                    if self.use_priority:
                        self._sort_by_priority()
                    
                    logger.info(f"已从缓冲区移除消息: {source} - {event_id}")
                    return True
            return False
    
    def _retarget_displaying_id_if_needed(self, old_msg_id: int, new_msg_id: int) -> None:
        """buffer 中原地替换 MessageItem 后，将当前展示指针从旧对象 id 指向新对象 id。"""
        if self._current_displaying_msg_id == old_msg_id:
            self._current_displaying_msg_id = new_msg_id

    def _remove_lowest_priority_message(self) -> Optional[MessageItem]:
        """从缓冲区中移除最低优先级、最旧的消息。"""
        if not self.buffer:
            return None

        def removal_key(msg: MessageItem) -> tuple:
            """缓冲区溢出时的移除排序键：低优先级、较旧的消息优先淘汰。"""
            priority = _EVICT_PRIORITY_OVERRIDE.get(
                msg.source, get_source_priority(msg.source)
            )
            add_order = self._message_add_order.get(id(msg), float('inf'))
            # 先按优先级降序，低优先级先被移除；同优先级内先移除最旧消息
            return (-priority, add_order)

        remove_index = min(range(len(self.buffer)), key=lambda i: removal_key(self.buffer[i]))
        removed_msg = self.buffer.pop(remove_index)
        msg_id = id(removed_msg)
        if msg_id in self._message_add_order:
            del self._message_add_order[msg_id]
        # 被挤出缓冲后允许本轮稍后再播同 source 的新条目
        if removed_msg.source:
            self._shown_sources_this_round.discard(removed_msg.source)

        if self.current_index > remove_index:
            self.current_index -= 1
        elif self.current_index == remove_index:
            self._current_displaying_msg_id = None
            if self.current_index >= len(self.buffer):
                self.current_index = 0

        return removed_msg

    def _sort_by_priority(self):
        """按优先级与固定 source 顺序排序缓冲区"""
        # 保存当前正在显示的消息ID
        current_msg_id = self._current_displaying_msg_id
        
        def sort_key(msg: MessageItem) -> tuple:
            """缓冲区排序键：(优先级, 固定 source 顺序, 添加顺序)。"""
            # 排序键：(优先级, 固定source顺序, 添加顺序)
            # 优先级越小越靠前；同优先级内按固定 source 次序；同 source 才回退添加顺序
            priority = get_source_priority(msg.source)
            source_order = SOURCE_FIXED_ORDER_INDEX.get(msg.source, len(SOURCE_FIXED_ORDER_INDEX) + 999)
            msg_id = id(msg)
            add_order = self._message_add_order.get(msg_id, float('inf'))  # 如果没有记录，放在最后
            return (priority, source_order, add_order)
        
        # 排序前保存当前消息的引用（如果存在）
        current_msg = None
        if current_msg_id is not None:
            for msg in self.buffer:
                if id(msg) == current_msg_id:
                    current_msg = msg
                    break
        
        # 执行排序
        self.buffer.sort(key=sort_key)
        
        # 排序后，找到当前显示消息的新位置并更新索引
        if current_msg is not None:
            for i, msg in enumerate(self.buffer):
                if id(msg) == id(current_msg):
                    self.current_index = i
                    logger.debug(f"排序后更新索引: 当前消息位置={i}, 数据源={msg.source}")
                    return
        
        # 如果当前显示的消息不在缓冲区中（被移除了），重置索引为0
        # 这样下次轮播会从第一条消息开始
        if self.current_index >= len(self.buffer) or self.current_index < 0:
            self.current_index = 0
            logger.debug(f"排序后重置索引为0（当前消息不在缓冲区中）")
    
    def get_current(self) -> Optional[MessageItem]:
        """获取当前消息"""
        with self._lock:
            if not self.buffer:
                self._current_displaying_msg_id = None
                return None
            
            # 如果当前显示的消息ID存在，尝试找到它的位置
            if self._current_displaying_msg_id is not None:
                for i, msg in enumerate(self.buffer):
                    if id(msg) == self._current_displaying_msg_id:
                        self.current_index = i
                        return msg
            
            # 如果没找到，使用索引获取（确保索引有效）
            if self.current_index < 0 or self.current_index >= len(self.buffer):
                self.current_index = 0
            
            msg = self.buffer[self.current_index]
            # 更新当前正在显示的消息ID
            self._current_displaying_msg_id = id(msg)
            return msg
    
    def get_next(self) -> Optional[MessageItem]:
        """
        获取下一条消息（按优先级轮播）
        
        轮播策略：
        1. 如果启用优先级，按优先级组轮播（先轮播完高优先级组，再轮播低优先级组）
        2. 如果未启用优先级，简单循环轮播
        """
        with self._lock:
            if not self.buffer:
                self._current_displaying_msg_id = None
                return None
            
            if not self.use_priority:  # 关闭优先级时按队列顺序循环
                # 简单循环轮播
                self.current_index = (self.current_index + 1) % len(self.buffer)
                msg = self.buffer[self.current_index]
                self._current_displaying_msg_id = id(msg)
                return msg
            
            # 按优先级轮播
            return self._get_next_by_priority()

    def mark_source_shown(self, source: str) -> None:
        """标记某 source 已在本轮播过（首条上屏、同事件待更新重显时调用）。"""
        if not source:
            return
        with self._lock:
            self._shown_sources_this_round.add(source)

    def begin_round_with(self, message: MessageItem) -> None:
        """从预警切到速报等场景：新开一轮并从该消息起算已播。"""
        with self._lock:
            self._shown_sources_this_round.clear()
            if message is not None and message.source:
                self._shown_sources_this_round.add(message.source)
            if message is not None:
                self._current_displaying_msg_id = id(message)
                for i, msg in enumerate(self.buffer):
                    if id(msg) == id(message):
                        self.current_index = i
                        break

    def get_next_excluding_sources(self, exclude_sources: List[str]) -> Optional[MessageItem]:
        """
        获取下一条消息（按优先级轮播），但跳过 source 在 exclude_sources 中的消息。
        若有非排除消息则返回其中下一条；若全部被排除则返回第一条（用于回退到如自定义文本）。
        """
        with self._lock:
            if not self.buffer:
                self._current_displaying_msg_id = None
                return None
            exclude_set = set(exclude_sources)
            if self.use_priority:
                self._sort_by_priority()
                prev_source = "None"
                if self._current_displaying_msg_id is not None:
                    for msg in self.buffer:
                        if id(msg) == self._current_displaying_msg_id:
                            prev_source = msg.source
                            break
                for i, msg in enumerate(self.buffer):
                    if msg.source in exclude_set:
                        continue
                    if msg.source in self._shown_sources_this_round:
                        continue
                    self.current_index = i
                    self._current_displaying_msg_id = id(msg)
                    self._shown_sources_this_round.add(msg.source)
                    logger.debug(
                        f"轮播顺序: {prev_source}(p={get_source_priority(prev_source) if prev_source != 'None' else -1}) -> "
                        f"{msg.source}(p={get_source_priority(msg.source)}, idx={i})"
                    )
                    return msg
                # 本轮非排除源均已播完：开新一轮
                self._shown_sources_this_round.clear()
                logger.debug("完成一轮轮播，从气象预警开始重复轮播")
                for i, msg in enumerate(self.buffer):
                    if msg.source in exclude_set:
                        continue
                    self.current_index = i
                    self._current_displaying_msg_id = id(msg)
                    self._shown_sources_this_round.add(msg.source)
                    return msg
            first_excluded_msg = None
            for msg in self.buffer:
                if msg.source not in exclude_set:
                    for i, m in enumerate(self.buffer):
                        if id(m) == id(msg):
                            self.current_index = i
                            self._current_displaying_msg_id = id(m)
                            break
                    return msg
                if first_excluded_msg is None:
                    first_excluded_msg = msg
            if first_excluded_msg is not None:
                for i, m in enumerate(self.buffer):
                    if id(m) == id(first_excluded_msg):
                        self.current_index = i
                        self._current_displaying_msg_id = id(m)
                        break
                return first_excluded_msg
            self._current_displaying_msg_id = None
            return None

    def _get_next_by_priority(self) -> Optional[MessageItem]:
        """
        按优先级轮播消息。

        策略：缓冲区按优先级排序后，取「本轮尚未播过」的第一条。
        这样中途插入的更高优先级（如气象预警）会在当前条滚完后立刻插入播放，
        而不会被跳到整轮结束后才出现。
        本轮全部播完后清空已播集合，从队首（通常为气象）重新开始。
        """
        if not self.buffer:
            self._current_displaying_msg_id = None
            return None
        
        self._sort_by_priority()

        prev_source = "None"
        current_msg_index = -1
        if self._current_displaying_msg_id is not None:
            for i, msg in enumerate(self.buffer):
                if id(msg) == self._current_displaying_msg_id:
                    current_msg_index = i
                    prev_source = msg.source
                    break

        # 本轮尚未播过的第一条（按已排序缓冲）
        for i, msg in enumerate(self.buffer):
            if msg.source in self._shown_sources_this_round:
                continue
            self.current_index = i
            self._current_displaying_msg_id = id(msg)
            self._shown_sources_this_round.add(msg.source)
            priority = get_source_priority(msg.source)
            prev_priority = get_source_priority(prev_source) if prev_source != "None" else -1
            logger.debug(
                f"轮播顺序: {prev_source}(p={prev_priority}, idx={current_msg_index}) -> "
                f"{msg.source}(p={priority}, idx={i})"
            )
            return msg

        # 全部播完：新开一轮
        self._shown_sources_this_round.clear()
        logger.debug("完成一轮轮播，从气象预警开始重复轮播")
        msg = self.buffer[0]
        self.current_index = 0
        self._current_displaying_msg_id = id(msg)
        self._shown_sources_this_round.add(msg.source)
        priority = get_source_priority(msg.source)
        prev_priority = get_source_priority(prev_source) if prev_source != "None" else -1
        logger.debug(
            f"轮播顺序: {prev_source}(p={prev_priority}, idx={current_msg_index}) -> "
            f"{msg.source}(p={priority}, idx=0)"
        )
        return msg
    
    def size(self) -> int:
        """获取缓冲区大小"""
        with self._lock:
            return len(self.buffer)

    def remove_where(self, predicate) -> int:
        """
        按条件移除缓冲消息。

        Args:
            predicate: 接受 MessageItem，返回 True 表示应移除

        Returns:
            移除条数
        """
        with self._lock:
            if not self.buffer:
                return 0
            kept: List[MessageItem] = []
            removed = 0
            for msg in self.buffer:
                if predicate(msg):
                    msg_id = id(msg)
                    self._message_add_order.pop(msg_id, None)
                    if self._current_displaying_msg_id == msg_id:
                        self._current_displaying_msg_id = None
                    if msg.source:
                        self._shown_sources_this_round.discard(msg.source)
                    removed += 1
                    continue
                kept.append(msg)
            if removed:
                self.buffer = kept
                if self.current_index >= len(self.buffer):
                    self.current_index = max(0, len(self.buffer) - 1)
                if self._current_displaying_msg_id is not None:
                    for i, msg in enumerate(self.buffer):
                        if id(msg) == self._current_displaying_msg_id:
                            self.current_index = i
                            break
                    else:
                        self._current_displaying_msg_id = None
                        self.current_index = 0
            return removed
    
    def clear(self):
        """清空缓冲区"""
        with self._lock:
            self.buffer.clear()
            self.current_index = 0
            self._priority_group_index.clear()
            self._message_add_order.clear()
            self._add_order_counter = 0
            self._current_displaying_msg_id = None
            self._shown_sources_this_round.clear()


def _normalize_warning_text(text: str) -> str:
    """
    归一化预警文本用于比较：
    - 去掉报次标记（如“第3报”“最终报”）
    - 去掉空白和常见标点
    """
    if not text:
        return ""
    
    normalized = text
    normalized = re.sub(r'第\s*\d+\s*报', '', normalized)
    normalized = normalized.replace('最终报', '')
    normalized = normalized.replace('Final Report', '')
    normalized = normalized.replace('final report', '')
    normalized = normalized.replace('FINAL REPORT', '')
    normalized = re.sub(r'\s+', '', normalized)
    normalized = normalized.replace(',', '').replace('，', '')
    normalized = normalized.replace('。', '').replace('.', '')
    return normalized.strip()