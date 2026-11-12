# 无界 14SAH P4HPLNAV

## 精确身份

控制台注册表只在以下三个 DMI 字段完全相等时识别此机型：

```text
sys_vendor   = MECHREVO
product_name = WUJIE Series
board_name   = WUJIE Series-P4HPLNAV
```

这些字段和 BIOS `N.1.01MRO05`、EC `1.1` 来自一份无界 14SAH 的 Linux 硬件报告。BIOS 仅作为该报告的环境记录，不是本项目识别条件或固件兼容承诺。

## 音频路径

该报告将内置扬声器和麦克风识别为 AMD ACP6.3 加 Everest ES9356 SoundWire，记录的 Ubuntu 7.0 内核没有匹配的声卡机器驱动。Linux 7.4-rc1 的声音维护者拉取内容列入了 ACP6.3 ES9356 机器驱动和 ES9356 DAI 格式修正；机主随后报告，用这些修正构建的内核在该硬件上创建了扬声器、耳机、内置麦克风和耳麦端点。

该机的桌面端还需要能识别 ES9356 组件的 ALSA UCM 配置。它属于 ALSA 配置层。

这仓库中的新增内容只帮助控制台识别机型并展示对应平台证据。它不包含 ACP6.3 声卡驱动、ES9356 编解码器补丁或 ALSA UCM 配置，也没有验证某个发行版内核是否已经带齐这些改动。登记信息不会给该机解锁 EC、风扇、充电或功耗控制；`hardware_validated` 保持为 `false`。

## 来源

- [无界 14SAH 硬件报告及 DMI 字段](https://www.mail-archive.com/ubuntu-bugs%40lists.ubuntu.com/msg6319052.html)
- [Linux 7.4-rc1 声音维护者拉取内容](https://lists.openwall.net/linux-kernel/2026/10/23/536)
- [机主在实际硬件上的补丁测试及 UCM 说明](https://www.mail-archive.com/ubuntu-bugs%40lists.ubuntu.com/msg6319765.html)
