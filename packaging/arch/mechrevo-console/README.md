# Arch / AUR 控制台包

`mechrevo-console` 安装 Rust CLI、原生 GUI、受限 OEM helper 和统一的
`mechrevo-control` 桥接工具，不依赖 DKMS 包。安装会把未改过的 TUXEDO 默认 profile
迁移为机械革命 Gaming profile，并保留用户已经修改过的 profile；不会覆盖用户曲线。
包同时提供两个互斥的热键处理者：

- 用户级 `mechrevo-gaming-hotkey.service`：需要可用的 tccd/D-Bus，在实体按键、GUI 或
  电源状态切换后同步 TCC profile 与机身性能档位灯。
- 系统级 `mechrevo-ec-hotkey.service`：root、无 tccd 依赖，只监听 F6，通过
  `/dev/tuxedo_io` 切换 EC 模式字节，按 Windows 54919 profile 写 PL1/PL2/PL4，
  并同步 UEFI `UniWillVariable.PowerMode`。

只能启用一个，否则同一次按键会切两档。另安装
`/usr/lib/systemd/system-sleep/mechrevo-touchpad`：只恢复由
`mechrevo-control touchpad off|on` 保存的 i2c 硬件状态；KDE/libinput 自己的
`Enabled=false` 不会生成该状态文件。

只能启用一个，否则同一次按键会切两档：

```sh
# 走 TCC（需要 tccd）
systemctl --user enable --now mechrevo-gaming-hotkey.service
# 或走 EC-only（不需要 tccd；先停用用户级服务）
systemctl --user disable --now mechrevo-gaming-hotkey.service
systemctl enable --now mechrevo-ec-hotkey.service
```

实体性能按钮循环为办公 → 游戏 → Turbo → 办公，使用三个不同的硬件模式请求。
游戏低噪仍可单独选择，与游戏模式共用硬件档位；按下按钮后继续进入 Turbo。
本机 Turbo 小灯变化已有用户确认，其余灯态及唤醒后的行为见
[灯光验证记录](../../../docs/PERFORMANCE-INDICATOR.md)。

