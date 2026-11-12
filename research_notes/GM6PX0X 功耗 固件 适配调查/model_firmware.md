# GM6PX0X 型号、固件身份与 Linux 兼容证据

调查时间：2026-10-15（Asia/Taipei）。本分支只做只读调查及本笔记写入，没有下载固件、安装第三方程序、执行 WMI/EC 调用、更新 BIOS、睡眠、重启、重载模块或改变服务。只读运行保持检查另存本地 `local-runtime.json`：当前内核仍为 7.2.9-arch1-1，五个运行模块 GNU build-ID notes 均与前轮 preflight 一致，未发生新修复运行生效的变化。GitHub 源码与 DMI 链接尽量固定到已阅读提交；第三方用户的硬件报告仍是他机原始观察，不替代本机实测。

## 公开材料是否精确匹配本机的型号、CPU 与 BIOS？

### Takeaway

找到了一个同时匹配 MECHREVO / Kuangshi16Pro Series GM6PX0X、i9-12900HX 和 N.1.09MRO07 的公开 DMI 样本；另一个同产品字符串的样本却是 i9-13900HX 与 MRO12。TUXEDO、PCSpecialist 也有 GM6PX0X 字符串，但这些材料只支持“同板族的调查线索”，不支持固件互刷或 EC 控制行为等同。

### Cited Findings

