# 机械革命全系列型号与同方/Uniwill 模具拓扑矩阵

日期：2026-10-18
收录原则：严格区分源码确认（**seen**）、开源项目提取（**seen**）、社区实机反馈（**inferred**）与仍待核验项（**unknown**）。

---

## 1. 全系列产品线与 OEM 模具映射总表

机械革命（MECHREVO）绝大多数笔记本由**清华同方（Tongfang / Uniwill OEM）**代工制造，海外孪生品牌包括 Tuxedo Computers（德国）、XMG / Schenker（德国）、Eluktronics（美国）等。早期少数机型曾采用蓝天（Clevo）或宝龙达（Baolongda）模具。

### 1.1 轻薄本 / 全能本系列 (Thin & Light / Creator)

| 市场销售型号 | OEM 模具代号 | 硬件平台 | 键盘与控制特征 | Linux/开源对齐项目 |
| --- | --- | --- | --- | --- |
| **无界 14 (初代)** | `IP3_4N39` / `IP3_6N39` | AMD Ryzen 4000/5000 / Intel 11/12 代 | 单色背光，Fn+X 性能模式，EC RAM 背光延时 | `xuwd1/mechrevo-wujie14-kmod` |
| **无界 14+ / 14 Pro** | `GX4HRX` / `GX4MRX` / `IP3` 衍生 | AMD Ryzen 7040/8845HS / Intel Ultra 1代 | 白光背光，标准 WMI 性能档位 | `xuwd1/mechrevo-wujie14-kmod` |
| **无界 14X** | `GX4HRXL` / `GX4MRXL` | AMD Ryzen 8845HS / Intel 14650HX / Ultra | 白光可调，双风扇双热管，同 Tuxedo IBP14 Gen9 | `sund3RRR/mechrevo14X-linux` |
| **无界 15 / 15X / 16** | `GX5HRXL` / `GX6HRXL` / `PF5` / `PF6` | AMD Ryzen 7000/8000 / Intel 13/14 代 | 全尺寸键盘，大电池，无独显/轻量独显 | Tuxedo Pulse 16 / InfinityBook Pro 16 |
| **Code 01 (初代)** | `PF5NU1G` | AMD Ryzen 7 4800H 集显 | 白光背光，双风扇，静音/性能切换 | `692367/tongfang-fan-control`, Tuxedo Pulse 15 Gen1 |
| **Code 01 (二代)** | `PF5NU1F` / `PF5NU1G-v2` | AMD Ryzen 7 6800H 集显 | 双通道 USB4，双扇多热管 | Tuxedo Pulse 15 Gen2 |
| **Code 10 / 11** | `PF5MU` / `PF5PU` | Intel 酷睿 H 系列 | 白光单色，办公平衡模式 | Uniwill WMI 标准协议 |
| **S1 / S2 / S3 / F1 系列** | `PF4PU1F` / `PF4NU1F` / `GJ4` | 早期酷睿/锐龙超轻薄 | 单色背光，标准 ACPI 控制 | 内核通用 ACPI 驱动 |

### 1.2 主流游戏本：极光 (Aurora) & 蛟龙 (Jiaolong)

| 市场销售型号 | OEM 模具代号 | 硬件平台 | 键盘/灯效/散热 | 协议特征与出厂功耗参考 |
| --- | --- | --- | --- | --- |
| **极光 15 / 16** | `GM5PG0O` / `GM6PX0X` | Intel 12/13/14 代 + RTX 3050/4050/4060 | 单区 RGB，双风扇，RamFan1p5 | PL1 45W/75W/115W, TGP 105-140W |
| **极光 Pro** | `GM5PG7X` / `GM6PX7X` | Intel 12/13/14 代 HX + RTX 4060/4070 | 单区 RGB，16 节风扇曲线 | `mechrevo-drivers` (本仓库基座) |
| **极光 X** | `GM5HG0X` / `GM6HG0X` | Intel 13/14 代 HX + RTX 4060/4070 | 极光流线灯，RGB 背光 | 新版 Uniwill WMI + EC 控制 |
| **蛟龙 15 / 16** | `GM5PX7X` / `GM6PX7X` | AMD Ryzen 7000/8000 + RTX 4050/4060 | RGB 键盘，双独立温控曲线 | PL1 45W/75W/90W, TGP 140W |
| **蛟龙 16 Pro** | `GM6XG7X` / `PH6TRX1` | AMD Ryzen 7945HX/8845HX + RTX 4060/4070 | 4区/单区 RGB，双风扇独立控制 | 支持 RamFan1p5，多级风扇表锁定 |
| **蛟龙 16S / 17** | `GM7PX7N` / `PH6` | AMD Ryzen + RTX 40 系 | 大尺寸机身，17寸高刷 | 高功耗释放 |

### 1.3 旗舰游戏本：旷世 (Kuangshi) / 耀世 (Yaoshi) / 翼龙 (Yilong)

