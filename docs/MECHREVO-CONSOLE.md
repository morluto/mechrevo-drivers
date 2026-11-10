# Rust 双端控制台

源码位于 [console](../console/README.md)，与内核驱动和 TCC 分开构建。CLI 和原生图形界面使用同一 Rust 核心。Windows 和 Linux 各有系统后端；实际功能以运行时能力结果为准。

## 设备工作台与五档性能控制（2026-11-02）

原生前端改为宽屏侧栏／窄屏顶部导航，采用石墨橄榄与象牙白两套语义配色。首页优先显示五档性能选择、真实温度趋势、电池保养、亮度与常用控制入口；请求目标与实际运行值分开，选择不立即写入，仍需预览与显式应用。详细布局及权限边界见 [界面设计](../console/DESIGN.md)。

新增 `mechrevo-performance-profile` OEM 控制，仅开放给 `MECHREVO / GM6PX0X` 的已安装可信控制器和本机保存的 tccd 配置。支持办公、游戏低噪、游戏平衡、狂暴、强冷五档，不新增寄存器或推测的功率参数，也不覆盖用户已保存的参数。缺失、重复或不可信配置不会生成可执行计划；预览绑定当前配置、守护进程身份和控制程序，应用前变化会拒绝旧计划。

```sh
mechrevo-console oem list
# 仅在枚举到此 ID 和目标后预览；去掉 --dry-run 才显式应用并请求授权
mechrevo-console oem set mechrevo-performance-profile mechrevo_turbo --dry-run
```

本轮 175 项 Rust 测试通过，格式、Clippy、rustdoc 和 Windows 目标编译检查通过。Python 全量回归执行 1101 项，其中 22 项环境相关跳过，不将跳过计为通过。候选原生 GUI 在独立 headless compositor 中读取本机状态并复核中文、性能卡片与真实温度趋势；不访问用户其他窗口。

候选 root 事务完成五档真实切换并逐档回读 tccd ID 和 CPU policy0：办公为 `balance_power`、0.8–3.2 GHz；游戏、低噪和强冷为 `balance_performance`、0.8–4.9 GHz；狂暴为 `performance`、0.8–4.9 GHz，结束恢复狂暴。这是配置及频率边界回读，不是持续运行频率、固定瓦数、灯光、实际 RPM、噪声或游戏帧率验收；普通用户认证弹窗与 Windows 硬件也不在本次证明范围内。打包固定提交与本地安装状态见 [Arch 配方](../packaging/arch/mechrevo-console/README.md)，不表示 AUR 发布。

## 无 tccd 的 EC-only 模式键（2026-11-07）

GM6BG0Q 的实体模式键已经由 `tuxedo_keyboard` 驱动确认为 WMI `0xB0`，驱动会合成
`Meta+Alt+F6`。原先的用户级 `mechrevo-gaming-hotkey.service` 在启动时调用
`com.tuxedocomputers.tccd.GetActiveProfileJSON`；本机没有运行 tccd，服务因此直接退出，
表现为按键无反应、模式灯不变。这不是 EC 未发事件，也不是 `0x782` 未使能。

新增 root 系统服务 `mechrevo-ec-hotkey.service`，执行
`mechrevo-control daemon --ec-only`：只监听 F6，通过 `/dev/tuxedo_io` 的
`W_UW_MODE`/`R_UW_MODE` 在办公 `0xA0` → 游戏 `0x00` → Turbo `0x10` 之间循环，
并逐次回读 EC 模式字节；不调用 tccd 或 D-Bus。root 权限是必要的：
`/dev/tuxedo_io` 为 `0600 root:root`，输入节点为 `0660 root:input`。

每次切模式后还会按 Windows Control Center 5.17.49.19 的 `UserPofiles` 应用
PL1/PL2/PL4：Office `35/35/215`、Gaming `80/80/215`、Turbo `95/95/215`，
通过 `W_UW_TDP0/1/2` 写入并逐项回读。`TccOffset=5`、cTGP、Dynamic Boost 和
安装包里的用户风扇表没有在本服务中写入；EC 模式字节仍负责 EC 自身的风扇策略。

