# CPU 长期功耗上限

`mechrevo-power-control` 是独立、可选的用户态工具。它配置本机的 Intel RAPL
长期功耗约束（PL1），由原生 `thermald` 继续温控，也可显式提前 CPU 软件降温阈值。
它不开放 MECHREVO EC TDP
接口，也不提供 GPU、风扇或整机总功耗调节。

目前只允许以下组合：MECHREVO 旷世 16 Pro `GM6PX0X`、BIOS `N.1.09MRO07`、
Intel Core i9-12900HX、`thermald 2.5.13`，并且本机必须满足程序检查的固件、
RAPL 和服务配置条件。其他型号、BIOS、PPCC 或自适应温控平台会拒绝应用。
本次还固定已核对的发行版二进制 SHA-256；更新 `thermald` 后需要重新核验，不能仅凭版本相同放行。
命令下限为 35 W，上限不超过首次配置时保存的长期限值。55 W 的热设计参考值
用于核对本机身份，不是 RAPL 最低可写功率。35／45 W 的原生温控范围已通过源码回归，
包括继续降限、解除降温限制后回到用户上限，以及升级到下一降温设备。
各目标值的实机结果另见硬件记录；命令接受不等于厂商额定安全值或性能最佳值。

## 使用

安装独立工具包后：

```sh
sudo mechrevo-power status
sudo mechrevo-power set 55
sudo mechrevo-power set 55 --target-celsius 90 --polling-seconds 1
sudo mechrevo-power status
sudo mechrevo-power clear
```

`status` 同时报告请求值和两套实际长期限值。只存在配置文件不代表设置已生效。
`holding_scope=cpu_package_pl1` 明确 `holding_now` 只验证 PL1；`pl2_managed=false`，
`rapl_constraints` 独立显示两套 PL1/PL2 和平均窗口。诊断缺失显示 `null` / `available=false`，
记入 `diagnostic_errors`，不能把缺失解释成零或宣称 PL2 已受管。
`package_temperature` 独立报告唯一 `x86_pkg_temp` 传感器的一次实际读数：
`millicelsius` 是毫摄氏度（例如 `95000` 为 95°C），`sensor_identity` 保留解析到
`/sys/devices` 内的传感器及文件身份，`read_window_ns` 是涵盖发现、读取和身份复核的
`CLOCK_MONOTONIC` 窗口。允许的 `0..125000` 只是诊断值范围。它与
`temperature_target` 的 TCC 激活参考、软件目标是不同字段，一次采样不能证明温度受控。
传感器缺失、多重、数值无效或身份改变时，读数显示不可用，原因仅进入
`diagnostic_errors`，不改变 PL1 的 `holding_now` 或退出码；未配置时的读数也不代表硬件已通过资格验证。
状态检查发现错误（包括损坏的状态、未完成事务或上限未保持）时，仍输出 JSON，
但退出码为 1；正常的未配置状态退出码为 0，`holding_now` 为 false。
缺少状态文件但托管 XML 或服务 drop-in 仍存在时（包括断开的符号链接），也报告错误并返回 1，
保留原文件供恢复核对。`status` 是一次只读观察；配置并发修改时可能读到中间状态，
不能作为跨文件的原子快照。
状态及其嵌套的事务、初始快照和应用收据必须通过类型及一致性检查，不能将字符串
`"false"` 当作应用成功。损坏状态会阻止 set/apply/clear/recover 写入，保留原文件及运行中的温控；
应保留并核对恢复材料后修复，不能把手工删除 state 当作正常撤销或恢复流程。
`set` 设置 CPU package 的长期功耗上限，温控可以使用更低的值。未带温度参数时，
保留原生温控区、温度阈值及其他降温设备；短暂重启 `thermald` 以读取配置。
`clear` 撤销本工具配置并重启原来的温控策略；恢复后功耗限值继续由该策略决定，
不是固定写回某个旧的高限值。

