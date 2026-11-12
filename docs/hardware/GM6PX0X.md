# 旷世 16 Pro GM6PX0X 本机验证

日期：2026-10-14；2026-10-15／16／17／18 续验（Asia/Taipei）。这是单台机器的部分功能验证，不是完整兼容认证。

当前状态与剩余验收见[适配进度](../ADAPTATION-STATUS.md)。以下各节为历史记录，包版本和运行结论以各节时间为准。

## 2026-10-23 低速风扇配置调整

本机运行内核 `7.2.11-arch1-1`、驱动包 `4.24.0.r165.gfc48597-1` 和
stock TCC `3.0.10-1`；`tuxedo_keyboard` 运行与磁盘 srcversion 均为
`5899CC006083121EA48734C`。用户报告风扇偏慢，读取到狂暴模式下 CPU 约 61°C、
CPU 风扇约 1750 RPM、GPU 风扇约 3343 RPM。未复现驱动读取错误。
模式切换时的风扇重新初始化由用户测试触发；未开启采集时 D-Bus 速度 `-1`
是 TCC 的既有行为，均不作为故障依据。

办公配置已有 60% 最低转速，但游戏、狂暴与默认配置仍为 0%。本轮仅将这三个
现有配置的 `minimumFanspeed` 提到 60，保留其余字段、100% 上限和温度调速。
通过 SIGHUP 重读配置后，活动狂暴模式回读为 60；26 个约一秒间隔样本中
CPU 风扇为 2619–2782 RPM、GPU 为 3599–3855 RPM，CPU EC 温度为 59–60°C。
自然负载下的这段观察证明最低请求与转速发生变化，不证明满载散热、其他模式的
物理效果、重启保持或其他型号兼容。百分比请求也不等于固定机械转速。

源码中的办公、游戏、狂暴新建配置采用相同 60% 下限；同步逻辑仍保留已有用户
配置，不自动覆盖旧下限。已有安装需要单独调整其配置。原配置及采样保存在
`~/Backups/mechrevo-drivers/light/2026-10-23/fan-floor/`，私有日志不提交。
未更换内核模块或 TCC 包，未发布 AUR。

## 2026-10-24 thermald 功耗抖动修复

只读检查发现当前受管 `thermald` 配置在 `x86_pkg_temp` 达到 90°C 时，日志反复记录
`rapl_controller` 在 55W、48W、34W 和 27.5W 之间切换，随后在温度回落后立即回到
55W。该循环与 1 秒轮询和原先的零滞回一致，会把温度采样噪声变成可见的功耗／性能抖动；
它不是风扇 RPM 读错的证据。

源码把这个已限定在 GM6PX0X / N.1.09MRO07 的 90°C 软件控制点改为 3°C 滞回：降温动作
仍在 90°C 触发，需低于 87°C 才释放热限制。55W 上限、双 RAPL 接口、原生降温设备顺序
和硬件 TCC 均不变。离线功耗回归覆盖 124 项且通过。

本机随后备份旧状态，先用旧版工具清除原配置（两路 PL1 回到 140W），再安装固定源码
`c60aee5e6ffe8ac46a57a7922112a79ae1b063df` 构建的 `mechrevo-power-control 0.1.0-19`，
重新设置 `55W + 90°C + 1 秒轮询`。安装后的 `thermald` 日志解析到 `hyst:3000`，两路
PL1 回读均为 55W，服务 active，`pacman -Qkk` 为 22 项零改动。复核时 CPU package 约
83–85°C、CPU/GPU 风扇约 3575/4939 RPM；当时系统 load 约 26–29，属于背景负载观察，
不能当作满载性能、长期稳定性或完整散热验收。恢复材料在
`~/Backups/projects/mechrevo-drivers/light/thermal-hysteresis-20261024/`。

## 2026-10-18 r158 驱动与 Rust 控制台部署（待重启）

固定干净源码 `a1904557bbea55f39aadab03dbc31813e64c3f9b` 构建的两个包已实际安装：
`mechrevo-drivers-dkms-git 4.24.0.r158.ga190455-1`、
`mechrevo-console 0.1.0.r158.ga190455-1`。
安装文件的字节、模式、root 归属及 `pacman -Qkk` 检查通过。
内核 `7.2.9-arch1-1` 与 `7.2.7-arch1-1` 各安装 28 个模块，56 份模块均通过系统公开证书的 CMS 验签；
实际损坏内容的负对照被拒绝。构建和验签不能代替启动及硬件验收。

签名启动镜像已发布至 `/efi/EFI/Linux/omarchy_linux.efi`，主菜单已同步其摘要。
新镜像仅替换 r106 启动 initrd 中的四个 Mechrevo 模块；
其余 255 个模块及主 zstd 载荷保留原字节。
原有 NVIDIA 核心模块的磁盘构建与当前运行／旧镜像构建不同，本次保留旧镜像的 NVIDIA 字节，
没有将这项既有差异算作 NVIDIA 修复。`sbverify` 验签通过，Secure Boot 当前关闭，尚未实际启动新镜像。

没有热重载或重启。当前 `7.2.9-arch1-1` 下六个运行核心模块的身份仍为 r106，
不能写成 r158 已运行。TCC 的 profiles／settings、风扇与功耗配置、
`tccd`／`thermald`／`nvidia-powerd` 及旧 `mechrevo-control daemon` 的进程身份均保持。
既有键盘映射移至 `/etc/udev/hwdb.d/90-mechrevo-local.hwdb`，更新数据库后实际查询结果不变。
Rust 图形界面入口为应用菜单“机械革命控制台”，CLI 入口为 `mechrevo-console`；
没有新增常驻服务，也未替换 stock TCC。

Recovery 菜单仍指向原 `/efi/EFI/Linux/omarchy_linux_r106.efi`。
它只恢复启动镜像与 initrd，不会自动回退根文件系统中的软件包。
新的恢复材料统一存于 `~/Backups/mechrevo-drivers/light/2026-10-18/deploy-a190455/`；
旧 r106 恢复包及 56 个签名恢复模块仍保留原位置。
本轮构建及安装的文件跟踪保留 partial 缺口，不能用后验载荷核对补称完整写入历史。
公开版本、摘要和验收范围见[部署收据](../verification/deployment-r158.json)。

本次未发布 AUR、未执行 Windows 实机验收，也未解决风扇异响、温度尖峰或 NVIDIA 长期稳定性。
硬件验收仍为 **9/20**；下一阶段是重启后核对实际加载身份，再逐项验收硬件功能。

## 2026-10-18 IO 模块身份只读复核（部署前）

内核 `7.2.9-arch1-1`，已安装 `mechrevo-drivers-dkms-git 4.24.0.r106.gaaf6b36-1`。
从磁盘模块 ELF 与 `/sys/module/tuxedo_io/notes/.note.gnu.build-id` 分别读取身份：
两者 GNU build ID 均为 `a0aeba3f4ea1cd34f3e88b6f255224ec2b0381ac`，
srcversion 均为 `36810A4292AEA1531F6D02B`。这更新了此前 IO 仍运行 r37 的历史结论，
但不补称其他模块也已复核。

本轮未安装/加载新模块，未切换服务或写入功耗、风扇、EC 控件。
未绑定特征保护的模拟回归和编译属于源码验证，不是本机 NULL 故障复现、
transport 并发解绑修复或风扇噪声的实机验收；硬件验收评分不变。
私有身份与配置快照保存在 `.local-tests/console-redesign/driver-continuation/runtime-before.json`。

## 2026-10-17 功耗试验恢复修复 r17 与快速采样

`mechrevo-power-control 0.1.0-17` 已安装，候选 70499 字节，SHA256：
`50b327b63d62dbfaa4e73724dfa71c71be100e967799625f82b38a8c86667d80`。
固定源码 `a07327a656e3b620b9d5cf944928529b64ca09d4`；相对 r16 仅 `peak_limit_trial.py` 改变。
关闭监测的异常现在不会跳过条件恢复或最终回执；各阶段错误独立保留。
180 项功耗回归与 8 项打包回归由根代理独立通过，旧实现对应负例保留。

实际宿主 libalpm NOLOCK 准备及紧邻安装的再次准备均为单升级、零删除，已释放句柄；
这些准备不代替安装时文件冲突检查或签名验证。实际 pacman 升级 exit0，
22 项包完整性检查零改动，10 个安装文件的字节、模式及 root 归属一致，安装入口 `--help` 成功。
升级前后保护配置、服务及 GUI 进程身份、已加载模块、boot/CPU online 和其他包记录一致；
PackageKit 保持 inactive/PID 0。使用已审私有 HookDir，不改系统 hooks 或服务。
所选输出、载荷、包数据库、日志及锁目录的安装跟踪为 complete/0 gap/0 unresolved；
`/usr` 父时间戳不在跟踪根内，不能称为整个文件系统写入历史完整。
原 r16 恢复包保留，没有执行回退或新的功耗试验；这不是热恢复效果的实机验收。
安装材料归档于 `power-control-r17-installed-20261017/`，20 个载荷、10,679,839 字节，
根代理以外部清单 SHA 独立核对内容、模式、归属和时间戳；没有重复复制原 r16 恢复包。
本轮源码与配方已推送，未发布 AUR 制品。

安装前另做一次独立的自然负载采样，仅使用 coretemp、package energy、每 CPU `/proc/stat` 和已有双扇 RPM 接口：
100 帧、2100 次读取，采样 10.000081795 秒；每帧最大 4.795ms，无漏周期。
封装 66–96°C，最高核心 97°C；CPU/GPU 风扇分别 2826–3332 / 4171–4427 RPM。
99 个约 100ms 能耗区间的平均功率为 9.9999–65.6115W，没有计数回绕；
2376 个每 CPU 区间增量均非负。包温 96°C 出现在帧 59–69 和 81–91，
最大能耗区间却是帧 16–17；不能据此直接建立或排除瞬时因果。
100ms 轮询不保证硬件温度按此周期刷新，缓存和热滞后未量化。
没有新增压力、trace、MSR/EC 写入、策略或服务动作；前后保护配置、进程身份、boot/online 一致。

原始采样 SHA256 `e64c84974f780b73c29d59a77fc8416abc875821ad97d62828b7a9e5898ed922`，
采样跟踪 `2ecedeac` complete/0 gap/0 unresolved。原始数据与分析保存在统一 Backups 的
`natural-thermal-10s-20261017/`，5 个载荷 2,534,867 字节由根代理独立读回；
备份清单绑定内容/大小，未包含完整元数据字段，未把缺失字段补称已绑定。
硬件验收仍为 9/20，热尖峰和动态温度参考修改者仍未解决。

## 2026-10-17 控制中心 pkgrel6 生产交付（未安装）

`dbbc614` 的温度异常反馈修复已完成生产构建与私有候选打包。
实际包内 Worker、FanData、D-Bus getter 和三语言界面消费者的来源已核对；
七组新异常测试通过，旧 pkg5 的六组负例命中具体失效断言。
根代理独立核对 67 个载荷项、33 个普通文件及三份元数据，并完整读回 147 份归档。
包 SHA256 为 `1779b24e4d37261fb881441afbc097e9b70bd2536327bc753c4477784897cd65`。

源码、构包和运行状态分开：当前仍运行 stock TCC 3.0.10-1，未安装或执行这个候选，
未停止 GUI／服务或写入硬件。构建固定旧源码提交；后续 `0bbaf09` 只修测试命令日志重跑覆盖，
不改变该候选载荷。新日志回归的五项独立测试通过，旧入口实际复现四次调用只留下两条记录。
旧 Settings 使用 `settings-001.json`、Fan 使用 `001.json`；同一次不同类运行必然互相覆盖的旧推断不成立。
已经核实的问题是相同 suite 在同目录重跑、计数归零后覆盖；新入口每条独占创建文件，历史记录不补造。