切换成功后还会同步 UEFI `UniWillVariable` 的 `PowerMode`，对应关系为
Gaming=0、Office=1、Turbo=2；变量数据偏移 `0x52`（efivar 文件偏移 `0x56`，前面
是 4 字节属性）。只对精确的 `MECHREVO / GM6BG0Q / Jiaolong16K Series GM6BG0Q /
N.1.19MRO15` 生效，保留其余全部字节和属性，清除/恢复 efivarfs 的 immutable 位，
并在写入后重新读取整个变量做逐字节回读。efivarfs 对 `fsync` 返回 `EINVAL`，写入路径
按同步写处理并忽略该 `EINVAL`；其它错误仍然上报。UEFI 写失败只记录错误，不回滚已经
完成的 EC 模式切换。

```sh
# 两个热键处理者只能选一个，避免同一次按键切两档
systemctl --user disable --now mechrevo-gaming-hotkey.service
systemctl enable --now mechrevo-ec-hotkey.service
```

上一版 EC-only 服务已在本机安装并运行：启动时读到 EC `0xA0`、UEFI `PowerMode=0`；
按三次 F6 后日志为 Gaming `0x00`/UEFI 0、Turbo `0x10`/UEFI 2、Office `0xA0`/UEFI 1，
最终 EC 与 UEFI 一致为 Office。UEFI 受控写读回环验证了 `0→2→1→0` 并恢复原文件哈希；
除文件偏移 `0x56` 外无字节变化，immutable 位恢复。

新增的 Windows profile TDP 写入目前只有源码和 mock 回归，**没有把 95 W / PL4 215 W
写入本机 EC 做满载验收**；需要重载新驱动、安装新脚本并单独做受控高功率测试。这里也
不证明底盘灯珠实际亮灭、持续功耗、风扇 RPM 或 TCC profile 已被应用。

### 触控板熄屏/恢复

KDE 的触控板开关是 libinput 会话状态，不是 i2c 硬件锁。`kcminputrc` 里
`Enabled=false` 时 i2c 设备仍可能绑定；熄屏/恢复后 KWin 重新应用 per-device
状态失败，触控板就会回到默认开启。仓库的 `mechrevo-control touchpad off`
走 i2c unbind，并写入 `/var/lib/mechrevo-control/touchpad_state`。

新增 system-sleep hook `/usr/lib/systemd/system-sleep/mechrevo-touchpad`：
恢复（`post`）后读取保存状态，等待 `i2c-UNIW0001:00` 重新出现，再执行
`mechrevo-control touchpad restore`，保持关闭或开启。它只恢复由
`mechrevo-control touchpad off|on` 写入的状态；只在 KDE 里关闭不会生成该文件，
hook 因此不做任何事。

```sh
sudo mechrevo-control touchpad off   # 硬件锁，写入持久状态
mechrevo-control touchpad status     # 查看 i2c 绑定状态
```

该 hook 是 root 执行的 systemd-sleep 脚本，不依赖 tccd 或 EC-only 热键服务。

## r160 历史安装基线（2026-10-18）

`mechrevo-console 0.1.0.r160.g5542b9d-1` 已从固定提交 `5542b9d66eb3bb95b2edd07e4f2fe94afc36ea60` 构建并通过 pacman 安装。CLI、GUI、受限 OEM helper 与授权策略已落盘；21 个包文件零改动，9 个正规载荷的字节、权限及 root 归属逐项一致。release 的 31 份输入与通过 146 项 Rust、95 项 Python 检查的快照相同；release 与早期 debug 候选的二进制摘要分别保留。

安装版普通用户 CLI 的版本、状态和 OEM 枚举通过，策略注册可见。另用普通用户已安装 CLI 生成新预览，再由 root 经 `pkexec` 调用固定已安装 helper，完成两次 Fn 切换／恢复；四项控制独立回读恢复，运行保护状态保持不变。这证明已安装路径可执行，不证明普通用户管理员认证弹窗或 GUI 应用流程已验收；其余三项控制没有在这次 release 验收中写入。

安装版 GUI 在独立 headless compositor 中持续运行约 25.58 秒，1280×720 的概览、四个 OEM 选择项及 Fn 当前值面板已人工复核。没有访问其他三个面板、预览或应用，也没有通过 GUI 写硬件；自有进程均已结束。来源、包摘要、恢复材料与跟踪缺口见 [r160 部署收据](verification/deployment-console-r160.json)。

本次只更新控制台，没有更改 EFI、TCC、风扇或功耗配置，没有重载驱动或重启。磁盘驱动仍为 r158，运行中仍为 r106。Windows OEM 与 Windows 实机验收未完成；没有发布 AUR。本轮源码已在本地提交，远端推送因系统密钥环锁定待完成。

