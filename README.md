# 地震情报实况栏
> [!WARNING]
> 软件目前仍处于测试阶段，无法保证软件稳定性。

> [!NOTE]
> **安全提示**：本软件会连接外部数据源以获取地震、海啸、火山、气象等实时信息，请从可信渠道下载使用。若被杀毒软件或安全软件拦截（如误报联网行为），可将本程序添加至信任名单；如有疑虑或问题，请联系我们（QQ群：947523679 / 邮箱：jian0786@foxmail.com）。

## 简介

地震情报实况栏为桌面端滚动字幕工具，通过连接多个 WebSocket/HTTP 数据源，在屏幕上以滚动字幕形式实时展示地震预警、地震速报、海啸情报、火山情报及气象预警等信息。

## 功能

* 滚动字幕显示地震预警、速报、海啸情报、火山情报、气象预警等
* 支持多 WebSocket/HTTP 数据源（Fan Studio、Wolfx、P2PQuake 等）
* 可自定义界面样式与颜色
* 灵活的配置管理，支持在设置中启用/禁用各数据源
* 完整的日志记录
* **预估烈度与告警序列**：达到强触发阈值时，字幕条最左侧显示固定「地震预警」红底白字并明暗闪烁；可选叠加**仅主窗口范围**的四边半透明闪烁（不覆盖整屏、不遮住中间滚动正文，不影响预警/速报轮播切换）

## 预估烈度与告警闪烁

设置 → 高级 → "预估烈度与全屏闪烁" 区域：

* **启用**：总开关；关闭后不会进行任何站点烈度估算或告警序列。
* **最低触发阈值**：达到该烈度（1–12 度）时仅显示阶段一/二的警示文本，不闪屏。
* **红屏闪烁阈值**：达到该烈度时启动左侧「地震预警」红条闪烁（并视「闪烁范围」可选主窗口四边半透明闪烁）；该值始终 ≥ 最低触发阈值。
* **最低震级 / 最大震中距**：兜底过滤；远场或弱震不触发。
* **站点经纬度 / 地点名称**：用于估算所在地烈度；近似 0 时不计算（避免赤道附近误触发）。
* **阶段一 / 阶段二时长**：分别为标题文本与警示文本的展示时长。
* **闪烁范围**：可选「主窗口四边闪烁 + 左侧红条」「仅左侧红条（字幕条内）」「不闪烁」。
* **目标屏幕**：保留字段（当前四边闪烁仅作用于主窗口，与屏幕序号无关）。**最大透明度 / 颜色 / 闪烁间隔**：作用于左侧红条与主窗口四边闪烁。
* **模拟告警**：填入烈度后点击按钮可立即触发完整序列，便于无真实预警时调参。

> 从旧版升级时会自动迁移 `enable_china_intensity / enable_felt_alert_flow / felt_alert_stage*_ms / strong_felt_stage*_ms / alert_flash_interval_ms` 等字段到 `ALERT_CONFIG`，旧字段保留两版本后清理；站点经纬度由 `GUI_CONFIG.site_lat / site_lon / site_region_name` 迁移到 `ALERT_CONFIG`。

## 数据来源

* 日本气象厅地震速报、地震情报、海啸情报：[P2PQuake API](https://www.p2pquake.net/develop/json_api_v2/)
<<<<<<< HEAD
* 日本地震预警（JMA）：[Wolfx WebSocket API](https://wolfx.jp/)、[FAN Studio API](https://api.fanstudio.tech/)
* 中国地震预警：[中国预警网](https://www.cea.gov.cn/)、[FAN Studio API](https://api.fanstudio.tech/)
* 中国地震速报：[中国地震台网中心](https://www.cenc.ac.cn/)、[FAN Studio API](https://api.fanstudio.tech/)
* 气象预警：[中央气象台](https://www.nmc.cn/)、[FAN Studio API](https://api.fanstudio.tech/)
=======
* 日本地震预警（JMA）：[Wolfx WebSocket API](https://wolfx.jp/)
* 中国地震预警：[中国预警网](https://www.cea.gov.cn/)、[FAN Studio API](https://api.fanstudio.tech/)
* 中国地震情报：[中国地震台网中心](https://www.cenc.ac.cn/)、[FAN Studio API](https://api.fanstudio.tech/)
* 气象预警：[中央气象台](https://www.nmc.cn/)
>>>>>>> c17681b33da85c19059f750ad048b7a9ea34d2ee
* 其他地震情报：[FAN Studio API](https://api.fanstudio.tech/)

## 许可证

本项目采用 [GNU GPLv3](LICENSE) 开源协议
