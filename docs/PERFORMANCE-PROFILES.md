# GM6PX0X 本地性能档位

这些是 Linux 控制策略，不是已验证的原厂固定瓦数档。支持范围为本机
GM6PX0X、BIOS N.1.09MRO07、i9-12900HX 和已安装的 TCC 3.0.10 本地补丁版。
不能将本机参数直接用于其他型号。

## 调整依据

2026-11-02 实机检查发现，旧 Turbo 的 `useMaxPerfGov=true` 使 TCC 选择
performance governor，并把最低频率请求设到每个 CPU 的硬件最高频率。
例如 policy0 的 scaling_min_freq 和 scaling_max_freq 同为 4900000。
TCC CpuWorker.applyCpuProfile 的该分支明确调用
`setGovernorScalingMinFrequency(-2)`；普通分支则使用配置中的 800000。
这证明频率请求被固定，不证明处理器实际一直运行在 4.9GHz；热限制、
空闲状态等仍可能降低实际频率。

旧办公档使用最偏省电的 `power` EPP；新默认改为 `balance_power`，仍保留
3.2GHz 上限。此变化是交互响应与节能的策略取舍，不是已经量化的速度提升。
默认值没有提高 CPU/GPU 功耗限额，也没有猜测或修改新的 EC 寄存器。

## 档位分工

- **办公**：powersave governor、balance_power 偏好、0.8–3.2GHz 请求范围，
  全部 24 个逻辑 CPU 在线，保留睿频。风扇下限请求仍为 60%。
- **游戏平衡**：powersave governor、balance_performance 偏好，上限请求仍为
  4.9GHz；各 CPU 的实际可用范围还受自身硬件上限约束。风扇下限仍为 60%。
- **游戏低噪**：CPU 参数与游戏平衡一致，保留已有的 50% 风扇下限请求。
  它与游戏档共用硬件模式，不是实体键循环中的额外一步。
- **狂暴性能**：powersave governor 搭配 performance 偏好，关闭
  `useMaxPerfGov`，允许最低频率请求回到 0.8GHz，上限请求仍为 5.0GHz。
  在 intel_pstate 上 powersave 是动态调节接口，不等于禁止睿频。
  保留既有 Freezy 风扇策略及 60% 下限，不保证持续峰值频率。
- **一键强冷**：保留已有 CPU 参数和 100% 风扇请求。请求百分比不等于
  已测得的 RPM、噪声或降温效果。

所有档位不再默认改变屏幕亮度；分辨率、刷新率策略保持不启用。
既有风扇曲线、最低转速请求及 NVIDIA offset 字段不在本次调参范围。
保存了 customFanCurve 不代表 TCC 在 Balanced/Quiet/Freezy 档实际采用该表。

## 功耗与温控独立

这些 profile 的 odmPowerLimits.tdpValues 仍为空。旧说明中的 45W、75W、130W
没有相应的实际写入依据，因此从默认描述和切档通知中移除。切档通知仅确认
保存的 profile 已选中，不承诺瓦数、实际转速或持续频率。

本机另有 mechrevo-power 管理的 55W CPU package 长期功耗上限与 90°C 软件
温控目标，每秒检查。它们在本次优化中保持原样；PL2 不由该工具管理。
软件目标不是硬温度上限。功耗状态需以 `sudo mechrevo-power status` 的实际
回读及 holding_now/errors 为准，不能从某个档位的名称推断。

## 已有配置和验收边界

`sync-profiles` 仍然只补齐缺失档位，除原有的未修改 TUXEDO 默认迁移外，
不悄悄覆盖已有 CPU、亮度或风扇设置。更新软件默认值不会自动调好一台已有
配置的机器。明确请求优化本机后，才备份 /etc/tcc/profiles 并逐字段调整；
保留未知字段和用户风扇设置，并在写入前检查文件未变化。

回归测试覆盖新默认值、已有配置逐字节保留、损坏文件拒绝、写入与并发失败，
以及切档成功/拒绝/超时后的硬件和通知边界。硬件验收还需逐档检查活动
profile、各 cpufreq policy、亮度、风扇请求/遥测与独立功耗保护。
按键重复触发的复现与修复见 [性能按键记录](PERFORMANCE-INDICATOR.md)。

不将合成按键测试写成实体灯态验收，也不将 governor/频率请求正确写成游戏
帧率、续航、噪声、满载温度、睡眠恢复或其他型号均已验证。
