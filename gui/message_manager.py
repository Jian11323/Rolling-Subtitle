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

# 数据源优先级定义（数字越小优先级越高）
# 注意：这是速报消息的优先级，预警消息（除气象预警外）永远优先于速报
# 速报播放顺序：气象预警、cenc, ningxia, guangxi, shanxi, beijing, cwa, p2pquake, hko, usgs, emsc, bcsf, gfz, usp, kma, fssn
SOURCE_PRIORITY: Dict[str, int] = {
    # 气象预警 - 优先级最高（速报中）
    'weatheralarm': 1,
    
    # 速报数据源 - 按指定顺序设置优先级
    'cenc': 2,
    'ningxia': 3,
    'guangxi': 4,
    'shanxi': 5,
    'beijing': 6,
           'cwa': 7,
           'p2pquake': 8,  # P2P日本气象厅地震情报
           'p2pquake_tsunami': 8,  # P2P日本气象厅海啸预报
           'hko': 9,
           'usgs': 10,
           'emsc': 11,
           'bcsf': 13,
           'gfz': 14,
           'usp': 15,
           'kma': 16,
           'fssn': 17,
    
    # 地震预警数据源 - 保持高优先级（优先级0，最高）
    'cea': 0,
    'cea-pr': 0,
    'sichuan': 0,
    'cwa-eew': 0,
    'jma': 0,
    'sa': 0,
    'kma-eew': 0,
    # Wolfx 预警/速报
    'wolfx_sc_eew': 0, 'wolfx_jma_eew': 0, 'wolfx_fj_eew': 0,
    'wolfx_cenc_eew': 0, 'wolfx_cwa_eew': 0, 'wolfx_all_eew': 0,
    'wolfx_cenc_eqlist': 8, 'wolfx_jma_eqlist': 8,
    # NIED 预警
    'nied': 0,
    # 其他数据源
    'fanstudio': 99, # Fan Studio
    
    # 默认优先级（未知数据源）
    'default': 99,
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
    event_id: str = ""  # 事件唯一ID，用于识别同一条地震事件的更新
    shock_time: Optional[str] = None  # 发震时间（用于预警消息有效期检查）
    parsed_data: Optional[Dict] = None  # 解析后的数据字典（用于气象预警颜色计算和热修改）
    first_displayed_at: Optional[float] = None  # 首次在窗口显示的时间（用于预警至少展示5分钟）
    
    def __post_init__(self):
        if not hasattr(self, 'timestamp') or self.timestamp is None:
            self.timestamp = time.time()
    
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
        self.queue = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        
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
            logger.warning("消息队列已满，丢弃最旧消息")
            try:
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
    
    def __init__(self, max_size: int = 10, use_priority: bool = True):
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
        # 用于优先级轮播：记录每个优先级组的当前索引
        self._priority_group_index: Dict[int, int] = {}
        # 用于记录消息的添加顺序，确保相同优先级内的消息按添加顺序排序
        self._add_order_counter = 0
        # 记录每个消息的添加顺序（使用消息对象的内存地址作为键）
        self._message_add_order: Dict[int, int] = {}
        # 记录当前正在显示的消息ID，用于排序后重新定位
        self._current_displaying_msg_id: Optional[int] = None
    
    def add(self, message: MessageItem):
        """
        添加消息到缓冲区，如果启用优先级，会自动排序
        
        Args:
            message: 消息项
        """
        with self._lock:
            # 限制缓冲区大小
            if len(self.buffer) >= self.max_size:
                removed_msg = self.buffer.pop(0)
                # 清理被移除消息的添加顺序记录
                msg_id = id(removed_msg)
                if msg_id in self._message_add_order:
                    del self._message_add_order[msg_id]
                # 调整当前索引
                if self.current_index > 0:
                    self.current_index -= 1
            
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
                    # 找到同一条事件，替换
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
                    # 如果启用优先级，重新排序
                    if self.use_priority:
                        self._sort_by_priority()
                    return True
            
            # 没有找到同一条事件，添加新消息
            if len(self.buffer) >= self.max_size:
                removed_msg = self.buffer.pop(0)
                # 清理被移除消息的添加顺序记录
                msg_id = id(removed_msg)
                if msg_id in self._message_add_order:
                    del self._message_add_order[msg_id]
                # 调整当前索引
                if self.current_index > 0:
                    self.current_index -= 1
            
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
                        # 找到同一条事件，替换
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
                        unique_results.append(True)
                        replaced = True
                        break
                
                if not replaced:
                    # 没有找到同一条事件，添加新消息
                    if len(self.buffer) >= self.max_size:
                        removed_msg = self.buffer.pop(0)
                        # 清理被移除消息的添加顺序记录
                        msg_id = id(removed_msg)
                        if msg_id in self._message_add_order:
                            del self._message_add_order[msg_id]
                        # 调整当前索引
                        if self.current_index > 0:
                            self.current_index -= 1
                    
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
                    # 找到相同数据源，替换
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
                    # 如果启用优先级，重新排序（但保持当前显示的消息位置）
                    if self.use_priority:
                        self._sort_by_priority()
                    return True
            
            # 没有找到相同数据源，添加新消息
            if len(self.buffer) >= self.max_size:
                removed_msg = self.buffer.pop(0)
                # 清理被移除消息的添加顺序记录
                msg_id = id(removed_msg)
                if msg_id in self._message_add_order:
                    del self._message_add_order[msg_id]
                # 调整当前索引
                if self.current_index > 0:
                    self.current_index -= 1
            
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
                    if message.timestamp > existing_msg.timestamp:
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
                        # 找到相同数据源，替换
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
                        unique_results.append(True)
                        replaced = True
                        break
                
                if not replaced:
                    # 没有找到相同数据源，添加新消息
                    if len(self.buffer) >= self.max_size:
                        removed_msg = self.buffer.pop(0)
                        # 清理被移除消息的添加顺序记录
                        msg_id = id(removed_msg)
                        if msg_id in self._message_add_order:
                            del self._message_add_order[msg_id]
                        # 调整当前索引
                        if self.current_index > 0:
                            self.current_index -= 1
                    
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
    
    def _sort_by_priority(self):
        """按优先级和添加顺序排序缓冲区"""
        # 保存当前正在显示的消息ID
        current_msg_id = self._current_displaying_msg_id
        
        def sort_key(msg: MessageItem) -> tuple:
            # 排序键：(优先级, 添加顺序)
            # 优先级越小越靠前，相同优先级内按添加顺序（FIFO）排序
            priority = get_source_priority(msg.source)
            msg_id = id(msg)
            add_order = self._message_add_order.get(msg_id, float('inf'))  # 如果没有记录，放在最后
            return (priority, add_order)
        
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
            
            if not self.use_priority:
                # 简单循环轮播
                self.current_index = (self.current_index + 1) % len(self.buffer)
                msg = self.buffer[self.current_index]
                self._current_displaying_msg_id = id(msg)
                return msg
            
            # 按优先级轮播
            return self._get_next_by_priority()
    
    def _get_next_by_priority(self) -> Optional[MessageItem]:
        """
        按优先级轮播消息
        
        策略：严格按照优先级顺序轮播，缓冲区已经按优先级排序
        无论什么时候，都基于当前显示的消息找到下一条，确保顺序正确
        轮播结束后自动从气象预警开始重复轮播
        速报轮播顺序：气象预警、cenc, ningxia, guangxi, shanxi, beijing, cwa, p2pquake, hko, usgs, emsc, bcsf, gfz, usp, kma, fssn
        """
        if not self.buffer:
            self._current_displaying_msg_id = None
            return None
        
        # 确保缓冲区按优先级排序（每次轮播前都检查，确保顺序正确）
        self._sort_by_priority()
        
        # 找到当前正在显示的消息在缓冲区中的位置
        current_msg_index = -1
        if self._current_displaying_msg_id is not None:
            for i, msg in enumerate(self.buffer):
                if id(msg) == self._current_displaying_msg_id:
                    current_msg_index = i
                    break
        
        # 如果找到了当前消息，从下一条开始；否则从第一条开始（气象预警）
        if current_msg_index >= 0:
            # 找到当前消息，从下一条开始轮播
            next_index = (current_msg_index + 1) % len(self.buffer)
            # 如果回到索引0，说明完成了一轮轮播，从气象预警开始
            if next_index == 0:
                logger.debug("完成一轮轮播，从气象预警开始重复轮播")
        else:
            # 没找到当前消息（可能是新消息或排序后丢失），从第一条开始（气象预警）
            next_index = 0
            logger.debug("未找到当前消息，从气象预警开始轮播")
        
        # 确保索引有效
        if next_index >= len(self.buffer) or next_index < 0:
            next_index = 0
            logger.debug(f"索引超出范围，重置为0（从气象预警开始）")
        
        # 更新索引和当前显示的消息ID
        self.current_index = next_index
        msg = self.buffer[next_index]
        self._current_displaying_msg_id = id(msg)
        
        # 调试日志：显示轮播顺序
        priority = get_source_priority(msg.source)
        logger.debug(f"轮播: 当前消息索引={current_msg_index}, 下一条索引={next_index}, 数据源={msg.source} (优先级={priority})")
        
        return msg
    
    def size(self) -> int:
        """获取缓冲区大小"""
        with self._lock:
            return len(self.buffer)
    
    def clear(self):
        """清空缓冲区"""
        with self._lock:
            self.buffer.clear()
            self.current_index = 0
            self._priority_group_index.clear()
            self._message_add_order.clear()
            self._add_order_counter = 0
            self._current_displaying_msg_id = None


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