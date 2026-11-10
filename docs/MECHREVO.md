# 机械革命支持范围

独立的 [Rust Windows / Linux 控制台与 CLI](MECHREVO-CONSOLE.md) 已开始实现。官方型号目录、精确硬件身份和各项实机验收分别记录；营销型号收录不等于驱动兼容通过。

这是社区维护分支，与 MECHREVO、TUXEDO 没有官方授权或支持关系。上游作者、版权和 GPL 许可证全部保留。

## 当前改动

基线为 TUXEDO 正式版本 `v4.24.0`。品牌适配在
`src/tuxedo_compatibility_check/tuxedo_compatibility_check.c` 的品牌检查表中增加三个独立条目：

- `DMI_SYS_VENDOR` 包含 `MECHREVO`；
- `DMI_BOARD_VENDOR` 包含 `MECHREVO`；
- `DMI_CHASSIS_VENDOR` 包含 `MECHREVO`。

`DMI_MATCH` 是区分大小写的包含匹配，三个条目是「任意一个命中即可」，不是要求三个字段同时满足。
不添加泛化的 OEM 品牌、不关闭检查，也不添加任意绕过参数。
原有 TUXEDO 条目和旧 CPU 平台跳过检查的逻辑不变。

这与 AUR `mechrevo-drivers-dkms` 的品牌放行思路一致，但这里直接维护源代码及上游更新，
不依赖每次下载上游后再应用外部补丁。

另修复两个通用 Uniwill 问题：不支持的 TDP 读取返回负错误码，避免将 `-ENODEV`
显示成 `4294967277`；不支持 Mini LED 或控制接口注册失败时，跳过局部调光初始化命令。
这些修改没有为未知型号添加功耗表，也没有改变已支持型号成功读取时的 32 位数据格式。

后续补齐 Uniwill ioctl 的输入/输出复制、EC 读取、TDP 写入和 profile 错误传播；
WMI 保留原有 8 字节请求，校验分配和 4–40 字节响应，失败时不更新调用方输出。
精确匹配 `MECHREVO / GM6PX0X` 时不再强制写入显卡电源初始值；cTGP 同值设置不重复写 EC。
没有新增功耗参数或把 NVIDIA 未支持的固件通知映射成其他操作。

风扇接口拒绝超过一个字节的转速，避免将 256 截成 0；底层读写失败、重试耗尽和
回读不匹配会报告错误。全速模式重复启用保持原状态，初始化及同步写入只在成功后更新缓存。
旧式风扇后台任务和睡眠恢复的失败路径保留双风扇目标，避免部分恢复将另一只风扇写成 0。
这些是通用错误处理修正；原有曲线、寄存器、速度映射和正常成功路径的定时策略保持。
后台失败后，下一次手动请求会取消旧定时任务并立即排队恢复。

风扇、MODE/profile 和睡眠回调的状态更新使用共享同步，避免并发请求覆盖另一个操作的设置。
卸载先停止后台风扇任务，再拆除设备资源；卸载后的风扇/模式请求返回“不存在设备”，
重新探测后恢复可用。MODE 仍保留原有低字节写入格式；没有改变性能模式的位映射。
DEBUG 任意地址 EC 写入不包含在这些同步保障中。

旷世 16 Pro `GM6PX0X` 的安装、模块加载和部分接口验证见[本机记录](hardware/GM6PX0X.md)。
当前系统的只读运行检查见 [2026-10-29 记录](hardware/GM6PX0X-2026-10-29.md)。

其他机型的精确匹配、源码依据与待验证功能见[其他机型说明](hardware/OTHER-MODELS.md)。
`GX4HRXL` 新增三档模式，不启用旧式风扇表复制；`JIAOLONG Series-X6xR55xK`
按已公开实测补丁接入既有 TDP 表及 custom-profile 流程。只匹配 `MECHREVO` 厂商和完整板号。
无界 15X Pro `WUJIE Series-X5SP4NAG` 和蛟龙 16K `GM6BG0Q` 增加接电开机、USB 供电开关。
蛟龙 16K 还要求完整产品名和 BIOS `N.1.19MRO15`，并接入只读 EC 温度/双风扇 RPM、
三档模式（`0x0751` 的 `0xA0/0x00/0x10`）和按 OEM 控制台 profile 点收紧的
TDP 范围（PL1/PL2 35–80 W，PL4 固定 100 W）。本机已验证 PL1 写入对 package
功耗的影响；PL2/PL4、风扇曲线迁移和睡眠恢复未闭环，详见[本机记录](hardware/GM6BG0Q.md)。
寄存器及位定义经过公开 Uniwill 实现与 ACPI 反汇编核对，识别不修改开关值。

