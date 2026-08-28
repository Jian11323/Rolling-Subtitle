# 地震情报实况栏

当前版本：**v2.8.4**

> [!WARNING]
> 软件目前仍处于测试阶段，无法保证软件稳定性。

> [!NOTE]
> **安全提示**：本软件会连接外部数据源以获取地震、海啸、火山、气象等实时信息，请从可信渠道下载使用。若被杀毒软件或安全软件拦截（如误报联网行为），可将本程序添加至信任名单；如有疑虑或问题，请联系我们（QQ群：947523679 / 邮箱：jian0786@foxmail.com）。

## 简介

地震情报实况栏（Rolling Subtitle）是一款 Windows 桌面端滚动字幕工具：通过 WebSocket / HTTP 聚合多个数据源，在屏幕上实时展示地震预警、速报、海啸、火山及气象等信息，并可选音效 / TTS / 系统通知反馈。本项目基于 **PyQt5**开发。

使用说明见 Wiki：[GitHub](https://github.com/Jian11323/Rolling-Subtitle/wiki) · [Gitee](https://gitee.com/jian0786/Rolling-Subtitle/wikis)

## 下载

- 介绍页（安装包 / 便携版）：[sismotide.top/rolling-subtitle](https://sismotide.top/rolling-subtitle)
- 安装包：https://sismotide.top/rolling-update/Setup_Rolling_Subtitle.exe
- 便携版：https://sismotide.top/rolling-update/Rolling_Subtitle_Portable_v2.8.4.zip
- GitHub Release：[v2.8.4](https://github.com/Jian11323/Rolling-Subtitle/releases/tag/v2.8.4)
- Gitee Release：[v2.8.4](https://gitee.com/jian0786/Rolling-Subtitle/releases/tag/v2.8.4)

## 功能

### 实况信息发布

以桌面滚动字幕形式，实时展示地震预警、地震速报、海啸情报、火山情报、气象预警等灾害相关信息；在达到设定条件时，支持预警标识闪烁、安全提示与条文轮播等告警序列展示。

### 数据接入

- **主数据源（三选一）**：Fan Studio、WeJet、Jian Project（默认）；切换主数据源后自动清空消息缓冲并重新订阅；保存后按所选主源启用连接。
- **辅助数据源**：可与主源并行启用 Wolfx、EQSC、P2PQuake、OpenQuakeAPI、台风 HTTP、CENC 烈度速报等独立通道；各源解析范围可单独配置。P2PQuake 地震情报（551）与主数据源 JMA 情报互斥。
- **气象预警源（三选一）**：Fan Studio、WeJet、OpenQuakeAPI单独选用，避免同类信息重复推送。
- **国际及地区机构速报**：支持 USGS、EMSC、HKO、GFZ、USP、CWA、KMA、BMKG、GeoNet、INGV、PTWC 等机构信息，经主聚合服务或辅助通道接入。

### 界面与告警反馈

支持字幕样式、配色、背景等界面自定义；提供预警音效、语音播报（TTS）、机构专属音效及系统通知等多种告警反馈方式。

### 性能配置

提供低、中、高、极致四档性能预设，统一调整渲染方式、数据源连接范围与告警负载；应用后即时热重载生效，首次启动依据本机硬件资源自动推荐合适档位。

### 运行维护

内置完整运行日志记录；发行版支持启动时自动检查更新。

## 数据来源

* 日本气象厅地震情报、海啸情报：[P2PQuake API](https://www.p2pquake.net/develop/json_api_v2/)
* 日本地震预警（JMA）：[Wolfx](https://wolfx.jp/)、[Fan Studio](https://api.fanstudio.tech/)、[WeJet](https://auth.beecld.com/)
* 中国地震预警 / 速报：[中国预警网](https://www.cea.gov.cn/)、[中国地震台网中心](https://www.cenc.ac.cn/)、[Fan Studio](https://api.fanstudio.tech/)
* 气象预警：[中央气象台](https://www.nmc.cn/)、[Fan Studio](https://api.fanstudio.tech/)、[WeJet](https://api.beecld.com)
* 国外机构地震速报：
[USGS](https://earthquake.usgs.gov/)
[EMSC](https://www.seismicportal.eu/)
[HKO](https://www.hko.gov.hk/)
[GFZ](https://www.gfz.de/)
[USP](https://www.moho.iag.usp.br/)
[CWA](https://www.cwa.gov.tw/)
[KMA](https://www.weather.go.kr/)
[BMKG](https://www.bmkg.go.id/)
[GeoNet](https://www.geonet.org.nz/)
[INGV](https://www.ingv.it/)
[PTWC](https://ptwc.weather.gov/) 
[Jian Project](https://api.sismotide.top/)
[Fan Studio](https://api.fanstudio.tech/)
[WeJet](https://api.beecld.com/)

## 系统要求与性能模式

### 系统要求

| 项目 | 建议 |
|------|------|
| 操作系统 | Windows 10 及以上 |
| 内存 | 4 GB 及以上（首次启动会按本机内存与 CPU 核心数自动推荐性能模式） |
| 网络 | 稳定宽带，用于连接主数据源与辅助聚合服务 |

### 性能模式

程序提供 **低 / 中 / 高 / 极致** 四档预设，在 **设置 → 外观与显示 → 性能与渲染** 中选择并点击 **应用性能模式** 即可生效（热重载，无需重启）。各档以滚动字幕流畅为优先（低配及以上均保证 ≥30 fps），在资源占用、数据源范围与告警反馈之间取舍：

| 模式 | 渲染 | 数据源与解析 | 告警反馈 |
|------|------|--------------|----------|
| **低性能** | CPU 软件渲染，30 fps | 仅保留主聚合源；关闭 Wolfx、Jian Project、P2PQuake、Nowquake 等辅助连接；精简国际速报解析；HTTP 轮询间隔约 2.5 倍 | 默认关闭音效 / TTS |
| **中性能** | CPU 软件渲染，30 fps | 主聚合源 + 台风 HTTP、OpenQuakeAPI 等常用辅助源；解析开关恢复程序默认 | 跟随默认设置 |
| **高性能** | OpenGL 硬件渲染，30 fps | 启用全部可选 WebSocket / HTTP 源（含 Jian Project、Wolfx、P2PQuake、Nowquake 等）及完整解析 | 开启预警音效 |
| **极致** | OpenGL 硬件渲染，60 fps，2× MSAA | 与高性能相同的数据源与解析范围 | 开启预警音效与 Toast 通知 |

**自动匹配**（仅首次初始化时）：物理内存小于 3 GB 或 CPU ≤ 2 核 → 低性能；小于 6 GB 或 ≤ 4 核 → 中性能；小于 12 GB 或 ≤ 6 核 → 高性能；其余 → 极致。

手动修改渲染、数据源或解析等单项设置后，性能模式下拉框会显示「自定义（未跟随预设）」。

## 许可证

本项目采用 [GNU GPLv3](LICENSE) 开源协议

## 开源声明与免责声明

为尽可能避免本项目被用于违法或恶意目的，维护者在此郑重声明如下法律立场（下列条款构成对使用者的明确约定）：

- **用途限制**：本项目仅供研究、教学、应急演练、灾害防范与减灾等合法、正当用途。任何将本项目用于违法、侵权、危害他人安全或其他恶意用途的行为均被明确禁止。
- **无担保声明**：本软件按“原样”（AS IS）提供，不对其适用性、可靠性、可用性、性能、正确性或满足特定用途作任何明示或暗示的保证，包括但不限于对适销性、特定用途适用性或不侵权的保证。
- **责任限制**：在适用法律允许的最大范围内，维护者对因使用、修改、分发或无法使用本软件而导致的任何直接、间接、附带、特殊、惩罚性或后果性损害不承担责任，即便维护者已被告知可能发生此类损害。本条款不得视为对法律强制性责任的放弃（例如在某些法域中对人身伤害或故意违法行为的责任承担）。
- **赔偿义务**：使用者应对因其使用、修改、配置或再分发本软件而导致的任何第三方索赔、损失、责任、损害或费用（包括合理的律师费）承担全部赔偿责任，并应在法律允许的范围内，使维护者免受此类索赔、损失或费用的损害。
- **遵守许可与保留声明**：任何修改、再发布或商业使用均须遵守本项目所载的 [LICENSE](LICENSE) 条款，并在分发时保留本声明、原始版权信息及许可文件。如需超出本许可的额外授权，请与维护者取得书面协议。
- **非法律意见**：本声明反映维护者对风险与责任的商业立场，不构成法律意见。如需具有法律约束力的文本或具体法律咨询，请寻求专业律师服务。

如需就免责或使用许可进行协商或签署特殊许可协议，请使用安全提示内提供的联系方式与开发者联系。
