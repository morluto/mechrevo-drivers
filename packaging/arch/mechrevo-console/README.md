# 本地 Arch 控制台包

`mechrevo-console` 安装 Rust CLI、原生 GUI、受限 OEM helper 和统一的
`mechrevo-control` 桥接工具，不依赖 DKMS 包。安装会把未改过的 TUXEDO 默认 profile
迁移为机械革命 Gaming profile，并保留用户已经修改过的 profile；不会覆盖用户曲线。
包同时提供用户级 `mechrevo-gaming-hotkey.service`，用于在实体按键、GUI 或电源状态切换
后同步机身性能档位灯。首次安装后执行：

```sh
systemctl --user enable --now mechrevo-gaming-hotkey.service
```

实体性能按钮循环为办公 → 游戏 → Turbo → 办公，使用三个不同的硬件模式请求。
游戏低噪仍可单独选择，与游戏模式共用硬件档位；按下按钮后继续进入 Turbo。
本机 Turbo 小灯变化已有用户确认，其余灯态及唤醒后的行为见
[灯光验证记录](../../../docs/PERFORMANCE-INDICATOR.md)。

当前配方固定源码提交 `cee10ecbf7e86582e2e0f7ba887c13385c96c50d`，包版本为
`0.1.0.r1535.gcee10ec-1`。这是本地部署配方，不表示已经发布到 AUR。
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

构建需要系统已有 Rust 1.95 以上、Git、pkgconf、desktop-file-utils、libxml2，以及锁文件
对应的 Cargo 缓存。Cargo 使用 `--release --workspace --all-features --locked --offline`，
缺少依赖时直接失败，不安装依赖或修改锁文件。内嵌字体和型号目录随二进制分发；
中文字体通过 fontconfig 使用系统回退字体，可选安装 `noto-fonts-cjk`。
运行依赖包含 `polkit`。桌面会话需有可用的授权代理才能显示管理员认证；本包不安装
新的常驻服务，也不自动启动授权代理。

在此目录执行；将本地仓库路径设为实际位置，Git 只取固定提交，工作区改动不进入包：

```sh
MECHREVO_CONSOLE_SOURCE=file:///home/lightjunction/Documents/GITHUB/mechrevo-drivers \
CARGO_BUILD_JOBS=2 \
nice -n 15 ionice -c 3 makepkg
```

不设置 `MECHREVO_CONSOLE_SOURCE` 时，makepkg 从项目 GitHub 仓库取得同一固定提交。
`CARGO_TARGET_DIR` 可指定绝对路径，以复用受跟踪的构建缓存；未设置时，产物在
makepkg 的 `src/cargo-target` 中。不要并行复用正在被其他 Cargo 构建写入的目录。

检查包内容和部署材料后，通过 pacman 安装本地产物：

```sh
pacman -Qlp mechrevo-console-0.1.0.r1535.gcee10ec-1-x86_64.pkg.tar.zst
sudo pacman -U ./mechrevo-console-0.1.0.r1535.gcee10ec-1-x86_64.pkg.tar.zst
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

`prepare()` 核对固定提交、干净工作树及必要文件的 Git 跟踪和普通文件类型；
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
