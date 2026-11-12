# 复用 Linux 已加载的原生驱动

2026-10-29：控制台新增 `uniwill_laptop` 与 `bitland_mifs_wmi` 的有限 sysfs 接入。它们与本仓库的 `tuxedo_keyboard` 分开识别，不要求为了使用控制台而换装另一套 EC 驱动。新增源码尚未安装到开发机器，也没有新增型号可做硬件验收。

| 原生驱动 | 控制台接入范围 | 判断依据 |
| --- | --- | --- |
| `uniwill_laptop` | Fn 锁、接电开机、关机 USB 高功率供电、键盘背光亮度 | 只列出已绑定 `INOU0000:XX` 设备实际存在的 `fn_lock`、`ac_auto_boot`、`usb_powershare_high` 和归属该设备的键盘 LED；不复制其他型号的控制项 |
| `bitland_mifs_wmi` | 键盘背光亮度 | 只识别控制 GUID `B60BFB48-3E5B-49E4-A0E9-8CFFE1B3434B` 的实例及其 LED；亮度上限读取 `max_brightness`，Linux v7.2 实现为 3 |

接口分别核对了 [Linux v7.2 Uniwill ABI](https://github.com/torvalds/linux/blob/v7.2/Documentation/ABI/testing/sysfs-driver-uniwill-laptop) 和 [Bitland 驱动源码](https://github.com/torvalds/linux/blob/v7.2/drivers/platform/x86/bitland-mifs-wmi.c)。Uniwill 原生 RGB 通道的范围与 TUXEDO 接口不同，本轮不提供原生 RGB 写入，也不把缺失的上限补成 255。Bitland 的风扇、MUX、性能模式和键盘模式不在接入范围内。

## 型号依据

蛟龙 16 Pro 2023 的公开 DMI 为厂商 `MECHREVO`、产品名 `Jiaolong Series MRID6`、版本 `1`、板号 `MRID6-23`、BIOS `MRID6_23_P_V35`。机主公开的[硬件记录](https://github.com/Tanpinsary/JiaoLongOnArch/blob/f75e2522ab6cda6fd6990a3d8468cf0d27d067dd/docs/hardware.md)和[原生驱动测试记录](https://github.com/Tanpinsary/JiaoLongOnArch/blob/f75e2522ab6cda6fd6990a3d8468cf0d27d067dd/docs/linux-stage3-results.md)提供了这条接入路线。本项目只接入已加载原生驱动的背光接口，没有移植该项目的原始 WMI 命令，也没有照搬全速风扇或性能档位设置。

翼龙 15 Pro 的[机主与维护者讨论](https://lore-kernel.gnuweeb.org/platform-driver-x86/tencent_36699D13D174660E0D76C4F5EFB825D86609%40qq.com/T/)给出产品名 `Yilong15Pro Series GM5HG0A`、板号 `GM5HG0A`、BIOS `N.1.09MRO19`，并报告背光、Fn 锁以及分别测试的接电开机和 USB 供电有效。报告使用了强制加载的候选驱动，不能据此声称发行版内核已经自动识别；控制台只使用当前已绑定且通过核验的接口，不执行强制加载。触控板、USB-C 功率分配和充电模式的物理效果未获确认，未加入本轮支持声明。

两个型号的身份表均为外部源码/机主证据，不标记为本项目实机通过，也不授予硬件写入能力。实际可用性由已加载驱动及其 sysfs 接口决定。

## 绑定与应用

先用 `mechrevo-console oem list` 查看实际列出的完整 ID、范围、来源和可写状态。原生 Uniwill 的布尔控制 ID 含模块和设备实例，例如 `fn-lock:uniwill_laptop:INOU0000:00`，防止多个设备混用计划。背光 ID 仍为 `keyboard-brightness:<LED 名称>`。预览与已有后端一样不写入、不提权；显式应用继续走已有受限 helper。

发现时检查固定总线驱动目录、设备到驱动的链接、驱动到模块的链接及设备路径。应用时重新检查驱动版本、设备身份、当前值和允许范围。模块缺失、`srcversion` 不可读、模块或设备被替换、LED 指向别处、属性无效或不可写时拒绝应用。内建驱动若没有这里要求的模块身份接口，也不显示为可写支持。

控制台不加载、卸载、强制绑定驱动，不发送原始 WMI/EC 命令。Bitland 的事件 GUID `46C93E13-EE9B-4262-8488-563BCA757FEF` 不能充当控制设备；MRID6-23 记录中的 `redmi-wmi` 事件绑定冲突没有由控制台自动解除，实体热键事件仍需单独验收。

驱动回读只证明接口报告的状态，背光回读可能是 LED 请求缓存。它们不能代替物理灯光、Fn 行为、冷接电、关机供电、睡眠恢复和长期稳定性验证。本轮没有安装新包、加载新模块、更新 AUR 或对新增型号写硬件。

## 本地验证

核心回归覆盖两种原生驱动的枚举和背光范围、Uniwill 三种布尔开关的预览/应用、错误模块和换绑拒绝、事件节点拒绝、多设备隔离，以及不继承 TUXEDO RGB 范围。CLI 通过真实 `Service` 路径验证原生控制的选择、只读预览、状态序列化和导出。模拟文件不能替代原生驱动及硬件验收。

完整测试与内核编译结果见[其他机型说明](OTHER-MODELS.md#本地回归)。这些检查不证明普通用户授权弹窗、图形界面或新增硬件已经验收。