## r158 历史安装基线（2026-10-18）

`mechrevo-console 0.1.0.r158.ga190455-1` 已通过 pacman 安装，固定源码为
`a1904557bbea55f39aadab03dbc31813e64c3f9b`。
包内文件的字节、权限、root 归属和包完整性检查通过。
安装版 CLI 的状态查询与导出读到 38 个唯一读数、33 个 hwmon 输入，时间元数据及拒绝覆盖检查通过。
安装版 GUI 在独立 compositor 中持续运行 16 秒，1280×720 截图人工复核通过；仅验证概览与只读遥测，没有执行硬件控制。
应用菜单入口为“机械革命控制台”，也可直接运行：

```sh
mechrevo-console-gui
mechrevo-console status --json
```

本机安装配方见 [Arch 打包说明](../packaging/arch/mechrevo-console/README.md)，
来源、安装及验证范围见[部署收据](verification/deployment-r158.json)。
这次安装未新增常驻服务或替换 stock TCC，没有改变现有风扇／功耗配置。
同期安装的 r158 内核驱动仍待重启激活；控制台已安装不等于新版驱动已经运行。
未发布 AUR，Windows 仍只有编译检查和开发产物，没有 Windows 实机验收。
后文各次候选验收保留当时的范围，不能将其中“未安装”理解为当前安装状态。

## Linux OEM 控制

本轮源码已通过 146 项 Rust 测试、95 项 Python 检查、格式、Clippy 和 Windows 编译检查。本机四项控制完成 11 次可逆写入及 7 次写前拒绝，独立回读确认全部恢复原值，配置、服务与加载模块保持不变；候选原生窗口的概览和控制页已人工复核。[OEM 验收收据](verification/oem-controls.json)记录源码指纹、二进制摘要及具体边界。这些是 r160 构建前 debug 候选验收，18 次事务与已安装 release 的两次 Fn 验收分别记录；r158 历史基线不含这些新控制，当前 r160 已安装。完整 Windows／Linux 目标继续以 [OEM 功能覆盖](OEM-FEATURE-COVERAGE.md) 为准。

核心、CLI 和 GUI 共用 OEM 后端。它接入已加载 `tuxedo_keyboard` 驱动实际暴露并通过绑定校验的固定 sysfs 接口；2026-10-29 源码另增加原生 `uniwill_laptop` / `bitland_mifs_wmi` 的[有限接入](hardware/NATIVE-KERNEL-CONTROLS.md)，尚未安装或实机验收。不从相似型号推测寄存器。状态文档的 `oem_controls` 逐项保留 ID、类型、当前值、允许范围、来源、驱动绑定、可写状态及 `readback_scope`。没有接口就不生成控制项，接口无效或权限不足也不伪造可用状态。原生 Uniwill 布尔控制 ID 含模块与实例后缀，CLI 使用枚举给出的完整 ID；充电档位与 RGB 不在原生接入范围内。

| 控制项 | CLI 值与当前范围 | 回读边界 |
| --- | --- | --- |
| Fn 锁 | 枚举 ID `fn-lock`；`on`／`off` | EC 经加载驱动报告的状态，实体 Fn 行为与重启持久化需另验。 |
| 充电档位 | `charging-profile`；仅接受驱动列出的原始选项 | 档位不等于固定 60%／80% 阈值，回读不证明电池已实际停止充电。 |
| 键盘亮度 | 使用列出的完整 `keyboard-brightness:…` ID；整数 `0..max`，本机当前最大级别为 4 | 使用驱动给出的原始级别，不当作百分比；LED 请求状态缓存不测量实际发光。 |
| 单区键盘颜色 | 使用完整 `keyboard-color:…` ID；`'#RRGGBB'` | 仅针对识别到的单区 RGB 接口；回读请求缓存，不承诺实际颜色、逐键或多区灯效。 |
| 接电开机／关机 USB 供电 | `ac-auto-boot`／`usb-power-share`；`on`／`off` | 只有实际暴露才列出，本机未暴露；冷接电、关机供电需对应设备另验。 |

```sh
# 先查看本机真实 ID、选项和回读范围
mechrevo-console oem list
# 仅在上一步确实列出 fn-lock 时预览；不会写入或提权
mechrevo-console oem set fn-lock on --dry-run
```

