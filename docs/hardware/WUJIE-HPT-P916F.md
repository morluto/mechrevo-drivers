# 无界 15 Pro HPT 与星耀 P916F HPT-R

2026-10-29：本轮增加两个独立平台的精确识别和控制台适配。开发机器仍为 GM6PX0X，没有这两个型号供本项目实机验收；身份目录不授予 EC/WMI 写入权限。

| 型号 | 必须完整匹配的 DMI | 接入范围 |
| --- | --- | --- |
| 无界 15 Pro HPT | 厂商 `MECHREVO`、产品 `WUJIE15 PRO`、板号 `WUJIE15 Series-HPT` | 已绑定 Bitland 的背光接口；F2/F1 风扇读数标注；拒绝旧驱动的错误档位映射，标记不存在的 MIFS 传感器 |
| 星耀 P916F HPT-R | 厂商 `MECHREVO`、产品 `XINGYAO Series`、板号 `XINGYAO Series-P916F-HPT-R` | 精确身份及实际存在的标准温度、电池、电源和性能档位接口；不新增 OEM 背光、风扇或充电写入 |

没有这两个型号的本地固件验收，`qualified_bios` 均为空。无界 HPT 不匹配已经适配的 `WUJIE Series-X5SP4NAG`；星耀 HPT-R 不扩展到 STX、ARL 或其他星耀型号。

## HPT 固件差异

机主的[首次投稿与测试](https://lists.openwall.net/linux-kernel/2026/09/14/65)、[第二版补丁](https://lkml.iu.edu/hypermail/linux/kernel/2609.2/19484.html)和[后续背光测试](https://lkml.iu.edu/2610.2/04186.html)确认了与通用 Bitland 固件不同的行为：

- 固件档位仅为性能、均衡、安静三档，原始值依次为 0、1、2。旧驱动的通用四档映射不适用。
- 风扇数据是 F2、F1 两路，不等于已确认的 CPU/GPU 归属；机主没有独立校准 RPM。
- MIFS 没有 CPU 温度和第三个风扇。未实现的 GET 可能成功返回全零，不能据此报告真实 0 °C 或第三个风扇停转。
- 普通背光亮度为 0–3；无 RGB、GPU 切换或强冷能力声明。事件 GUID 与 `redmi-wmi` 的冲突由内核修正处理。

控制台发现精确 HPT 身份、Bitland 性能档位处理器以及旧接口的 `balanced-performance` 选项时，会禁用性能档位计划并给出 `bitland_hpt_kernel_quirk_required` 诊断。不会把已知错误标签重新解释后写入。缺少该四档特征也不代表本项目已验证映射、供电或睡眠行为；仍须使用包含相应 HPT 修正的内核并单独验收。

`bitland_mifs` 的前两个风扇标为 `Fan 2`、`Fan 1`，保留真实零转速。该接口多出的温度和第三风扇条目仍显示来源及不可用原因，值为未知，不静默丢弃。其他 hwmon 芯片和其他板号不套用这条规则。这只修正控制台对已知接口的解释，不修复内核或固件。

## P916F 证据与限制

[固定版本源码](https://github.com/longwudf/mechrevo-p916f-linux/blob/1168e9c4dce3a0a63bac71a54b9e08ceb1c1a273/mechrevo-p916f-wmi.c)核对了上表三项 DMI。[同版本说明](https://github.com/longwudf/mechrevo-p916f-linux/blob/1168e9c4dce3a0a63bac71a54b9e08ceb1c1a273/README.md)记录 AMD PMF 已提供标准性能档位，以及专用 WMI 驱动只读处理热键。它与 Huawei 共享 GUID，但调用协议不同，不能套用 Huawei 控制命令。

本项目不复制或安装该热键模块，不自动卸载 `huawei_wmi`，不新增重复的 PMF 档位提供者。采集和档位能力均以当前内核真实接口为准；没有接口就报告未知或不可用。音频、I2C、SMBus、睡眠恢复、原厂热键和充电阈值不属于本轮已完成的硬件适配。

## 新版内核性能档位接口

原先控制台只检查 `/sys/firmware/acpi/platform_profile{,_choices}`。现在仅在这两个旧接口均不存在、且 `/sys/class/platform-profile` 中恰有一个处理器时，接入该设备的 `name`、`choices`、`profile`。接口依据为 [Linux 官方说明](https://www.kernel.org/doc/html/latest/userspace-api/sysfs-platform_profile.html)与 [v7.2 实现](https://github.com/torvalds/linux/blob/v7.2/drivers/acpi/platform_profile.c)。这是标准内核接口兼容，不是新机型的 EC 参数表。

旧聚合接口继续优先；旧接口损坏、权限不足或多个处理器时，不选择某个驱动绕过聚合语义。新设备须解析到所选 sysfs 根的 `devices` 目录内，属性不能是符号链接。计划记录设备、驱动名称和属性身份；应用前重新核对，并固定同一文件描述符完成写入、回读和必要恢复。接口被替换、当前值变化、权限不足或范围不支持时拒绝应用。系统档位应用不自动提权。

## 本地验证

旧实现会在新版接口枚举/应用和 HPT 错误映射/传感器回归中失败。修复后 Rust 默认功能工作区 146 项通过（核心 106、CLI 15、GUI 状态逻辑 25），控制台 Python 105 项通过，无跳过。覆盖单处理器预览/应用/回读、旧接口优先、多处理器拒绝、路径越界、属性符号链接、只读权限、设备/名称/属性替换，以及 HPT 专属判断和其他板号不受影响。

核心/CLI 全部目标与 feature 的 Clippy（`-D warnings`）、核心文档生成及工作区格式检查通过。新源码 CLI 在 GM6PX0X 上完成只读状态采集：原有四项 OEM 接口均可用，保留 38 条传感器记录；这不增加新型号的实机验收。

本轮只改控制台及身份数据，没有更改内核模块源码；前轮模块编译证据不冒充本轮新编译。没有安装、加载或发布新驱动，也未更新 AUR、写入新增型号硬件或验收真实 GUI/Windows。
