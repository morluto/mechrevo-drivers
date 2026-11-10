# 蛟龙 16K GM6BG0Q 本机记录

日期：2026-11-07。范围：MECHREVO `Jiaolong16K Series GM6BG0Q` /
`GM6BG0Q` / BIOS `N.1.19MRO15`（2023-06-29），AMD Ryzen 7 7735H +
RTX 4060 Max-Q。以下结论来自本机 ACPI 表、只读 EC 读取、已安装驱动和
受控写入实验，不是完整兼容认证。

## 1. 身份与 ACPI 材料

| 字段 | 值 |
| --- | --- |
| `sys_vendor` | `MECHREVO` |
| `product_name` | `Jiaolong16K Series GM6BG0Q` |
| `product_version` | `Standard` |
| `board_name` | `GM6BG0Q` |
| `board_version` | `Standard` |
| `chassis_vendor` | `MECHREVO` |
| `bios_version` | `N.1.19MRO15` |
| `bios_date` | `06/29/2023` |
| EC 型号字节 `INOU.ECRR(0x0740)` | `0x10`（项目 `GK7NxxR` 一族，见主线定义） |
| EC `0x250` 起 16 字节 | ASCII `1D05128CQ1100100` |

Windows 侧导出的全部 22 张表（DSDT + 21 个 SSDT）与 Linux
`/sys/firmware/acpi/tables` 的对应表**逐字节相同**：

- DSDT SHA-256 `6634a14b56aedc2fda0edde3de8af0ebe50ca3a9311c96e8bac0edd029e6a7f5`
- ECMG / EC0 所在的 OEM 表标识：`ALASKA` / `A M I `，OEM revision `0x01072009`
- 两个导出目录中其余 SSDT 的 `sha256` 一一对应；本记录不依赖某个导出来源。

复现（只读）：

```bash
sudo acpidump -o /tmp/gm6bg0q.tables
cd /tmp && acpixtract -a gm6bg0q.tables && iasl -da DSDT.dat SSDT*.dat
```

## 2. DSDT 中与本机型相关的接口

- `\_SB.INOU`（`_HID` `INOU0000`）提供 `ECRR`、`ECRW`、`T1WR`、`MMRW`、
  `PWBT`、`PWUP` 等方法。`ECRR(addr)` 实际读取
  `MMRW(0xFED50000 + addr, 0, 0, 0)`，即 `ECMG` 内存映射窗口的 8 位值；
  `ECRW(addr, value)` 是同一窗口的 8 位写。
- `\_SB.PCI0.SBRG.EC0` 定义 `OperationRegion (ECMG, SystemMemory, 0xFED50000, 0x1000)`，
  并在字段表中给出本机命名：
  `CPTM 0x043E`、`VGAT 0x044F`、`APL1/APL2/APL4 0x0783-0x0785`、
  `APTC/APTN 0x0786`、`CTWA 0x0788`、`DBEN/DBST 0x07C4`、
  `GFID 0x07D2`、`CPUA/DBAP 0x07D4/0x07D5` 等。
- `T1WR` 的分支和参数与主线 Uniwill 定义一致：`0x81` PL1、`0x82` PL2、
  `0x84` PL4、`0x85` TCC offset、`0x1171` cTGP、`0x1173` Dynamic Boost 等。
- `\_SB.AMW0`（`_HID` `PNP0C14`）的 `_WDG` 声明
  `ABBC0F6D/E/F` 管理与 `ABBC0F6A/B/C` 旧管理 GUID，以及
  `ABBC0F70/71/72` 事件 GUID；内核 `uniwill_wmi` 使用 `BC` 管理方法。
- 本机 Windows 控制台静态材料（用户提供的逆向报告）给出相同的 EC 符号、
  `0x0751` 模式字节和 `0x0783-0x0785` PL 地址。本机只读 EC 默认值为
  Gaming `65/65/100`、Office `35/35/100`、Battery Saver `80/80/100`、
  TCC `99`。Windows Control Center 5.17.49.19 的 `UserPofiles` 则是
  Gaming `80/80/215`、Office `35/35/215`、Turbo `95/95/215`、TccOffset `5`；
  这些是软件 profile 值，不是 EC 默认值，也不是厂商安全规范。

## 3. 实机测量

### 3.1 只读 EC 快照（加载本分支驱动后）