CLI `oem set ID VALUE` 在没有 `--dry-run` 时生成计划并显式应用。GUI 导航中的“控制”页按选择功能、调整目标、预览更改、应用并回读的顺序执行，继续使用单个后台任务。计划记录原值、驱动与设备绑定、范围及伴随亮度；应用前重新校验，拒绝过期、绑定已变或已失效的计划。写事务、回读及恢复期间延后关窗；不自动重放旧计划。

Linux 普通用户对真实 `/sys` 的 OEM 写入由 `pkexec` 调用固定 `/usr/lib/mechrevo-console/oem-helper`。helper 重新使用 `Service::new()` 访问真实 `/sys`，校验类型化计划，并以 `flock` 互斥；不接受任意路径、替代 sysfs 根、shell 或插件。无需将整个应用作为 root 运行，也不将 sysfs 改为全局可写。授权只发生在显式应用，枚举和 `--dry-run` 不提权；随包策略对活动会话使用 `auth_admin_keep`，管理员授权可短时缓存，非活动会话要求 `auth_admin`，`allow_any` 为 `no`。helper 与策略已随 r160 安装并核对，旧 r158 不具备这条通路；当前实测范围仍按前述 root pkexec 验收区分，不扩写为普通用户认证或 GUI 应用通过。

特权 helper 必须等待真实退出，不以超时杀进程宣称写入已取消。输出失败但进程已退出时报告 `outcome_unknown`；若进程存活状态也未知，继续阻止后续写入和关窗。写入原始错误、恢复写入、恢复回读分别保留；检测到第三方修改或状态未知时不覆盖他人的值。RGB 恢复写入失败，即使 LED 缓存仍显示旧值，也按状态未知处理。这些流程不等于已完成实体恢复验收。

Windows OEM 后端尚未实现，已有 Windows 系统亮度与电源策略后端继续保留。Linux 新增的五档桥接只应用本机已保存的配置，不提供任意功率或风扇曲线编辑，不代表风扇异响已解决。性能事务若部分失败或回读不一致，报告状态未知而不自动回写旧 ID；刷新后再创建计划。充电、按键、灯光及持久化仍需在对应驱动加载版本上分别验证。

## 型号与证据

官网目录快照收录 298 条公开记录，含 178 条笔记本、70 条台式机、28 条软件、16 条外设和 6 条待分类记录。它是营销目录，不能算成 298 台已适配电脑。同一个名称可能对应多块主板和多代固件。

```sh
python -B scripts/sync_mechrevo_catalog.py --dry-run
python -B scripts/sync_mechrevo_catalog.py --check --output data/mechrevo-catalog.json
```

同步器按页校验数量、重复 ID 和总数变化，保存每页 SHA-256，网络或校验失败时保留原文件。官网没有快照令牌，因此校验完成也不能证明抓取期间绝无等量替换。

Rust 身份识别使用独立的精确规则。品牌命中仅是身份线索；GM6PX0X 的产品名、主板和 BIOS 同时命中，仍只对应历史部分实机验证。来源匹配、固件匹配、硬件验证分别表示；冲突不选择首条规则。控制台不读取序列号、UUID 或 MAC。

## 系统功能

电源策略使用 Linux `platform_profile` 和 Windows `powercfg`。这里的系统策略不等于原厂办公、狂暴或指定瓦数模式。修改先生成计划，再检查当前值，最后写入并回读；失败报告与恢复结果分开。

屏幕亮度使用 Linux backlight 或 Windows `WmiMonitorBrightness`。控制值与实际亮度分开；多屏需要选择目标。缺驱动、权限不足或不支持的目标值会返回明确错误，不显示虚构的成功状态。

遥测保留设备 ID、单位和来源。EC 温度不是 CPU 核心温度，GPU 休眠也不证明功耗为零。缺失值显示不可用。启动和查询不自动调整 GPU、风扇、充电、ICC、MUX 或功耗限值。

Linux hwmon 的传感器 `id` 使用解析符号链接后的完整输入路径，例如 `/sys/devices/…/hwmon/hwmon7/temp1_input`。旧版使用物理设备路径加通道名；同一设备的多个 hwmon 接口都含 `temp1_input` 时会发生 ID 冲突。新版把这些接口分别保留，即使读数相同也不会合并。多个 class 路径若指向同一输入，只保留排序后的第一个来源，并记录 `sensor_source_alias` 诊断。`device_id` 仍表示物理设备归属，`source.path` 仍保留实际枚举到的原始路径。

