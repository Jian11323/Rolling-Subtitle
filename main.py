#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地震预警及情报实况栏程序 - 主程序入口
采用模块化架构，职责清晰
使用PyQt5 GUI框架，解决窗口静止时卡顿问题
"""

import sys
import os
import logging
import traceback
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 启动/崩溃日志：exe 同目录，仅用 stdlib，不依赖 config/logger，便于闪退时排查
def _startup_log_path():
    try:
        base = os.path.dirname(os.path.abspath(sys.argv[0] or __file__))
        return os.path.join(base, "启动日志.txt")
    except Exception:
        return "启动日志.txt"

def _write_startup_log(line):
    try:
        with open(_startup_log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# 最早写入一行，确认进程已执行到此
_write_startup_log("启动时间: " + datetime.now().isoformat())

# 检查必要的依赖
try:
    import websockets
    import requests
    from PyQt5.QtWidgets import QApplication
except ImportError as e:
    _write_startup_log("ImportError: " + str(e))
    print(f"错误: 缺少必要的依赖包: {e}")
    print("请运行以下命令安装依赖:")
    print("pip install websockets requests PyQt5")
    sys.exit(1)

# 导入阶段异常也写入启动日志，便于打包后闪退排查
try:
    from config import Config
    from utils.logger import get_logger
    from gui import MainWindow

    logger = get_logger()

    # 修复websockets库在Python 3.13下的兼容性问题
    try:
        import websockets.asyncio.connection as ws_connection
        original_connection_lost = ws_connection.Connection.connection_lost

        def patched_connection_lost(self, exc):
            try:
                if not hasattr(self, 'recv_messages'):
                    self.recv_messages = type('', (), {'close': lambda self: None})()
                original_connection_lost(self, exc)
            except Exception as e:
                logger.error(f"【websockets修复】 connection_lost异常: {e}")

        ws_connection.Connection.connection_lost = patched_connection_lost
        logger.info("已应用websockets库Connection.connection_lost方法修复")
    except Exception as e:
        logger.warning(f"应用websockets库修复时出错: {e}")
except BaseException:
    _write_startup_log("---")
    _write_startup_log("导入阶段异常:")
    _write_startup_log(traceback.format_exc())
    sys.exit(1)


def main():
    """主函数"""
    try:
        logger.info("程序启动")

        # 加载配置
        config = Config()
        logger.set_log_config(config.log_config)
        logger.info(f"数据源: {len(config.ws_urls)}个")

        # 在创建 QApplication 之前设置 OpenGL 与垂直同步（仅当选择 GPU 渲染时；CPU 渲染不设置）
        # 部分机器无独显/驱动异常会导致 Qt 初始化失败，此处做回退
        if config.gui_config.use_gpu_rendering:
            try:
                from PyQt5.QtCore import Qt
                from PyQt5.QtGui import QSurfaceFormat
                QApplication.setAttribute(Qt.AA_UseDesktopOpenGL, True)  # 优先使用桌面 OpenGL
                fmt = QSurfaceFormat()
                fmt.setRenderableType(QSurfaceFormat.OpenGL)
                fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
                fmt.setVersion(2, 1)
                fmt.setSwapInterval(1 if config.gui_config.vsync_enabled else 0)
                fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
                QSurfaceFormat.setDefaultFormat(fmt)
                logger.info(f"OpenGL 默认格式已设置（VSync: {'开启' if config.gui_config.vsync_enabled else '关闭'}）")
            except Exception as e:
                logger.warning(f"OpenGL 设置失败，回退到默认渲染: {e}")
                _write_startup_log("OpenGL 回退到默认渲染: " + str(e))
        else:
            logger.info("已选择 CPU（软件）渲染，跳过 OpenGL 设置")

        # 创建QApplication
        app = QApplication(sys.argv)
        
        # 设置应用程序图标（用于任务栏和窗口标题栏）
        # 使用try-except包装，避免文件系统操作阻塞
        try:
            from PyQt5.QtGui import QIcon
            icon_path = os.path.join(os.path.dirname(__file__), 'logo', 'icon.ico')
            try:
                if os.path.exists(icon_path):
                    app.setWindowIcon(QIcon(icon_path))
                    logger.info(f"已设置应用程序图标: {icon_path}")
                else:
                    logger.debug(f"图标文件不存在: {icon_path}")
            except (OSError, PermissionError) as e:
                logger.debug(f"检查图标文件时出错（非阻塞）: {e}")
        except Exception as e:
            logger.warning(f"设置应用程序图标失败: {e}")
        
        # 设置中文语言环境（使QColorDialog等系统对话框显示中文）
        # 延迟加载翻译文件，避免阻塞启动
        def load_translator_async():
            try:
                from PyQt5.QtCore import QTranslator, QLocale, QTimer
                translator = QTranslator()
                # 尝试加载Qt的中文翻译文件
                # 翻译文件通常位于 PyQt5 安装目录的 translations 文件夹中
                qt_translations_path = os.path.join(os.path.dirname(__file__), 'translations')
                try:
                    if os.path.exists(qt_translations_path):
                        translator.load(QLocale(QLocale.Chinese, QLocale.China), 'qtbase_', '', qt_translations_path)
                        app.installTranslator(translator)
                        logger.info("已加载Qt中文翻译")
                        return
                except (OSError, PermissionError) as e:
                    logger.debug(f"检查本地翻译文件时出错（非阻塞）: {e}")
                
                # 如果本地没有翻译文件，尝试从PyQt5安装目录加载
                try:
                    import PyQt5
                    pyqt5_path = os.path.dirname(PyQt5.__file__)
                    translations_path = os.path.join(pyqt5_path, 'translations')
                    if os.path.exists(translations_path):
                        translator.load(QLocale(QLocale.Chinese, QLocale.China), 'qtbase_', '', translations_path)
                        app.installTranslator(translator)
                        logger.info("已加载Qt中文翻译（从PyQt5安装目录）")
                except (OSError, PermissionError) as e:
                    logger.debug(f"检查PyQt5翻译文件时出错（非阻塞）: {e}")
            except Exception as e:
                logger.warning(f"加载Qt中文翻译失败: {e}，将使用系统默认语言")
        
        # 延迟执行翻译文件加载，避免阻塞启动
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, load_translator_async)
        
        # 创建主窗口
        window = MainWindow()
        window.show()

        # 调试版：启动阶段日志已正常显示；启动完成后控制台仅保留报错日志（ERROR 及以上）
        if getattr(sys, "frozen", False) and getattr(sys.stderr, "isatty", lambda: False)():
            logger.set_console_level(logging.ERROR)

        logger.debug("使用PyQt5 GUI框架")

        # 运行主循环
        sys.exit(app.exec_())

    except KeyboardInterrupt:
        logger.info("程序被用户中断")
    except BaseException as e:
        # 任何未捕获异常都写入 exe 同目录启动日志，便于无控制台时排查
        try:
            _write_startup_log("---")
            _write_startup_log("异常: " + str(e))
            _write_startup_log(traceback.format_exc())
        except Exception:
            pass
        if logger and logger.logger:
            try:
                logger.error(f"程序运行失败: {e}")
                logger.exception("详细错误信息:")
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        # 捕获 main() 之外异常（如导入阶段崩溃），同样落盘
        try:
            _write_startup_log("---")
            _write_startup_log("启动或导入阶段异常:")
            _write_startup_log(traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)