| 地址 | 读数 | 说明 |
| --- | --- | --- |
| `0x0740` | `0x10` | 项目号 |
| `0x043E` / `0x044F` | 随负载 40–99 / 40–65 | CPU / GPU EC 温度，单位 °C |
| `0x0464`/`0x0465` | 16 位大端 | CPU 风扇 RPM |
| `0x046C`/`0x046D` | 16 位大端 | GPU 风扇 RPM |
| `0x046A`/`0x046B` | 始终 `0x41` | 不随风扇变化，不作为转速 |
| `0x0461` / `0x0469` | 请求值（0–200） | CPU / GPU 风扇占空比回读 |
| `0x078E` | `0x6C` | bit6 universal fan control、bit3 charging profile 置位 |
| `0x07C5` / `0x07C6` | 手动风扇时为 `0x80` / `0x04` | split tables / 启用自定义表；AUTO 后清零 |
| `0x0783`–`0x0785` | 默认全部 `0x00` | 未覆盖时由 EC 固件策略决定 |
| `0x07A7`–`0x07A9` | `0x50 0x50 0x64` | 控制台默认 PL 副本 |

### 3.2 风扇转速与占空比

通过 `W_UW_FANSPEED`/`W_UW_FANSPEED2` 分别设置两只风扇，等待 9–10 秒后读取：

| CPU/GPU 请求 | `0x0461`/`0x0469` 回读 | CPU RPM `0x0464:0x0465` | GPU RPM `0x046C:0x046D` |
| --- | --- | --- | --- |
| 25 / 25（被 EC 抬到 50） | `0x32` / `0x32` | 1755 | 1708 |
| 100 / 100 | `0x64` / `0x64` | 3208 | 3147 |
| 150 / 150 | `0x96` / `0x96` | 4400 | 4286 |
| 200 / 200 | `0xC8` / `0xC8` | 5431 | 5337 |
| 200 / 50 | `0xC8` / `0x32` | 5445 | 1699 |
| 50 / 200 | `0x32` / `0xC8` | 1755 | 5350 |

交叉设置证明 `0x0464/0x0465` 只跟随 CPU 风扇，`0x046C/0x046D`
只跟随 GPU 风扇；`0x046A/0x046B` 在全部采样中恒为 `0x41`。
这与主线 `uniwill-acpi.c` 的 `EC_ADDR_MAIN_FAN_RPM_1/2 = 0x0464/0x0465`、
`EC_ADDR_SECOND_FAN_RPM_1/2 = 0x046C/0x046D` 一致。
`W_UW_FANAUTO` 后 `0x07C5/0x07C6` 清零，恢复 EC 默认曲线。

### 3.3 性能模式与功耗

全部核心满载、每档保持 18 秒后取 3 秒 package 能量差：

| `0x0751` 模式 | 持续 package 功耗 | CPU EC 温度 | CPU / GPU RPM |
| --- | --- | --- | --- |
| `0xA0`（Office） | 35 W | 78 °C | 3466 / 2875 |
| `0x00`（Gaming） | 54 W | 99 °C | 4697 / 4186 |
| `0x10`（Turbo） | 53 W | 99 °C | 5431 / 5389 |

模式字节写入后能原样回读。Gaming 与 Turbo 的持续功耗相同，是因为当前
`power-profiles-daemon` 的 RAPL 约束也在限制 package 功耗；这不能证明
EC 的 65 W 与 80 W profile 在其它 RAPL 状态下没有差别。

### 3.4 TDP 写入效果

在同一模式、同一 RAPL 状态下：

1. `ECRW(0x0783, 0x23)`（35 W）后读回 `0x23`；满载 package 功耗从 54 W
   降到 **35 W**。
2. `ECRW(0x0783, 0x00)` 恢复默认；读回 `0x00`，满载回到 54 W。

因此本机 `0x0783` 是有效的 PL1 设置，`0` 表示不覆盖。PL1 是**持续**限制：
在 Turbo 模式（`0x0751=0x10`）写入 PL1=35 W 后，前 3 秒仍约 50 W、
3–6 秒约 46 W，6 秒后才稳定在 35 W。把 PL2 也写成 35 W 并写 PL4=100 W
没有消除这段短时 boost；PL2/PL4 的写入和回读成功，但本机未观察到它们
改变 boost 窗口。OEM 的 AMD profile 还会设置 SPL/SPPT/FPPT，本分支不写
这些字段。

### 3.5 键盘背光

驱动注册了单区 RGB 接口 `/sys/devices/platform/tuxedo_keyboard/leds/rgb:kbd_backlight`。
本机实测：

| sysfs 写入 | EC 回读 |
| --- | --- |
| `brightness` 0/1/2/3/4 | `0x078C` = `0x08/0x28/0x48/0x68/0x88`（bits 5–7 = 0–4） |
| `multi_intensity` `255 0 0` | `0x0769/6A/6B` = `0x32/0x00/0x00` |
| `multi_intensity` `0 255 0` | `0x00/0x32/0x00` |
| `multi_intensity` `0 0 255` | `0x00/0x00/0x32` |
| `multi_intensity` `255 255 255` | `0x32/0x32/0x32` |