当前配方固定源码提交 `c152ca3fe2599aababcaf83f454987285ebf1abd`，包版本为
`0.1.0.r1535.gc152ca3-1`。该提交在 r1535 基线上增加无 tccd 的 EC-only 热键服务、Windows 54919 TDP profile、UEFI PowerMode 同步与触控板恢复 hook；
发布收据仍对应旧的 r1535-2 包，不表示新包已经发布或完成整包验收。
该配方已发布到独立的 [AUR 包](https://aur.archlinux.org/packages/mechrevo-console)，
签名安装包与配方源包见 [GitHub Release](https://github.com/LIghtJUNction/mechrevo-drivers/releases/tag/console-v0.1.0-r1535-2)。
发布构建、制品摘要、远端状态与验收边界见 [发布收据](../../../docs/verification/console-release-r1535-2.json)；
本次发布验收机仍保留此前已验证的 `-1`，没有重新安装控制台或更新内核驱动。
后续更新应一并修改提交、版本和部署验证记录，不能只替换安装目录里的二进制。

该固定提交包含 OEM helper 与策略。本轮包的实际构建、安装及硬件验证结果由部署
收据单独记录，更新配方本身不代表已安装或已经验证实体效果。
本机旧 r188 的构建与验收边界保留在
[历史收据](../../../docs/verification/performance-mode-cycle-r188.json)。
动态 Turbo、办公偏好与亮度策略见
[档位说明](../../../docs/PERFORMANCE-PROFILES.md)，上一轮参数调整及安装记录见
[r1531 收据](../../../docs/verification/performance-profiles-r1531.json)。
本轮新增响应式设备工作台、真实温度趋势和 GM6PX0X 的五档性能选择，继续复用已保存的参数；
安装、受限文件摘要、五档 root 事务及原生界面验证见
[r1535 收据](../../../docs/verification/console-workspace-r1535.json)。普通用户认证交互、
实体灯光／RPM、游戏性能及 Windows 实机不在本轮结论范围内。
更新不自动覆盖已有用户配置；本机 profile/settings 安装前后内容一致，恢复材料保存在本机统一备份目录。

构建需要 Rust 1.95 以上、Git、pkgconf、desktop-file-utils 和 libxml2；makepkg/AUR helper
可按配方安装缺失的系统构建依赖。`prepare()` 先用 `cargo fetch --locked` 下载当前架构的
锁定依赖，首次构建不要求事先准备 Cargo 缓存；网络或锁文件检查失败就停止。
编译仍使用 `--release --workspace --all-features --locked --offline`，不会联网更新依赖
或修改锁文件。已有完整缓存时，可设置 `CARGO_NET_OFFLINE=true` 进行全离线构建。
内嵌字体和型号目录随二进制分发；中文字体通过 fontconfig 使用系统回退字体，
可选安装 `noto-fonts-cjk`。运行依赖明确包含 `python`、`systemd` 与 `polkit`。
桌面会话需有可用的授权代理才能显示管理员认证；本包不自动启用常驻服务或授权代理，
也不自动安装或升级 DKMS/TCC；已有 profile 的迁移规则见开头说明。
五档控制仍需受支持机型及可信、有效的 tccd 配置。

在此目录执行；将本地仓库路径设为实际位置，Git 只取固定提交，工作区改动不进入包：

```sh
MECHREVO_CONSOLE_SOURCE=file:///home/lightjunction/Documents/GITHUB/mechrevo-drivers \
CARGO_BUILD_JOBS=2 \
nice -n 15 ionice -c 3 makepkg
```

不设置 `MECHREVO_CONSOLE_SOURCE` 时，makepkg 从项目 GitHub 仓库取得同一固定提交。
`CARGO_TARGET_DIR` 可指定绝对路径，以复用受跟踪的构建缓存；未设置时，产物在
makepkg 的 `src/cargo-target` 中。不要并行复用正在被其他 Cargo 构建写入的目录。

## 预编译发布约束

公开的 Arch `x86_64` 安装包必须在干净的官方 Arch 环境中构建，而不是直接分发
CachyOS 或其他按本机 CPU 优化的产物。C/C++ 使用 `-march=x86-64 -mtune=generic`，
Rust 使用 `-C target-cpu=x86-64`；三个 ELF 产物均需检查 GNU ISA 属性，不得带有
`x86-64-v2/v3/v4` 的最低要求。只改编译参数而继续链接宿主的 v3 启动对象／库并不足够。
这只约束公开二进制；AUR 本机构建仍尊重用户自己的 makepkg 编译设置。

发布附件应同时包含构建配方源包、`SHA256SUMS`、其 OpenPGP 分离签名和维护者公钥。
从可信渠道核对公钥指纹后，再验签、校验摘要并检查包内容。源码标签与二进制摘要分别
记录；GitHub 自动生成的整个仓库源码压缩包不等同于 AUR 配方源包。

检查包内容和部署材料后，通过 pacman 安装本地产物：

```sh
pacman -Qlp mechrevo-console-0.1.0.r1535.gc152ca3-1-x86_64.pkg.tar.zst
sudo pacman -U ./mechrevo-console-0.1.0.r1535.gc152ca3-1-x86_64.pkg.tar.zst
mechrevo-console --version
mechrevo-console status --json
```

安装目标为 `/usr/bin/mechrevo-console`、`/usr/bin/mechrevo-console-gui`、
`/usr/bin/mechrevo-control` 和
`/usr/share/applications/best.lmm.mechrevo-console.desktop`；desktop ID 与 GUI
的 Wayland app ID 一致。另安装 root 归属的
`/usr/lib/mechrevo-console/oem-helper`（0755，无 setuid）和
`/usr/share/polkit-1/actions/org.mechrevo.console.oem.policy`（0644）。
许可放在 `/usr/share/licenses/mechrevo-console/`，
包含项目 GPL 许可声明和两份内嵌字体的 OFL；控制台说明放在对应的 `/usr/share/doc/` 目录。

`prepare()` 先核对固定提交、干净工作树及必要文件的 Git 跟踪和普通文件类型，再获取锁定依赖；
`check()` 验证 desktop 文件及策略 XML，不联网读取 DTD，并核对唯一 action、固定
helper 路径及授权默认值。`package()` 要求三个真实可执行产物为非符号链接普通文件，
将 helper 改名放到上述固定路径，再核对 helper／策略的字节与权限。

OEM 枚举与预览不提权。只有显式应用时，普通用户通过 `pkexec` 请求受限 helper
执行类型化计划；活动会话策略为 `auth_admin_keep`，管理员认证可短时缓存，非活动
会话为 `auth_admin`，`allow_any` 为 `no`。不赋予任意路径写入权限，不放宽 sysfs
权限，也不让整个 GUI 以 root 运行。授权拒绝、缺少代理或 helper 不可用均须作为
失败报告；不能自动重放旧计划。

安装后应核对 `pacman -Qkk mechrevo-console`、包内与安装后二进制的摘要、CLI
只读状态及原生 GUI 启动结果。还要核对 helper／策略的 root 归属、0755／0644 模式、
固定执行路径，以及取消授权时没有硬件写入。实际 OEM 写入、回读和恢复另作硬件
验收；LED 请求缓存不证明物理颜色，充电档位不证明固定百分比停充。
安装包成功不代表 GUI 或硬件控制已验收；运行中的
内核模块也不会因安装控制台而更新。回滚使用保留的上一个本地包执行 `pacman -U`；
首次安装可用 `pacman -R mechrevo-console` 卸载，用户 GUI 偏好不会由该包删除。
