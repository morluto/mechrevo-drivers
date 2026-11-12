# Mechrevo Console

独立的 Rust 工作区，包含共用核心、命令行和 Windows / Linux 原生界面。系统电源策略与屏幕亮度已有双端后端；Linux 接入驱动提供的 Fn 锁、充电档位与键盘背光控制。2026-11-02 原生工作台新增 GM6PX0X 的五档性能选择、充电快捷控制与设备入口，复用本机已有 `mechrevo-control` 和 tccd 配置，不另写寄存器或任意功率参数。机械革命控制桥接工具还负责 profile 初始化、实体性能档位灯同步和已有 TCC 的连接。Windows OEM 后端、自定义风扇曲线、MUX 与水冷等继续按[完整功能清单](../docs/OEM-FEATURE-COVERAGE.md)推进，型号目录不授予硬件写入权限。

r160 历史基线通过 146 项 Rust 测试、95 项 Python 检查、Clippy 与 Windows 编译检查；当时本机四项 OEM 控制完成 11 次可逆写入及 7 次写前拒绝验收，全部恢复原值。范围见 [OEM 验收收据](../docs/verification/oem-controls.json)，安装版本另以[部署记录](../docs/MECHREVO-CONSOLE.md)为准。2026-10-29 新增原生 Uniwill / Bitland 有限接口，范围及本轮验证见[原生驱动说明](../docs/hardware/NATIVE-KERNEL-CONTROLS.md)，未安装或实机验收。驱动回读不等于实体按键、停充或灯光测量。

后续源码补上新版内核单处理器 `platform-profile` 接口，以及无界 HPT / 星耀 P916F HPT-R 的[精确范围与固件差异](../docs/hardware/WUJIE-HPT-P916F.md)。旧聚合接口继续优先，多处理器不自动选第一个。

```sh
cargo run --manifest-path console/Cargo.toml -p mechrevo-console-cli -- status --json
cargo run --manifest-path console/Cargo.toml -p mechrevo-console-cli -- export --output /tmp/mechrevo-status.json
cargo run --manifest-path console/Cargo.toml -p mechrevo-console-cli -- models 无界
cargo run --manifest-path console/Cargo.toml -p mechrevo-console-cli -- capabilities
cargo run --manifest-path console/Cargo.toml -p mechrevo-console-cli -- oem list
cargo run --manifest-path console/Cargo.toml -p mechrevo-console-cli -- oem set fn-lock on --dry-run
cargo run --manifest-path console/Cargo.toml -p mechrevo-console-cli -- profile balanced --dry-run
cargo run --manifest-path console/Cargo.toml -p mechrevo-console-gui --features gui
```

构建和验收方式、平台边界见 [使用说明](../docs/MECHREVO-CONSOLE.md)。依赖锁定在 `Cargo.lock`。构建不安装或加载驱动，不运行 Windows 原厂程序，也不修改系统服务。

OEM 示例仅适用于 `oem list` 实际列出的 ID 和范围；预览不写入、不提权。Linux 普通用户显式应用时，经安装的受限 helper 请求管理员授权，无需把整个图形界面作为 root 运行。充电档位不等于固定百分比限充，键盘灯回读也不等于物理发光效果。完整流程见 [OEM 控制](../docs/MECHREVO-CONSOLE.md#linux-oem-控制)，五档性能桥接和本轮验证边界见该文档开头。

CLI 状态 JSON 与导出文件保留 `schema_version: 1`，新增采集起止时间、单调耗时、工具版本和运行内核信息。Linux hwmon 传感器 ID 改为解析后的输入路径，物理设备归属与原始来源路径仍分别保留；依赖旧 ID 的消费者需要迁移索引。字段范围、休眠处理及 ID 稳定性限制见 [CLI JSON 与采集时间](../docs/MECHREVO-CONSOLE.md#cli-json-与采集时间)。

官方营销目录和精确硬件身份依据分别保存在 `data/mechrevo-catalog.json` 与 `data/mechrevo-platform-evidence.json`。别名、项目号前缀、`mine` 或自定义功耗配置不能替代硬件识别。