颜色写入后 `0x0767` bit5（apply color）由 EC 消费并回到 0；`0x0767` bit4
（USB 供电）没有被改动。写入是异步的：sysfs 会立即回读请求值，EC 状态需要
短暂等待。恢复原始状态（`brightness=0`、白色）后 `0x078C=0x08`、
`0x0769-0x076B=0x32`。本记录只证明 EC/sysfs 一致，实体亮度、颜色和键盘
是否支持逐键 RGB 仍需机主目视确认。

### 3.6 已加载驱动的其它功能

加载本分支后以下 sysfs 属性存在并可读：`fn_lock`、`charging_profile`
（`charging_profiles_available` = `high_capacity balanced stationary`）、
`ac_auto_boot`、`usb_powershare` 和 `leds/rgb:kbd_backlight`。
读取值不写 EC。RGB 实体效果、睡眠恢复、重启保持未在本记录中验收。

## 4. 本次驱动改动

1. `mechrevo_ec_sensors`：新增 GM6BG0Q 精确 DMI 配置，GPU 转速低字节使用
   `0x046D`（GM6PX0X 保持 `0x046B`）。温度仍为 `0x043E/0x044F`，
   探测时通过 `ECRR` 核对项目号 `0x10` 与 `0x078E` bit6，不写 EC。
2. `tuxedo_io` 的 GM6BG0Q TDP 表：`PL1/PL2` 35–95 W，`PL4` 100–215 W。
   上限按 Windows Control Center 5.17.49.19 的 Gaming `80/80/215` 和
   Turbo `95/95/215` profile 设置；同一条目仍要求完整产品名和 BIOS
   `N.1.19MRO15`。高功率数值没有在本机做满载热验证。
3. 三档性能模式：把 GM6BG0Q 加入 `uniwill_profile_v1_three_profs`，
   只写 `0x0751` 的 `0xA0/0x00/0x10`，并在计算 legacy 标记之后加入，
   避免复制风扇曲线。实机 35 W 与 54 W 的差异见 3.3。
4. 延迟识别：`tuxedo_io` 可能先于 `uniwill_wmi` 初始化。此前
   `R_UW_MODEL_ID`、TDP、profile 和风扇占空比查询会一直返回 `ENODEV`，
   直到用户手动调用 `R_HWCHECK_UW`。现在首次使用会重试识别；参数校验和
   `copy_from_user` 仍在探测之前完成。

### 4.1 2026-11-07 r204 安装与运行验收

- 用本分支提交 `a8bb20f` 经 AUR 配方在本地构建
  `mechrevo-drivers-dkms-git 4.24.0.r204.ga8bb20f-1` 并安装；DKMS 只有一个
  `mechrevo-drivers` 版本，`pacman -Qkk` 为 148 个文件 0 变化。本地包不是
  AUR 发布，AUR 仍从 `main` 构建。
- 为复现启动竞争，先加载 `tuxedo_keyboard`、`tuxedo_io`，此时
  `R_UW_MODEL_ID` 返回 `ENODEV`；再 `modprobe uniwill_wmi` 后**未调用**
  `R_HWCHECK_UW`，`R_UW_MODEL_ID` 直接返回 `16`，TDP 范围为
  `35/35/100`–`80/80/100`，可用档位为 3。
- `mechrevo_ec` hwmon 注册成功：CPU/GPU EC 温度 `69/43 °C`，CPU/GPU 风扇
  `3348/3036 RPM`；同一时刻 `ECRR` 的温度与转速在相同范围。`rmmod` 后节点
  消失，`modprobe` 后只有一个节点。
- `W_UW_TDP0 = 35` 后 `0x0783` 读回 `0x23`，满载 package 功耗 35 W；
  `ECRW(0x0783, 0x00)` 恢复后读回 0，满载 53 W。`34/81` 和 profile `0/4`
  均返回 `EINVAL`，未写 EC。
- `W_UW_PERF_PROF` 的 1/3/2 分别写入并回读 `0xA0`/`0x10`/`0x00`。
- 已加载模块的 srcversion 与磁盘模块一致：`tuxedo_io`
  `65CB632BCDD17CFA054EB29`，`mechrevo_ec_sensors` `2072E2742665514F4649EFA`。
  未重启；开机自动加载和重启保持另需验收。
- 完整机器可读记录见
  [verification/gm6bg0q-r204.json](../verification/gm6bg0q-r204.json)。

### 4.2 2026-11-07 边界复验

以下每项都在写入前后读取寄存器，并在结束后恢复 `PL=0`、模式 `0x00`、
风扇 AUTO；最终快照与测试前一致（`0x0751=0x00`、`0x0783-0x0785=0x00`、
`0x07C6=0`、占空比回到 EC 自动曲线）。

