地震预警及情报实况栏程序

一个用于显示地震预警及情报实况栏的Python应用程序，支持多个WebSocket数据源。

功能特性

- 📺 滚动字幕显示地震预警和速报信息
- 🔌 支持多个WebSocket数据源
- 🎨 可自定义界面样式和颜色
- ⚙️ 灵活的配置管理
- 📝 完整的日志记录

支持的数据源

WebSocket数据源
1. **Fan Studio** (`wss://ws.fanstudio.tech/all`)
2. **NIED 日本防災科研所** (`wss://sismotide.top/nied`)
3. **P2PQuake 日本气象厅地震/海啸** (`wss://api.p2pquake.net/v2/ws`)

安装依赖

```bash
pip install websockets requests
```

使用方法

运行程序

```bash
python main.py
```

配置文件

配置文件位置：`C:\Users\账户名\AppData\Roaming\subtitl\settings.json`

程序首次运行时会自动创建配置目录和配置文件。

项目结构

```
滚动字幕/
├── main.py                    # 主程序入口
├── config.py                  # 配置管理
├── gui/                       # GUI模块
│   ├── main_window.py         # 主窗口
│   ├── scrolling_text.py      # 滚动文本组件
│   └── message_manager.py     # 消息管理
├── adapters/                  # 数据源适配器
│   ├── base_adapter.py
│   ├── fanstudio_adapter.py
│   ├── nied_adapter.py
│   └── p2pquake_adapter.py 等
├── data_sources/              # 数据源管理
│   └── websocket_manager.py
└── utils/                     # 工具模块
    ├── logger.py
    └── message_processor.py
```

许可证

本项目采用 [GNU GPLv3](LICENSE) 开源协议（因使用 PyQt5 等 GPL 组件，遵循 Copyleft 要求）。