- `linuxhw/DMI` 的 `22CB98B41F6A` 样本：系统 MECHREVO / Kuangshi16Pro Series GM6PX0X，主板 MECHREVO / GM6PX0X；CPU 12th Gen Intel Core i9-12900HX；BIOS `N.1.09MRO07`、日期 `05/10/2023`、BIOS Revision `5.27`、Firmware Revision `1.8`。OEM String 11 为 `FGM-GM6PX0X0070202`，String 12 为 `GM6PX0X`，String 16 为 `1D051356X1100100`。这是 SMBIOS 上报值，不是对固件镜像的密码学认证，也没有该样本的睡眠/热键/充电验收结果。[精确样本](https://github.com/linuxhw/DMI/blob/57b21bc6fdd863380e99c228c22aafcd1509528c/Notebook/MECHREVO/Kuangshi16Pro/Kuangshi16Pro%20Series%20GM6PX0X/22CB98B41F6A)
- 同产品字符串的 `CA26E23DF859` 样本：i9-13900HX，BIOS `N.1.09MRO12`、日期 `09/21/2023`、Firmware Revision `1.16`，OEM String 11 `FGM-GM6PX0X0084202`，String 16 `1D051272X1100100`。MRO12 的存在只证明有另一组合的上报，不能证明它适用于本机 12900HX、修复某 Linux 问题，或是本机可安装的最新版。[另一 MECHREVO 样本](https://github.com/linuxhw/DMI/blob/57b21bc6fdd863380e99c228c22aafcd1509528c/Notebook/MECHREVO/Kuangshi16Pro/Kuangshi16Pro%20Series%20GM6PX0X/CA26E23DF859)
- TUXEDO Stellaris Intel Gen5 样本：i9-13900HX、BIOS `N.1.09A09`、日期 `07/20/2023`、Firmware Revision `1.11`；主板制造商 NB02、主板产品 `GMxPXxx`；OEM String 11 `FBM-GM6PX0X0050STG`，String 12 `GM6PX0X`，String 16 `1D051272X2200100`。主板字段并没有与 MECHREVO 样本逐字相同。[TUXEDO DMI 样本](https://github.com/linuxhw/DMI/blob/57b21bc6fdd863380e99c228c22aafcd1509528c/Notebook/TUXEDO/Stellaris/Stellaris%20Intel%20Gen5/5E8A3DF90CF3)
- PCSpecialist Recoil 16 两个 DMI 样本均为 TongFang / GM6PX0X、i9-13900HX、OEM String 11 `FBM-GM6PX0X0062PCS`，String 16 `1D051272X2200100`，但 BIOS 分别为 `N.1.09A03`（`08/02/2023`、Firmware Revision `1.5`）及 `N.1.09A04`（`12/05/2023`、Firmware Revision `1.17`）。[A03 样本](https://github.com/linuxhw/DMI/blob/57b21bc6fdd863380e99c228c22aafcd1509528c/Notebook/PC%20Specialist/Recoil/Recoil%2016/0B318385D45F)；[A04 样本](https://github.com/linuxhw/DMI/blob/57b21bc6fdd863380e99c228c22aafcd1509528c/Notebook/PC%20Specialist/Recoil/Recoil%2016/AAE1D0068D47)
- `linuxhw/TestDays` 的 Xero Notebook 汇总出现一台 MECHREVO Kuangshi16Pro Series GM6PX0X；这只是报告计数，不是完整兼容认证，也没有在此汇总中给出 Fn-lock、睡眠、充电等测试。[Xero 汇总](https://github.com/linuxhw/TestDays/blob/85f48321efe6abe83a1532e89ee10ad928d97d34/Dist/Xero/Notebook/README.md)
- 本仓库的本机记录限定了本机为 i9-12900HX / N.1.09MRO07 / Uniwill 路径，且明确列出未完成的硬件验证。[本机记录](https://github.com/LIghtJUNction/mechrevo-drivers/blob/8859a6f9f204c235cf2e8970692b9ab1a22d68b7/docs/hardware/GM6PX0X.md)

### Inferences

- 有公开精确 CPU+BIOS+DMI 样本，说明不能把本机 12900HX 当作不可能的 DMI 误报。若以后比较其他项目的 ACPI 行为，应先要求 CPU、BIOS 和 ACPI 表身份的完整匹配。
- 跨品牌 GM6PX0X 线索足以扩大源码和维护者讨论的检索范围；不足以借用 TUXEDO/PCSpecialist 的 BIOS、EC 安全功耗范围、风扇曲线或 TDP 白名单。
- SMBIOS `Firmware Revision` 是上报的版本字段；本文没有取得 EC 固件镜像和 OEM 版本说明，不把该字段独立解释为已认证 EC 固件身份。

### Gaps

- 未确认公开 DMI 精确样本是否来自与本机完全独立的设备；匿名报告不是独立厂商认证。
- DMI 样本没有 PCI GPU 列表。本轮对本机只读执行 `lspci -nn` 和 `nvidia-smi --query-gpu=name,driver_version --format=csv,noheader`，得到 Intel `8086:4688` / NVIDIA `10de:28a0`、RTX 4060 Laptop GPU、驱动 `615.78.08`；这是本轮本机观察，未上传 serial/UUID，没有把 DMI 样本补写成同 GPU。
- 未找到本机 OEM String、EC 固件镜像哈希、ACPI 表身份与上述跨品牌样本的一致性证明，不能据此认定硬件完全相同。

## GitHub 同型号项目能否补齐固件、热键和显示适配？

### Takeaway

`Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center` 是值得继续核对的精确型号逆向项目，有 Windows 原厂控制中心分析和 Linux 试验记录，但不是厂商支持声明。该项目公开的 MUX 支持仍标为实验性，且本次未找到作者的 CPU、BIOS 版本或可对应的固件镜像身份，不能直接照搬到本机。

### Cited Findings

- README 明确定位为 GM6PX0X 的 Linux ACPI/WMI 逆向工作区，Windows `GCUService.exe` 是优先逆向目标；原厂二进制和运行 capture 有意保留本地、不纳入仓库。本次读取的 HEAD 为 `cae0afbaa704d253e29a268cc2d5f7fa4167106b`（GitHub API 显示 2026-04-09 的 `fan: add OEM fanboost control`）。因此文档中的本地日志路径不是我们能复核的完整运行制品。[README 固定版本](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/README.md)；[HEAD 提交](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/commit/cae0afbaa704d253e29a268cc2d5f7fa4167106b)
- `CURRENT-FINDINGS.md` 记录了实际 OEM 性能按钮能改变功耗和温度目标，以及一个旧运行 daemon 曾改变模式字节、升级并重启 daemon 后不再发生的区别；该文档保留了未验证项目。这支持今后必须核对“已安装”和“运行中”的版本，不能把作者的按钮观察外推成本机完整热键支持。[Current Findings](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/CURRENT-FINDINGS.md)
- `AMW0-analysis.md` 记载 `_Q53`、`_Q77`、`_Q78` 发出 WMI 事件；作者做的 `WMBC(..., 0x03, value)` 软件事件试验未改变其观察的 OSDF/HBTN/BRTS/W8BR。这是作者 AML 和软件事件通路的证据，不是本机实体按键、ACPI 通知序号或事件含义的认证。[AMW0 analysis](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/AMW0-analysis.md)
- GPU MUX 文档明确称 dGPU only/direct-connect 仍为 experimental，找不到主 `UniWillVariable` 中的明显 MUX 字段，并要求与主要 profile 路径分离；其“需要重启”是该实验项目的保守设计边界，不是本机已验证的操作流程。[GPU Mux](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/docs/gpu-mux.md)
- 对其安装的 Windows `UEFI_Firmware.dll`，逆向报告只找到 `ReadUefi/WriteUefi`，未找到 managed service 声明的 `ReadSwitchUefi/WriteSwitchUefi`；主变量路径是完整设置 blob 的读改写。不能仅因 Windows 程序提到 MUX 就在 Linux 写猜测的 UEFI 字段。[UEFI reverse report](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/windows-control-center/UEFI_Firmware_reverse_report.md)
- hardware-validation 文档主张标准 ABI/AMW0 路由分别归因、未知值保留 null、PL4 尚未充分验证，并区分传输成功与风扇行为证据；该文档是验证方法和作者证据边界，不是已经在本机执行的结果。[Hardware Validation](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/docs/hardware-validation.md)

### Inferences

- 安全的下一步是离线比较本机已保留的 ACPI 表与作者 AML 的设备、方法和标识，先核对身份与只读字段的语义；不要直接运行该仓库的 probe/scan/apply 脚本，其名字不能证明只读。
- 未来热键验收应区分实体按键触发、内核输入事件、WMI 通知及实际硬件变化；软件注入事件成功只能证明其中一层。
- 不建议将该用户态项目安装到当前已运行 TCC/thermald 的本机。它的测试与安装说明包含服务重启和功耗/风扇变更，当前授权范围是调查。

### Gaps

- 在 GitHub code search 对精确项目检索 `N.1.09MRO07`、`12900HX` 均未找到结果；本次读取 README、Current Findings、AMW0、UEFI、GPU Mux 和 Hardware Validation 也没发现作者 BIOS/CPU 身份。搜索无结果可能受索引影响，不等于仓库所有历史都不存在这些信息。
- 本轮未发现该项目能直接解决本机 NVIDIA `0xC5`、充电阈值持久性或睡眠恢复的实机补丁证据。EC 控制细节由同轮另一个研究分支单独审查，本文不重复给出寄存器建议。

## 还有哪些原始 Linux 报告和 OEM 固件资料能指导下一步验收？

### Takeaway

有同 GM6PX0X 板号、同 RTX4060 PCI ID 的 PCSpecialist 外接显示器问题原始报告，能帮助设计更完整的外屏验收；它们的 CPU、BIOS、内核、桌面和 NVIDIA 版本与本机不同。查到机械革命官方驱动入口，但在本次已查页面与精确检索范围内，未找到明确适用于本机 12900HX/MRO07 的 BIOS/EC 更新包和 release notes，不能说“厂商没有固件”或建议刷另一品牌。

### Cited Findings

- NVIDIA 官方开发者论坛 2024-07-18 原始报告：PCSpecialist/TongFang GM6PX0X，i9-13900HX、BIOS `N.1.09A02`（2023-05-15）、RTX4060 `10de:28a0`、NVIDIA 550.100、Manjaro 6.6.40。作者描述 HDMI 可用但限 60Hz，USB-C 外屏在桌面起来后插入可用，连着 USB-C 启动/重启则可能黑屏卡死。它不是 NVIDIA 官方确认的已定位缺陷，所见主题没有可核实的修复结论。[NVIDIA 原始报告](https://forums.developer.nvidia.com/t/manjaro-problems-with-new-monitor-black-screen-and-frozen/300285)
- 2025-08-22 Manjaro 用户原始报告：同板号 PCSpecialist、i9-13900HX/A02/RTX4060，NVIDIA 575.64.05、内核 6.12.41、KDE X11；USB-C 屏在解锁后约 2–3 分钟关闭，HDMI 未受影响。作者后续澄清只想关闭屏幕，另一屏仍工作；不能把他人回复的“可能睡眠故障”当作已确诊，更不能把 resolution 切换 workaround 写成驱动修复。[解锁外屏报告](https://forum.manjaro.org/t/monitor-turns-off-after-unlocking-session/180910)
- 机械革命官方 `/cn/downloads` 提供分类以及序列号查询入口；本轮没有输入或上传本机序列号，也没有提交客服请求。[官方驱动入口](https://www.mechrevo.com/cn/downloads)
- 当前官方 `旷世16` 下载页列有 IRST、读卡器、网卡、IPF、GNA、蓝牙、无线、HID、声卡、OED、触控板等条目；该页展示内容没有 GM6PX0X/12900HX/BIOS MRO07 的适配说明，产品名也不是精确 `旷世16Pro`，不能把该页的 Windows 驱动合集当作本机 BIOS 更新依据。[官方旷世16页](https://www.mechrevo.com/cn/products/kuang-shi-16/downloads)

- 新增核对 `YYplus/Mechrevo-BIOS` 固定 HEAD `fdf8258babda84cb7a54821fea1e3d05a5f26750`（GitHub API 显示提交时间 2026-09-18）：README 明确为独立社区归档、没有机械革命官方关系；已列平台包括 GMxHGxx、XxRPxxxx、耀世15 Pro、耀世16 Ultra、蛟龙16 Pro，当前树未列 GM6PX0X 或 N.1.09MRO07。[社区归档 README](https://github.com/YYplus/Mechrevo-BIOS/blob/fdf8258babda84cb7a54821fea1e3d05a5f26750/README.md)；[固定目录树](https://github.com/YYplus/Mechrevo-BIOS/tree/fdf8258babda84cb7a54821fea1e3d05a5f26750/models)
- 该归档的 `XxRPxxxx` 条目虽含“旷世 / 极光”名称，明确已知机型为极光 X Pro、系列 `KUANGSHI-JIGUANG Series-X6xx55xW-B2`、BIOS N.1.35MRO58；不是本机 Kuangshi16Pro Series GM6PX0X。GMxHGxx 条目则为翼龙15 Pro/蛟龙16S、N.1.10MRO28。两 manifest 的 `tested_on` 和 `paired_ec` 都是 unknown，不能借用其 status 中 official/verified 标签推断本机刷写验证。[XxRPxxxx manifest](https://github.com/YYplus/Mechrevo-BIOS/blob/fdf8258babda84cb7a54821fea1e3d05a5f26750/models/XxRPxxxx/manifest.yaml)；[GMxHGxx manifest](https://github.com/YYplus/Mechrevo-BIOS/blob/fdf8258babda84cb7a54821fea1e3d05a5f26750/models/GMxHGxx/manifest.yaml)；[元数据说明](https://github.com/YYplus/Mechrevo-BIOS/blob/fdf8258babda84cb7a54821fea1e3d05a5f26750/docs/metadata.md)
- 原始来源可追溯性：上述两个 manifest 指向 `driver.mechrevo.com`。本轮只对原始 `.EXE` URL 发 HTTP HEAD，不请求固件正文；均返回 200、没有跳转，Content-Length 分别 10,729,168 与 10,778,544，与 manifest 数值一致。该检查只证明目前原始 URL 可达、服务器声明长度一致，未下载镜像、未校验内容哈希/签名，也不证明适用本机。[XxRPxxxx 官方来源](https://driver.mechrevo.com/d.mechrevo.com/driver/BIOS/Intel_RPLRefresh/XxRPxxxxN135MRO58_CAP.EXE)；[GMxHGxx 官方来源](https://driver.mechrevo.com/d.mechrevo.com/driver/MECHREVO2026/BIOS/GMxHGxxN110MRO28_CAP.EXE)

### Inferences

- 后续获得实机操作授权和设备条件后，外屏验收应按 HDMI 与 USB-C 分开，记录连接器实际所属 GPU、运行桌面/驱动版本、热插拔和锁屏/解锁；开机已连接、睡眠恢复、刷新率切换则各自单列。上述他机原始报告仅提供测试情景，不证明本机存在同故障。
- 可以在本机保持只读地盘点 DRM connector `status`、显卡 PCI 身份、当前桌面和 NVIDIA 参数，先记录基线；无需先改启动参数、强制独显或切换 MUX。
- 若继续找 OEM 固件，应优先寻找明确列出 GM6PX0X + 12900HX + 原 BIOS/EC 版本及升级限制的 release notes；仅有同板号或更大版本号不够。

### Gaps

- 已查范围：GitHub code/repository/issues 精确词 `GM6PX0X`、项目内 `N.1.09MRO07/12900HX`；网页精确 `N.1.09MRO07`、GM6PX0X BIOS/firmware/Linux/suspend，以及机械革命官方 `GM6PX0X`、`旷世16Pro` 检索和官方驱动入口/相近产品页。没有得到精确本机组合的 OEM BIOS/EC release notes、sleep 修复清单或可核实的充电控制规范；不将未检出扩大成全网不存在。
- 没有得到精确本机组合的完整睡眠/唤醒、全部实体热键、充电档位实际电量变化、外屏多连接状态或长期负载通过记录；这些仍要本机验收，网上资料不能直接填“通过”。
- 不支持的结论：MRO12 是本机安全升级；Stellaris/Recoil BIOS 可互刷；同 GM6PX0X 就允许全部同一寄存器/功耗范围；他机 USB-C 问题就是本机 0xC5；公开一个 Linux DMI 样本就等于 Linux 完整兼容。
