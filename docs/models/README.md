# 机械革命官方出厂硬件规格与风扇参数库

本目录归档从机械革命 40/50 系列原厂固件及逆向分析产物中提取的 **29 组官方真实机型硬件参数表**（[mechrevo_factory_models.json](file:///home/lightjunction/Documents/GITHUB/mechrevo-drivers/docs/models/mechrevo_factory_models.json)）。

## 1. 字段语义核准 (Seen 确认)

每个机型对象包含如下核心硬件规格定义：

1. **`model_id` / `bios_project_id`**：
   - 固件与 DMI 匹配标识符（例如 `GM6IX9B` 对应耀世 16 Super，`PH6TRX1` 对应蛟龙 16 Pro，`PH4AQE3` 对应翼龙/耀世系列）。
2. **`factory_specs` (出厂功耗与温控配置)**：
   - `office` / `balanced` / `turbo` 三档预设：
     - `pl1`：持续功耗上限 (W)。
     - `pl2`：短时爆发功耗上限 (W)。
     - `pl4`：硬件瞬时峰值硬上限 (W)。
     - `temp_offset`：TCC Offset 温度降额偏移（如 `temp_offset: 5` 表示 TjMax 100°C - 5°C = 95°C 触发温控降频）。
   - `base_tgp` 与 `max_db`：GPU 基础 TGP 瓦数及 Dynamic Boost 动态补偿上限（例如 150W + 25W = 175W 满血显卡释放）。
3. **`fan_tables` (16 节点出厂风扇曲线)**：
   - `cpu_upt` / `cpu_downt`：CPU 风扇升温启动点与降温回滞点（摄氏度数组，255 表示未配置/保留）。
   - `cpu_duty`：对应的 PWM 占空比阶梯（0-255 或 0-100）。
   - `gpu_upt` / `gpu_downt` / `gpu_duty`：GPU 风扇对应的双向温度节点与占空比。
   - `max_duty`：该机型允许达到的最高风扇占空比。
4. **外设与硬件能力标记**：
   - `has_water_cooler`：是否具备外置磁吸水冷端口（用于开启 BLE 水冷动力舱控制逻辑）。
   - `keyboard_type`：键盘控制器协议类型（`TypeA` 单区 RGB、多区 RGB 或逐键寻址）。

## 2. 纳入跨平台控制中心的自动化策略

在跨平台控制中心（Rust）启动时，`ModelRegistry` 模块将直接反序列化该参数库：
- 当本机 DMI 精确匹配某一项时，直接加载出厂风扇曲线和出厂功耗基线；
- 允许用户基于官方出厂风扇表进行平滑微调（贝塞尔平滑插值），杜绝因盲目猜测曲线导致机器散热不良或风扇狂转。