| 边界 | 结果 |
| --- | --- |
| TDP 拒绝值 | PL1/PL2 `0/34/81/-1`、PL4 `0/99/101` 全部 `EINVAL`，对应寄存器不变 |
| TDP 接受值 | PL1/PL2 `35` 与 `80`、PL4 `100` 写入并回读一致；`0` 可读但驱动拒绝（低于 min） |
| PL1 持续限制 | Gaming 和 Turbo 模式下 35 W 均能把持续 package 功耗压到 35 W |
| 短时 boost | Turbo + PL1=35 时前 6 秒仍可到 46–50 W；PL2=35/PL4=100 未消除 |
| 最大 80 W | 只验证写入、回读和拒绝路径；未做 80 W 满载，原因见下 |
| 模式位 | profile `0/4/5/-1` 返回 `EINVAL`；1/3/2 写入 `0xA0/0x10/0x00` |
| full-fan 位 | `0x0751` bit6 置位时 `W_UW_FANSPEED` 返回 `EBUSY`；profile 写入保留 bit6（`0xE0/0x50/0x40`） |
| 风扇拒绝值 | `201/255/256/-1` 返回 `EINVAL`，占空比寄存器不变 |
| 风扇下限 | 请求 `25/49` 被抬到 `50`；请求 `24` 写入占空比 `0x01`，两只风扇 RPM 为 0，AUTO 后恢复 |
| WMI 移除 | 键盘平台设备消失；缓存的 model/profile 仍可读；风扇/TDP 读返回 `EIO`、模式写返回 `ENODEV`，均未写 EC；hwmon 仍可读；重新加载 WMI 后恢复 |
| 模块重载 | `tuxedo_io` 在 WMI 已存在时重载，init 即识别成功；`mechrevo_ec_sensors` 卸载/重载正常 |
| 自动加载 | `rmmod mechrevo_ec_sensors` 后 `udevadm trigger --action=add /sys/devices/virtual/dmi/id` 会按 DMI modalias 自动重新加载 |

未做 80 W 满载的原因：本机默认 54 W 持续负载已到 99 °C，且内核没有暴露
可读写的 RAPL 约束来限定实验；35 W 方向已能证明写入生效，继续加压只会
触发固件热限制，不能得到干净的 80 W 结论。

风扇表副作用：手动风扇测试使用了现有 universal fan control 路径，它会重写
`0x0F00-0x0F5F` 的自定义曲线区。AUTO 会清除 `0x07C6` bit2，EC 回到自身
曲线；本记录已按 Windows 快照恢复该区域中**有记录**的字节（含 `0xFF`
终止符），终止符之后未记录的 5 字节仍是驱动写入值。该区域当前未启用，
任何再次启用手动风扇的路径都会重新写入整张表。

### 4.3 2026-11-08 Windows 5.17.49.19 profile bounds

Windows 安装包 `UserPofiles/Mode1..3_Profile1.json` 的模式值：

| 项目 | Office (Mode2) | Gaming (Mode1) | Turbo (Mode3) |
|---|---:|---:|---:|
| PL1 / PL2 / PL4 | 35 / 35 / 215 | 80 / 80 / 215 | 95 / 95 / 215 |
| TccOffset | 5 | 5 | 5 |
| cTGP | switch 0 / 150 W | switch 1 / 150 W | switch 1 / 175 W |
| 风扇最大 duty | 55% | 90% | 100% |

驱动边界现在为 `min={35,35,100}`、`max={95,95,215}`，只通过 fixture/单元
测试验证边界和写入路径；没有把 95 W 或 PL4=215 W 写入本机 EC 做满载验收。
4.2 的 `80/80/100` 边界表和测量是 **2026-11-07 r204 历史结果**，不是当前
高功率边界的热验证。EC 默认值仍为 Gaming `65/65/100`、Office `35/35/100`、
Battery Saver `80/80/100`，与安装包 profile 分开记录。

## 5. 未验证与边界

- PL2/PL4 的实际生效范围、TCC/`0x0786`、AMD SPL/SPPT/FPPT、GPU cTGP /
  Dynamic Boost / Whisper Mode 未在本机闭环。
- OEM 风扇曲线表（`0x0F00-0x0F5F`）没有迁移或重写；手动风扇只使用现有
  universal fan control 路径和其自建表。
- 睡眠/恢复、重启后的 PL 保持、EC 版本差异、其他 BIOS、同型号不同配置
  未验收。EC 版本不是本分支的识别条件。
- OEM profile 数值来自本机 Windows 控制台静态材料；它们不是厂商公开规范。
  历史 r204 的 `PL1/PL2` 35/65/80 W、`PL4=100 W` 是当时已观察/写入成功的边界；
  当前代码按 5.17.49.19 profile 允许 `PL1/PL2` 35–95 W、`PL4` 100–215 W，
  但 95 W / 215 W 没有做满载热验证。它们**不是**建议运行值，也不保证散热或
  电源适配器余量。
- 本机 RAPL 由 `power-profiles-daemon` 管理；驱动本身不修改 RAPL、
  thermald 或平台档位。
