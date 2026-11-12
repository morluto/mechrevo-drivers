# 跨平台机械革命控制中心架构与设计规范 (Rust)

日期：2026-10-18
设计目标：
1. **全平台统一内核**：一套 Rust 核心业务层，同时原生运行于 **Linux** 与 **Windows**。
2. **极客 HUD 界面规范（禁止雷同）**：彻底推翻现有 Electron / Win32 控制中心单调卡片堆叠风格，采用赛博机甲电竞 HUD 仪表盘交互系统（Cyber-HUD Dashboard），信息层级高密度、可视化曲线直观。
3. **功能全集超集**：覆盖并超越官方 Control Center 的全部能力，全面解决已知的所有缺陷。

---

## 1. 软件架构分层 (Architecture)

```
+-------------------------------------------------------------------------+
|                  Cyber-HUD UI Layer (前端展示层)                        |
|  - 实时机甲能耗拓扑图 (CPU/GPU/EC/VRM 温度 & 功耗热力球)                |
|  - 16 节点双轨平滑贝塞尔风扇曲线绘制器 (带实时转速与温度锚点吸附)       |
|  - 智能电池健康管家 (3 档阈值 + 自定义 % + PD/DC 差异化策略)           |
|  - 全息矩阵灯光工作台 (静态/动态/音乐律动/逐键自定义/A壳透光Logo)        |
|  - 水冷智能控制中心 (解耦循环水泵与水排散热，状态动画与流速计)          |
|  - 快捷模式抽屉与系统托盘 Mini HUD 悬浮球 (自适应 DPI 与多显示器)       |
+-------------------------------------------------------------------------+
                                    | IPC (Tauri 2 / WebSocket / JSON-RPC)
+-------------------------------------------------------------------------+
|                   Rust Core Engine (跨平台业务核心)                     |
|                                                                         |
|  - TelemetrySupervisor: 高频低开销硬件遥测 (CPU/GPU功耗、双扇RPM、温度) |
|  - ProfileSupervisor: 性能档位状态机与 MSR/MMIO PL1/PL2/PL4 智能钳位   |
|  - FanCurveManager: 16 节点出厂风扇表、实时 Latch 校验与双向温度回滞    |
|  - BatterySentinel: 充电阈值守护、AC/DC/PD 动态感知与原子位操作保护      |
|  - LightMaster: ITE HID 与 EC 背光协同控制器，多区 RGB 与防闪烁驱动     |
|  - WaterCoolerEngine: BLE 自动发现、保底微循环、重连状态机              |
|  - ModelRegistry: 全系机型库 (出厂预设、通用回退策略、宝龙达屏障隔离)   |
|  - ReplayWatchdog: 睡眠/唤醒 (S3/S0ix) 事件总线，唤醒后自动重放恢复状态 |
+-------------------------------------------------------------------------+
                                    |
                 +------------------+------------------+
                 |                                     |
+------------------------------------+ +----------------------------------+
|           Linux HAL Layer          | |        Windows HAL Layer         |
|  - /dev/tuxedo_io (ioctl 事务接口) | |  - \\.\UniwillAcpiDriver (PnP)   |
|  - /sys/class/hwmon (温度/RPM/PWM) | |  - WinRing0 / DirectIO (EC RAM)  |
|  - /sys/firmware/acpi/prof         | |  - NVAPI (GPU 遥测与时钟)        |
|  - /sys/class/power_supply         | |  - Windows.Devices.Bluetooth     |
|  - BlueZ BLE D-Bus API             | |  - Win32 PowerBroadcast API      |
|  - systemd-logind 睡眠事件监听     | |  - Windows PPM 电源方案覆盖接口  |
+------------------------------------+ +----------------------------------+
```

---

## 2. 界面设计独创性与禁止雷同规范 (UI Innovation)

为坚决杜绝与任何现有软件（如原厂 GCUService 或 TCC）界面风格雷同，跨平台控制中心采用独创的**全息机甲电竞 HUD（Cyber-HUD）设计语言**：

### 2.1 视觉与布局创新
1. **能耗与散热全息拓扑（Core Flow Topology）**：
   - 放弃传统孤立的数字卡片，使用中央三维热流管线拓扑图：清晰展现热量从 CPU (HX) / GPU 经由热管、均热板流动至双散热风扇及外置水冷排的动态粒子流速，粒子速度与风扇实际 RPM 成正比，颜色随核心温度从冷蓝、金橙至赤红渐变。
2. **双通道 16 节点交互式贝塞尔曲线编辑器**：
   - 采用对数响应坐标系，同时呈现 CPU 与 GPU 独立的上升温（UpT）与下降温（DownT）回滞曲线。
   - 悬浮显示出厂预设参考线、静音区间、狂暴临界点，并提供鼠标一键平滑插值（Auto-Bezier Smoothing）。
3. **水冷动力舱仪表盘（Cooling Reactor Gauge）**：
   - 模拟液冷反应堆仪表盘，将出水温度、回水温度、水流计脉冲（L/min）、水泵转速与排风扇 PWM 整合为环形多维罗盘，直观提示冷却增益（Delta T）。
4. **轻量化 Mini HUD 侧边抽屉与悬浮岛**：
   - 完全自适应高 DPI（100%、125%、150%、200%），杜绝在 125%/150% 缩放下的按钮裁切与窗口错位问题；提供全局快捷键（如 `Ctrl+Shift+F1`）呼出半透明毛玻璃悬浮 HUD。

---

## 3. 功能全集与超集设计 (Feature Superset)