| 市场销售型号 | OEM 模具代号 | 硬件平台 | 特殊外设与特征 | 协议与出厂规格 |
| --- | --- | --- | --- | --- |
| **旷世 16 / 16 Pro / Super** | `GM6PX0X` / `GM7PX7N` | Intel 12/13/14 代 HX + RTX 4060-4090 | 外置水冷接口（磁吸）、RGB 灯带、双 EC 探头 | PL1 45W/75W/130W+, 水冷联动控制 |
| **旷世 G16 / 旷世 X** | `GM6HG0X` / `GM7PX0N` | Intel HX 旗舰 + RTX 4080/4090 | 机械键盘/逐键 RGB，外置水冷 | 独创水冷 BLE 协议，高压水泵 |
| **耀世 15 / 16 / 16 Pro** | `PH4PRxx` / `PH6PG7x` / `GM6IX9B` | Intel 14 代 HX + RTX 4060/4070/4080 | A 壳透光 Logo、超薄全金属、TypeA 键盘 | PL1 最高 205W，16 节点出厂风扇表 |
| **翼龙 15 / 15 Pro** | `PH5` / `PH4AUxx` / `PH4AQxx` | AMD Ryzen 8845H/HX + RTX 4060/4070 | 极简机身，无界/游戏双跨界 | 新型 3-byte WMI 性能档位协议 |

### 1.4 早期经典系列 (Legacy GK / GJ 系列)

| 市场销售型号 | OEM 模具代号 | 硬件平台 | 键盘控制芯片 | 驱动特征 |
| --- | --- | --- | --- | --- |
| **深海幽灵 Z2 / Z2-G / Z2 Air** | `GK5CN5Z` / `GK5CN6Z` / `GK5CP6Z` | Intel 8/9 代 + GTX 1060 / RTX 2060 | ITE 8291 / 光轴机械键盘 | `faraway030/tongfang-unofficial-control-center` |
| **深海幽灵 Z3 / Z3 Air** | `GK5NR0O` / `GK5NR2O` | AMD Ryzen 4000 + GTX 1650/RTX 2060 | 单区 RGB，EC 寄存器映射 | 通用 Uniwill 驱动 |
| **深海泰坦 X1 / X2 / X3 / X8Ti / X9Ti** | `GK5CP0Z` / `GK7CP0S` / `GK7CP7S` | Intel 8/9 代 + GTX 1060 / RTX 2060/2070 | ITE 8291 / 前置灯条 (Lightbar) | `pobrn/qc71_laptop`, `siphomateke/tongfang-control` |
| **深海泰坦 X10Ti / X10Ti-S** | `GK5CQ7Z` / `GM5MP0Y` | Intel 10 代 + RTX 2070 Super | 4 区 RGB，高刷电竞屏 | 早期 Uniwill WMI |

---

## 2. 硬件控制层技术分型与统一协议栈

为了实现全系列 100% 适配，控制中心将底层通信划分为五大协议驱动器（Protocol Drivers）：

1. **Uniwill WMI 协议族（Modern & Legacy）**：
   - 现代版（40/50 系列）：3 字节载荷（Command, Arg1, Arg2），处理性能档位（Quiet/Balanced/Turbo/Custom）、显卡直连切换（MUX Switch）。
   - 传统版（20/30 系列）：单字节状态机，通过 `PNP0C14` GUID 方法调用。
2. **EC RAM 直接寄存器协议族**：
   - 功耗控制：`0x0783..0x0786`（PL1/PL2/PL4 硬件写入入口）。
   - 电池充电阈值：`0x07a6`（模式与百分比上限），配合位掩码读改写杜绝覆盖指示灯。
   - USB 关机供电与开机自启：`0x0767` bit 4 与 `0x0726` bit 3。
   - 风扇曲线：16 节点 UpT/DownT/Duty 占空比双通道映射表，严格执行加锁（Latch）提交流程。
3. **ITE USB HID 背光协议族**：
   - 控制芯片：ITE 8291, ITE 8297, ITE 829x。
   - 通信：通过 USB 控制传输或中断传输下发 Feature Report，支持静态色彩、呼吸、波浪、彩虹以及逐键独立寻址。
4. **外置水冷机 BLE 蓝牙遥测协议族**：
   - 蓝牙服务 UUID 与特征值：包含水泵 RPM 调节、排风扇占空比、出水/回水温度双探头遥测、水流计转速反馈。
   - 保守控制策略：解耦水泵与风扇，水泵设定恒定循环下限，彻底消除频繁启停隐患。
5. **操作系统原生抽象层 (HAL)**：
   - **Linux**：优先使用本仓库驱动提供的 `/dev/tuxedo_io` ioctl，上报为标准 Linux 子系统：`hwmon`（温控与风扇）、`platform_profile`（电源模式）、`leds`（背光）、`power_supply`（充电阈值）。
   - **Windows**：直接对接 `\\.\UniwillAcpiDriver` 或 WinRing0 / DirectIO，配合 NVAPI 与 WinRT BLE。
