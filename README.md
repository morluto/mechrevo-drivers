<div align="center">
  <h1>mechrevo-drivers</h1>
  <p><strong>机械革命笔记本的社区 Linux 平台驱动维护分支。</strong></p>
  <p>基于 TUXEDO drivers · DKMS · 精确 DMI/固件匹配 · 可审计硬件边界</p>

  [![Upstream baseline](https://img.shields.io/badge/upstream-v4.24.0-111111?style=flat-square)](https://gitlab.com/tuxedocomputers/development/packages/tuxedo-drivers)
  [![AUR](https://img.shields.io/badge/AUR-mechrevo--drivers--dkms--git-111111?style=flat-square&logo=archlinux)](https://aur.archlinux.org/packages/mechrevo-drivers-dkms-git)
  [![License](https://img.shields.io/github/license/LIghtJUNction/mechrevo-drivers?style=flat-square)](LICENSE)
  [![Last commit](https://img.shields.io/github/last-commit/LIghtJUNction/mechrevo-drivers?style=flat-square)](https://github.com/LIghtJUNction/mechrevo-drivers/commits/main)
</div>

> [!CAUTION]
> 这是非官方社区项目，与 MECHREVO、TUXEDO 均无官方支持关系。错误的 EC、风扇或功耗写入可能损坏硬件。**品牌检查通过不等于机型兼容，更不等于所有控制接口安全。**

## 先看结论

这个仓库做的事情很具体：保留 TUXEDO 驱动原有结构和模块名，只在有明确硬件身份、源码依据或实机证据时增加机械革命适配，并修复通用错误传播与并发状态问题。

```text
DMI / BIOS / 板号精确匹配
          ↓
复用已知平台接口，而不是猜 EC 寄存器
          ↓
DKMS 为当前内核编译模块
          ↓
只在明确范围内加载、验证、记录结果
```

它不是“机械革命全机型驱动包”，也不是自动性能优化、降温或风扇调校工具。

## 当前证据等级

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| 旷世 16 Pro `GM6PX0X` | **部分实机验证** | 已安装、加载并验证部分背光、Fn 锁、传感器、功耗拒绝路径与状态保持；不是完整认证 |
| 无界 14X `GX4HRXL` | 源码适配，待本项目实机验收 | 三档模式，未复制旧式风扇表 |
| 蛟龙 16 Pro 2025 `JIAOLONG Series-X6xR55xK` | 精确身份接入，待实机验收 | 复用已有 TDP 范围和 custom-profile 流程 |
| 无界 15X Pro、蛟龙 16K、翼龙 15 Pro | 精确型号/固件接入，待实机验收 | 接电开机、USB 供电等已有接口 |
| 蛟龙 16 Pro 2023 `MRID6-23` | 原生 Bitland/Uniwill 接口整合 | 不移植其他机型 EC 参数 |
| 无界 15 Pro HPT、星耀 P916F HPT-R | 精确识别与控制台适配 | 固件差异和未确认 OEM 控制保持封闭 |
| 其他 MECHREVO 机型 | **未知** | 只命中品牌字符串不能推导功能安全性 |

详细身份、固件限制和验证项见：

- [机械革命支持范围与边界](docs/MECHREVO.md)
- [GM6PX0X 实机记录](docs/hardware/GM6PX0X.md)
- [其他机型证据](docs/hardware/OTHER-MODELS.md)
- [原生内核控制范围](docs/hardware/NATIVE-KERNEL-CONTROLS.md)
- [HPT / P916F 范围](docs/hardware/WUJIE-HPT-P916F.md)

## 安装（Arch Linux / AUR）

先读取上面的支持范围，再安装与当前内核匹配的 headers。标准 Arch 内核示例：

```bash
sudo pacman -S --needed base-devel linux-headers
yay -S mechrevo-drivers-dkms-git
# 或：paru -S mechrevo-drivers-dkms-git
```

LTS、Zen、Hardened 或自定义内核必须安装对应 headers。安装后检查：

```bash
dkms status
```

AUR 发布的是**构建配方**，不是预编译内核模块。DKMS 会为装有 headers 的内核编译模块。替换磁盘上的包不代表当前已加载模块已经切换；通常应在确认恢复方案后重启，而不是随意热卸载一组互相依赖的平台模块。

> `mechrevo-drivers-dkms-git` 与另一维护者的 `mechrevo-drivers-dkms`、原版 `tuxedo-drivers`、旧 `tuxedo-keyboard` DKMS 包互斥。它不使用 `replaces`，不会接管其他维护者的包。

完整安装、卸载和发布流程见 [Arch / AUR 文档](docs/AUR.md)。

## 只读识别本机

下列命令不加载模块，也不写 EC：

```bash
uname -r
for field in \
  sys_vendor product_name product_version \
  board_vendor board_name chassis_vendor bios_version
do
  printf '%s: ' "$field"
  cat "/sys/class/dmi/id/$field" 2>/dev/null || true
done
```

反馈兼容性时请附型号、CPU/GPU、BIOS、发行版、内核、驱动版本，以及每项功能的实际结果。不要上传序列号、UUID、MAC 地址或未脱敏的完整系统报告。

## 这个分支改了什么

相对上游正式版 `v4.24.0`，主要维护内容包括：

- 将 `MECHREVO` 加入受限的 DMI 品牌检查，不关闭兼容性门禁；
- 为已知板号、完整产品名和 BIOS 增加精确匹配；
- 修正 Uniwill TDP、WMI、输入输出复制和失败传播；
- 拒绝越界风扇值、底层读写失败和回读不一致；
- 让风扇、模式、睡眠与卸载路径使用一致的同步和状态更新；
- 避免 `GM6PX0X` 探测时覆盖已有显卡电源配置；
- 保留原有 TUXEDO 匹配、模块名称、用户态接口和许可证。

没有新增泛化 EC 地址、未知机型风扇曲线、自动 GPU 功耗、自动降温或续航策略。

## 构建与验证

需要编译器、`make` 和当前内核 headers：

```bash
make -j2 KDIR=/usr/lib/modules/$(uname -r)/build
python3 -m unittest discover -s tests -v
```

编译成功只证明源码能针对该内核构建，不能证明硬件兼容。不要为了试验未知机型直接执行 `make install`：上游安装目标会写系统模块和规则，且绕过发行版包管理的卸载保障。

优先使用独立 DKMS 包，在明确支持范围内测试，并为安装前状态保留可验证的恢复材料。

## 上游同步

- 开发分支每日镜像到 `upstream`。
- 只有上游正式版本进入自动更新 PR。
- `main` 不被强推，也不会自动合并上游更新。
- 同步策略、冲突处理和发布门槛见 [维护文档](docs/MAINTENANCE.md)。

这意味着“上游已有新提交”与“本分支已审阅、构建、安装、加载并完成硬件验证”是五个不同状态，README 和验证记录不会把它们混为一谈。

## 相关组件

独立的机械革命 Rust 控制台与 CLI 正在实现，范围见 [控制台文档](docs/MECHREVO-CONSOLE.md)。`GM6PX0X` 的 CPU 长期功耗工具也独立维护，不包含在 DKMS/AUR 驱动包中，见 [功耗控制说明](docs/POWER-CONTROL.md)。

## 上游模块

仓库保留上游的 Clevo、Uniwill、ITE、NB04/NB05 等模块，可提供 Fn 键、键盘背光、传感器、风扇、功耗和平台相关用户态接口。具体模块能否绑定，仍由各自 DMI、控制器和固件条件决定。

上游正在逐步把适合主线的部分提交到 Linux 内核。引用或移植 TUXEDO 代码时，应保留作者与许可证信息，并在提交主线前与上游协调相应 `Codeveloped-by` 归属。

## License

本项目保留 TUXEDO 上游历史、版权与 GPL 许可证。具体条款见 [LICENSE](LICENSE)。