程序拒绝覆盖已有的其他温控配置、其他服务覆盖文件或被外部修改的托管文件。
新恢复材料统一放在 `/home/lightjunction/Backups/projects/mechrevo-drivers/`。
发生应用失败时应查看命令错误和 `status`，不能只看退出前打印的目标值。
卸载工具前先运行 `clear`，确认温控服务仍 active，再移除工具包。

若命令被强制终止或断电，`status` 显示未完成事务，可运行 `sudo mechrevo-power recover`。
恢复命令确认原事务进程已退出、受管文件仍属于本工具后，撤销配置并恢复原温控策略；
原命令仍在运行时会拒绝恢复。不要通过手工删除 state 文件绕过这项检查。

## 提前软件降温

本机经过 CPU 型号、偏移位宽与能力位确认的只读探测显示 TjMAX 为 100°C。
本轮不同只读检查分别读到 TCC offset 5°C 和 15°C，对应触发阈值 95°C 和 85°C。
阈值会变化，修改者尚未确认，不能据此归因 thermald 或推断实体散热原因。
本轮源码与安装实例复核进一步缩小了候选范围：当前 thermald 命令没有
`--adaptive` 或 `--workaround-enabled`，本机相关 TCC sysfs 节点也不存在，
因此已检查的两条显式 TCC 设置路径不满足当前执行条件；这不排除间接固件行为。
TCC 的两个 ODM worker 虽有定时周期，`onWork` 为空，不能据周期推断它们不断抢写；
电源状态、所选 profile 或配置刷新仍可能触发 `onStart` 重新应用。
已核对的安装 ASAR 与部分构建 JS 一致，但守护进程内嵌的 V8 字节码尚未证明源码等价。

运行中的 nvidia-powerd 持有可读写 MSR 文件描述符，静态 ELF 也存在通用 MSR 写入函数，
但这些只证明能力。已识别的目标寄存器读取和遥测路径不是写入证据，
尚未闭合它实际写入 `0x1a2` 的调用链，不能将它认定为阈值修改者。

随后一次独立、限时的私有 tracefs 实机检查成功启用并清理了专属实例；
20 秒窗口内 195 次 CPU0 参考读取保持 TCC offset 15°C／触发参考 85°C，
未捕获匹配 `msr/write_msr` 的 `0x1a2` 写入事件。195 为在线累计检查数，
只保存末 16 组参考明细。全局追踪控制与受保护配置未变，
CPU buffer 统计没有丢失记录。此前两个候选均在启用事件前拒绝，失败材料保留。
这只是一次 Linux wrapper 追踪窗口，未覆盖 SMM、固件及绕过 wrapper 的直接汇编；
未捕获不能证明没有修改者，也不能据此确认是固件。IRQ／远程 IPI 里的 PID／comm
只代表执行现场，不能直接当作发起写入的用户进程。实验工具尚未加入安装包。


