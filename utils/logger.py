#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志系统模块
提供统一的日志记录功能，支持文件和控制台输出
"""

import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path


class Logger:
    """日志管理器 - 单例模式"""
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # 数据目录：与配置文件、翻译缓存放在一起
        # 统一目录：C:\Users\账户名\AppData\Roaming\subtitl\
        try:
            # 使用与配置文件相同的目录
            data_dir = Path.home() / 'AppData' / 'Roaming' / 'subtitl'
            data_dir.mkdir(parents=True, exist_ok=True)
            self.log_dir = str(data_dir)
        except Exception:
            # 如果失败，使用项目根目录下的 data 目录作为后备
            self.log_dir = "data"
        
        self.log_file = None
        self.logger = None
        self.console_handler = None
        self.file_handler = None

        # 不再在初始化时调用 Config()，避免与 config 的循环依赖及启动阶段崩溃
        # 使用与 config.LogConfig 一致的默认值；main 在 Config 加载后可调用 set_log_config 同步
        self.output_to_file = True
        self.clear_log_on_startup = True
        self.split_by_date = False
        self.max_log_size = 10

        # 初始化日志
        try:
            self._setup_logger()
        except Exception as e:
            # 如果日志初始化失败，至少设置控制台输出
            print(f"警告: 日志初始化失败: {e}")
            self.logger = logging.getLogger('EarthquakeScroller')
            self.logger.setLevel(logging.INFO)
            self.console_handler = logging.StreamHandler()
            self.console_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            self.console_handler.setFormatter(formatter)
            self.logger.addHandler(self.console_handler)
        
        self._initialized = True
    
    def _setup_logger(self):
        """设置日志记录器"""
        self.logger = logging.getLogger('EarthquakeScroller')
        self.logger.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S'
        )
        self.console_handler = logging.StreamHandler()
        self.console_handler.setLevel(logging.INFO)
        self.console_handler.setFormatter(console_formatter)
        self.logger.addHandler(self.console_handler)
        self._setup_file_handler(clear_if_config=True)

    def _setup_file_handler(self, clear_if_config: bool = True):
        """创建或重建文件处理器。clear_if_config 为 True 时执行启动前清空逻辑。"""
        if self.file_handler and self.logger:
            self.logger.removeHandler(self.file_handler)
            try:
                self.file_handler.close()
            except Exception:
                pass
            self.file_handler = None
        if not self.output_to_file:
            self.log_file = None
            return
        try:
            file_formatter = logging.Formatter(
                '%(asctime)s [%(levelname)s] %(name)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            if self.split_by_date:
                log_filename = os.path.join(self.log_dir, f"log_{datetime.now().strftime('%Y%m%d')}.txt")
            else:
                log_filename = os.path.join(self.log_dir, "log.txt")
            if clear_if_config and self.clear_log_on_startup:
                try:
                    log_dir = Path(self.log_dir)
                    main_log_path = Path(log_filename).resolve()
                    if log_dir.exists():
                        try:
                            with open(log_filename, 'w', encoding='utf-8'):
                                pass
                        except OSError as e:
                            print(f"警告: 无法清空日志文件 {log_filename}: {e}")
                        for f in log_dir.glob('log.txt*'):
                            if f.resolve() != main_log_path:
                                try:
                                    f.unlink()
                                except OSError:
                                    pass
                        for f in log_dir.glob('log_*.txt'):
                            if f.resolve() != main_log_path:
                                try:
                                    f.unlink()
                                except OSError:
                                    pass
                except Exception as e:
                    print(f"警告: 清空日志文件时出错: {e}")
            max_bytes = self.max_log_size * 1024 * 1024
            if self.split_by_date:
                self.file_handler = logging.handlers.TimedRotatingFileHandler(
                    log_filename, when='midnight', interval=1, backupCount=30, encoding='utf-8'
                )
            else:
                self.file_handler = logging.handlers.RotatingFileHandler(
                    log_filename, maxBytes=max_bytes, backupCount=5, encoding='utf-8'
                )
            self.file_handler.setLevel(logging.WARNING)
            self.file_handler.setFormatter(file_formatter)
            self.logger.addHandler(self.file_handler)
            self.log_file = log_filename
        except (OSError, PermissionError) as e:
            print(f"警告: 无法创建日志文件: {e}")
            self.file_handler = None

    def set_log_config(self, log_config):
        """从 Config 同步日志配置（main 在 Config 加载后调用）。会按新配置重建文件处理器。"""
        self.output_to_file = getattr(log_config, 'output_to_file', True)
        self.clear_log_on_startup = getattr(log_config, 'clear_log_on_startup', True)
        self.split_by_date = getattr(log_config, 'split_by_date', False)
        self.max_log_size = getattr(log_config, 'max_log_size', 10)
        if self.logger:
            self._setup_file_handler(clear_if_config=False)

    def debug(self, message: str, *args, **kwargs):
        """记录调试信息"""
        if self.logger:
            self.logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """记录一般信息"""
        if self.logger:
            self.logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """记录警告信息"""
        if self.logger:
            self.logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        """记录错误信息"""
        if self.logger:
            self.logger.error(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        """记录异常信息"""
        if self.logger:
            self.logger.exception(message, *args, **kwargs)
    
    def set_console_level(self, level: int):
        """设置控制台日志级别"""
        if self.console_handler:
            self.console_handler.setLevel(level)

    def disable_console(self):
        """关闭控制台输出（调试版启动完成后调用，使控制台只保留启动阶段日志）"""
        if self.logger and self.console_handler:
            self.logger.removeHandler(self.console_handler)
            try:
                self.console_handler.close()
            except Exception:
                pass
            self.console_handler = None
    
    def set_file_level(self, level: int):
        """设置文件日志级别"""
        if self.file_handler:
            self.file_handler.setLevel(level)


# 全局日志实例
logger = Logger()


def get_logger() -> Logger:
    """获取日志实例"""
    return logger