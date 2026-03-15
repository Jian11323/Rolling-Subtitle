# 地震情报实况栏
> [!WARNING]
> 软件目前仍处于测试阶段，无法保证软件稳定性。

> [!NOTE]
> **安全提示**：本软件会连接外部数据源以获取地震、海啸、火山、气象等实时信息，请从可信渠道下载使用。若被杀毒软件或安全软件拦截（如误报联网行为），可将本程序添加至信任名单；如有疑虑或问题，请联系我们（QQ群：947523679 / 邮箱：jian0786@foxmail.com）。

## 简介

地震情报实况栏基于Python/PyQt5开发，通过连接多个数据源，在屏幕上以滚动字幕形式实时展示地震预警、地震速报、海啸情报、火山情报及气象预警等信息。

## 功能

* 滚动字幕显示地震预警、速报、海啸情报、火山情报、气象预警等
* 支持多数据源（Fan Studio、NIED、P2PQuake、JMA 火山等）
* 可自定义界面样式与颜色
* 灵活的配置管理
* 自定义水印
* 完整的日志记录

## 数据来源

* 日本气象厅地震速报、地震情报、海啸情报：[P2PQuake API](https://www.p2pquake.net/develop/json_api_v2/)
* 日本气象厅火山情报：[気象庁防災情報XMLフォーマット形式電文の公開（PULL型）](https://xml.kishou.go.jp/xmlpull.html)（日本气象厅官方 XML 电文）
* 中国地震预警：[中国预警网](https://www.cea.gov.cn/)、[FAN Studio API](https://api.fanstudio.tech/)
* 中国地震情报：[中国地震台网中心](https://www.cenc.ac.cn/)、[FAN Studio API](https://api.fanstudio.tech/)
* 实时震度/地震速报：[NIED 日本防災科研所](https://www.bosai.go.jp/e/index.html)
* 气象预警：[中央气象台](https://www.nmc.cn/)、[FAN Studio API](https://api.fanstudio.tech/)
* 其他地震情报：[FAN Studio API](https://api.fanstudio.tech/)

## 许可证

本项目采用 [GNU GPLv3](LICENSE) 开源协议（因使用 PyQt5 等 GPL 组件，遵循 Copyleft 要求）。
