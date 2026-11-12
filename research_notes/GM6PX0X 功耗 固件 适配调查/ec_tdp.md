# GM6PX0X EC TDP 公开证据调查

调查日期：2026-10-15。范围：MECHREVO Kuangshi16Pro / GM6PX0X / i9-12900HX / BIOS N.1.09MRO07；全部为只读调查，没有执行任何 EC/sysfs 写入、服务动作或模块动作。公开源码抓取只在内存处理，没有安装或运行外部工具。

## 1. 是否已有足以开放本机 EC TDP 的依据？

### Takeaway
找到了精确型号作者的逆向项目，EC 功耗地址与 TUXEDO 家族源码一致，调查已从“无资料”推进到“可审查候选协议”。仍未找到同时证明本机 CPU、BIOS、EC/ROM-ID、完整前置模式、单位及安全范围的证据链，不能开放本机 EC TDP 白名单。

### Cited Findings
- TUXEDO 官方项目冻结于 `a929f9ce143316b3b18d5f3fbf9cc54f0c1122e2`：`uw_id_tdp()` 按产品 SKU/特定主板选择限值表；`tdp_*_gmxpxxx` 的适用分支是 `STELLARIS1XI05`，不是任意 `GM6PX0X` 字符串。表中下限 5/5/5、上限 130/130/200 不能迁移为本机安全值。没有匹配时指针为空，查询/设置返回 `ENODEV`。— [官方源码：机型表和门禁](https://github.com/tuxedocomputers/tuxedo-drivers/blob/a929f9ce143316b3b18d5f3fbf9cc54f0c1122e2/src/tuxedo_io/tuxedo_io.c#L123)
- 官方通用读写使用 `0x0783 + index`；index 2 在 `uniwill_has_double_pl4` 为真时，读取乘 2、写入除 2。此标志来自 `0x0727` bit 7；一些机型另需 `0x0727` bit 6 的 custom-profile 初始化以及 OVERBOOST 模式。它证明“相同地址未必相同单位/前置条件”。— [功耗编码](https://github.com/tuxedocomputers/tuxedo-drivers/blob/a929f9ce143316b3b18d5f3fbf9cc54f0c1122e2/src/tuxedo_io/tuxedo_io.c#L434)、[custom 模式](https://github.com/tuxedocomputers/tuxedo-drivers/blob/a929f9ce143316b3b18d5f3fbf9cc54f0c1122e2/src/uniwill_keyboard.h#L339)、[double PL4 探测](https://github.com/tuxedocomputers/tuxedo-drivers/blob/a929f9ce143316b3b18d5f3fbf9cc54f0c1122e2/src/uniwill_keyboard.h#L1676)
- Intel 官方列出 i9-12900HX Processor Base Power 55 W、Maximum Turbo Power 157 W、Minimum Assured Power 45 W；这些是 CPU 规格，页面要求系统相关信息向系统厂商确认，没有提供本机 EC 寄存器或笔记本整机安全范围。— [Intel 产品规格](https://www.intel.com/content/www/us/en/products/sku/228441/intel-core-i912900hx-processor-30m-cache-up-to-5-00-ghz/specifications.html)
- Linux 官方 powercap 文档把 RAPL 定义为 CPU package/子域约束，功率限制的 sysfs 单位为微瓦；RAPL 没有瞬时功率值。该标准接口不等于 OEM EC 控制协议。— [Linux powercap 文档](https://www.kernel.org/doc/html/latest/power/powercap/powercap.html)
- 本项目已有 55 W 验证明确只涉及 Intel RAPL 长期约束及 thermald 协调，并未开放 EC TDP。— [本项目冻结说明](https://github.com/LIghtJUNction/mechrevo-drivers/blob/8859a6f9f204c235cf2e8970692b9ab1a22d68b7/docs/POWER-CONTROL.md)

### Inferences
- `0x783/0x784/0x785` 已有多份公开源码交叉支持，是值得继续核对的候选地址；“候选地址一致”不足以推出本 BIOS 下的写入范围、PL4 单位、初始化序列及生效条件。
- Intel 55/157/45 W 规格不能直接变成 EC 白名单最小/最大值，更不能成为整机与电源适配器安全保证。当前 55 W 用户态 RAPL 工具应与 EC 适配分开维护。

### Gaps
- 未取得 MECHREVO 对 `GM6PX0X + N.1.09MRO07 + i9-12900HX` 的 EC TDP 编程规范、已匹配 OEM profile 表或安全上限说明。
- 未取得该组合的 EC 固件/ROM-ID 与公开作者机器一致的证据；板号和 BIOS 文本本身也不能替代固件与硬件配置匹配。
- 未进行本机 EC 写入或故障注入；本调查不宣称任何新的实机功耗结果。

## 2. 精确型号社区项目和其他驱动实际证明了什么？

### Takeaway
Semcosm 项目是强逆向线索，有真实作者观测及可审查源码；它没有公开足够的本机固件身份和安全范围证明。另一套 `dumingqiao/uniwill-laptop-dkms` 自动加载白名单只有 XMG FUSION 15 与 Intel NUC X15，其常量不能借给本机。

### Cited Findings
- Semcosm 项目自称针对 MECHREVO Kuangshi16Pro Series `GM6PX0X`，定位为 Linux 逆向工作区；固定提交 `cae0afbaa704d253e29a268cc2d5f7fa4167106b`。— [README](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/README.md)
- 其逆向报告给出 Windows `GCUService.exe` SHA-256 `e2095ea378382e00f910c3bb9c031990b6002f262f932f838f9f7be80ea767c8`、版本包 `ControlCenter_5.17.51.33_Mechrevo`，静态常量 `0x751` 模式、`0x783/784/785` PL1/2/4、`0x786` TCC；作者 Linux 观测中 `0x783..0x787` 曾全零，`0x751` 随 OEM 模式出现 0x00/10/20/30/A0。这是作者报告的二进制静态分析和单机观察，并非 OEM 公布的规范。— [GCUService 报告](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/windows-control-center/GCUService_reverse_report.md#L1)
- 作者报告过：相同 Linux PL1/PL2 140/140，OEM 按钮不同状态下实际约 45 W 与 130 W，温度目标也不同；这是“模式具有额外影响”的观察，不是安全范围或模式位完整定义。— [Current Findings 第 23 项](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/CURRENT-FINDINGS.md#L104)
- 其 `ec-addr-map.h` 固定上述功耗地址；`amw0_apply_power_limits()` 直接按字节写 PL1/2/4/TCC，成功后先记录 cache。该函数没有 TUXEDO 式的 PL4 条件倍数处理或按本机 BIOS 的范围表。— [地址头](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/src/backends/amw0/ec-addr-map.h#L12)、[真实写入函数](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/src/backends/amw0/backend.c#L725)
- 其 `amw0_probe()` 直接标记 can_apply_power_limits；`model-map.c` 默认 model=GM6PX0X，capabilities JSON 只描述功能，均未验证本机 DMI/CPU/BIOS/EC-ROM-ID。读函数可调通本身不是硬件兼容证明。— [probe](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/src/backends/amw0/backend.c#L338)、[model 默认值](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/src/core/capabilities/model-map.c)、[capabilities](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/data/capabilities/gm6px0x.json)
- 最关键的区别：其 converged 后端在 standard 与 AMW0 都 available、都可应用功耗且请求同时含两组字段时，把 PL1/PL2 交给 standard powercap，把 PL4/TCC 交给 AMW0；不满足拆分条件时仍允许 primary/fallback 把整组交给 AMW0（L723-742）。standard 后端向 `constraint_*_power_limit_uw` 写 W×1,000,000。作者 hardware-validation 明确 PL1/PL2 证明依赖 turbostat、intel-rapl、MSR 一致，PL4 尚未完全用 Intel 遥测证明。因此不能把 PL1/PL2 成功记录当作 EC 0x783/784 生效闭环。— [路由源码](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/src/backends/converged/backend.c#L665)、[标准 powercap 实现](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/src/backends/standard/powercap.c#L354)、[作者硬件边界](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/docs/hardware-validation.md#L218)
- 其 Mode4_Profile1 模板为 PL1/2 130、PL4 200、TCC offset 5；模板不是安全白名单。作者 backend-amw0 文档明确区分“已证明的 Linux transport”与“Windows 数据模型/地址图”，还需把两者连接成可重现包序列。— [模板](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/data/profiles/mode4_profile1.json)、[作者明确的未闭环说明](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/docs/backend-amw0.md#L39)
- `dumingqiao/uniwill-laptop-dkms` 冻结 `a8f80174aacba936da71777c3f463d976c3b2e74`：README 自动加载只列 `SchenkerTechnologiesGmbH + LAPQC71A/B` 和 `Intel(R) Client Systems + LAPKC71E/F`。DMI 表确实如此，无 GM6PX0X；不匹配时默认 `ENODEV`，force 则假定全部功能并警告。— [README 白名单](https://github.com/dumingqiao/uniwill-laptop-dkms/blob/a8f80174aacba936da71777c3f463d976c3b2e74/README.md#L95)、[DMI 与 force 源码](https://github.com/dumingqiao/uniwill-laptop-dkms/blob/a8f80174aacba936da71777c3f463d976c3b2e74/uniwill-acpi.c#L3217)
- 该驱动保留 Armin Wolf 2025 版权及前期贡献致谢；WMI EC GUID `ABBC0F6F-8EA1-11D1-00A0-C90629100000`、method 4、read/write selector 1/0；PL 地址仍 0x783/784/785。ROMID_START=0x770、length14 是定义，不是 GM6PX0X ROM-ID 白名单。— [协议头与来源](https://github.com/dumingqiao/uniwill-laptop-dkms/blob/a8f80174aacba936da71777c3f463d976c3b2e74/uniwill-acpi.c#L1)、[地址/ROM-ID 定义](https://github.com/dumingqiao/uniwill-laptop-dkms/blob/a8f80174aacba936da71777c3f463d976c3b2e74/uniwill-acpi.c#L222)
- 该驱动固定 PL min=5、PL1 max=80、PL2 max=100、PL4 max=120、clear=0；probe 在 WMI PL1 读取成功后置 TDP_CTRL/PERF_PROFILE。这是该作者为其支持设备实施的策略，不是厂商对本机的范围证明，也不能把“能读一个字节”当作本型号兼容。— [常量](https://github.com/dumingqiao/uniwill-laptop-dkms/blob/a8f80174aacba936da71777c3f463d976c3b2e74/uniwill-acpi.c#L369)、[能力探测](https://github.com/dumingqiao/uniwill-laptop-dkms/blob/a8f80174aacba936da71777c3f463d976c3b2e74/uniwill-acpi.c#L2979)
- 搜索发现 `undefined-ux/mechrevo-kuangshi16pro-kmod`，但其 README 仍针对 WUJIE14/IP3 xN39；标题不构成 GM6PX0X 的真实测试证据。— [仓库 README](https://github.com/undefined-ux/mechrevo-kuangshi16pro-kmod)

### Inferences
- Semcosm 作者的 CPU/BIOS/EC 版本缺口，和功耗路径混合，阻止其默认 130/130/200 模板成为本机白名单。可学习其静态逆向入口与字段归属，不能直接安装 daemon 或执行其 raw/scan 脚本。
- dumingqiao 项目可作为通用 Uniwill 协议交叉核对，不能 force 加载来试出兼容。其较低 max 常量也不是本机“保守就一定安全”的范围。

### Gaps
- 在已检查的 Semcosm README、CURRENT-FINDINGS、GCUService/UEFI 报告、hardware-validation、backend-amw0、capabilities 和 model-map 中，没有找到 i9-12900HX、N.1.09MRO07、EC 版本/14 字节 ROM-ID 的完整机型身份。没有把“未在这些文件找到”扩大为“整个互联网不存在”。
- 未获取作者日志中 raw EC 写入、硬件回读、RAPL/MSR 变化与同一 CPU/固件的完整收据。作者未跟踪的 vendor 二进制也未下载，不能独立复核逆向报告全部结论。

## 3. 下一步怎样安全补证？

### Takeaway
下一步应先做本机固件身份与 OEM 原始软件包的静态对应，再决定是否设计有限写入实验；现有标准只读接口足以推进身份、状态和 RAPL 证据，不需要现在改白名单或向任意 EC 地址探测。

### Cited Findings
- 本项目已有实际硬件记录和 fail-closed 的 TDP 行为；当前已知 CPU model/BIOS 组合的验证范围写在 POWER-CONTROL。— [项目硬件记录](https://github.com/LIghtJUNction/mechrevo-drivers/blob/8859a6f9f204c235cf2e8970692b9ab1a22d68b7/docs/hardware/GM6PX0X.md)、[功耗工具边界](https://github.com/LIghtJUNction/mechrevo-drivers/blob/8859a6f9f204c235cf2e8970692b9ab1a22d68b7/docs/POWER-CONTROL.md)
- OEM 有官方驱动下载入口，可以继续获取精确适配包的公开元数据；当前打开页面没有直接提供 EC 编程规范。— [MECHREVO 官方下载](https://www.mechrevo.com/cn/downloads)

### Inferences
建议的安全后续（本调查未执行）：
1. 只读核对 `/sys/class/dmi/id/{sys_vendor,product_name,product_sku,board_name,bios_version,bios_date}` 与 `/proc/cpuinfo`；按既有机器记录对照 CPU stepping、DMI 固件修订值、ACPI 表哈希。避免上传主机序列号。
2. 对现有 DSDT/SSDT 静态材料查 `INOU.ECRR/ECRW`、`ECMG`、`0x783..0x786` 与 `0x727/0x751` 字段和方法关系，不执行 acpi_call，不写 `/proc/acpi/call`。在旧材料已存在时优先复用并核对哈希。
3. 只读 `mechrevo-power status` 与现有 RAPL 的 name、constraint_*_name、power_limit_uw、time_window_us；它能明确当前 CPU 长期限值，但不能证明 EC 调节。保留 thermald 的控制权，不跑后台抢写。
4. 在官方或可追溯 OEM 包中找针对本机 CPU/ROM-ID 的 profile 与 dispatcher；静态确认单位、PL4倍数、前置模式、AC/DC分支、恢复、固件保护。不要用通用模板或跨品牌 firmware 代替身份匹配。
5. 即使以上静态证据补齐，也需另行获得有限硬件实验授权、保存恢复材料并定义读回与独立功耗/温度观测，再讨论最小范围白名单。此次搜索授权不等于 EC 写入或 BIOS 更新授权。

### Gaps
检索范围及限制：
- 全网组合：`"GM6PX0X" TDP`、`"GM6PX0X" EC`、`"N.1.09MRO07"`、`"GM6PX0" power limit`、`"GM6PX0X" github`、`"GM6PX" "TDP" github`、`"uniwill" "tdp" "0x" github`、`"GM6PX0X" "PL1"`、`"旷世16Pro" "EC" 功耗`、`Uniwill EC TDP github tuxedo 0783 0727`、`GM6PX0X firmware BIOS`，并读官方 TUXEDO、Intel、kernel.org、MECHREVO 页面及原始源码。
- 实际 GitHub Code Search：`gh search code GM6PX0X --limit 30`、`gh search code N.1.09MRO07 --limit 20`。结果主要为本项目、linuxhw/DMI、Semcosm 的另一个 mock 项目等。GitHub 索引没有返回 Semcosm Linux 项目本身，说明搜索未命中不代表不存在。
- 对社区视频“提高功耗上限”和跨型号 BIOS 刷写讨论只作发现线索，没有采纳其寄存器、范围或操作建议。
- YYplus/Mechrevo-BIOS 固件归档线索已转交型号调查分工，本文件不重复推断其固件安全性。