本方案不仅涵盖原版控制软件的全部功能，更针对现有痛点提供全面超越的超集能力：

### 3.1 性能与功耗调节 (Power & Tuning)
- **四档出厂模式 + 无级自定义狂暴模式**：
  - 办公（Office，低噪 35-45W）、平衡（Balanced，全能 65-75W）、狂暴（Turbo，激进 115-140W）、水冷极限（Extreme，最高 205W+）。
- **PL1/PL2/PL4 硬件钳位守护**：
  - 在 Linux 下利用 MSR、MCHBAR MMIO 与 EC 真实入口 `0x0783..0x0786` 联合写入；解决 Issue #115 功耗被 EC 锁死在 65W 的历史顽疾。
- **离电自适应与 PD 适配器感知**：
  - 精准区分传统 DC 适配器供电与 Type-C PD 100W/140W 握手供电（解决 Issue #96）；允许用户单独定义“离电/电池模式下的性能档位”（解决 Issue #105）。

### 3.2 散热与风扇工程 (Thermal Engineering)
- **出厂 16 节点转速表直读与回写**：
  - 完整加载各型号官方 BIOS 出厂风扇表（包含 GM6、PH4、PH6、GX4 全系列）；
  - 严格遵守加锁事务流程（Latch Write），解决 2024 款蛟龙 16 Pro 风扇失控问题（解决 Issue #108）。
- **一键极速强冷（Fan Boost）与瞬间退出平滑衰减**：
  - 支持实体热键与软件触发 100% 全速强冷，退出强冷时引入 3 秒转速平滑阶梯过渡，避免转速骤降产生电机刺耳啸叫。
- **外置水冷机微循环守护**：
  - 解耦水泵控制与排风扇控制；水泵保持保底微循环（解决 Issue #114），防止低负载关泵导致热冲刷。

### 3.3 智能电池哨兵 (Battery Sentinel)
- **多档健康养护模式**：
  - 长寿办公（60% 阈值，适合长期插电）、平衡日常（80% 阈值）、最大续航（100% 满电）。
- **全机型协议兼容与原子位操作**：
  - 兼容老款钛钽/深海泰坦模具（解决 Issue #111）与现代 40/50 系模具；
  - 严格采用位掩码原子读改写，杜绝在修改充电上限时意外冲掉性能指示灯（解决 Issue #92）。
- **断电/睡眠唤醒自动重放**：
  - 监听电源插拔事件，在适配器重新接通后自动维持设定的充电上限。

### 3.4 光效与外设管理 (Lighting & Peripherals)
- **ITE HID 与 EC 双重同步熄灯**：
  - 彻底解决无法熄灯与灯光错乱（解决 Issue #110, #91, #99）。
- **A 壳透光 Logo 与独立灯条支持**：
  - 开放耀世 16 Pro 等机型的 A 面灯效独立调节（解决 Issue #103）。
- **Fn 锁、Win 键锁与触控板物理锁定**：
  - 支持开机自启保持锁定状态；修正不同 BIOS 的 Fn 键映射错位（解决 Issue #102）。
- **屏幕色彩与亮度预设联动**：
  - 支持模式与屏幕亮度深度联动（解决 Issue #113），加载 ICC 校色配置文件（解决 Issue #100）。

---

## 4. 跨平台 Rust HAL Trait 接口定义

控制中心将底层操作系统差异完全隔离在硬件抽象层（HAL）之后：

```rust
/// 跨平台硬件抽象层统一 Trait
#[async_trait::async_trait]
pub trait HardwareAbstractionLayer: Send + Sync {
    /// 获取当前机型信息与 DMI 探测结果
    async fn detect_model(&self) -> Result<DetectedModelInfo, HalError>;

    /// 读取实时遥测数据 (CPU/GPU 温度、功耗、风扇转速、电源状态)
    async fn read_telemetry(&self) -> Result<TelemetryData, HalError>;

    /// 设定运行模式 (包含功耗限值与 TCC offset)
    async fn apply_power_profile(&self, profile: &PowerProfileConfig) -> Result<(), HalError>;

    /// 写入 16 节点双通道风扇曲线
    async fn write_fan_table(&self, table: &DualFanCurveTable) -> Result<(), HalError>;

    /// 切换一键强冷状态
    async fn set_fan_boost(&self, enabled: bool) -> Result<(), HalError>;

    /// 设定电池充电阈值 (0-100%)
    async fn set_charge_limit(&self, limit_percent: u8) -> Result<(), HalError>;

    /// 控制键盘背光 (颜色、亮度、动效模式)
    async fn set_keyboard_lighting(&self, config: &LightingConfig) -> Result<(), HalError>;

    /// 设置辅助硬件状态 (Fn锁, Win键锁, 触控板, 摄像头授权)
    async fn set_hardware_switches(&self, switches: &HardwareSwitches) -> Result<(), HalError>;

    /// 注册系统电源事件钩子 (S3/S0ix 睡眠准备与唤醒重放)
    async fn subscribe_power_events(&self, sender: tokio::sync::mpsc::Sender<PowerEvent>) -> Result<(), HalError>;
}
```

- **Linux 实现**：绑定 `/dev/tuxedo_io` ioctl 命令集，直接复用本仓库经过严格单测与验证的内核驱动能力；
- **Windows 实现**：绑定 `\\.\UniwillAcpiDriver` 符号链接与 WinRing0 / NVAPI 接口；
- **核心业务层**：零平台相关代码，纯 Rust 异步运行时调度（Tokio），全面保证内存安全、零崩溃与高并发响应。
