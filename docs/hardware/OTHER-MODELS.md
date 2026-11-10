# 其他机械革命机型

2026-11-07：蛟龙 16K GM6BG0Q 已在本项目实机完成部分验收；其他新增型号仍只有源码适配或外部报告，不能把本地测试或编译当成硬件验收。

| 型号 | 必须同时匹配的 DMI 字段 | 本次行为 | 证据与验收边界 |
| --- | --- | --- | --- |
| 无界 14X | 厂商 `MECHREVO`、板号 `GX4HRXL` | 通过既有 ioctl 提供节能、均衡、性能三档；只改模式位，保留强冷等其他位 | [mech-forza-kmod 固定版本](https://github.com/minortex/mech-forza-kmod/blob/00769343a82f66bcbf44f58924d88b7035066b71/mechrevo-ec.c) 确认 `0x0751` 的 `0xa0/0x00/0x10`；不启用 legacy 风扇表初始化、custom-profile 位或 CPU 功耗表；BIOS 范围待实测 |
| 蛟龙 16 Pro 2025 | 厂商 `MECHREVO`、板号 `JIAOLONG Series-X6xR55xK` | 接入已有 `x6fr5xx` CPU 功耗表及 custom-profile；成功和失败沿用原来的完整事务 | [社区实测补丁固定版本](https://github.com/sklynic/pkgbuild-mechrevo-driver-dkms-16-pro/blob/cf71e4cc1b2d8d4ebdf68a98ca00910087f1678d/patch.diff) 和 [作者说明](https://github.com/sklynic/pkgbuild-mechrevo-driver-dkms-16-pro/blob/cf71e4cc1b2d8d4ebdf68a98ca00910087f1678d/README.md)；作者实测 9955HX，未据营销名称扩展到苍龙、XPro 或其他板号；本项目 BIOS 范围待实测 |
| 蛟龙 16K | 厂商 `MECHREVO`、产品名 `Jiaolong16K Series GM6BG0Q`、板号 `GM6BG0Q`；新增控制另要求 BIOS `N.1.19MRO15` | 接电开机、USB 供电、控制台精确识别、只读 EC 温度/双风扇 RPM、手动风扇占空比、三档模式和 TDP 范围（PL1/PL2 35–80 W，PL4 100 W）；不迁移 OEM 风扇曲线 | [本机记录](GM6BG0Q.md) 与 ACPI 反汇编；[主线驱动投稿](https://lists.openwall.net/linux-kernel/2026/10/23/301) 报告该 BIOS、EC 1.24 的实测；[Uniwill 原始实现](https://github.com/Wer-Wolf/uniwill-laptop/blob/a9e5ac3b10ed09c6d9aedd23288d3c7887afb450/uniwill-acpi.c) 确认寄存器布局；PL2/PL4 效果、睡眠恢复和其他 EC 版本仍待验证 |
| 无界 15X Pro | 厂商 `MECHREVO`、板号 `WUJIE Series-X5SP4NAG` | 接电开机、USB 供电开关及控制台精确识别 | 投稿者的[实测说明](https://lists.openwall.net/linux-kernel/2026/09/28/2519)、[v4 补丁](https://lists.openwall.net/linux-kernel/2026/10/16/1522) 与上述 Uniwill 原始实现；投稿未限定 BIOS，不能据此认证所有固件；不启用其他机型功耗表、风扇曲线或 NVIDIA 控制 |
| 翼龙 15 Pro | 厂商 `MECHREVO`、产品名 `Yilong15Pro Series GM5HG0A`、板号 `GM5HG0A`；本分支新增开关另要求 BIOS `N.1.09MRO19` | 接电开机、USB 供电开关及控制台精确识别；也可使用已加载原生 Uniwill 的有限接口 | [机主与维护者测试讨论](https://lore-kernel.gnuweeb.org/platform-driver-x86/tencent_36699D13D174660E0D76C4F5EFB825D86609%40qq.com/T/)中报告两个开关分别测试有效；不扩展触控板、充电档位或 USB-C 功率分配声明；本项目实机验收待完成 |
| 蛟龙 16 Pro 2023 | 厂商 `MECHREVO`、产品名 `Jiaolong Series MRID6`、产品版本 `1`、板号 `MRID6-23` | 控制台精确识别，并接入已加载原生 `bitland_mifs_wmi` 的键盘背光亮度 | [机主硬件记录](https://github.com/Tanpinsary/JiaoLongOnArch/blob/f75e2522ab6cda6fd6990a3d8468cf0d27d067dd/docs/hardware.md)、[原生驱动测试记录](https://github.com/Tanpinsary/JiaoLongOnArch/blob/f75e2522ab6cda6fd6990a3d8468cf0d27d067dd/docs/linux-stage3-results.md)及 Linux v7.2 驱动；记录 BIOS 为 `MRID6_23_P_V35`，本项目未实测；不复制 Uniwill EC 路径、功耗表、风扇或 MUX 控制 |
| 无界 15 Pro HPT | 厂商 `MECHREVO`、产品 `WUJIE15 PRO`、板号 `WUJIE15 Series-HPT` | 精确识别、Bitland 背光接入、F2/F1 读数标注；拒绝旧内核的错误四档映射，标记不存在的温度和第三风扇 | 与 X5SP4NAG 为不同平台；[机主依据与内核修正要求](WUJIE-HPT-P916F.md)，未本项目实机验收 |
| 星耀 P916F HPT-R | 厂商 `MECHREVO`、产品 `XINGYAO Series`、板号 `XINGYAO Series-P916F-HPT-R` | 精确识别及实际存在的标准监测/性能档位接口；不新增 OEM 控制 | [固定源码与适配边界](WUJIE-HPT-P916F.md#p916f-证据与限制)；只读热键模块不等于背光、风扇或充电可控，不扩展到 STX/ARL |
| 无界 14SAH P4HPLNAV | 厂商 `MECHREVO`、产品 `WUJIE Series`、板号 `WUJIE Series-P4HPLNAV` | 新增控制台精确识别；记录原生 AMD ACP6.3 / ES9356 声卡路径，不增加 EC、风扇或功耗写入 | [机型身份与 Linux 音频边界](WUJIE14SAH.md)；本项目未在该机上实测 |

厂商、板号使用完整字段相等比较。类似前缀、后缀、缺失字段和其他厂商不会获得新增能力。GM6BG0Q 的控制台证据等级为 `hardware-partial`，表示部分功能已在本机核对，不是完整认证；它不会继承蛟龙 16 Pro 的 CPU 功耗接口，其他型号仍为 `upstream-source`。

接电开机复用 `0x0726.bit3`，USB 供电复用 `0x0767.bit4`，通过已有共享读改写事务保留其他位。新型号检测只增加功能标记，不在检测时更改开关状态；加载后的 sysfs 文件是否成功注册仍需单独检查。控制台沿用实际 sysfs 属性发现和回读，不会仅因机型命中就显示功能可用。投稿中的 RGB、充电模式、Fn、风扇等其他能力没有被整体照搬成本分支支持声明。

初始化另修正一处源码确认的失败路径：以前先创建控制接口，再忽略 EC 读取失败并缓存未初始化的值。现在先成功读取和初始化状态，之后才创建接口；读取或注册失败均记录错误且不标记已加载。这是本地模拟与编译器确认的问题，未声称在新增型号上复现过。

控制台现在也能使用已加载且绑定有效的原生 `uniwill_laptop` / `bitland_mifs_wmi` 接口，不必因此换成另一套 EC 驱动。原生 Uniwill 接入 Fn、接电开机、USB 供电和背光，Bitland 仅接入背光；模块身份、设备归属、ID 及事件节点边界见[原生驱动说明](NATIVE-KERNEL-CONTROLS.md)。原生接口按已加载驱动提供的能力发现，不由身份目录授予，也不自动加载、强制绑定或解除驱动冲突。

蛟龙 16 Pro 表的校验范围为 PL1/PL2 25–162 W、PL4 25–195 W，复用既有值；这些是接口允许范围，**不是建议功耗或散热能力承诺**。PL4 是否双倍编码仍读取设备自身能力位。识别与读取不会自动写入功耗目标；手动功耗设置依旧需要已绑定的控制接口、有效索引和值，且失败会向调用者报错。custom-profile 标记也参与加载、接电与睡眠恢复，因此这些生命周期需要新增机型实测。

无界 14X 的三档能力与旧式风扇曲线初始化分开。不能因为模式寄存器相同，就复制未知风扇表。原有通用驱动加载仍有其他 EC 初始化动作；本次修改并非为未验证固件提供安全认证。

## 本地回归

`tests/test_uniwill_mechrevo_models.py` 编译实际 C 函数及功耗表，替换 DMI 和硬件传输；覆盖新增板号、相似名称拒绝、现有 TUXEDO/GM6PX0X 行为、全部模式字节、功耗边界、PL4 编码、读写失败和失败后重试。模拟版本覆盖 4.17、4.18 和 7.2.11 的预处理分支；不代表在这些真实内核或硬件上运行过。

```sh
python -B scripts/verify.py --domain driver
cargo test --manifest-path console/Cargo.toml --workspace --locked
```

旧源码不能通过新增功能用例；独立替换旧 ioctl 源码也应无法通过蛟龙功耗范围用例。新增设置项的回归通过实际 feature 检测、开关读写辅助函数和初始化函数验证：严格身份和 BIOS、两个寄存器全部 256 种原值的位保留、原错误码传播、缓存不误更新、读取或注册失败不发布已加载状态、成功重试，以及识别过程零写入。开关身份与事务用例已扩展到 GM5HG0A；仅替回本轮修改前的 keyboard 头文件就会失败。控制台回归检查八个其他型号的精确身份和未实机验收状态，以及新增原生后端的有效写入、失败拒绝与设备隔离。

原生接口轮次 `d99c13e` 的本地结果：驱动 506 项、控制台 Python 105 项、Rust 工作区默认功能 138 项（核心 98、CLI 15、GUI 状态逻辑 25）全部通过，无跳过；默认功能全部目标的 clippy、核心文档生成、工作区格式检查通过。`7.2.11-arch1-1` headers 下 28 个模块以 `W=1 -j1` 编译成功，57 份源码输入与当前文件逐字一致，28 个 vermagic 均对应该内核；未修改的 Clevo/NB04/NB05/TUXI 文件仍有 5 处未使用变量告警，未隐藏。按单线程、低 CPU/I/O 优先级依次构建，没有触发远程 CI，也没有安装或加载新模块。本轮未重新验收 GUI 窗口或 Windows。

新源码 CLI 在开发机 GM6PX0X 上完成只读枚举：原有 Fn 锁、充电档位、背光亮度和 RGB 四项接口均为 `available`。只读取接口，没有应用计划或写入；这不增加新增型号的硬件验收数量。

后续 HPT / P916F 轮次新增标准性能档位 class 接口兼容及 HPT 已知固件差异处理，Rust 146 项、控制台 Python 105 项通过，无跳过。该轮没有改动内核模块源码，没有重新编译或安装模块；[具体行为与验证范围](WUJIE-HPT-P916F.md)。

## 新机验收仍需完成

先记录上述非敏感 DMI、CPU/GPU、BIOS/EC 和内核版本，再逐项验证安装、实际加载模块身份、模式回读及物理表现。蛟龙功耗操作另需验证约束范围、散热、失败恢复和睡眠/接电恢复；不能在不同型号上套用 GM6PX0X 的 `mechrevo-power` 55 W 配置。

已有 `uniwill-laptop`、`mech-forza-kmod` 或另一套直接控制 EC 的驱动时，应先确认接口归属，避免多套控制器同时写硬件；本分支不会替用户卸载它们。新增机型尚未验证安装、加载、风扇、充电、键盘、睡眠和长期稳定性，也未发布新的 AUR 配方或安装到本机。