生产候选的准备与打包各保留一处跟踪缺口；生产构建及最终独立包审查完整。
这些成功不代表实机风扇恢复、持续散热或完整 Windows 移植通过，验收仍为 9/20。
原始收据、首次三语言提取拒绝及恢复材料均保留在本地，详见
[生产候选说明](../../packaging/arch/tuxedo-control-center-mechrevo/README.md#pkgrel6-production-candidate-2026-10-17-not-installed)。

## 2026-10-17 自然负载下的温度功耗与风扇

在同一 boot、内核 7.2.9 和已安装观察器 r16 下，另做一次只读自然负载观测。
13 个样本的实际 CPU 温度首末读取中点相隔 12.000373 秒；单个顺序采样窗口最长约 124.38 ms。
未增加压力负载，未停止背景任务或执行功耗、风扇、服务、驱动及固件切换。

| 观测项 | 本次结果 |
| --- | --- |
| 原生 `x86_pkg_temp` CPU 封装温度 | 74–97°C |
| 包能量差计算的区间平均耗电 | 18.31–37.84 W；全段加权平均约 29.10 W |
| 整机 CPU 忙碌比例 | 每区间约 6.13–24.86%，均值约 12.47%；不是单核占用率 |
| CPU 风扇实际接口读数 | 2487–3194 RPM |
| GPU 风扇实际接口读数 | 3915–4427 RPM |
| 三次 GPU 查询 | P8、56°C、5.03–5.14 W；利用率 0%、12%、0% |
| 当次 MSR / MMIO PL1 限值 | 27.5–55 W / 55 W，允许现有温控进一步下调 |

实际温度使用已安装的 `mechrevo_power.py` 原生 getter，源码 SHA-256 为
`d1e17518587105c6e9137b5e776e1124918127e7bf79cad5f14ef98fa1abe25f`。
功率由 `intel-rapl:0/energy_uj` 差值及读取中点间隔计算，按计数器模数处理一次回绕；
不是由 PL1 限值推算，也不归因到某个进程。
CPU 忙碌比例取 `/proc/stat` 前八项增量，扣除 idle/iowait，排除重复统计 guest。
进程增量仅配对 PID 和启动时间相同的对象；新生及退出进程未纳入该配对表。
后台任务及观察器本身有 CPU 开销，因此该记录不能称为空闲基线。

EC CPU 温度与原生封装温度的顺序读数最多相差 21°C；没有同时采样，
也未测得固件刷新时序，不能据此判定缓存错误或传感器错误。
当前 TCC 设置 `fanControlEnabled=false`。只读 RPM 及该设置均不足以证明固件曲线的控制权、
机械实际转速或散热效果已经验收；热尖峰与动态温度参考修改者仍未解决。
本次没有读取新 MSR 写事件或检查新增 GPU 内核故障，不能补称长期稳定性通过。

五个受保护配置 SHA、指定服务 PID/启动时间、boot 与 CPU online 起止一致。
私有原始记录为 `.local-tests/postboot-20261016/thermal-iterate/cpu-fast/native-load-observation-20261017/receipt.json`，
271078 字节，SHA-256：`735338690e45bdcccb8652715bce99d950d834ab13d5bceba0f294818e213d34`。
跟踪 `bd12be12-93fb-4169-9457-d20f9c7896d3` 命令成功、complete、0 gap、0 unresolved；
这不补全此前安装的 partial 历史。原始进程资料留在本地，不公开完整机器日志。
验收分数仍为 9/20。

## 2026-10-17 观察器 r16 已安装并核验

`mechrevo-power-control 0.1.0-16` 已完成单次安装，包 SHA-256：
`9d88c3ca3c245123e9464af4734ffa5dd746276ae2531acd0c1c1d11aa470516`。
固定功能源码为 `2e76e5a174c69ec8e9a060d751d15e2bfb53b02c`；
10 个载荷的字节、模式和 root 归属逐项一致，`pacman -Qkk` 为 22 项、0 改动。
141 项功耗与温度回归、8 项包装测试的范围及候选阶段另见后文历史记录。

安装后的实际入口成功返回 `package_temperature.available=true`、87°C 和传感器身份／读取窗口，
`errors`、`diagnostic_errors` 均为空。两套 PL1 限值当次为 34.5W／55W，
`holding_now=true`；这些是限值，不是测得的实际耗电功率。
没有调整策略，单次温度不能证明热尖峰已经修复。

五个受保护配置、四个指定进程身份、boot、加载模块及既有全局追踪状态前后相同，
PackageKit 保持 inactive／PID 0；未执行 TCC／thermald 切换、驱动加载或功耗／风扇设置。
安装使用已审查的私有 HookDir 覆盖；实际执行的三个 hook 仅检查 Omarchy 入口、
等待 Limine 锁及更新时间戳，没有音频／温控服务重启、EFI 或 DKMS 动作。
覆盖机制见 [ALPM hook 手册](https://man.archlinux.org/man/alpm-hooks.5.en)。

恢复包 15 的 SHA-256 为 `936eeb3f37511a4d03d88ffb90a7f2d392ba1f3884d880451c45099d45e871c4`，
已逐载荷确认与升级前磁盘内容相同。安装及恢复材料存于
`~/Backups/projects/mechrevo-drivers/light/power-control-r16-installed-20261017/`，
122 个文件、500856 字节已独立完整读回；本轮未实际执行回退。
安装跟踪保留 partial（0 gap、10 条未解析删除事件），归档完整不能补全安装历史。
硬件验收仍为 9/20；温控候选和完整 Windows 移植仍待验证。

## 2026-10-16 观察器 r15 安装与额外 PM 补偿

MSR 观察器修复源码 `cbb3396`，内建支持/设备身份/描述符生命周期66项回归通过，
根代理的普通文件及叶子符号链接两条独立旧负例均在新源拒绝。
包 `mechrevo-power-control 0.1.0-15`（63358字节）已单次安装，SHA256
`936eeb3f37511a4d03d88ffb90a7f2d392ba1f3884d880451c45099d45e871c4`。
仅观察器与POWER-CONTROL、THERMAL-OBSERVATION两份文档改变，其余7载荷原字节相同；
10载荷的字节/模式/root归属及包完整性22项0改动均核对通过。
安装后执行新版入口3秒显式MSR只读观测，3样本/3.140753秒，complete/valid、errors/faults空，
双扇RPM及3项原始MSR读取通过。五配置、六loaded notes、三服务PID、节点/CPU online起止一致，
没有服务重启、驱动加载、MSR/EC写、trace或EFI动作。55W/90°C/poll1/debounce0保持。
该短时诊断通过不代表热尖峰或整机散热已修复；其间参考95°C，稍后状态85°C，写入者仍未知。

源码 `f2435d1` 另修条件式profile挂起清位写不确定落地后的恢复，143相关回归通过；
固定 `a20a146` 干净副本完整818项、无跳过、69.059秒通过，log SHA256
`f1f24f13518f17d62e49ca9fdfdc8e8f5ba42d9f82146a2dcfac477588ec9e21`。
当前7.2.9内核28模块以W=1 -j2编译通过、5既有警告，57个跟踪文件前后相同。
此PM功能分支在本机为false，未打包/安装/加载此新增驱动源码；r112候选仍固定e389，磁盘/主镜像仍r106。

跟踪分别保留：观察器作者partial6gaps/239unresolved，完整818回归partial6gaps/1142unresolved，
构包partial1权限gap/0unresolved，安装selected roots partial0gap/13unresolved，
实机checkpoint partial0gap/12unresolved，源码编译partial0gap/311unresolved；后验核对不修补历史。
安装未跟踪/usr父时间戳及pacman.log范围；UKI保护门禁为元数据，未重复全镜像解析。
PackageKit旧补充快照曾误用不存在大写unit；本轮按真实packagekit.service确认loaded/inactive0，不能补证早期历史。
完整收据见本地 `power-control-r15/evidence/` 与 `root-full-init/target-dirty/pm-msr-iteration/`；
统一Backups `power-control-r15-installed-20261016/`、`thermal-msr-fixed-20261016/`、
`pm-profile-abort-20261016/`、`pm-profile-root-build-20261016/` 分别保留交付、诊断、PM及编译证据。

## 2026-10-16 r112 候选包与完整回归（未安装）

固定功能源码 `e389631bbaac7bdfb8deacc68c54e4c4f908b6ba` 的干净副本完整运行803项测试，
86.994秒、全部通过、无跳过，结束时受跟踪源码无改动。使用已有 Node/TypeScript 工具链，
TCC 原生/服务测试通过模拟 IO 执行，没有启动生产 daemon 或执行硬件控制。
日志 SHA256 `32bef997a8b6b29ae48339232b9384f448a96c9ca067f9a38b37207eed302257`。
跟踪 `3aa5aea0` 为 partial：3个 path-disappeared gaps、1486 unresolved，
具体gap位于测试临时模拟 sys/proc 路径；命令成功不补回历史。

候选 `4.24.0.r112.ge389631-1`，214706字节，SHA256：
`fe4dd0d7735146f3eedb65d32acfcab928d0c5b085aca99c0dcb5635a556c0ad`。
作者与根代理独立解包核对87份载荷及3份元数据的字节、模式、root归属；
56份驱动源码与固定Git逐字节一致，dkms.conf只替换版本占位符。
私有DKMS在7.2.7/7.2.9 headers各编译28模块，实际日志均为 `W=1 -j2`，每套保留5条既有警告。
56份模块通过指定私有公钥证书的CMS密码学验签；实际内容篡改、签名篡改、错误证书3负例均拒绝。
私有测试证书不代表系统信任或Secure Boot验收。namcap无错误，保留两条既有配方警告。
构包跟踪partial：1个payload staging权限gap、0 unresolved；双内核及签名验证跟踪完整。

该候选没有安装、加载或发布AUR，未修改EFI。系统保护状态起止核对一致；
磁盘安装与主启动镜像仍r106，运行核心r37/WMIr60/传感器r76，硬件验收仍9/20。
候选证据位于 `.local-tests/fan-port-iteration/driver-candidate-fan-recovery/`，
完整回归位于 `.local-tests/fan-port-iteration/root-full-init/target-dirty/full-suite/`。
统一 Backups 的 `driver-candidate-r112-20261016/` 保存候选包等41份载荷，
根代理独立核对全部字节、散列、权限和归属；不重复保存构建对象、私钥或镜像。

## 2026-10-16 universal 部分设速失败恢复（最新源码，未安装）

源码 `e389631bbaac7bdfb8deacc68c54e4c4f908b6ba`，`uniwill_keyboard.h` SHA-256：
`55b4242278891ae52f140f984d4fa4140bf6fc330a700755c4752dc4cc0322e2`。
实际 C 故障模型复现：CPU/GPU 83/97 后 CPU110 的表写成功、直控写 EIO，
旧状态为表110/直控83/缓存83、初始化有效且无待恢复标记；
后续 GPU120 或公开初始化返回0仍不修复 CPU。根代理的两条独立用例在旧源码 SIGABRT、新源码通过。

任一目标写失败现保存最后成功双目标（仅首次创建待恢复意图），初始化失效，
后续同扇、另一扇、显式初始化或 PM 走完整恢复；内层失败不覆盖原 saved pair。
失败 setter 不新增 EC/AUTO 操作，错误原样传播；未写入的前置读取失败、非法输入和 FULL 拒绝不标脏。
失效缓存且 FULL 已置位时，显式初始化会清 FULL 并恢复双目标，沿既有失效缓存初始化行为；
这是新增可达行为，旧错误有效缓存曾无操作。setter under FULL 的拒绝及取消旧意图保持。
139 项相关回归通过，覆盖双扇/两写/模拟落地或未落地/三 errno/四恢复入口、
saved0/0 经部分规范化为1后的嵌套失败、独立清理错误、AUTO/FULL 和前置拒绝。

私有干净副本在 `7.2.9-arch1-1` headers 下 `W=1 -j2` 编译28模块通过，5条既有其他模块警告保留。
作者139回归和独立负例/修复例跟踪完整；根构建 `54ab8bf0` 命令0，跟踪 partial：
1个 make GMfifo 非普通文件事件读取 gap、411 unresolved。未通过重跑补造历史。
本地根证据在 `.local-tests/fan-port-iteration/root-full-init/target-dirty/`，作者证据在
`.local-tests/fan-port-iteration/universal-full-init/target-partial-next/`。
统一 Backups 的 `universal-target-partial-20261016/` 保存17份作者载荷，
`universal-target-partial-root-20261016/` 保存13份独立证据及实际核心ko，均逐文件回读核验。
未安装或加载新修复；磁盘及主启动镜像仍r106，当前运行核心r37/WMIr60/传感器r76。
TCC实验包仍未安装，热尖峰及动态偏移修改者未解决，实机验收仍9/20。

## 2026-10-16 启动条目的后续维护审查（只读）

固定源码检查普通 limine-snapper-sync 只重建 Snapshots 节点，保留主条目的原路径和散列；
显式恢复会替换主条目。成功的官方 kernel rebuild 会按 kernel-id=linux 切到新生成的标准文件名，
不应把这个成功路径称作回退到保留的旧镜像。原 wrapper 的吞错问题仍要求重建后验证实际产物。
10 项静态源码合同和4条源码篡改负例通过，17份源/菜单/历史身份起止一致；
没有执行 native 同步，也没有证明未来所有配置或实机启动行为。

当前 EFI 占用72.44%，实际快照启动项为空、有效 LIMIT_USAGE_PERCENT=65；
发布前每小时日志已报告创建受限，新保留的镜像进一步占用空间。
主启动及独立Recovery入口核验不能替代快照启动恢复功能验收；本轮未改门槛、配置、服务或EFI。
新冻结证据 `.local-tests/fan-port-iteration/boot-management-audit/`，
统一 Backups 的 `boot-management-r106-20261016/` 保存36份小证据，逐文件回读通过，跟踪 complete/0。

## 2026-10-16 r106 启动镜像与菜单同步（前轮，未重启）

`/efi/EFI/Linux/omarchy_linux_r106.efi` 已写入，256,729,144 字节，SHA-256：
`67febd41124b2dc9ce0770701962b64d3af4c7a44e6f42bc0a1633280cb410a2`。
主菜单仅该条目的路径及 BLAKE2b 改变；旧 UKI 和原 Recovery 条目完整保留。
从 EFI 实际读回的 259 个模块全部与磁盘一致，内核载荷与 `7.2.9-arch1-1` vmlinuz 一致，
无内嵌 cmdline，使用现有 db 公钥证书的 `sbverify` 验签通过。Secure Boot 关闭，未进行启动验收。

旧镜像的内核及四个 NVIDIA 模块与磁盘相同，仅四个核心模块过旧；没有把解析错误当作镜像损坏。
本轮先在私有目录构建/签名，保留既有 `xhci_pci_renesas` 缺失固件警告；
后续唯一一次发布持全局启动锁，先 fsync/核验唯一镜像，再替换菜单并 fsync/回读。
20 项发布回归、14 组解析回归与 6 个真实镜像篡改负例通过；事务 5.817609 秒，未调用启动器 hooks。
已有 wrapper 忽略部分失败及锁超时，故未以其退出成功代替实物验证。
针对 VFAT 的历史 inode-only 差异作明确记录后，持有只读文件句柄，事务内路径必须继续指向该对象；
其他字节、权限、归属和时间元数据仍严格核对。非 EFI 文件保持完整身份比较。
这一处理不宣称已确定本次 inode 变化原因，也不证明 FAT 断电一致性。

15:48:34 后台快照清理更新了菜单/历史身份并重新签名启动器；本轮经日志、PE 各节相同及验签，
在锁下保存三份变化文件并捕获新基线。发布后其余二十份受保护文件保持，
六个运行模块、五份配置、三个服务 PID 均保持；PackageKit 状态见本轮更正。
当前核心仍为 r37、WMI r60、传感器 r76；磁盘包为 r106，功耗工具 r14、TCC 3.0.10-1。
TCC pkgrel 3 未安装、AUR 未更新；未重启、重载模块、睡眠或执行新硬件策略。
高温尖峰及动态偏移修改来源未解决，硬件验收保持 9/20。

本地证据在 `.local-tests/fan-port-iteration/boot-sync/evidence/`，独立解析器在 `boot-sync-audit/`。
统一 Backups 的 `boot-before-r106-sync-20261016/` 保存实际旧 UKI、原配置及变化补充，
`boot-r106-published-20261016/` 保存 42 份小证据及冻结工具，不重复复制大型镜像或密钥。
构建会话 `c1939fe7` 命令 0，跟踪 partial（27 gaps/1884 unresolved）；
发布 `3bf48f41` 命令 0，跟踪 partial（0 gaps/1 unresolved）；
独立 EFI 核验 `37eb5c11` 和归档 `2e66cb30` 均 complete/0，不能补回构建/发布阶段的历史缺失。
当次 EFI 可用 295,366,656 字节，保留恢复所需旧镜像，未清理。

## 2026-10-16 r106 磁盘安装（前轮）

`mechrevo-drivers-dkms-git 4.24.0.r106.gaaf6b36-1` 已安装，固定源码
`aaf6b3622758552cc4902760741abdc6d0544e2c`；包 SHA-256：
`c01256efdbc4e3ac7b79059e3c937fb2241c9f0347435e9c7f6a7b1f366788e4`。
87 个安装载荷逐项核对字节、权限和 root 归属，`pacman -Qkk` 为 114 个文件、零改动。
系统 DKMS 在 `7.2.7-arch1-1`、`7.2.9-arch1-1` 各安装 28 个签名模块，实际 make 为 `-j2`。
56 个签名密钥标识逐项与经散列核验的 r87 恢复模块一致；不等于启动信任或硬件功能验收。
完整源码回归 799 项、无跳过；实际风扇、PM 和散热效果仍待验收。

单次受控 pacman 事务使用独立配置和最后优先的 hook 目录，局部屏蔽全局 udev change、
UKI 重建和 PackageKit refresh，系统 pacman 配置及全局 hooks 未改。
实际四个前置 hooks、三个后置 hooks 包含旧 DKMS 移除、新 DKMS 安装、depmod 和 hwdb 更新。
安装后五份配置、六个运行 build ID、三个服务 PID（97821/397302/1003）、
传感器/RGB inode、五个启动文件完整身份及 EFI mount 与安装前一致；PackageKit 状态见本轮更正。
当前核心 r37、WMI r60、传感器 r76；启动 UKI 未更新，不能把磁盘安装或一次重启当作新核心已激活。
功耗工具仍为 r14，TCC 仍为上游 3.0.10-1；pkgrel 3 候选未安装，AUR 未更新。
高温尖峰和动态 TCC offset 修改来源仍未解决，硬件验收保持 9/20。

安装/核验回执位于 `.local-tests/fan-port-iteration/driver-install/evidence/`。
恢复及证据归档位于统一 Backups 的 `driver-r106-preinstall-20261016/`、
`driver-r106-preinstall-tools-20261016/`、`driver-r106-installed-20261016/`；旧 r87 签名模块另行保留。
安装会话 `d62f49c2`、安装后验证 `ba10f2fa` 均退出 0，所选根目录跟踪 complete、零 gap/未决事件。
安装使用轮询回退，不能证明全部瞬时历史；`/usr` 父目录时间戳不在选定跟踪范围。
构包和完整测试的历史 partial 仍单独保留，后续归档不修复这些历史缺失。

## 2026-10-16 r14 安装与阈值变化失败现场（前轮）

`mechrevo-power-control 0.1.0-14` 已安装，源码固定
`ff2add6f2ec24766a76b6cab88c43e85e31248b2`，配方固定
`72ce81633d43ccdf0413936120209a7634fa1a11`。
包为 60,976 字节，SHA-256：
`00ebf4d9b948eb4e0d959f53dabc1ebb74afb6af93765eed564e096d21225e32`。
root 独立核验 10 个 payload 的源码/权限一致，`pacman -Qkk` 为 22 个文件、零改动。
新增可选 CPU0 温度参考诊断，失败不影响 PL1 判断；公开观测工具遇到受管功耗状态
缺字段或类型错误会拒绝观测，修复原先可能放过残缺状态的问题。
安装后正式 `status` 的 Tjmax 为 100°C、偏移 15°C、TCC 参考 85°C，诊断可用且 diagnostic_errors=[]；
holding=true、errors=[]，55 W/90°C/每秒轮询/零 RAPL 防抖保持。
本轮另一次只读检查读到 95°C，说明参考动态变化；未确认修改者，不归因 thermald。

5 份配置、6 个运行模块 build ID、3 个服务 PID（97821/397302/1003）、传感器 inode 与 RGB 保持。
磁盘驱动仍为 r87，运行 keyboard/IO/NVIDIA/compatibility r37、WMI r60、传感器 r76；
TCC 实验包 pkgrel 2 未安装，未激活新核心，未新增硬件策略写入或物理 PM 验收，AUR 未发布。
安装会话 `0c38725b` 的命令退出 0，跟踪为 partial，0 个 gap、10 个未决事件；
构建另有 1 个权限 gap。独立文件核验不能补造缺失的跟踪历史，两者分别记录。

最新唯一一次私有只读观测完成 124 组读取、13.6102 秒后因温度参考变化终止；
保留的是末 16 组及全程统计，不是全部读取 trace：
CPU0 目标寄存器从 `0x05640000` 变为 `0x0f640000`，Tjmax 保持 100°C、偏移 5→15°C，
即 TCC 95→85°C；本次变化仅涉及已知偏移位，未见未知位变化。
exit=1、footer/receipt 无效，现场已保留，不重跑或伪造有效尾部。
原始 API 标准输出为 5 行、45,537 字节；包含元数据的收据 JSON 保存在
`.local-tests/postboot-20261016/thermal-iterate/cpu-thread-fan/product-diagnostic/root-stdout-reference-capture.json`。
收据 JSON 文件 SHA-256（不是上述原始标准输出的 SHA）：
`fce9e49dc0e9ae205e8b38589c432a67097d9e355631528e8192a7456cbc0c3d`。
这只闭合本次失败瞬间的变化类型，旧第二轮失败现场仍不能据此补判。
有效首轮 99°C、散热根因和修改者仍未解决；这些结果不构成散热改善或完整迁移验收。
已核验冻结材料、首次现场及恢复备份继续保留。
本轮统一恢复材料位于 `~/Backups/projects/mechrevo-drivers/light/` 下：
`power-control-r14-20261016/` 保存新包、固定源码及安装证据，
`power-control-r13-before-r14-20261016/` 保留旧包恢复材料，
`thermal-reference-stdout-20261016/` 与 `thermal-reference-stdout-firstlive-20261016/`
分别保存冻结观察器及其后首次实机失败现场。均已独立逐文件回读内容、散列、权限和归属。

## 2026-10-16 r87 错误处理与 CPU 快速只读观察（前轮）

驱动源码 `92aaebd523f5c9bb5760ffdc382d58951c2b34d8` 已提交并推送，包含
`cca5a42` 的充电保留编码检查、`66c8f92` 的直通 EC 握手/清理错误传播，以及
`92aaebd` 的 legacy 首次/恢复设速同步返回。同步路径逐次检查原有写入序列，
失败保留目标供显式重试；周期维护仍为 50 分钟。成功只说明该序列传输完成，
不证明机械转速达到目标，也不承诺部分写入原子回滚或固定总耗时。
实际 C 故障及并发回归、旧源码负例已验证；完整回归 753 项通过（66.120 秒），
日志在本地 `.local-tests/postboot-20261016/read-windows/error-contract-regression.log`。

`mechrevo-drivers-dkms-git 4.24.0.r87.g92aaebd-1` 已安装，包 SHA-256：
`473f32745a2d1585882319cef5c05a12bed3507955c7d62aad1c6ffd15a2e7d1`。
87 个包内文件、56 个源码文件、114 个安装文件/零改动核验通过；
`7.2.9-arch1-1`、`7.2.7-arch1-1` 各 28 个模块签名核对通过。
安装核验在本地 `.local-tests/postboot-20261016/oem-binding/package/error-contract-driver/installed-verification.json`。
运行传感器仍为 r76，keyboard/IO/NVIDIA/compatibility 为 r37，WMI 为 r60；
核心模块、配置及三个服务 PID 保持，新核心没有加载。观测包仍为 `0.1.0-13`。
直通 EC 参数 `ec_direct_io=N`；未新增实机手动风扇、legacy 硬件、充电效果或物理 PM 验收。
universal 设速遇到 FULL 返回 `EBUSY`，不会清除 FULL 或表；PM 验证释放是独立路径。
AUR 尚未更新。TCC 第二轮本地修复补齐调用方请求串行、profile 失败重试、
守护进程终止状态、等待正在执行的风扇任务结束后交还自动控制，以及未知错误阶段格式化。
此前初始化/退出返回值忽略和退出竞态已在源码与测试中修复；8 项实际测试无跳过通过，
service TypeScript 和完整生产构建通过，pkgrel 2 最终包已核验。
包为 36,421,440 字节，SHA-256：
`3082b17d63d99f68e77f4ab9892f69e604e40f73ed0a4a5ef1dac288c7efcd5c`。
26 项实际 asar 契约通过，8,692 个依赖文件 SHA 一致。源码已提交并推送 `da74739`；
未安装、未启动新守护进程，不代表实体风扇或物理 PM 验收。没有本轮驱动、限值或性能策略改动。

只读 CPU 快速观察完成 59.050324963 秒、567 个样本，完整记录和标准输出校验通过，
无采集超限或错误。按固定 v6.12 turbostat 公式换算的核心/封装最高温度为 99°C；
有 47 次采样间隔超过 150 ms，不能当作稳定 100 ms 采样或独立校准。
该窗口没有读取 EC、写硬件、重载模块或重启服务；不是受控前后对照。
MSR PL1 为 27.5/34.5/41.5 W，MMIO PL1 保持 55 W，两路 PL2 均保持 140 W。
六个核心最高 99°C 样本仅涉及物理核心 16/24（代表 CPU 8/12），相应热状态 bit0 均置位；
这些样本的 MSR PL1 已为 27.5 W，时间窗约 0.999424 秒。前一能量区间的平均封装功耗
为 25.58–29.01 W，六次均值 27.12 W；140 W 限值不是实际达到 140 W 的证据，
区间平均值也不能排除更短的功耗尖峰。该观察尚不能确定物理散热或调度原因，先前 100°C 问题仍未解决。
本地证据在 `.local-tests/postboot-20261016/thermal-iterate/cpu-fast/capture.jsonl`，
分析保存在同目录 `capture-analysis.json`。

第二轮联合采集整体失败：CPU 205 个样本、22.4845 秒，因参考状态变化而无效；
侧录 23 个传感器样本、38 次扫描、26.5285 秒，150 ms 时间上限最终达到 162.691 ms，也无效。
有效前缀 DTS 最高 87°C、CPU RPM 3611–3970/GPU RPM 4939 只是失败实验的局部读取，
不能当作散热改善或前后对照。约 26 秒窗口内 agcc 消耗约 25 CPU 秒，
观测/跟踪负担显著，未通过空闲开销验收。

另一次 root 只读能力探测退出成功，守护快照前后不变；CPU model 151 对应 ALDERLAKE，
Turbostat 的 6 位偏移及 platform 0xce bit30 资格成立，Tjmax 为 100°C。
首次合格值 `0x05640000` 对应 TCC 95°C，第二次/当前 `0x0f640000` 对应 85°C。
早先未确认资格的原始值不能套用；没有修改者证据，也不能归因当前未启用 adaptive/workaround 的 thermald。
记录在本地 `thermal-iterate/cpu-thread-fan/msr-target-capability.json`（位于同一 postboot 证据根）。
这些读取不证明物理散热或调度原因，有效首轮 99°C 热尖峰仍未解决。

r87 已核验恢复材料在 `~/Backups/projects/mechrevo-drivers/light/error-contract-r87-20261016/`，
目录为 root/700，36 个文件共 333,901 字节。manifest SHA-256：
`4607960d66dbe175fabc9fa276ee8cfc3c4f754c53f5aed53347ccf9b8af101a`。
TCC 第二轮恢复归档保留在 `~/Backups/projects/mechrevo-drivers/light/tcc-lifecycle-v2-20261016/`，
102 个文件共 39,510,669 字节，manifest SHA-256：
`2431584f930d8e54f5f2fef5935cf801d10e4d04db4347d030cf9b28dcd83fdb`。
这些源码、安装与只读结果不构成完整迁移或散热验收。以下保留前轮记录。

## 2026-10-16 r81 legacy 模式修复与 r13 读取时间窗（前轮）

驱动源码 `0e755246beed89f70d770dfeedd686db06612aaf` 为 legacy 风扇的显式模式切换
加入后台任务屏障：FULL/模式请求先停止周期重放；失败保留显式重试意图并阻止 worker/PM
自动恢复旧目标，成功后才解除旧手动状态。只更新 profile/TDP、保留 FULL 位的请求仍保留目标。
170 项定向回归通过；旧 HEAD 的三条实际负例失败，证明测试能捕获原有覆盖问题。
两套内核各 28 个模块 W=1 构建通过，各五条既有警告、无新增警告。
完整本地回归 738 项通过（40.681 秒）。没有在本机制造 legacy FULL 交错或执行物理挂起/唤醒，
其他 legacy 硬件未验证，不能用这些模拟 EC 结果替代固件与实体功能验收。

观测源码 `6da3237e5d82c13ed19eb7b0376f11aeead607a0` 为 package、EC、RAPL、RPM 等
通道分组记录 `read_windows`，校验时间戳有限且不倒退；保持原有读取顺序和硬件访问次数。
52 项相关回归通过。源码直接运行的实机只读观察完成 30.191 秒、23 个有效样本，
EC 读取组耗时约 235–248 ms。这记录调用起止时间，不能当作原子硬件采样或风扇响应延迟。
源码窗口最高内部温度 95°C。安装 r13 后正式命令另完成 30.14039 秒、23 个有效样本，
无新增受监测故障（faults=[]），每组样本十个读取时间窗全部有序。
正式窗口 EC 读取组约 233–248 ms、RPM 读取组约 0.49–1.87 ms，内部封装/核心最高 99°C。
两段自然负载与初始状态不同，不能比较散热收益；先前 100°C 热尖峰未解决。

驱动包 `mechrevo-drivers-dkms-git 4.24.0.r81.g0e75524-1` 已安装并核验，固定上述驱动源码。
包 SHA-256：`04befe844fd05fe3a1eb1e1bb07b07fe5cea91af776d3d2635de4f09e5683175`。
87 个包内文件、56 个源码文件、114 个安装文件/零改动一致；两套内核各 28 个模块签名核对通过。
观测包 `mechrevo-power-control 0.1.0-13` 固定上述观测源码，已安装并核验 10 个包内文件、
22 个安装文件/零改动；更新后的实际打包回归 8 项通过。
包 SHA-256：`5fba697973725804df6709e443730c484b0ace75497981f37bf7b0620272e390`。
六个运行模块 build ID、三个服务 PID、配置、RGB 节点及传感器接口均保持。
运行 keyboard/IO/NVIDIA/compatibility 仍为 r37，WMI r60，只读传感器仍为 r76；
新驱动及此前 remove/PM 修复仅安装到磁盘，没有核心激活、实机风扇策略写入、legacy FULL 或物理 PM 验收。
remove/rebind 仍保留失败拆除及同模块重新绑定先验证释放的边界，所有权不跨模块重载持久化。

r81 的已核验回滚材料保留在 `~/Backups/projects/mechrevo-drivers/light/fan-legacy-full-20261016/`，
目录为 root/700。r13 的已核验回滚材料在
`~/Backups/projects/mechrevo-drivers/light/thermal-read-windows-20261016/`，28 个文件的原权限、
所有者及 SHA 全部回读一致；目录为 root/700、manifest 为 600。
manifest SHA-256：`9b8d683254cad6c9bf83ae22570677dfe7831c519a79911f7d068d1f49f5b5ce`。
以下保留此前各轮记录；上述安装与只读观察不构成完整硬件功能或散热验收。

## 2026-10-16 r76 手动风扇 PM 修复与 r12 观测（前轮）

源提交 `4a22fc74197b9f0550b93337be4eae9da09ef342` 修复 universal 手动风扇未参与 PM 的问题。
独立追踪已拥有/可能启用的 RAM 表；初始化成功或提交无法确认时均不能当作 AUTO。
睡眠前保存双目标并验证关闭表，恢复时使缓存失效、重建并恢复双目标；部分失败保留目标、
尝试回 AUTO，原错误与恢复错误分别报告。FULL 覆盖先验证关闭旧表，保留 FULL 位，
不能在后续恢复错误中复活旧目标。universal 路径不启动 legacy 周期 worker。
旧源码的公共请求 PM roundtrip 负例确实失败；修复后 371 项相关及全部 710 项回归通过。
并发覆盖 suspend/manual、resume/AUTO、resume/remove；均为实际 C 的模拟 EC，不是固件睡眠测试。

两内核隔离 W=1 构建各 28 个模块成功；每套五条既有警告与旧源码对照相同，无新增警告。
62 条导出符号名称/类型/namespace 与 r72 相同，但内核未启用符号 CRC，不能当作完整 ABI 证明。
包 `4.24.0.r76.g4a22fc7-1` 已安装，SHA-256
`0a8ea5f581a205ca51b5908348d3f13daa96cabb527358e1c98f08d71834713b`。
86 个包内文件字节/权限、56 个源码、113 个安装文件/零改动核验通过。
`7.2.9-arch1-1`、`7.2.7-arch1-1` 各 28 个模块完成 DKMS 安装、vermagic/签名检查。
三项现有 EFI 映像签名检查通过，不代表 Secure Boot 验收或第二内核已实机启动。

只独立重新加载只读传感器并完成十组读取，运行 build ID 与 r76 安装文件一致。
keyboard/IO/NVIDIA/compatibility 仍运行 r37，WMI 仍运行 r60，核心 PM 修复仅安装到磁盘，
没有实机挂起/恢复、核心热重载、重启或手动风扇写入。三个服务 PID、五个核心 build ID、
键盘节点及配置散列保持，GPU 查询与身份保持，加载窗口无新增受监测 GPU/PCIe 故障。
legacy FULL/周期 worker 和 remove 的固件 AUTO 语义仍未修复；不泛化本轮 universal PM 结果。

观测包 `mechrevo-power-control 0.1.0-12` 固定源码
`0c0c65eaf07534eaed3c957a174a961b579eae57`、配方 `d434f824995c40e232f51b9be9312df3fd3c4911`；
包 SHA-256 `a50905b98885ebe77a157e24e447a6bba625f8a8e64d29f522b47615c351547d`。
10 个 payload 字节/权限与固定提交匹配，22 个安装文件/零改动，配置/PID/六模块/键盘节点保持。
新增 `fan_rpm` 不替代原始刻度；缺接口明确标不可用，读取错误、重复/损坏设备或运行中消失使观测失效。
47 项观察回归和 8 项实际打包回归通过，全部包含在上述 710 项中。

| 自然桌面观测 | 时长/样本 | CPU OEM RPM | GPU OEM RPM | 最高内部采样 |
| --- | --- | --- | --- | --- |
| 新源码直接运行 | 30.59 秒/23 | 3041–3970 | 4427–4939 | 97°C |
| 安装 r12 后正式命令 | 30.50 秒/23 | 2453–3175 | 3915–4427 | 88°C |

两窗口均 complete/valid，无新增受监测 GPU/PCIe 故障；负载、初始温度不同，不能比较散热收益。
55W PL1、90°C 软件目标、每秒轮询、零 RAPL 防抖保持，PL2 140W 未持久托管。
先前 100°C 热尖峰仍未解决；RPM 尚未用独立转速计校准。

原厂字符串动态方法和另五个已定位载荷均静态恢复；六载荷共 735 条 CIL，另有
3,320 个唯一字符串/10,965 处相邻调用。指令、字段和字符串明文全部留在私有证据。
`19f3` 的 79 个 opcode 绑定 64 个处理函数，`19f6` 为 native VM 取指桥；handler/native VM 仍待分析。
原厂 51 的充电优先级支持函数无条件 false，不应为 GM6 盲目新增该白名单。

原厂 EFI managed 结构为 188 字节，但本机固定变量共 184 字节；按 Linux efivarfs 前四字节属性格式，
实际数据为 180 字节。[Linux efivarfs 格式](https://docs.kernel.org/filesystems/efivarfs.html)。
仅以 O_RDONLY 对精确变量做一次有界读取，未补零/重排/写入。
已证明偏移的 APVersionCheck、ACRecoverySupport、ACRecoveryStatus 前缀字节均为 0，
回执始终 `partial_prefix=true`、`format_qualified=false`，不据此宣称完整 ABI 兼容、最终功能不支持或 EFI 写资格。
原厂 DLL 忽略读取长度而将缓冲尾部置零的行为不能作为 Linux 兼容依据。

私有回执在 `.local-tests/postboot-20261016/oem-binding/`：
`linux-fan-audit/pm/` 保存测试/双内核构建，`package/pm-driver/` 保存包/安装/传感器核验，
`package/observer-r12/` 保存观测包/安装/正式实机观测，`native/` 和 `managed/` 的新动态分析保存恢复证据，
`power-semantics/setting-gates/efi-abi/prefix-receipt.json` 保存 root600 的有界 EFI 读取。
恢复材料位于 `~/Backups/projects/mechrevo-drivers/light/fan-pm-20261016/`（原 r72 包/原传感器及 r76 核验），
以及 `power-thermal-20261016/observer-r12-recovery/`（r11 包/配置和 r12 核验）；均逐文件回读校验。
源码已推送，AUR 元数据未更新。完整目标及剩余项见[功能覆盖](../OEM-FEATURE-COVERAGE.md)。

## 2026-10-16 r72 RPM 安装与原厂功耗默认值续验（前轮）

完整本地回归 689 项通过，其中实际 C 风扇运行/并发 53 项、温度/RPM 10 项。
RPM 故意破坏 GPU 低地址、缩放、错误传播、跨字节刷新四个负例均被回归捕获。
源提交 `749949a50d1a0c038c83d5cf02261536e4b80360` 已推送。
包 `mechrevo-drivers-dkms-git 4.24.0.r72.g749949a-1` 已安装，SHA-256
`14d30c1b30fdafb09df87beda98148f452c592f30ff9b25cb04df549595008fd`。
86 个包内文件的内容/权限、56 个驱动源文件与固定提交一致；113 个安装文件、0 改动。
`7.2.9-arch1-1`、`7.2.7-arch1-1` 各 28 个模块完成 DKMS 安装、vermagic 和签名核对。
三项现有 EFI 映像签名检查通过；这不等于 Secure Boot 实机验收。

仅独立卸载/加载 `mechrevo_ec_sensors`，运行 build ID 与正式安装文件一致。
新增 `fan1_input/fan2_input` 和 CPU fan/GPU fan 标签，连同原温度接口均为 0444，无 PWM 写接口。
正式加载后十组样本 CPU 字值 3,558–3,617、GPU 4,939；`sensors` 显示 RPM。
这是已恢复的 OEM 算术公式及只读接口验收，未用独立转速计校准。
每次最多三次高/低/高字节读取，跨字节刷新未稳定返回 EAGAIN，传输失败明确报错。
精确 DMI/BIOS、项目 `0x10`、`0x078e` bit 6 及启动 RPM 读取任一失败时，整个传感器模块拒绝加载。

临时试用曾完成十组采样并恢复 r61 模块；正式安装后另行加载、采样和核验。
全过程 TCC/thermald/nvidia-powerd PID、五个核心模块 build ID、键盘节点 inode、配置/状态散列保持，
GPU 身份保持、加载窗口无新增受监测 GPU/PCIe 故障。
keyboard/IO/NVIDIA/compatibility 仍为开机 r37，WMI 为先前 r60；传感器为 r72。
新曲线提交修复已安装但尚未在核心模块生效，未在本机主动写曲线或切换手动模式。
回归验证先关闭表控制、完整写入再启用，提交失败与恢复失败分别报告；未改现有 96 字节常速表布局。
universal/legacy 手动模式状态所有权与真实睡眠恢复仍待修复及实机验收。

另一个固定十五地址 ECRR 只读探针完成三次相同快照后卸载：

| OEM 默认模式 | PL1 字节 | PL2 字节 | PL4 字节 | DState 字节 | TCC 偏移字节 |
| --- | --- | --- | --- | --- | --- |
| Gaming | 75 | 75 | 200 | 1 | 5 |
| Office | 45 | 45 | 200 | 1 | 20 |
| Turbo | 130 | 130 | 200 | 1 | 5 |

地址及真实 getter/caller 见[原厂策略迁移](../OEM-MIGRATION-NEXT.md)。这是固件保存的原始默认值，
不是当前 RAPL/MSR 限制、实测瓦特或已执行温度目标；未据此写入 EC 或改变 Linux 策略。
十五字节探测前后全部既存模块、配置、服务 PID、键盘节点和 GPU 保持，未新增受监测故障。
55W PL1 上限、90°C 软件目标、每秒检查、零 RAPL 防抖保持，PL2 140W 仍未持久托管。
先前已观测到 100°C；本轮接口与协议推进不能当作热尖峰修复或 Windows 性能比较。

安装后另完成 30.51 秒、23 样本只读温度/功耗/MSR 观测，回执 complete/valid，
最高采样 97°C，CPU0 package throttle 计数首末增加 1,949，仍存在热限制；
无新增受监测 GPU/PCIe 故障。此短窗口只补安装后健康证据，不构成持续负载散热验收。

私有证据：`.local-tests/postboot-20261016/oem-binding/` 下
`integration-tests.log`、`hardware/rpm-trial-receipt.json`、`hardware/installed-load-receipt.json`、
`package/package-verification.json`、`package/installed-verification.json`、`power-semantics/defaults-receipt.json`。
安装后短窗口另见 `hardware/rpm-thermal-30s.json`。
原厂 IL/密钥/二进制不公开。恢复材料均在 `~/Backups/projects/mechrevo-drivers/light/`：
`windows-oem-recovery-20261016/`、`oem-power-defaults-20261016/` 保存已回读校验的分析证据；
`oem-rpm-install-20261016/` 保留 r61 包，`rpm-live-20261016/` 保留原传感器模块。
各目录内有 manifest 与恢复说明；恢复只读传感器无需卸载 WMI/keyboard/NVIDIA 核心。
源码已推送，未更新 AUR 发布元数据；AUR git 配方与本机固定提交安装应分开理解。

## 2026-10-16 OEM 方法恢复与本机布局只读复核

原始 5.17.51.34 服务的方法表已恢复 5,183 个 CIL 方法体，每条均通过独立 OEM 尾标记。
328,357 条指令、20,342 个显式跳转目标的静态边界核验通过；没有执行 OEM 代码，
没有完成 CLR 栈/类型验证、完整 VM 还原或全部 Windows 功能移植。
布局、RPM、表写入及失败路径的事实见 [方法恢复](../OEM-METHOD-BODIES.md)
和 [原厂策略迁移](../OEM-MIGRATION-NEXT.md)。原厂指令/密钥/二进制不随 Git 发布。

本机 `7.2.9-arch1-1` 上仅临时加载固定地址只读 ECRR 探针，完成十组样本后移除：

- 十组均为 `0x078e=0xec`、`0x0740=0x10`；按真实支持判定、项目号及工厂选择分支，
  正常读取成功时会使用 `MyFanManager_RamFan1p5` 和 `FanTable_Manager1p5`。
- OEM CPU 公式为高字节 `0x0464`、低字节 `0x0465`；GPU 为高字节 `0x046c`、低字节 `0x046b`。
  同组公式字值分别为 3,816–3,878 和 4,939；不是独立机械转速校准，也未新增运行中的 RPM 接口。
- 真实 Windows 表写入同样包含 16 个 GPU duty，含 `0x0f5d..0x0f5f`；它们在默认表获取时另作握手。
  不能仅凭 STATUS/CTRL 常量别名断言 Linux 末三项错写。已确认先关闭表控制、写入、再启用的顺序，
  但本轮没有试写曲线、触发默认表握手或验证散热收益。
- 探针加载及移除成功；六个原模块 build ID、TCC/thermald/nvidia-powerd PID 和配置/状态散列前后相同。
  GPU 查询健康、设备身份相同，期间没有新增受监测 GPU/PCIe 故障。没有重载核心驱动、睡眠或重启。

私有回执在 `.local-tests/postboot-20261016/oem-binding/hardware/`：
`hardware-receipt.json`、`comparison.json`。对应恢复映射、语义和源码 hash 位于同级
`mapping/`、`fan-layout-body/`、`rpm-bodies/`。这是只读协议核对，不是风扇控制或长期稳定性验收。
安装仍为驱动 r61、功耗工具 r11，运行模块组合保持原样；55W PL1上限、90°C目标、
每秒轮询和零RAPL防抖保持。此前仍观测到100°C，热尖峰没有因这次分析而解决。

## 2026-10-16 快速降限与 Windows 保护层续验

新增显式 `--rapl-debounce-seconds 0`，仅允许与90°C目标、每秒轮询一起使用。
默认两秒防抖配合整秒计时，典型每三秒才继续降限；冻结原生C++回归用可控时钟证明
默认连续动作在1000/1003/1006秒，零等待在1000/1001/1002秒，同秒重复仍被抑制。
两者均保持27.5–55W范围，先降到RAPL底限再接管intel_pstate，降温后恢复所设上限。

本轮157项回归通过：功耗事务114、原生温控11、PL2试验24、实际打包8。
独立工具包 `mechrevo-power-control 0.1.0-11` 已安装，固定源码
`558ccef7cc9d7d7997fdd532dcfd52e5c99be87f`；10个文件的内容／权限与包和源码一致，
`pacman -Qkk` 为22个文件、0改动。安装保持原配置和三个服务PID；应用策略才重启thermald。
旧版本状态及XML字节兼容，实机撤销快速递进后恢复原XML精确哈希，再次启用成功。

四个自然桌面窗口均有效，没有新压力工作进程，无新增受监测GPU／PCIe故障：

| 窗口 | RAPL防抖 | 时长／样本 | 最高采样温度 | 平均封装功耗 | CPU0封装热节流计数增量 |
| --- | --- | --- | --- | --- | --- |
| F | 原生 | 120秒／87 | 100°C | 22.767W | 4871 |
| G | 0秒 | 180秒／136 | 99°C | 30.804W | 5749 |
| H | 撤销回原生 | 60秒／46 | 97°C | 26.177W | 4056 |
| I | 再启用0秒 | 120秒／89 | 100°C | 25.794W | 3275 |

按各窗口单调时钟边界核对48→34→27.5W完整降限序列：F典型相邻动作3.015秒，
G约1.005秒，H典型3.015秒（一次2.010秒，与整秒计时边界相符），I约1.002–1.005秒。
这是实际控制递进变快的证据，不能当作相同负载下的降温／性能改善。
I窗口中thermald日志也读到100°C，**热尖峰仍未解决**；PL2保持140W且未持久托管。
当前保留55W长期上限、90°C目标、每秒轮询和零RAPL防抖；撤销最后一项用
`sudo mechrevo-power set 55 --target-celsius 90 --polling-seconds 1`。
撤销全部额外温控选项用 `sudo mechrevo-power set 55`。r10／r11包与策略快照已校验留存。

风扇复核确认原始数值会升降，D／E窗口范围105–170／82–142，不能据此公开RPM或延迟。
同为内部99°C的两个样本分别对应EC94/raw170与EC68/raw105，读取时序、缓存及传感器来源
不同，不能据此认定曲线错误。该阶段手动风扇初始化仍缺本机布局证据，因此没有试写；后续布局只读复核见上节，硬件写入仍未验收。

Windows静态分析已排除关键方法仅是反编译显示问题，原始51版确实共享异常桩；
已取出两个保护模块、静态重建可分析的native PE，并独立复现三个完整性校验范围。
该阶段尚未恢复布局判定/RPM方法；后续已经恢复，当前结果见上节及[原厂方法体恢复](../OEM-METHOD-BODIES.md)。
本轮源码已推送，未更新AUR；内核模块未重载，其他硬件验收限制保持。
原始数据、安装收据、动作序列与恢复验证在 `.local-tests/postboot-20261016/thermal-iterate/`，
文件跟踪有权限及短暂文件事件缺口，安装和运行结果另行独立核验。

## 2026-10-16 一秒轮询续验

前轮日志确认原生降限存在约三秒的递进间隔，且低于轮询控制点后基础检查恢复四秒。
新增显式 `--polling-seconds 1`，必须同时指定 90°C 目标；仅缩短基础检查，不改防抖、
温度回差或风扇曲线。旧版90°C配置的 XML 哈希保持，成功、失败回滚、孤儿事务恢复、
损坏状态与旧状态迁移均有回归。相关回归共200项通过：功耗事务101、PL2试验24、
观测及分析47、原生thermald控制20、打包8；完整引擎启动另由实机核对。

工具包 `mechrevo-power-control 0.1.0-10` 已安装，源码固定于
`2c5daf5937f899280044366dc464dc8823e7e756`。10个安装文件与包、固定提交的字节及权限一致，
`pacman -Qkk` 为22个文件、0改动；升级保持配置及服务PID。
随后执行 `sudo mechrevo-power set 55 --target-celsius 90 --polling-seconds 1`，
thermald PID变为249017，日志明确报告 `Poll interval is defined in XML config 1 seconds`，
并保留有效传感器及四个本机原生降温绑定。TCC 97821、nvidia-powerd 1003保持。

E轮约120秒／90样本有效，零采集错误、无新增受监测GPU／PCIe故障。封装采样温度
64–95°C、样本均温72.43°C、平均封装功耗16.338W，CPU0封装热节流计数增加1327。
但同一采样窗口内，thermald自己的温度日志最高为 **99°C**；用单调时钟核对确认处于窗口内。
因此不能把较慢观测工具的95°C最高值当成实机温度上限，也不能用前后自然负载不同的窗口
宣称性能／散热改善。策略确已更早检查和降限，但热尖峰仍未解决；长期及满载散热未验收。

当前保留55W PL1上限、90°C软件目标与一秒基础轮询；PL2仍为140W，原生温控可继续降低
实际PL1。只撤销一秒轮询用 `sudo mechrevo-power set 55 --target-celsius 90`，
撤销温度目标和轮询用 `sudo mechrevo-power set 55`。已核验r8／r9／r10恢复包及配置快照
在统一备份目录；不要直接把旧状态文件覆盖回系统或在新配置活动时降级旧程序。
证据：`target90-poll1-E.json`、其summary、`runtime-target90-poll1-verification.json`、
`journal-thermal-crosscheck.json`、`installed-package-r10-verification.json`，均位于
`.local-tests/postboot-20261016/power-thermal/`，原始私有日志不上传。
源码已同步远端，未更新AUR。文件跟踪因执行服务中断及权限／短暂文件事件存在缺口，
实机状态和包完整性采用独立核验；不把恢复后的扫描说成完整事件历史。

## 2026-10-16 功耗与散热续修

本轮将长期功耗 PL1 和短时功耗 PL2 分开显示：`holding_now` 只确认 CPU 封装
PL1 上限，不能解释为 PL2 或温度已经受控。新增有时限、带持久恢复记录的 PL2
试验工具，以及可选的原生 thermald 温度目标；没有写入新 EC 风扇曲线或执行 OEM 程序。

四轮约 60 秒自然桌面观测如下；没有新增压力工作进程，后台负载并不一致：

| 轮次 | PL1 / PL2 | 封装最高温 | 平均封装功耗 | CPU0 封装热节流计数增量 |
| --- | --- | --- | --- | --- |
| A1 | 55 / 140 W | 97°C | 17.550 W | 695 |
| B | 55 / 55 W | 96°C | 17.769 W | 814 |
| A2 | 55 / 140 W | 100°C | 31.486 W | 3646 |
| C | 35 / 35 W | 96°C | 17.736 W | 442 |

B、C 的试验恢复记录均为 `valid=true`、`restored=true`；试验后恢复 PL1 55 W、
PL2 140 W。以上窗口仍出现高温，不能据此归因于 PL2，也不计算散热改善百分比。
节流计数是内核中断处理时观察到内部热状态的计数，不是独立事件数、持续时间或性能损失。
采样间隔内的平均功耗也不能排除毫秒级突发；风扇原始值不能当作 RPM。

只读温度目标 MSR 为 `90439680`，对应参考温度 100°C、偏移 5°C，即硬件热控目标
95°C；thermald 启动日志同时报告默认被动温控点 95°C。执行
`sudo mechrevo-power set 55 --target-celsius 90` 后，日志确认 CPU zone 的被动温控点为
90000 m°C、绑定有效的 `sensor id:4`，并保留四个本机可用的原生降温设备：
`rapl_controller`、`intel_pstate`、`intel_powerclamp`、`Processor`。
未注册的 `cpufreq` 没有进入最终绑定列表。日志已记录超过目标时 RAPL 降到 48 W、
温度回落后恢复 55 W；这证明策略被解析并动作，不代表能消除瞬时超温。

随后 D 轮以 90°C 目标、PL1 上限 55 W、PL2 140 W 完成约 120 秒自然桌面观测：
91 个样本，`complete=true`、`valid=true`，没有采集错误或新增受监测的 GPU／内核故障。
封装温度 65–99°C，样本均温 82.46°C，平均封装功耗 22.881 W，CPU0 封装热节流
计数增加 4012。MSR PL1 采样值为 27.5、34、48、55 W，MMIO PL1 保持 55 W，
说明原生温控继续降限并能恢复所设上限；结束时两者均为 55 W。
这轮仍出现 99°C 尖峰，90°C 是反馈控制目标而非瞬时温度硬上限。D 与前四轮时长、
后台负载不同，不能据此宣称散热改善或完成长期验收；PL2 也仍未持久托管。

190 项相关回归通过：功耗事务 92、PL2 试验 24、观测及分析 47、原生 thermald
控制 19（12 项功耗控制、7 项温度目标）、实际打包 8。独立工具包 `mechrevo-power-control 0.1.0-9` 已安装，
交付源码固定于 `92e65c73e579194f5bae132ac0fa58a2cc8cb780`；10 个文件与冻结源码、
实际包和安装内容的字节及权限一致，`pacman -Qkk` 为 22 个文件、0 改动。
安装前后配置哈希与三个服务 PID 保持；随后启用 90°C 策略只重启 thermald，
新 PID 为 222684，TCC 97821、nvidia-powerd 1003 保持运行。

恢复原先仅限制功耗的策略可执行 `sudo mechrevo-power set 55`，这会取消显式温度目标；
PL2 没有被持久托管，仍为 140 W。用法及恢复边界见[功耗控制](../POWER-CONTROL.md)
和[短时功耗试验](../PEAK-LIMIT-TRIAL.md)。本地证据在
`.local-tests/postboot-20261016/power-thermal/`，B、C 私有试验记录及升级前恢复材料在
`~/Backups/projects/mechrevo-drivers/light/power-thermal-20261016/`。
文件跟踪有未解析事件，安装结果已另行逐文件核验；原始私有 JSON 不上传。

## 2026-10-16 采样进度保存与进程中断回归

源码复现了 r5 在观测结束前只创建空输出文件的问题：新增回归在旧实现上因空文件
JSON 解析失败，说明此前样本仅保留在内存。现改为预检前与每组采样后保存完整进度，
使用同目录临时文件、文件同步及原子替换；未完成进度始终为 `valid=false`、`complete=false`。
输出文件权限为 0600，已有路径／链接或被外部替换的文件不会被正常保存流程覆盖。

28 项采样测试和 6 项打包测试通过，含真实子进程的 SIGTERM、SIGHUP、SIGKILL，
已保存样本在中断后仍可解析；SIGTERM／SIGHUP 还保存中断原因。模拟写盘失败时上一份
完整进度保持，临时文件被正常清理。强制结束可能遗留临时文件或丢失最新未保存样本，
没有将这些测试扩大为断电、磁盘故障或 GPU 正常状态下的完整实机验收。

`mechrevo-power-control 0.1.0-6` 已安装，交付源码固定于
`315e20dcc22edeaa978b1e638001e3c7588c9d15`。实际包文件与安装内容一致，
真实 GPU 失联预检仍拒绝采样，新的 `--output` 保留完整失败 JSON 且权限为 0600。
升级前后 TCC settings、托管 XML、drop-in、state 哈希和三个服务 PID／状态保持，
55 W 请求仍生效；没有施加负载或调整硬件控制。旧 r5 包已校验归档。

证据在 `.local-tests/thermal-output-20261016/`，恢复包在
`~/Backups/projects/mechrevo-drivers/light/rapl-power-control/thermal-output-20261016/`。
安装文件跟踪记录了 14 项未完全解析的临时文件／文档路径事件，最终包和配置独立核验通过；
原始私有日志不上传。正常 GPU 下的实机观测及显卡失联根因仍待继续验证。

## 2026-10-16 故障保护采样工具（GPU 未恢复）

机器仍是上一轮启动，NVIDIA GPU 仍无法由 nvidia-smi 识别；没有重启、复位显卡、
调整功耗／风扇、重载驱动或增加压力负载。新增只读 `mechrevo-thermal`，用于防止
继续把失联状态下的数据当作有效热控观测。

23 项采样／适配器／命令回归和 6 项实际打包测试通过。覆盖 GPU 预检失败、采样中
新增 Xid／不可纠正 PCIe 错误、日志不可读、启动身份改变、PL1 短暂超限、配置变化、
读取失败、中断、异常参数，以及输出文件／链接拒绝覆盖。实际 sysfs 适配器测试
检查了五个请求均为读取 ioctl，正常夹具数据无文件修改。

本机真实执行源码及已安装命令均退出 1，输出 `valid=false`、`complete=false`、
零样本及 nvidia-smi 失败原因。源码命令的独立 strace 还确认未打开 `/dev/tuxedo_io`；
预检在 EC 采样之前拒绝，而非先采样后掩盖错误。

独立工具包 `mechrevo-power-control 0.1.0-5` 已本地安装，交付源码固定于
`d686fa0e29348ce66e02b21480101114a2d15f9d`。包内文件逐字节核对，`pacman -Qkk`
通过；旧 r4 包已复制至统一备份目录并校验与升级前安装的原命令／模块一致。
升级前后 TCC settings、托管 XML、drop-in、state 的 SHA-256 相同，
tccd／thermald／nvidia-powerd 的 PID 及 active 状态保持。55 W 请求仍确认生效且无待完成事务。
源码交付不是 GPU 恢复或散热改善；正常 GPU 下的完整采样仍待实机验收。

用法与边界见[只读采样说明](../THERMAL-OBSERVATION.md)。本地证据在
`.local-tests/thermal-guard-20261016/`，含测试、实际包、安装收据和失联拒绝结果；
恢复包在 `~/Backups/projects/mechrevo-drivers/light/rapl-power-control/thermal-guard-20261016/`。
系统安装的文件跟踪有一项文档路径删除事件未完全解析，最终安装文件另行独立核验。
原始机器日志留本地，不作为公开报告或 AUR 发布。

## 2026-10-15 较低 RAPL 上限与 GPU 掉线

修正了用户态功耗工具将 55 W 热设计参考值当作设置下限的问题。
本机身份检查仍要求 55 W 的参考字段；用户上限可低至 35 W，温控范围仍成对设置，
允许继续降限、解除降温限制后回到所设上限，以及升级其他降温设备。
74 项事务／状态测试、12 项原生 thermald 控制函数回归、6 项实际打包测试通过。
失败回滚、拒绝 35 W 以下请求、保留已生效的更低温控限值均有覆盖。

独立工具包 `mechrevo-power-control 0.1.0-4` 已本地安装；包内源码与提交
`56e876e691e455ec392dd979f102fe9042964416` 一致，`pacman -Qkk` 为零改动。
没有更换内核驱动或发布新的 AUR 包。

实机顺序为 55、45、35、55 W，每档 61 个样本、间隔约一秒。
每档第 8 秒启动两个固定 PBKDF2-SHA256 工作进程，各执行 50 秒；后台其他任务保持运行。
以下为约第 8–58 秒的描述性结果，**不是可用于选择最佳档位的有效对照**：

| 请求上限 | 封装均温 | 封装最高 | 平均封装功耗 | CPU0 封装节流计数增量 | 任务吞吐（次/秒） |
| --- | --- | --- | --- | --- | --- |
| 55 W（首轮） | 88.38°C | 96°C | 29.90 W | 4542 | 125.60 |
| 45 W | 93.22°C | 98°C | 33.74 W | 3819 | 151.08 |
| 35 W | 89.02°C | 96°C | 32.26 W | 1105 | 131.06 |
| 55 W（末轮） | 94.78°C | 98°C | 37.77 W | 3866 | 152.03 |

各档 MSR/MMIO PL1 样本均不高于请求值，MSR 仍可进一步下降；MMIO 分别保持对应上限。
PL2 始终为 140 W，未调整短时功耗。TCC settings SHA-256 前后相同，无新增 Uniwill
EC 读写错误。上述计数不是节流时间或性能损失比例。

23:28:24（Asia/Taipei）发生 NVIDIA Xid 79，并伴随 PCIe 不可纠正、非致命事务层错误；
驱动随后记录 Xid 154，恢复动作要求 OS Reboot。事后 `nvidia-smi` 无法识别显卡。
故障发生于 35 W 试验窗口，不能由时间相邻断定功耗调整导致，也不能将 GPU 故障后的
数据与故障前视为同等条件。各轮后台负载亦变化，因此不报告散热／性能改善百分比。
检查时 GPU 与根端口的 ASPM 均已 Disabled，不能盲目把关闭 ASPM 当作新修复。
[NVIDIA Xid 说明](https://docs.nvidia.com/deploy/xid-errors/analyzing-xid-catalog.html)

试验工作进程已结束，托管请求恢复 55 W；`holding_now=true`、无待完成事务，
tccd、thermald、nvidia-powerd 仍 active，但服务 active 不代表显卡功能正常。
未重启机器、复位 PCIe、重载驱动或改风扇曲线；需要先恢复 GPU，再做干净的交错复测。

本地证据在 `.local-tests/thermal-optimize-20261015/`，包括实际包、安装日志、
`comparison.json`、`comparison.log`、`gpu-failure-kernel.log`、PCIe 状态和故障时间戳。
恢复快照在 `~/Backups/projects/mechrevo-drivers/light/rapl-power-control/thermal-optimize-20261015/`，
包含原工具、托管配置与状态的逐字节校验副本。原始机器日志不上传。

## 2026-10-15 GitHub 与 OEM 资料研究（只读，无新硬件验收）

本轮找到匹配本机 i9-12900HX／BIOS N.1.09MRO07 的公开 DMI 样本、GM6PX0X 社区逆向项目
及机械革命官方精确商品与软件目录。社区源码和官方 TUXEDO 源码交叉提供 EC 功耗候选线索，
但本机固件到原厂配置目录的映射、编码／前置模式及安全范围尚未闭合；未开放 EC TDP。
公开样本不证明固件可互刷，其他机型的范围表不作为本机安全白名单。

NVIDIA 官方 main 仍无 GPU `0xC5` 分支，Q&A #1447 仍未回复；#1181／#1299 是他机
空闲 GPU 通知唤醒相关补丁，均未合并，不能作为本机 `0xC5` 的修复。
详见[功耗、固件与适配调查](<../../reports/GM6PX0X 功耗 固件 适配调查.md>)，其中区分了
原始源码、作者他机观察、现有本机证据及仍缺的材料。

本机只读保持核对显示：内核仍为 `7.2.9-arch1-1`，五个运行模块 build ID 与前轮基线一致；
已安装 DKMS 包仍为 `4.24.0.r37.gbd8f514-1`，功耗工具仍为 `0.1.0-2`，四个相关服务 active。
没有安装、加载、改写 EC／功耗、改变服务、下载或执行 OEM 二进制，也没有睡眠或重启。
本轮没有新增硬件验收；Fn-lock 生效、睡眠／唤醒、实体热键、充电、外屏和长期负载的限制保持。
私有原始运行收据只留本地，不纳入公开报告或源码提交；此前恢复材料未改动或清理。

## 2026-10-15 孤儿功耗配置诊断与 AC 自动开机事务（未安装）

接手时 `main`、远端及工作树核对与 `2d72972` 交接一致。五个运行模块的 build ID
与上一轮记录相同，仍为 IO r23、其余四个 r10；已安装 DKMS 包保持
`4.24.0.r37.gbd8f514-1`，独立功耗工具保持 `0.1.0-2`。
以下两项修复仅完成源码验证，没有安装或加载，不改变上一节 Fn 锁修复尚未生效的结论。

- `dabd57a` 修正功耗工具 `status` 在 state 缺失而 XML/drop-in 仍存在时错误报告正常的行为。
  现在包括断链在内的孤儿配置会保留 JSON 并退出 1，不删除文件或代替用户恢复。
  三种文件组合、两种断链均在旧源码上失败；新增 5 项回归还覆盖健康未配置、损坏 state
  及 state 已落盘、XML 尚未写入的固定交错。查询检查无控制写入、服务重启或文件变化。
  `status` 仍是跨文件的非原子只读观察，不承诺并发修改期间的完整快照。
- `40f6dc8` 将 AC 自动开机设置的分离读写换成现有共享 EC 事务，仅操作已有
  `0x0726` bit 3，保留低位输入语义、缓存成功条件和 sysfs 错误转换。
  新增 12 项实际 C 回归覆盖 256×256 字节/输入组合、读写错误、失败写副作用、sysfs，
  以及其他位更新和整字节写入的两种先后顺序。旧源码恰好失败两项，并留下陈旧写回的 transport trace。
  这是模拟 provider 并发回归；本机不匹配 AC 自动开机的支持名单，没有开放该功能或实机验收。
  现有 bool 缓存没有读者，写入仍在 provider 事务之外，不宣称缓存并发写入已同步。

功能源码及测试哈希在验证前后保持。**494 项完整本地测试通过**（39.997 秒）；
两个内核各在全新目录独立编译全部 27 个模块，逐个核对模块名和 vermagic，均无编译警告。
这些本地构建没有安装、签名或加载；不触发或等待远程 CI/CodeQL。

修改后的源码 CLI 在本机真实执行只读 `status`，现有 55 W 配置通过检查；
已安装 r2 CLI 也通过。保护文件的内容、权限及所有者在两次查询间保持；
五个运行模块、四个服务的 PID/启动时间及 Fn 锁、背光/RGB、cTGP 读值保持。
两包完整性检查分别为 103、16 个条目，均为 0 改动。
没有人为制造本机孤儿配置，没有再次 set/apply/clear、停止温控、热卸载、重载、睡眠或重启。
这不扩大持续负载、充电、实体热键、外接显示器或其他型号的验证范围。

独立工具配方另准备 `0.1.0-3`，冻结源码为
`dabd57a3532acbf41a67de2bbe08ac2651b5e8da`。本地真实打包、四个包内交付文件与固定提交的
逐字节核对、配方 ShellCheck 和 6 项打包回归通过；没有安装该包、正式发布或发布 AUR。
494 项全量验证之后只调整了包版本、源码 pin 及相应测试中的版本预期，相关打包回归单独重跑。

证据和本地新包在 `.local-tests/followup-20261015/`：`validation.json`、`all-tests.log`、
两份内核构建日志、AC 红绿回归、`power-orphan-red-final.log`、`power-orphan-green.log`、
`live-status.json` 及 `power-package.json`。早期尝试因测试夹具 fsync 超过 3 秒触发的异常，
以及版本升级时测试残留旧包文件名的失败日志均保留，不当作产品问题。
原始机器证据不上传。没有改动或删除既有恢复材料；两套独立构建目录为临时产物，未授权清理。

跟踪早期有启动失败和短暂心跳过期；检查就绪后才直接编辑，过期时暂停并改用独立包装器。
之后缩小 watcher 范围为源码、测试、文档和本轮证据。构建的 FIFO、测试短命文件及打包工作区
权限边界存在跟踪缺口，打包包装器的最终扫描状态为 failed，实际打包子命令成功且制品独立核对通过。
Git 内部目录不受该工具单独跟踪；最终扫描和测试成功不代表完整文件历史。

## 2026-10-15 Fn 锁共享 EC 事务修正（已安装，未加载）

已安装 `mechrevo-drivers-dkms-git 4.24.0.r37.gbd8f514-1`，包内驱动源码冻结于
`bd8f514a67faf9e68c4ce19a38b7b3c756ef58a7`。安装前为 r30，而不是 r34。
源码与回归已提交并推送 GitHub；本轮没有发布 AUR。

源码确认 Fn 锁设置原先在独立的读、写之间释放共享 EC 锁，其他请求可在间隙更新同一字节，
随后被旧值覆盖。现在通过现有 `uniwill_update_ec_ram()` 完成一个完整事务，仅更新已知的
`0x074e` 寄存器 `0x10` 位，保留其他字段和原有 sysfs 输入规则，没有猜测新寄存器。
固定线程交错在旧源码上复现两类失败；这是模拟并发错误，不是本机物理 EC 丢更新的实测记录。

- **477 项本地测试通过**；新增 12 项 Fn 锁用例覆盖全部 256 个寄存器字节、错误传播、
  失败写入的副作用、sysfs 边界，以及与其他位更新和整字节写入的两种先后顺序。
- `7.2.9-arch1-1`、`7.2.7-arch1-1` 均独立编译全部 27 个模块，安装时 DKMS 再次完成两套构建。
  两个内核的 54 个已安装模块均核对名称、vermagic 和非空 signer 字段；后者不是全部模块签名的密码学校验。
- 包完整性检查为 103 个条目、0 个改动；76 个包内普通文件与安装内容逐字节一致，
  55 个驱动源码文件另与固定 Git 提交逐字节一致。
- 安装钩子重新生成并签名当前内核 UKI；`sbctl verify` 的三项 EFI 文件检查通过。
  Secure Boot 仍关闭，另一个内核没有在本轮启动验证。保留原有 Renesas xHCI 固件缺失警告，未掩盖它。
- `tccd`、`thermald`、`nvidia-powerd`、`power-profiles-daemon` 均 active；Fn 锁仍为 0，
  背光/RGB 为 `1` / `4 4 4`，cTGP 为 25。没有主动切换这些设置。

**新修复尚未运行生效。** 五个运行模块的 build ID 仍与此前已核验的混合批次记录一致，
本轮安装前额外采集的三个模块 build ID 也保持；IO 仍为 r23，其余四个仍为 r10。
没有热卸载、单独重载 IO、停止温控、睡眠或重启。需要后续安排整机重启后，
再核对统一模块版本并实测新 Fn 锁；不能用磁盘安装和编译成功代替这一步。
EC TDP、GPU `0xC5`、实体热键和长期负载等既有限制没有因此解除。

旧 r30 包、旧源码/DKMS 状态、两套已安装模块及完整 EFI 文件保存于
`~/Backups/projects/mechrevo-drivers/light/20261015-fnlock/`，约 516 MiB。
归档 257 个条目逐项验证内容、权限、所有者及链接，旧包全部 75 个普通安装文件核对通过；
附校验清单和恢复说明。证据及新包在 `.local-tests/fnlock-20261015/`，约 57 MiB，
其中两套约 52 MiB 的独立编译目录为临时产物，未擅自删除。
文件跟踪覆盖选定源码、证据、DKMS、安装目录和 EFI；DKMS 链接边界及短命文件存在记录缺口，
安装钩子的 `/tmp` 工作目录和范围外系统状态不在完整跟踪内，不将最终核对称作完整写入历史。

## 2026-10-15 功耗工具状态检查加固（用户态已生效）

独立工具已从 `mechrevo-power-control 0.1.0-1` 更新为 `0.1.0-2`，
包内源码冻结于 `8578d5f9d28a27af2ee5354670cf9616a2c65e78`。
四个已安装文件的内容、root 所有者和权限均已核对；包完整性检查为 16 个条目、0 个改动，
原 `thermald` 包为 22 个条目、0 个改动。没有更新 DKMS 包或发布 AUR。

已复现损坏应用收据中的字符串 `"false"` 被当作成功、空数组事务被当作未配置事务，
以及缺少嵌套快照字段或错误收据类型导致未处理异常的问题。
现在加载状态时检查事务所有者、功耗快照、哈希及应用收据的类型和一致性；
损坏状态阻止修改命令，保留原文件和运行中的温控，不借修复之名删除状态。
`status` 发现错误仍输出 JSON，但退出码为 1；正常的未配置状态保持退出码 0。

最终 **465 项本地测试通过**。新增 5 项回归，其中损坏状态测试覆盖 36 组变体及
6 组无效事务所有者，并检查无功耗写入、无服务重启、无文件覆盖；
另覆盖有效状态、失败收据、暂未应用的状态及 CLI 退出码。
新增回归在旧源码上曾产生 26 次失败和 2 次未处理异常，最终源码及配方通过完整回归。
真实本地归档构建、源码冻结核对和配方 ShellCheck 均通过。

安装前后真实 `status` 均无错误，MSR 与 MMIO 的 PL1 当次回读均为 55 W。
受管状态/XML/drop-in、thermald 偏好和 feature 文件、原服务单元、TCC settings 的内容及权限保持；
四个驱动的运行 build ID 在本轮安装前后保持，Fn 锁、充电档位、背光/RGB/cTGP 读值保持。
前置快照误写 GPU 模块名，未捕获该项；随后用真实模块名 `tuxedo_nb02_nvidia_power_ctrl`
补查，其 build ID 与此前已核验记录相同，没有把缺失值当作前后验证。
`thermald`、`tccd`、`nvidia-powerd`、`power-profiles-daemon` 的 PID、状态和启动命令保持。
安装没有重启这些服务、重载模块、睡眠或重启机器，也没有再次进行真实 set/apply/clear。
本轮验证的是已有配置兼容与状态读取；不能据此扩大持续负载、睡眠恢复及其他型号的验收范围。

旧工具包与当前已安装旧文件逐字节核对后，恢复材料保存并校验于
`~/Backups/projects/mechrevo-drivers/light/20261015-power-state-validation/`，包含旧包、
带内容/权限/所有者的安装前快照、校验清单及 `RESTORE.txt`。
包回滚仅重新安装该旧工具包，不默认重启 thermald 或覆盖当前状态。
证据和新包保留在 `.local-tests/state-validation-20261015/`，不上传原始机器记录。
本轮该目录约 4.3 MiB，其中构建工作区约 1.4 MiB 为临时产物，未擅自清理旧证据。

文件跟踪保留早期包装器超时、数据库锁冲突，以及测试短命文件/打包权限造成的缺口；
后续使用独立状态目录并确认基线就绪。安装跟踪覆盖工具、包数据库、日志及功耗状态目录；
安装钩子的 `/usr` 目录时间戳及 PackageKit IPC 所涉范围外状态不在该跟踪内。
未把最终扫描或成功安装写成完整的文件写入历史。

## 2026-10-15 RAPL 用户上限与原生温控协调

独立用户态工具 `mechrevo-power-control 0.1.0-1` 已在本机安装，源码冻结于
`124a440bbad69643fd6752b90db6e2832ac61884`；实际包内四个文件与该提交逐字节一致，
包完整性检查为 16 个条目、0 个改动。它没有加入现有 DKMS 包或发布到 AUR。
本轮 460 项完整本地测试通过，其中新增 62 项 CLI 行为回归、11 项实际 thermald C++
控制链回归和 6 项打包回归。冻结源码在测试前后哈希一致，未用较早的变化中测试代替最终验收。

本机原有 `thermald 2:2.5.13-1.1` 二进制保持，22 个包文件完整性核对通过。
工具严格核对本机 DMI、BIOS `N.1.09MRO07`、i9-12900HX、发行版二进制哈希、
有效且已启用的两套 RAPL 长期约束，并拒绝 PPCC、自适应平台、外来配置及会触发
额外 TCC offset workaround 的情况。当前没有这些固件接口，原服务原本走 default 回退路径；
启用工具时明确使用该原生 default engine 与独立 XML，保留默认温控区及原温度阈值。

真实 `set 55` 将 MSR 和 MMIO 两套 PL1 下调到 55 W。
随后 90.44 秒、180 次样本中，MSR 为 34、41、48、55 W，MMIO 保持 55 W，
没有任何样本超过请求上限。独立内核跟踪捕获同一 thermald 进程的 44 次长期限值写入，
请求值同为 34、41、48、55 W，44 次返回全部成功。
这同时验证了本次观察内的上限保持、温控继续下调，以及降温约束放松后回到 55 W；
不是靠后台循环与温控反复抢写。临时探针和 trace instance 已撤除。

在较低温度窗口还执行了真实 `clear`：受管 XML、drop-in 和状态撤销，原始
`--adaptive` 服务命令恢复且服务 active，两套限值回读均为 140 W。
这是交回原生策略后的当次读值，不是工具主动写高功耗或保证该值以后固定。
随后重新应用 55 W 成功。受管配置下另一次直接重启 thermald，启动回调生成新的成功收据，
两套实际 PL1 再次不超过 55 W；服务退出到启动回调完成期间不承诺严格保持上限。
这次服务重启后的 60.35 秒、120 次样本也通过：MSR 仍为 34、41、48、55 W，MMIO 为 55 W。

五个运行模块 build ID、TCC settings 字节、cTGP、背光/RGB/Fn 锁、原内核温控 trip 值，
以及 tccd、power-profiles-daemon、nvidia-powerd 进程均保持。
PL2、peak 约束及 enabled 的采样值保持；长期时间窗口仍由 thermald 原生状态机调整。
XML 匹配使 thermald 创建偏好文件和 `.save`，偏好值保持原来的 ENERGY_CONSERVE，
没有宣称这些运行文件的存在性或字节完全不变。
没有重载驱动、重启 TCC、睡眠、重启机器或增加压测工作进程。

重要限制：现有任务下 90 秒 CPU package 能量差分均值约 39.31 W，低于 55 W，
因此没有证明持续满载下的平均功耗执行效果。温度采样为 86–100°C，曾达到本机
100°C 临界参考值；没有据此宣称温度下降、散热改善或长期稳定性已验收。
55 W 以外的设置、整机重启、睡眠恢复、不同内核、BIOS 和其他型号仍未实机验收。
CPU RAPL 不代替尚未开放的 EC TDP，也不解决 GPU `0xC5` 问题。

用法及撤销、中断恢复见 [功耗控制说明](../POWER-CONTROL.md)。
证据保留在 `.local-tests/rapl-fix-20261015/` 的完整测试、实际包、`held55_first.json`、
`first-hardware-summary.json`、`thermal-writer-identities.json`、`clear-reapply.json`
及 `restart55.json`、`held55_after_restart.json`、`restart-hardware-summary.json`。
每次配置事务的恢复材料统一保留在
`~/Backups/projects/mechrevo-drivers/light/rapl-power-control/`，原始机器日志不上传。

## 2026-10-15 Intel RAPL 临时降限试验

本轮已安装包为 `4.24.0.r30.g85bf136-1`，五个运行模块仍保持 IO r23、其余四个 r10。
本机 CPU 是 Intel Core i9-12900HX，Linux 同时暴露 MSR 和 MMIO 的 package-0 RAPL 接口。
这条标准 CPU 功耗控制路径与尚未适配的 MECHREVO EC TDP 接口不同。

第一轮预检观察到长期限值在 119、126、133、140 W 之间动态变化，因此没有执行写入。
第二轮在短暂稳定窗口，只向 MSR 接口的 `constraint_0_power_limit_uw` 写入一次 55,000,000，
从 140 W 下调为 55 W，并立即读回相同值。
约 0.255 秒后，该限值变为 133 W，时间窗口从约 55.97 秒变为约 1 秒，脚本停止，没有反复抢写。
外部控制接管后没有强行恢复更高限值；结束时回读的两套控制值均与 140 W 基线一致。
这不是本脚本主动恢复成功或长期固定限值的证明，之后仍可能被温控服务动态调整。

随后独立的六秒内核跟踪捕获 `thermald` 成功写入长期限值 126 W 和 133 W，返回值为 0。
这与前述覆盖模式吻合；跟踪发生在试验之后，没有直接捕获那一次覆盖事件。
临时探针和 trace instance 均已撤除，没有停止或重启温控服务。

55 W 来自本机长期约束的热设计参考值；[内核实现](https://github.com/torvalds/linux/blob/master/drivers/powercap/intel_rapl_common.c)
将该项映射到 `THERMAL_SPEC_POWER`，不能将它当作已核实的整机最大安全功耗。
试验前现有任务的 CPU package 能量差分采样均值约 40.34 W，没有另加压测；
低限值保持时间又很短，因此不能宣称已经验证满载限功耗、温度改善或稳定的手动调节。
sysfs 没有原子比较后写入的所有权机制，不能完全排除其他控制器写入相同值的竞争。

没有请求修改 PL2、时间窗口、enabled、MMIO、EC、GPU 或风扇。
五个运行模块 build ID、TCC 配置字节、cTGP、背光/RGB/Fn 锁及四个服务进程均保持。
没有睡眠、重启或模块重载；内核写 RAPL 时可能同时调整功耗通知处理，未声称全部硬件寄存器逐字节恢复。
接下来需要协调 RAPL 用户设置与 `thermald`，保留温控保护，再验证限值保持、恢复和负载效果。
EC 地址、单位和整机范围仍缺少本型号依据，没有据此开放 EC TDP 白名单。

原始记录保留在 `.local-tests/rapl-20261015/summary.json`、两轮 `probe-*/receipt.json`
和 `writer-trace.json`，不上传原始机器日志。
写入前控制快照已核对并保留于统一 Backups 目录的 `light/20261015-rapl-intel-rapl-0/`。

## 2026-10-15 probe、PM、Clevo 与 LED 修正（r23，部分生效）

已安装并发布 AUR `4.24.0.r23.gf1aa652-1`，包源码 `f1aa652`；功能提交最终为 `2c749ac`。
281 项本地测试通过，两个内核各重新编译全部 27 模块；包内隔离 DKMS 另通过 54 模块构建。
系统 DKMS 为两套内核编译、签名并安装 54 模块；包完整性、UKI 与引导器签名核对通过，未重启。
安装 hook 保留此前已有的 `xhci_pci_renesas` 缺少固件警告，没有隐藏日志或额外改动该驱动。

只精确重载 `tuxedo_io`，其运行 build ID 与新磁盘模块一致。
keyboard、WMI、兼容检查和 GPU 电源模块的运行 build ID 保持 r10；
新 probe 错误回退、适配器/PM 门禁、背光阻塞回调、睡眠队列及重绑修复仍未运行。
Arch 未启用 `CONFIG_MODVERSIONS`；重载前另核对共享头文件、十个项目接口的签名和导出、
新 IO 源码、导入符号和依赖均与已审版本一致，不能用未启用的 CRC 检查代替这项核对。

本机 profile 数量仍为 0，合法但不支持的模式返回 `ENODEV`，非法枚举返回 `EINVAL`，空指针返回 `EFAULT`。
无效风扇参数、九项不支持 TDP 读取及三项写入拒绝通过；失败读取的缓冲区保持不变。
Clevo 识别为不存在；空接口字符串、空指针和六项失败读取检查通过，未执行有效 Clevo 固件写入。
三次样本均为 CPU 95°C、GPU 55°C、双风扇原始值 170，不是 RPM 或散热改善证据。

cTGP 前后均为 25，原背光/RGB/Fn 锁读值保持；`tccd`、`thermald`、`nvidia-powerd` 均 active。
安装前后 `/etc/tcc/settings` 的 SHA-256 完全一致。
这些旧 keyboard 控件仅读取用于检查状态保持，不能当作新 LED 修复的硬件验收。
没有触发闪烁、物理按键、手动风扇、睡眠或重启，长期负载、电池及其他型号也未验收。
NVIDIA `0xC5` 仍未修复，GM6PX0X TDP 仍缺少规范；没有据此启用猜测性写入。

证据在 `.local-tests/next-20261015/` 的 `main-validation/receipt-final.json`、
`package-validation/receipt.json`、`system-install/receipt.json`、`live-runtime/output/receipt.json`
及 `postinstall/receipt.json`。r16 包、54 模块和原 TCC 配置已保存并校验于
`~/Backups/projects/mechrevo-drivers/light/20261015-next-r16/`。
跟踪保留事件队列溢出、临时 FIFO 等缺口；安装阶段使用轮询，Limine 的短命 `/tmp` 目录不在选定根目录内。
不把最终扫描当作完整历史，未额外清理。

## 2026-10-15 能力、序列及 EC 错误修正（r16，部分生效）

已发布 AUR 并安装 `4.24.0.r16.gb549e06-1`，包源码 `b549e06`，三项功能修复为
`8ab40fb`、`6a924ac`、`165434a`。包内源文件与该提交逐字节一致，包完整性检查通过。
两套内核的 27 个模块均经系统 DKMS 编译、签名和安装；UKI 与引导器签名检查通过。
这不代表已完成重启或启动验收。

本轮仅用 `rmmod tuxedo_io` 精确卸载 IO 后重新加载，新 IO 的 GNU build ID 与磁盘一致。
keyboard、WMI、兼容检查和 GPU 电源模块的运行 build ID 均保持 r10；
绑定、按键任务、序列和 custom-profile 修复尚未在运行中生效。
不通过旧 keyboard 的已知卸载问题路径强行重载，按用户安排留待以后重启。

本机公开 profile 数量为 0；向三个合法枚举写入均返回 `ENODEV`，
0、4、`UINT32_MAX` 返回 `EINVAL`，空指针返回 `EFAULT`。
拒绝前不访问 EC 的依据是实际 C 回归和已匹配的源码，没有声称做过实时 EC 探针。
两只风扇的超范围输入拒绝、九项不支持 TDP 读取及三项写入拒绝通过；
三次样本为 CPU 95°C、GPU 54°C、风扇原始值 170，不是 RPM 或散热改善证据。
cTGP 前后均为 25，背光/RGB/Fn 锁值保持，`tccd`、`thermald`、`nvidia-powerd` 均 active。
仅读取这些旧 keyboard 控件用于核对保持状态，不作为新修复的硬件验收。

新增修正按机型声明的能力限制公开性能模式，避免接受不存在的档位；
合法 custom TDP 的内部 OVERBOOST 和 raw MODE ABI 保持。
过滤器移除后及重新安装前清零半截触控板按键序列，避免跨重绑漏报或误排任务。
custom-profile 的读取/reset/enable 任一步失败后停止依赖操作，保留错误并继续其他初始化；
GM6PX0X 仍未启用该能力，没有据此开放本机 TDP 或写入新寄存器。

完整 **201 项本地测试通过**。新增能力测试检查全部 16 组标志组合；
8 项完整实际 probe/filter/remove 测试各编译四组 API 宏，初始化服务由模拟实现；
16 项 custom-profile 回归覆盖逐项 EC 失败和全部初始寄存器字节。
同一测试运行旧源码能分别捕获原错误；这些不是实机 EC 故障注入或物理按键验收。
源代码与日志保存在 `.local-tests/remaining-20261015/`。

安装前已保存并独立解包校验 r10 包和两套内核的 54 个项目模块，路径为
`~/Backups/projects/mechrevo-drivers/light/20261015-remaining-r10/`。
本轮按用户安排不睡眠、不重启；运行中的模块与磁盘包需分别核对。

## 2026-10-15 绑定失败修正（源码验证，未安装）

本节此前验证时安装包为 `4.24.0.r10.gc79a268-1`。当时修正尚未安装、加载或进行实机故障注入，
不代表运行中的模块已经包含这些改动。

模拟 EC 错误可使风扇启动和键盘探测失败；旧外层绑定仍报告成功，随后解绑可能访问空驱动。
修正将失败传回 WMI probe，回滚 transport 和事件回调，并处理重复解绑、错误接口解绑、
其他驱动占用和输入设备初始化失败后的残留指针。事件回调在成功初始化后才发布，解绑前清除。

另外修正触摸板辅助按键任务的生命周期：卸载先停止本驱动安装的 i8042 过滤器并同步排空任务，
再清空、释放输入设备；直接平台解绑也经过同一入口。输入设备注册失败时，任务不再访问空指针。
这解决已排队或正在运行的任务在卸载后继续访问输入设备的问题，不能只靠空指针检查替代排空。

新增回归提取真实绑定函数和风扇启动路径，模拟平台、输入设备及 EC。
本维护分支 **170 项本地测试通过**，其中 13 项绑定回归、11 项按键任务生命周期回归；
后者使用 pthread 条件变量固定排队、运行和卸载的交错，不是内核调度压力测试。
绑定修正前的维护源码在 13 项中失败 11 项；已修绑定但尚未修按键任务的源码在 11 项中
失败 9 项、通过 1 项、跳过尚不存在的并行准备入口用例 1 项。
最终维护源码独立通过 `7.2.9-arch1-1` headers 的全部 27 个模块编译，未安装或加载。
维护分支继续基于 `4.24.0`，独立运行全量测试并编译；上游贡献分支基于 `4.25.0`，
其构建结果不能代替本维护分支的验证。日志保存在
`.local-tests/upstream-20261015/local-binding-validation/`。
这类模拟失败不是本机真实 EC 故障，也不覆盖 LED、电池等完整探测流程。
按键任务用例模拟 filter 的安装状态，没有执行完整 probe 的 filter 安装尾部。

## 2026-10-15 并发修正（r10）

本节当时安装并加载 `4.24.0.r10.gc79a268-1`，功能提交 `c79a268`。
从已推送的 GitHub `main` 构建，经 `pacman -U` 升级；两个内核各完成 27 个模块编译、签名和安装。
五个运行模块的 GNU build ID 与磁盘一致，三个改动的驱动源文件与 `/usr/src` 安装内容逐字节一致。
包完整性检查仍为 100 个文件、0 个改动，UKI/引导器签名检查通过；未重启，Secure Boot 仍关闭。

本轮对风扇手动/自动模式、初始化、MODE/profile、睡眠恢复和卸载操作进行同步，
避免后台任务与请求交错时丢失目标或覆盖模式位。取消任务时释放其需要的状态锁；
卸载先排空任务再拆除资源，重新探测明确重置生命周期。
MODE 的低字节格式、profile 位映射、原有寄存器和曲线及正常 50 分钟周期保持。
DEBUG 任意地址 EC 写入不属于这套同步保障。

- **146 项本地测试通过**：46 项 ioctl、37 项风扇顺序/故障、12 项风扇并发、
  18 项 WMI、9 项电源、24 项打包/同步。
- 并发用例提取实际 C 函数，使用 pthread 条件变量固定执行交错，检查最终寄存器、缓存和任务状态。
  修改前源码有 9 项失败、2 项原有保障通过，1 项新增生命周期用例跳过；
  profile 基线提取真实旧函数，使用正确的 powersave 位映射。
  这些仍是模拟 EC/工作队列测试，不是实机故障注入或内核 lockdep 检验。
- 实机顺序两次自动模式及两线程合计四次自动模式请求均返回 0；两只风扇的 `256`、
  `UINT32_MAX` 参数仍各返回 `EINVAL`。没有请求任意手动转速或更改曲线。
- 背光 `1 → 0 → 1`、Fn 锁 `0 → 1 → 0` 写入/回读及恢复通过；RGB 恢复 `4 4 4`。
  九项不支持 TDP 读取、三项不支持写入和无效指针检查通过。
  三次温度样本均为 CPU 95°C、GPU 53°C，两个风扇原始值均为 170；不是 RPM 或散热改善证据。
- cTGP 在重载前、重载后 TCC 启动前及 TCC 启动后均为 25。
  `tccd`、`thermald`、`nvidia-powerd` 均恢复运行。
- 本轮采集窗口没有出现 NVIDIA `osapi.c:2198` 日志，但没有修改 NVIDIA 处理器，
  不能据此认定 `0xC5` 兼容问题已解决。官方后续源码核对见 [NVIDIA 记录](../NVIDIA-0xC5.md)。

真实重启、睡眠/唤醒、手动风扇、实体热键、外接显示器、充电行为及长期负载仍未验收。
TDP 仍没有本机安全边界依据，保持不支持。

本轮日志在 `.local-tests/concurrency-20261015/`，包含全量/双内核构建、并发基线/修复/独立复核、
安装和实机快照；`cpyref-receipt.json` 保存固定源码及测试引用的完整空间信息。
升级前 r8 包和两套内核的 54 个项目模块保存在
`~/Backups/projects/mechrevo-drivers/light/20261015-concurrency/`，独立解包校验及 `SHA256SUMS` 复核通过。
早期故意失败测试留下约 31 MiB core 转储，已观察并标为临时；创建时不在原 watcher 根目录内，
不能补作完整历史。测试现已禁止生成 core，详见本地 `coredump-observations.json`；未额外清理。

以下 r8、r6 内容保留为历史验证记录。

## 2026-10-15 续验

当前安装并加载 `4.24.0.r8.g90fae0c-1`，功能修复提交 `90fae0c`。
经 GitHub `main` 构建及 `pacman -U` 升级，两套内核各完成 27 个 DKMS 模块的编译、签名和安装。
安全重载项目模块后，五个运行模块的 GNU build ID 与磁盘一致；本轮改动的
`uniwill_keyboard.h`、`tuxedo_io/tuxedo_io.c` 与安装源码逐字节一致。
`pacman -Qkk` 报告 100 个文件、0 个改动，UKI/引导器的 `sbctl verify` 通过。
仍未重启，Secure Boot 仍关闭。

本轮修正风扇参数截断、EC 失败吞错、重试回读不匹配、全速模式幂等性和恢复缓存。
睡眠恢复先准备双风扇目标；部分失败不再让已排队任务使用另一风扇被清零的缓存。
挂起失败会在本回调尽力恢复，不依赖系统再调用恢复回调；后续手动/自动命令更新或取消旧目标。
后台失败后，下一次手动请求会取消旧定时任务并立即排队恢复。
原有寄存器、曲线、速度映射和正常成功路径的 50 分钟定时策略保持。

- 本地 **125 项测试通过**：42 项 ioctl、32 项风扇/睡眠恢复、18 项 WMI、9 项电源、
  24 项打包/同步。测试提取真实 C 函数，但 EC/ACPI 由模拟实现，不是实机故障注入。
  17 组风扇及 PM 回归也在修改前源码上失败，确认能捕获原错误。
- 实机向两只风扇接口分别传入 `256`、`UINT32_MAX`，四次均返回 `EINVAL`。
  连续两次标准自动模式命令均返回 0；没有请求任意手动转速或新曲线。
- 背光 `1 → 0 → 1`、Fn 锁 `0 → 1 → 0` 写入/回读及恢复通过，RGB 恢复 `4 4 4`。
  这些仍是接口验证，没有人工确认发光效果或逐键验证。
- 九项 TDP 读取仍返回 `ENODEV` 且输出未变，三项不支持写入及无效指针拒绝检查通过。
  三次传感器样本均为 CPU 93°C、GPU 53°C、双风扇原始值 170；不能当作 RPM 或散热改善。
- cTGP 在重载前、重载后 TCC 启动前及 TCC 启动后均为 25；原配置恢复，
  `tccd`、`thermald`、`nvidia-powerd` 均运行。
- NVIDIA `osapi.c:2198` 仍出现两次。已捕获 NPCF 通知和动态参数读取成功的独立链路，
  但不能据此认为 GPU `0xC5` 可忽略，见 [NVIDIA 诊断记录](../NVIDIA-0xC5.md)。

**真实睡眠/唤醒、实机 EC 故障、手动风扇控制和长期负载仍未验证。**
本轮修复不构成完整睡眠兼容或散热认证，也未解决既有整体风扇并发串行化问题。

证据保存在 `.local-tests/iteration-20261015/`：`all-tests.log`、两个内核构建日志、
`fan-runtime-tests.log`、`fan-regression-sensitivity.log`、`makepkg.log`、`install.log`、
`installed-validation.json`、`runtime-checks.json`、`after-install-checks.log`、`after-install-kernel.log`。
升级前的 r6 包和两个内核的 54 个项目模块保存在
`~/Backups/projects/mechrevo-drivers/light/20261015-iteration/`，
已独立解包校验内容、权限和所有者，`SHA256SUMS` 复核通过。

以下保留 2026-10-14 的 r6 历史验证，不代表当前安装版本。

## 2026-10-14 环境与安装状态

- DMI：`MECHREVO / Kuangshi16Pro Series GM6PX0X`，主板 `GM6PX0X`。
- BIOS：`N.1.09MRO07`。
- 系统：Omarchy 4.0.4，运行内核 `7.2.9-arch1-1`；另保留 `7.2.7-arch1-1` 的 headers。
- 安装包：`mechrevo-drivers-dkms-git 4.24.0.r6.g4bbbdc9-1`，驱动源码提交 `4bbbdc9`。
- 按仓库 AUR 配方从 GitHub `main` 构建，经 `pacman -U` 升级；不是手工覆盖系统模块。
- 两个内核的 DKMS 均完成全部 27 个模块的编译、签名和安装。
- 在当前会话安全卸载、重新加载相关模块，未强制卸载，未重启系统。
  五个已加载项目模块的 GNU build ID 全部与新安装模块一致；三个改动的驱动源文件
  与 `/usr/src` 中的安装内容逐字节一致。
- 安装 hook 重新生成并签名 UKI；`sbctl verify` 通过。当前 Secure Boot 关闭，
  不能据此认定 DKMS 签名密钥已在启用 Secure Boot 时受信任。

## 修复与结果

| 项目 | 实测结果与边界 |
| --- | --- |
| Uniwill 识别 | 使用 `uniwill_wmi`，硬件 model ID 为 16；没有强制启用 Clevo 路径 |
| TDP 读取 | 原包将不支持返回值 `-ENODEV` 显示成 `4294967277`；修复后全部九个当前值/最小值/最大值命令返回 `ENODEV`，用户缓冲区不被改写 |
| 错误处理 | 三项不支持的 TDP 写入返回 `ENODEV`，其空指针输入及七项空指针输出返回 `EFAULT`；未执行有效功耗调节 |
| Mini LED | 本机没有局部调光控制节点；回归测试验证不支持及 sysfs 注册失败时不发送初始化命令；未做 WMI 总线跟踪 |
| RGB 键盘亮度 | 标准 sysfs 亮度 `1 → 0 → 1` 写入与回读通过；恢复原 RGB 强度 `4 4 4`，未由人工确认实际发光效果 |
| Fn 锁 | 标准 sysfs `0 → 1 → 0` 切换与回读通过；未人工逐键验证 Fn 组合键 |
| 温度与风扇 | 三次样本均可读取 CPU/GPU 温度和两个风扇原始值；本轮为 CPU 94–95°C、GPU 53°C，风扇原始值 170；这是共享机器工作期间的样本，不能当作 RPM、散热改善或稳定性结论 |
| 充电 | 可读取 `high_capacity / balanced / stationary`，原配置 `high_capacity` 保持；未切换充电模式，未测实际充电行为；无标准 `charge_control_end_threshold` 节点 |
| TCC | 重载前短暂停止，验证后恢复运行；原键盘设置与 `ctgp_offset=25` 在守护进程启动后恢复，未主动调节 GPU 功耗 |
| 电源初始化 | 加载前和加载后、TCC 启动前的 cTGP 均为 25；本机跳过原有四项电源默认写入，没有套用其他型号的功耗表 |
| 同值设置 | 三次写入现值 25 均成功；旧版探针记录到三次 EC 写入，新版记录为零次；配置保持不变 |

`GM6PX0X` 未匹配现有 TUXEDO TDP 白名单。这里修复的是正确报告“不支持”，
没有借用相近型号的功率上限来启用调节。

92 项本地测试全部通过，包括 41 项 Uniwill 运行用例、18 项 WMI 用例、9 项电源用例和
24 项打包/同步检查。Uniwill 用例编译普通及 DEBUG 两个版本；WMI 用例启用 ASan/UBSan。
测试使用提取的实际 C 函数及 ioctl 定义，模拟 EC/ACPI 而不访问硬件；故意恢复历史错误的
回归有效性实验能检出错误。不能把 mock 的风扇 helper 或 Clevo 接口当作其内部错误路径已验证。
`namcap` 无错误，保留源文件架构及 DKMS hook 依赖的两个预期警告。

## 未解决与未验证

- 已捕获 NVIDIA `osapi.c:2198` 的直接条件：GPU 收到固件通知 `0xC5`，但
  [NVIDIA 615.78.08 的通知处理器](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/615.78.08/src/nvidia/arch/nvalloc/unix/src/osapi.c#L2163)
  没有对应分支。当前 DSDT 与既有反编译材料哈希一致，电源相关 `_Q83/_Q84` 同时向
  NPCF 发送 `0xC0`、向 GPU 发送 `0xC5`。不能未经依据把后者映射为 GPS 操作。
- 修复前模块加载及 TCC 启动各捕获一次 `0xC5`/断言；本轮修复后模块加载阶段没有出现，
  但 TCC 启动时真正改变功耗仍触发两次。修复消除了强制初始化及重复写入，
  **没有修复 NVIDIA 对 `0xC5` 的兼容性**，也没有屏蔽断言。
- 旧 NVIDIA PR #1402 处理的是另一种启动计数器问题，不能修复这里的 `0xC5`；本次没有更换 NVIDIA 模块。
- 未验证重启、睡眠/唤醒、外接显示器切换、实体热键、充电阈值或长期高负载稳定性。
- 没有主动修改风扇曲线、TDP 白名单、GPU 功率或充电策略；模块加载本身包含上游的
  EC/WMI 初始化，已有 TCC 服务也会应用原配置，因此不能称整个过程“没有 EC 写入”。
- 风扇/温度样本只证明正常读取路径可用，未模拟实机 EC 故障；TDP 仅验证拒绝不支持及无效输入，未验证任何成功功耗写入。

## 本地证据与恢复

本轮日志和快照位于 `.local-tests/continuation-20261014/`：`all-tests.log`、
`makepkg.log`、`install.log`、`runtime-checks.json`、`module-build-ids.json`、`after-tccd.json`、
`power-preserved.json`、`notify-reload-*`、`notify-corrected-reload-*`、`same-power-before.txt`、
`same-power-after.txt` 及两个内核的构建日志。初次验证仍保存在
`.local-tests/local-adaptation-20261014-2253/`。不将机器日志提交到源码仓库。

本轮升级前的 r3 安装包和两个内核的 54 个项目模块已归档到
`~/Backups/projects/mechrevo-drivers/light/20261014-continued-correction/`，
独立解包校验内容、权限和所有者，并保存 `SHA256SUMS` 与恢复说明。
恢复优先使用保存的包及 DKMS，不要手工删除 `/usr/src` 或 `/var/lib/dkms`。

## 2026-10-16：观测期间的无日志 GPU 故障检查

源码确认旧观测器只在开始、结束时查询 GPU，中间依赖增量内核日志。
日志延迟时，GPU 查询已失败仍可能继续 EC 采样。本轮没有实机复现新的掉线事件；
四个模拟回归用例分别覆盖采样前掉线、采样后掉线、设备集合变化及 GPU 查询期间新增 Xid，
在旧源码上全部失败，在修复后通过。现在每组采样前后查询 GPU，并在读取 EC 前再次检查日志。
这增加查询耗时和独显唤醒干扰，不能消除检查与硬件读取之间的竞态。

- 32 项观测测试及 6 项打包测试通过，包含真实进程信号中断和归档内容校验。
- 安装 `mechrevo-power-control 0.1.0-7`，包内容固定于
  `d40ad3f199cfd0dcf772b48a5a7b3b33909bcb7e`，安装完整性检查为 19 个文件、0 个变更。
- GPU 仍处于此前 Xid 79 后的失联状态；安装后的命令返回 1、零样本并记录 GPU 检查失败。
  正常 GPU 下的完整采样和新增中途故障检查尚未完成实机验收。
- 托管 55 W 上限仍保持，无待处理事务。TCC、thermald、功耗状态文件的哈希及三个相关服务
  PID 在安装前后相同；没有重启、驱动重载、压力负载或硬件策略调整。
- 当前 hwmon 没有 `fan*_input`。上游 Uniwill 的 RPM 读取实现仅为待核对线索，
  没有据相近型号新增 EC 寄存器读取或开放手动风扇控制。

本地构建、安装校验脚本和回执保存在
`.local-tests/thermal-output-20261016/gpu-guard/`。已校验的 r6 回滚包在
`~/Backups/projects/mechrevo-drivers/light/rapl-power-control/thermal-gpu-health-20261016/`，
使用 `sudo pacman -U` 指定该目录内包即可恢复观测器版本。
AgentGC 已跟踪选定源码、测试和制品目录；安装跟踪为 partial，13 项短暂文件事件未完全解析，
安装内容、回滚包及配置保留情况另行校验。包管理数据库和未改变的启动器目录不在安装跟踪范围内。
本轮改动不证明降温、性能提升或 NVIDIA 失联根因已经修复。

## 2026-10-16：回执信号竞态修复与 GPU 省电实验准备

真实 SIGTERM／SIGHUP 子进程测试发现共享 CheckpointFile 的一个可复现竞态：
文件替换已经完成，但 inode 身份更新被信号打断，最终保存会把自己的文件误判成外部替换。
临时省电测试的模拟控制已恢复，但磁盘回执仍停在未恢复状态。
确定性用例在旧源码复现同一错误；修复仅在 replace／身份更新期间阻塞三个中断信号，
随后恢复原掩码。新的省电工具保持实验状态，未加入安装包或默认设置。

- 16 项实验工具／共享回执测试、32 项观测测试及 6 项打包测试通过。
  真实信号测试另重复 15 次通过；安装后的回执实现也直接通过两个确定性回归。
- 已安装 `mechrevo-power-control 0.1.0-8`，内容固定于
  `f240313b2063c61ccee66398ce7cf17169c5c746`，完整性检查 19 个文件、0 个变更。
- 默认和显式实验入口均在 GPU 失联预检处拒绝，control 仍为 auto，未创建实验锁或回执。
  没有执行成功硬件切换；正常 GPU 下的切换、恢复和实际收益尚待实机验证。
- 安装前后的 TCC、thermald、功耗状态配置哈希及相关服务 PID 相同，55 W 上限仍保持。
  本轮没有重启、驱动重载或改变硬件策略。

安装回执和校验脚本位于 `.local-tests/thermal-output-20261016/gpu-guard/signal-fix/`。
已核验的 r7 回滚包位于
`~/Backups/projects/mechrevo-drivers/light/rapl-power-control/thermal-signal-fix-20261016/`。
安装跟踪为 partial，14 项短暂文件事件未完全解析；最终安装内容、回滚包和配置另行核对。
实验命令及风险边界见 [GPU 运行时省电隔离测试](../GPU-RUNTIME-PM-TRIAL.md)。

## 2026-10-17：实际温度诊断与写入观察资格

新增的 `status.package_temperature` 将实际传感器温度与配置目标、TCC 激活参考分开。
141 项功耗事务和温度诊断回归通过；独立实机只调用新读取函数成功，
取得 `x86_pkg_temp` 的 66°C 样本及传感器身份、单调时钟窗口。
此前另一次只读观察为 95°C，当时两套实际 PL1 分别为 48W 和 55W，上限仍保持。
这些是不同时间的样本，没有调整策略，不能将温差归因于代码修复或宣称持续温度已受控。
保护的五个配置及 boot 身份在两次各自观察前后相同。

源码已提交；`mechrevo-power-control 0.1.0-16` 候选固定于
`2e76e5a174c69ec8e9a060d751d15e2bfb53b02c`，包 SHA-256 为
`9d88c3ca3c245123e9464af4734ffa5dd746276ae2531acd0c1c1d11aa470516`。
10 个载荷文件已逐字节对照固定 Git 源码核验，无安装脚本或新增 hook；
另 8 项包装测试通过。当前安装仍为 15，TCC 和 thermald 新候选也未切换运行。

新的私有写入观察器经 127 项离线回归、独立源码审查及当前机器资格核验后，
完成单次约 3 秒的 `msr:write_msr` / `msr == 418` 过滤采集。
29 次 CPU0 只读样本均为 `0x05640000`，即 TjMAX 100°C、offset 5°C、激活参考 95°C，
**不是实际 CPU 温度**。未捕获匹配写入事件；24 CPU 的丢失计数为零，专属实例已清理，
保护配置、进程身份、模块及既有全局追踪状态前后相同。
这次验证了正常启停、过滤和只读采样，尚未验证真实匹配事件或实机强制中断恢复。
未捕获不能排除直接汇编、特定 ioctl、SMM 或固件写入，也没有确认修改者或改善散热。

实机采集跟踪为 partial（0 gap、20 条未解析事件）；独立回读不补全缺失的事件历史。
测试和包恢复材料继续保留。硬件功能验收仍为 9/20，完整 Windows 迁移未完成。