寄存器语义参考 [Intel Adaptive Thermal Monitor](https://edc.intel.com/content/www/us/en/design/ipla/software-development-platforms/client/platforms/alder-lake-desktop/12th-generation-intel-core-processors-datasheet-volume-1-of-2/011/adaptive-thermal-monitor/)
及固定版本 [Linux v6.12 turbostat 解码](https://github.com/torvalds/linux/blob/v6.12/tools/power/x86/turbostat/turbostat.c#L6766-L6777)，
Alder Lake 的 6 位偏移见该版本 [adl_features](https://github.com/torvalds/linux/blob/v6.12/tools/power/x86/turbostat/turbostat.c#L688-L700)。
这些链接是本诊断的固定解码依据，不表示当前最新内核实现。
此前冻结的 thermald 2.5.13 默认 CPU PASSIVE 计算曾得到 95°C，不能当作当前硬件阈值。
`--target-celsius 90` 是显式的 Linux 软件策略；只有硬件阈值为 95°C 时，数值上才低 5°C。
读到硬件阈值 85°C 时，90°C 软件目标并不早于该保护点。
它不是原厂档位、额定温度或保证永不超过 90°C 的硬上限。
新增源码中的 `status.temperature_target` 是可选的 CPU0 瞬时参考诊断，不调整 TCC。
`available` 为真时，`tjmax_celsius`、`tcc_offset_celsius`、`tcc_activation_celsius`
分别给出参考最高温、偏移及相减得到的硬件触发参考；不保证该阈值之后保持不变。
`software_target_celsius` 是受管软件目标；`software_precedes_hardware` 只比较两者数值，
不是响应速度或散热效果证明。未设置软件目标时比较值为 null。
仅在精确硬件与能力检查通过、已有内建 MSR 支持和 CPU0 设备可只读访问时提供硬件值；
不加载模块、不提权重试。权限不足或资格/读取检查失败时 `available=false`，硬件值为 null，
原因进入 `diagnostic_errors`，不改变 `holding_scope=cpu_package_pl1`、PL1 成功判断或命令退出码。
这是新增源码接口，已安装包是否包含它须分别核验。

当前只支持本机验证范围内的 90°C。此选项用有效的 `x86_pkg_temp` 传感器替换 CPU PASSIVE
控制点，并按冻结源码保留完整默认降温手段及顺序：`rapl_controller`、`intel_pstate`、
`intel_powerclamp`、`cpufreq`、`Processor`；实际不存在的设备与原生路径一样跳过。
不使用缺失传感器的错误分支来更新阈值，不改硬件 TCC、风扇表或 D-Bus 控制权限。
存在其他原生 CPU 传感器、自定义降温顺序或外来用户温度覆盖时拒绝启用，避免悄悄改变其语义。

该 90°C 控制点使用 3000m°C（3°C）滞回：达到 90°C 后可以进入降温，封装温度需回落到
87°C 以下才释放这次热限制。此前滞回为零时，1 秒轮询会在 90°C 附近反复切换 55W 与
27.5W，造成不必要的功耗和性能抖动；滞回只改变释放条件，不改变 90°C 目标、55W 上限或
硬件 TCC。实际温度尖峰和满载散热仍须通过独立观测确认。

温度目标与 XML、服务配置一起进入原有事务，包含备份、失败回滚、恢复和损坏状态检查。
`status` 的 `desired_temperature_celsius` 只是受管目标；实际温度与控制效果仍须观测。
启用目标时服务额外使用 `--loglevel=info`，便于从真实启动日志核对 CPU trip 和降温绑定；
不修改日志轮转或开放 D-Bus。更早降低功耗/频率可能影响性能。

`--polling-seconds 1` 必须同时指定 90°C 目标，将匹配平台的基础轮询缩为每秒一次。
本机原生冷态每 4 秒检查，超过 81°C 的轮询控制点后热态本来已每秒检查；
缩短基础轮询主要针对冷态突然升温的首次介入。原生降温设备的防抖和降限递进不变，
不能保证消除短时尖峰。省略此参数保持原生轮询，也保留旧版 90°C 状态的字节兼容。

连续降限还受原生降温设备默认两秒防抖控制：源码比较使用 `<= 2`，每秒检查时实际约每三秒
才推进一次。可显式使用快速 RAPL 递进，仅支持已核验的 90°C／每秒轮询组合：

```sh
sudo mechrevo-power set 55 --target-celsius 90 --polling-seconds 1 --rapl-debounce-seconds 0
```

此选项仅将 CPU trip 使用的 `rapl_controller` 的 `DebouncePeriod` 设为0，保留原生功耗范围、
递进公式、频率限制后备顺序与低温释放；不改MMIO控制器的防抖。同秒重复观察仍不连续降限。
状态字段 `desired_rapl_debounce_seconds` 只是配置目标，实际动作仍需核对日志。
省略此参数恢复原生防抖，旧版XML及状态保持兼容；更快限制功耗可能影响短时性能，
软件延迟、温度缓存与风扇响应仍可能造成超温，不能视为硬温度上限。

恢复每秒检查但撤销快速递进：

```sh
sudo mechrevo-power set 55 --target-celsius 90 --polling-seconds 1
```

恢复原生温度阈值而保留 55 W 长期上限：

```sh
sudo mechrevo-power set 55
```

`set` 不带温度参数会明确恢复原生温度策略，不会默默继承上一次的 90°C。
`clear` 则撤销整套工具配置。轮询、执行延迟和毫秒级突发仍可能造成温度尖峰。

## 本地打包

需要记录温度、PL1／PL2 和故障前样本时，可使用同包的
[`mechrevo-thermal`](THERMAL-OBSERVATION.md)。该命令只读，GPU 已失联时拒绝开始采样，
新增 Xid／不可纠正 PCIe 错误时会停止并标记结果无效。

配方在 `packaging/arch/mechrevo-power-control/`，只安装命令和说明，安装本身不会
启用功耗上限。它没有加入现有 DKMS 包，也没有作为新包发布到 AUR。
使用配方指定的源码提交构建；本地验证可以将来源切换为同一提交的本地 Git 仓库：

```sh
cd packaging/arch/mechrevo-power-control
MECHREVO_POWER_SOURCE=file:///absolute/path/to/mechrevo-drivers \
MECHREVO_POWER_COMMIT=<full-source-commit> makepkg --cleanbuild
```

不要把包含未提交更改的目录当作已经冻结的发布源码。

## 实现和边界

本机原来传给 `thermald` 的命令含 `--adaptive`，但没有可用的 INT3400 接口，
实际回退为 default engine。工具启用时明确选择 default engine 并指定独立 XML；
撤销时恢复原服务命令。没有替换 `thermald` 的二进制程序，也不开放其 D-Bus 控制权限。

XML 对 MSR 与 MMIO 两个 RAPL cooling device 同时设置范围：最高功耗为用户上限，
最低功耗按 `thermald 2.5.13` 自身的 50% 算法从该上限计算。
这里的 `MinState` 表示“最少降温、最高功耗”，`MaxState` 表示“最多降温、最低功耗”。
只修改前者可能弄反范围，使温控无法继续升级到其他降温设备，因此必须成对设置。
保留原步长后，控制状态的变化顺序会改变；这是一份带用户上限的原生温控配置，
不是原热控功率序列完全不变的承诺。

XML 本身只修改控制器缓存，不保证冷机时立即写入硬件。服务启动后的事件回调
检查两套长期约束，对高于上限的值各执行一次降限；已有更低值保持。
没有反复抢写功耗的后台循环。回调失败不会停止温控服务，但必须视为上限应用失败。

`thermald` 正常退出会恢复自身的启动快照。因此服务重启期间可能短暂回到原限值，
启动回调完成后再应用上限。服务停止期间、固件接管以及其他控制器写入不属于
持续保持保证。sysfs 没有原子比较后写入机制，初始化时也不能排除同时写入的竞争。
机器重启、睡眠恢复和 BIOS 更新需要另行验收。

这里只限制长期平均 CPU package 功耗。PL2 仍保留原策略，短时功耗可以高于 PL1；
平均窗口和能量采样也不能当成瞬时整机功耗。55 W 来自本机热设计参考值，
不是已验证的整机最大安全功耗。

需要临时验证 PL2 影响时，使用有独立恢复回执的
[`mechrevo-peak-trial`](PEAK-LIMIT-TRIAL.md)，不能把 `clear` 当作 PL2 恢复命令。

源码和测试依据为 Intel 官方 `thermal_daemon` 的
[`v2.5.13`](https://github.com/intel/thermal_daemon/tree/v2.5.13)，
冻结提交 `5fdc5bbca7f8c3f5bb2ad6540e8211a159a88a3a`。
实机结果单独记录在 [GM6PX0X 验证记录](hardware/GM6PX0X.md)，未验收项目不能由代码测试代替。