翼龙 15 Pro `GM5HG0A` 在完整产品名与 BIOS `N.1.09MRO19` 匹配时，也提供上述两个开关。
蛟龙 16 Pro 2023 `MRID6-23` 属于另一条 Bitland 路线，控制台通过已加载原生驱动提供背光亮度；
另接入原生 Uniwill 已暴露的 Fn、接电开机、USB 供电和背光接口，详见[原生驱动范围](hardware/NATIVE-KERNEL-CONTROLS.md)。
这些控制不依赖型号目录授权，不自动加载驱动或移植其他机型的 EC 参数。

另增加无界 15 Pro HPT 和星耀 P916F HPT-R 的精确身份与控制台适配，及新版内核性能档位 class 接口。
HPT 旧内核的错误档位映射会被拒绝，不存在的 MIFS 温度/第三风扇显示未知；P916F 不开放未经确认的 OEM 控制。
[板号、公开依据及验证边界](hardware/WUJIE-HPT-P916F.md)。

## 能力与边界

上游包括 Clevo、Uniwill、ITE 等平台模块，可能提供 Fn 键、键盘背光、传感器、风扇和功耗接口。
实际可用性还取决于具体型号、控制器和 BIOS/EC 固件；模块内的独立识别规则仍会生效。
通过统一品牌检查不代表每个模块都能匹配，也不代表这些接口对某台机器是安全的。

没有增加新 EC 寄存器、风扇曲线、GPU 功耗参数或睡眠/续航策略。
蛟龙 16 Pro 2025 复用已有 CPU 功耗校验范围；范围上限不是建议运行功耗，识别时不会自动应用。
不承诺自动提高性能，不承诺自动降低温度。没有实机验证的机型不得标为「完整支持」。

尤其注意：上游明确提醒，不兼容的 EC 操作可能损坏设备。不要在未知型号上强制写风扇、
充电阈值或功耗控制；不要运行网上来源不明的 EC 写入脚本。

## 查看本机信息（只读）

这些命令不加载模块、不写 EC，也不需要完整 `dmidecode` 输出：

```sh
uname -r
for field in sys_vendor product_name product_version board_vendor board_name chassis_vendor bios_version; do
    printf '%s: ' "$field"
    cat "/sys/class/dmi/id/$field" 2>/dev/null || true
done
```

反馈时附上：型号、CPU/GPU、BIOS 版本、发行版及内核、已有驱动版本，
以及背光/Fn/传感器等每个功能的具体结果。不要上传序列号、UUID、MAC 地址或未脱敏的完整系统报告。

## 构建验证

需要对应内核的 headers、编译器和 make。Arch 示例（选择已安装内核的对应 headers）：

```sh
# 安装依赖会更改系统；此命令仅为用户自行操作的示例。
sudo pacman -S --needed base-devel linux-headers
make -j2 KDIR=/usr/lib/modules/$(uname -r)/build
```

构建成功仅证明该内核下能编译，不证明硬件兼容。不建议为了试验直接 `make install`：
上游 install 目标会写系统模块及 `usr/` 中的规则，且不提供本分支的包管理卸载保障。
优先在明确兼容型号上通过发行版包管理/DKMS 打包测试，避免同时安装多个提供同名模块的包。
本分支使用独立的 AUR 包名 `mechrevo-drivers-dkms-git`，详见 [Arch / AUR 安装与打包](AUR.md)。
它与其他维护者的 `mechrevo-drivers-dkms` 互斥；现有第三方包不会自动变成这个仓库的版本。

## 维护原则

1. 先保留小而可审核的兼容性补丁。
2. 新型号适配需要型号/固件范围、只读探测依据和验证记录。
3. 风扇、功耗及充电控制单独评审，不以品牌放行代替安全检查。
4. 不重命名内核模块和用户态接口，避免破坏已有软件依赖；这也意味着不能与原版并装。
5. 不把本地编译结果、源码提交或 GitHub 发布说成已安装或已通过实机测试。
