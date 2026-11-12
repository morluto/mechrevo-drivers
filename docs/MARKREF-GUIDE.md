# markref 标签维护与代码文档追溯规范

日期：2026-10-18
工具路径：`/home/lightjunction/.cargo/bin/markref` (版本 0.2.2)

---

## 1. 为什么引入 markref

在大型跨平台软硬件适配项目（如本项目驱动层与控制中心）中，功能特性（如功耗锁定、风扇加锁写入、电池阈值、ITE RGB 灯控等）往往分散于多个文件（内核驱动、头文件、用户态工具、技术文档、回归测试）。

`markref` 提供了基于源码与文档注释的轻量级特征标签（Feature Marks）追溯体系：
- 零外部元数据依赖，直接通过代码和配置中的单行注释进行声明；
- 具备严格的近邻符号校验（声明标签后 24 行内必须有目标代码/配置实体）；
- 杜绝死链接、悬空功能声明与隐式破坏。

---

## 2. markref 语法与支持规范

### 2.1 基础语法
```
<注释前缀> @mark <label> [role=<role>] [contract=<contract>]
```

| 参数 | 说明 | 示例 |
| --- | --- | --- |
| `<label>` | 特征命名空间标签，点分小写命名 | `mechrevo.ec_bridge`, `mechrevo.fan_latch` |
| `role` (可选) | 标签角色：`specification` (规范/定义), `implementation` (具体实现), `verification` (测试验证), `authority` (核心判定) | `role=specification` |
| `contract` (可选) | 契约或协议描述 | `contract=atomic_rmw` |

### 2.2 各语言注释语法支持 (Scan Matrix)
- **C / C++ / Rust / JS / TS** (`.c`, `.h`, `.rs`, `.js`, `.ts`)：
  ```c
  // @mark mechrevo.fan_curve_latch role=implementation
  int uniwill_write_fan_table_with_latch(...)
  ```
- **Python / Shell / YAML / TOML** (`.py`, `.sh`, `.yml`, `.yaml`, `.toml`)：
  ```yaml
  # @mark mechrevo.driver_manifest role=specification
  name: mechrevo-drivers
  ```
- **HTML / XML / SVG** (`.html`, `.xml`, `.svg`)：
  ```html
  <!-- @mark mechrevo.ui_hud_topology role=presentation -->
  ```

---

## 3. 本项目标准标签命名空间 (Namespace Taxonomy)

| 命名空间 | 覆盖范围 | 规范定义位置 | 核心实现与验证位置 |
| --- | --- | --- | --- |
| `mechrevo.model_registry` | 全机型 DMI 与出厂规格矩阵 | `docs/MECHREVO-ALL-MODELS-MATRIX.md` | `src/tuxedo_compatibility_check/` |
| `mechrevo.ec_bridge` | EC RAM 寻址与原子读改写 | `docs/OEM-FEATURE-COVERAGE.md` | `src/uniwill_interfaces.h` |
| `mechrevo.power_control` | CPU PL1/PL2/PL4 硬件钳位 | `docs/POWER-CONTROL.md` | `src/tuxedo_io/tuxedo_io.c` |
| `mechrevo.fan_curve` | 16 节点风扇曲线与 Latch 加锁 | `docs/models/README.md` | `docs/models/mechrevo_factory_models.json` |
| `mechrevo.battery_sentinel`| 充电阈值、AC/PD 感知与防覆盖 | `docs/CHARGING-TRANSACTIONS.md` | `src/uniwill_interfaces.h` |
| `mechrevo.lighting` | ITE 829x USB HID 与双重关灯 | `docs/CROSS-PLATFORM-CONTROL-CENTER-DESIGN.md` | `src/ite_829x/` |
| `mechrevo.water_cooler` | BLE 外置水冷微循环与遥测 | `docs/CROSS-PLATFORM-CONTROL-CENTER-DESIGN.md` | 控制中心 BLE 驱动器 |
| `mechrevo.replay_watchdog` | 睡眠唤醒状态自动重放总线 | `docs/ADAPTATION-STATUS.md` | 唤醒事件监听器 |

---

## 4. 常用维护命令

1. **检查全仓标签合法性与悬空状态**：
   ```bash
   markref check --include-untracked
   ```
   若标签下方 24 行内缺少有效代码实体或语法错误，将返回具体行号诊断报错。
2. **列出当前所有已注册的特征标签与位置数量**：
   ```bash
   markref list
   ```
3. **精准展示某项标签的所有引用位置与代码切片**：
   ```bash
   markref show mechrevo.power_control
   ```
4. **获取特征的紧凑拓扑上下文**：
   ```bash
   markref context mechrevo.fan_curve
   ```