依赖旧 `id` 的消费者需要迁移已有索引；此变化仅涉及 Linux hwmon，电池等其他 ID 不变。新 ID 不保证跨重启或 hwmon 重新编号稳定。输入在枚举后消失时，优先使用解析后的父目录加文件名，仍无法解析才保留原路径。设备被报告为 runtime-suspended 时，控制台解析路径但不打开传感器输入，保留 ID 与来源，将读数标为不可用；它不会以旧读数或零值代替本次采样。

Windows 标准接口依据：[电源策略](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/powercfg-command-line-options)、[亮度类](https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmimonitorbrightness)、[亮度方法](https://learn.microsoft.com/en-us/windows/win32/wmicoreprov/wmisetbrightness-method-in-class-wmimonitorbrightnessmethods)。Linux 接口依据：[backlight](https://docs.kernel.org/gpu/backlight.html)。

## CLI JSON 与采集时间

`status --json` 和 `export --output PATH` 使用相同的状态文档结构，保留 `schema_version: 1`、原有快照字段及 `identity_evidence`，新增 `collection` 对象。导出命令另外返回导出路径等确认信息；文件内保存完整状态文档。导出使用显式路径，不覆盖已有文件或符号链接，也不自动创建父目录。

| `collection` 字段 | 含义与边界 |
| --- | --- |
| `started_at`、`finished_at` | 一次完整 `Service::snapshot()` 调用前后的系统时间，包含亮度枚举。各由 UTC Unix 纪元整数秒 `unix_seconds` 与不足一秒的整数纳秒 `nanoseconds` 组成；早于纪元的时间为 `null`。 |
| `wall_clock_status` | `ordered` 表示结束不早于开始，`moved_backwards` 表示系统时间回退，任一时间早于纪元则为 `before_unix_epoch`。有序不证明时钟已同步，也不证明绝对时间准确。 |
| `monotonic_elapsed`、`monotonic_clock_status` | 使用单调时钟计算耗时，包含快照与两次系统时间读取，以整数 `seconds`、`nanoseconds` 表示；不受通常的系统校时影响。若时钟顺序检查失败，耗时为 `null`、状态为 `moved_backwards`，正常为 `ordered`。 |
| `consistency`、`scope`、`time_basis` | `consistency` 固定为 `non_atomic_sequential_reads`；各项按顺序读取，可能对应不同瞬间或系统缓存。时间范围不包含运行环境收集、型号匹配与 JSON 序列化，不能把它当作所有传感器的同时硬件采样或新鲜度保证。其余两字段在文档内说明范围和时间基准。 |
| `tool`、`build_target` | 工具名称、Cargo 包名、包版本，以及构建目标操作系统和架构。构建目标不等于驱动版本或实机验收结果。 |
| `runtime.kernel_release` | Linux 从 `/proc/sys/kernel/osrelease` 读取运行内核版本，含 `value`、`source`、`status`，失败时附 `reason`。最多接受 256 字节，拒绝无效 UTF-8、空值和非可打印版本内容；状态为 `available`、`read_failed` 或 `invalid_data`。其他平台为 `not_collected`，值与来源均为 `null`，不推测 Windows 版本。 |

整数秒与纳秒分开保存，避免用浮点时间戳丢失精度；消费者仍须使用可保留整数精度的 JSON 解析方式。采集时间可用于关联录音和系统日志，但本身不判断风扇异响原因，也不改变风扇控制。

## 本地验证

```sh
mkdir -p .local-tests
python -B scripts/verify.py --domain console
python -B scripts/verify_console.py --output .local-tests/console-result.json
```

第一条检查 Python 同步器与验收工具契约；第二条执行 Rust 格式、测试、Clippy 和 Windows 目标编译检查。返回码 `0` 表示检查通过，`1` 表示失败，`2` 表示验证不完整。缺工具、缺目标或来源变化不能记为通过。构建记录和日志留在 `.local-tests`，不上传机器日志。

本机 Linux 运行结果、Windows 编译结果和 Windows 实机验收分别记录。交叉编译不能证明 Windows 上亮度、电源策略或厂商驱动已经运行成功。

## 设计边界
 
前期研究/设计中提出的功耗降级原因、跨机型 EC 地址、ITE 与 EC 联动、泵最低 PWM 和唤醒固定延时等主张，尚不足以作为当前实现的硬件规范。29 组内嵌配置也不能证明每台机器的出厂校准或安全上限。当前控制台没有把这些推测写入硬件。

原生界面已替换旧 Cyber-HUD，采用石墨橄榄／象牙白主题与有限的强调色，不以蓝色作为视觉方向，也不复制第三方内嵌资产。默认主窗为 1280×900 逻辑单位，宽屏采用左侧导航，窄屏转为顶部导航和单列内容。首页产品长名省略显示，完整名称可在悬停或设备详情中查看；传感器页可展开全部来源。视觉与交互约定见 [界面设计](../console/DESIGN.md)。

首页 CPU / GPU 分别显示同类当前最高读数，曲线只显示当前选定实际来源的真实温度历史，不推断物理热管拓扑。历史按机器与传感器身份隔离，每来源最多 120 点；未知读数保留断点，不补零、不补齐历史。实时采样默认开启、可关闭，距上次快照至少 3 秒且空闲时只读刷新，待确认的操作预览期间暂停；开启时空闲界面每 1 秒重绘。选中导航与常规控件的过渡为 180 ms，后台忙碌时刷新图标旋转，动画可关闭且偏好会保存。界面读取仍放在单个后台任务中，重复刷新不堆积，主线程不等待硬件调用。

电源与亮度保留预览、应用、回读、必要恢复及写事务结束后关窗的流程。有限 OEM 驱动控制与五档性能桥接沿用同一事务框架，具体失败和回读边界见前文。任意风扇曲线编辑、MUX、水冷及 Windows OEM 控制仍待完成；历史界面验收不自动覆盖新功能，也不增加 Windows 实机写入结论。

## 石墨界面改版验收（2026-10-18）

改版后的全工作区 67 项 Rust 测试通过，80 组布局场景通过；格式、Clippy 和 Windows 目标检查通过。展开全部传感器来源也执行真实宽度与末尾可达性检查。Linux 原生截图复核了滑轨、双风扇、长名称和来源展示，Windows 仍未实机运行。

新版开发包已分别链接并校验归档成员，源码摘要和产物摘要见 [改版验收记录](verification/console-ui-redesign.json)。[声音诊断工具](FAN-AUDIO-DIAGNOSTICS.md)另外通过 25 项音频回归与 16 项验收 runner 回归；它只分析已有本地录音，不是 GUI 风扇控制功能。以下保留初版的历史验收范围。

## 0.1.0 初版开发候选验收（2026-10-18）

以下为初版开发候选当时的记录：该阶段未安装、未发布 AUR，也未完成全系列或双端实机验收。GUI 依赖 Rust 1.95 以上；该轮使用 Rust 1.97。

| 检查 | 结果与范围 |
| --- | --- |
| Rust 全工作区 | 65 项通过，零忽略、零筛除；格式与 Clippy `-D warnings` 通过 |
| 原生界面布局 | 64 组场景覆盖 360×280／800×600 逻辑窗口、100／125／150／200% DPI、1.6 倍文字及不同页面；另验证写入与恢复完成前推迟关窗 |
| Python 控制台工具 | 70 项通过，覆盖静态 PE 清单、目录同步及验收脚本 |
| TCC 部署 | 工作区 TCC 域 58 项通过；隔离掉既有 UI 改动的提交版本另外通过 17 项部署回归 |
| 验收负对照 | 实际使用 `/usr/bin/true` 代替 Cargo 测试 runner，Cargo 返回 0，但验收工具正确判定为零测试、不完整 |
| Linux 运行 | 原生界面在隔离 headless compositor 中渲染并检查中文；包内 CLI 的帮助与只读状态查询通过，读到 38 项传感器及 1 个亮度设备 |
| Windows 产物 | CLI 与 GUI 均实际交叉链接出 x86_64 PE；没有 Windows 实机运行、驱动或硬件控制验收 |

本机没有暴露 ACPI `platform_profile`，普通用户也没有 backlight 写权限。这两项实际返回不可用；没有自动提权、改服务或绕过驱动。两端亮度与电源策略的成功、失败、过期计划和恢复路径由离线回归覆盖，不能据此宣称本机写入已生效。

同一份源码构建出 Linux `tar.gz` 和 Windows `zip` 开发包，归档成员逐字节校验，附 SHA-256 与来源清单。源码摘要及检查摘要见 [验收记录](verification/console-0.1.0.json)；机器原始数据、分析载荷与构建中间文件保留在本地。
