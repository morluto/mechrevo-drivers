# NVIDIA GPU ACPI 0xC5：官方源码、协议和候选补丁核对

核对时间：2026-10-15 08:42 UTC 前后。方法：在线全文、GitHub REST/GraphQL、官方仓库源码及 PR 实际 diff；没有加载模块、改服务、改功耗或发帖。下述 NVIDIA 版本来自实时远端 refs，不由本机旧安装记录推断。范围聚焦 GM6PX0X 已捕获的 GPU 0xC5，避免把 NPCF 0xC0 或 GPS 0xC0 当成同一事件。

## 0xC5 是否已有官方协议或已合并修复？

### Takeaway

目前仍没有足够依据实现 0xC5 功能处理。官方 Q&A #1447 没有回复或答案；当前 main 与 615.78.08 的相关文件相同，GPU 回调仍不支持 0xC5。仅查到其他机器的 NVPCF/GPS 电源管理问题，不能把这些观察变成本机协议定义。

### Cited Findings

- 通过 GraphQL 重新打开并查询正文、answer、comments/replies：#1447 的 isAnswered=false、answer=null、comments.totalCount=0；createdAt 和 updatedAt 均为 2026-10-14T19:14:33Z。本轮没有维护者回复可据以实现。该帖本身是本机采集者的观察及提问，不能当成 NVIDIA 已认可的协议说明。— [官方 Q&A #1447](https://github.com/NVIDIA/open-gpu-kernel-modules/discussions/1447)
- REST 实时核对 default_branch=main；main HEAD 为 ca2d03e6fafd4d4b56b383497d931c25b283bfcf，提交说明 615.78.08，committer 时间 2026-10-07T16:29:01Z。tags 首项为 615.78.08，其 tag 指向 1a82fbfda8f321b056eb3568850f9316c5e465c5；不能把 main SHA 和 tag SHA 写成同一个 commit，但本轮比较的两个文件内容一致。— [main 提交](https://github.com/NVIDIA/open-gpu-kernel-modules/commit/ca2d03e6fafd4d4b56b383497d931c25b283bfcf)、[615.78.08 tag](https://github.com/NVIDIA/open-gpu-kernel-modules/tree/615.78.08)、[refs API](https://api.github.com/repos/NVIDIA/open-gpu-kernel-modules/tags)
- kernel-open/nvidia/nv-acpi.c：main、615.78.08、615.71.09 三者 blob 都为 d0fe94a039a184bb2bedc21ef4e94f8fd61efc93，SHA-256 都为 39ea93250c6daec9fac485ddf2e277ff4b75184e3f057fa41c6524ee00d31beb。GPU 设备的 nv_acpi_notify_event() 原样传 event_type 给 rm_acpi_notify()；NPCF 的 nv_acpi_nvpcf_event() 则是另一回调，只有 ACPI_NVPCF_EVENT_CHANGE 才调用 rm_acpi_nvpcf_notify()。— [不可变源码 L147-L159](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/ca2d03e6fafd4d4b56b383497d931c25b283bfcf/kernel-open/nvidia/nv-acpi.c#L147)、[GPU notifier L251-L271](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/ca2d03e6fafd4d4b56b383497d931c25b283bfcf/kernel-open/nvidia/nv-acpi.c#L251)
- src/nvidia/arch/nvalloc/unix/src/osapi.c：main 与 615.78.08 blob 都为 22c4ede257066a2ef2b4bfab442f03835d7df910，SHA-256 都为 e4336f0e3bb55122680e0d344f970c123664122c2415134b7a6b517c98fcbe75。rm_acpi_notify() 的 switch 处理 ACPI_VIDEO_NOTIFY_PROBE、GPS 状态和 D1-D5；没有 0xC5 分支。未知事件会到 default 的信息日志和 L2198 NV_ASSERT(0)。615.71.09 的 osapi.c 整体 hash 不同，本轮没有把它说成整体相同。— [不可变 GPU switch L2163-L2203](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/ca2d03e6fafd4d4b56b383497d931c25b283bfcf/src/nvidia/arch/nvalloc/unix/src/osapi.c#L2163)
- 数值相同不表示通知协议相同：NPCF 的 ACPI_NVPCF_EVENT_CHANGE=0xC0 定义在 nv-acpi.c L68；GPU 的 ACPI_NOTIFY_GPS_STATUS_CHANGE=0xC0 定义在 acpi_common.h L88，并由 RmHandleGPSStatusChange() 消费；没有在该头文件找到 0xC5 定义。— [NPCF 常量](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/ca2d03e6fafd4d4b56b383497d931c25b283bfcf/kernel-open/nvidia/nv-acpi.c#L68)、[GPU 常量表 L76-L97](https://github.com/NVIDIA/open-gpu-kernel-modules/blob/ca2d03e6fafd4d4b56b383497d931c25b283bfcf/src/nvidia/inc/kernel/platform/acpi_common.h#L76)
- ACPI 6.6 §5.6.6 把 0xC0 及以上留给厂商定义；标准只限定命名空间和通知机制，不提供 GM6PX0X GPU 0xC5 的动作或确认语义。— [UEFI ACPI 6.6 §5.6.6](https://uefi.org/specs/ACPI/6.6/05_ACPI_Software_Programming_Model.html#device-object-notifications)
- 官方仓库还存在 #1300（NPCF 通知唤醒空闲 GPU）、#1419（另一台 Clevo 的 GPS 版本不匹配与 D2 重复通知）、#1345（Lenovo NPCF 预算字段为零）、#1162/#1393（HP/Lenovo Dynamic Boost 或 SBIOS 查询问题）。本轮全文检查未见这些 issue 提供 GPU 0xC5 定义；它们是各作者机器的报告，没有本机协议背书。#1344 还明确自称由 OpenCode 生成，应尤其避免把其中推测照搬为确定根因。— [#1300](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1300)、[#1419](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1419)、[#1345](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1345)、[#1162](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1162)、[#1393](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1393)、[#1344](https://github.com/NVIDIA/open-gpu-kernel-modules/issues/1344)

### Inferences

- 结合当前官方 switch，本机已有 trace 中 GPU event=197 与 osapi.c:2198 断言的因果说明仍成立；新增在线调查没有推翻此前结论。此前实际 trace 和固件关联来自本仓库 docs/NVIDIA-0xC5.md，本轮没有重复实机采集。
- 0xC5 紧随 NPCF 0xC0 只能说明固件触发有关联，不能推导可无条件丢弃、转为 GPS 0xC0、或重复转发 NVPCF。否则可能多执行一个协议动作、遗漏确认、或掩盖真正未处理功能。
- 搜索没有命中只是本轮检索范围内的负证据，不证明全网或所有 OEM 内部文档都没有定义。

### Gaps

- NVIDIA/OEM 尚未说明：0xC5 是兼容旧接口的冗余提示，还是必须独立消费并确认的状态；需要读取哪个已定义接口、是否要 ACK、用什么可观测状态验证。缺失的是处理语义，不是编译能力。
- 没有找到 GM6PX0X / N.1.09MRO07 的官方 0xC5 协议、已合并补丁或本机与同版本闭源模块的 A/B 证据。
- 615.78.08 Dynamic Boost README 的 us.download.nvidia.com 地址在本轮 web 工具访问失败；不依据搜索摘要扩展它的内容。相关结论基于能完整读取的源码和 GitHub API。

## PR #1181/#1299 能否安全用于本机 0xC5？

### Takeaway

不能。两者处理的是 runtime-suspend 期间通知引起的多余 GPU 唤醒，均未定义或接入 0xC5；均未合并。新增作者实测还表明：直接丢弃 NVPCF 通知会留下过期功耗限额，说明删通知或仅压掉断言不具有修复证明。

### Cited Findings

- #1181 当前 open、merged=false，head=154199c682f4c1069bfad2d46e2b279e04435507，updated_at=2026-08-16T14:59:43Z；REST reviews 为空，review_comments=0。实际 diff 只在 RmHandleGPSStatusChange() 和 rm_acpi_nvpcf_notify() 增加空闲状态判断，未改 rm_acpi_notify() switch，未新增 0xC5 分支。作者在 ASUS TUF RTX 4060 等环境的描述是实验观察，不是 NVIDIA 协议定义。— [PR #1181](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1181)、[实际 diff](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1181/files)
- #1181 的 lars76 评论报告，在 ASUS GA403UI、610.57.04、Linux 7.1.6 上丢弃空闲期 NVPCF 通知确实阻止唤醒，但切换 platform profile 后，即使 GPU 恢复使用仍沿用旧 75 W 而非新 90 W，直到下一次通知才更新。作者因此改为延迟重放，并且未声称 GPS 可安全抑制。该证据是该作者在另一型号上的观测，不能直接当成本机复现。— [具体评论](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1181#issuecomment-5308056264)
- #1299 当前 open、merged=false，head=555c98d1bdbc138c8ee2588f5e268e6eb005a468，updated_at=2026-10-11T22:21:39Z；REST reviews 为空，review_comments=0。实际改动为 nv-priv.h 的 pending 状态、osapi.h 声明、dynamic-power.c 的互斥/重放处理及 rm_acpi_nvpcf_notify() 入口条件。它保留恢复后的 NVPCF 通知并明确不处理 GPS，更没有修改 GPU 0xC5 switch。— [PR #1299](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1299)、[实际 diff](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1299/files)
- #1299 最近评论有在 ASUS GA605WI、NVIDIA 615.78.08、Linux 7.2.8 上对 4 次电池百分比下降的 A/B 报告：原版 4 次唤醒，补丁 0 次；它是短时间其他机型的作者报告，既不能证明 GM6PX0X 适用，也不能证明完整长期稳定。另有评论指出 GPU D1/D2/D3 通知可有独立的充电触发，进一步表明不同事件需要分别确认。— [615.78.08 作者测试](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1299#issuecomment-6114540423)、[D-notifier 观察](https://github.com/NVIDIA/open-gpu-kernel-modules/pull/1299#issuecomment-5823918807)

### Inferences

- 目前没有安全且有依据的本项目驱动行为修补可直接交付为 0xC5 修复；不应修改 EC、吞通知、把 0xC5 映射 GPS、删断言或安装第三方 NVIDIA 补丁来宣称已适配。
- 如果以后本机出现可重复的空闲 dGPU 周期唤醒，应先按通知目标/数值分辨 NPCF、GPS、D-notifier，再单独评估 #1299；这与当前 0xC5 语义问题是不同验收目标。
- 下一步可安全进行的是保留问题边界并继续只读核对官方回复、OEM 协议，以及已有本机 AML 的所有 0xC5 触发条件。硬件重启/睡眠/模块替换仍遵守用户授权边界。

### Gaps

- 两 PR 没有 GM6PX0X 的实测收据，也没有 NVIDIA maintainer review 支持本机采用。
- 本轮没有执行 GPU 唤醒实验、长负载、闭源模块比较、固件升级或 ACPI override；没有产生新的安装/加载/生效结论。
- 需要的最小修复依据：维护者/OEM 对 0xC5 的动作与确认定义，或可审计的对应官方实现；随后才可编写回归、构建并在获准的启动流程中加载验收。

检索与复核记录（负结果只限这些查询）：web `site:github.com/NVIDIA/open-gpu-kernel-modules "0xC5"`、`site:github.com/NVIDIA/open-gpu-kernel-modules "197" ACPI`、`NVIDIA ACPI "0xC5" Notify`、`NVIDIA "GM6PX0X" ACPI`、`NVIDIA ACPI "197" osapi.c`、`site:forums.developer.nvidia.com "0xC5" ACPI`、`site:github.com "ACPI_NOTIFY" "0xC5" nvidia`、`site:github.com "osapi.c" "2198" NVIDIA`；GitHub REST `repo:NVIDIA/open-gpu-kernel-modules NVPCF in:title,body` 返回 11 个（包括 #1181/#1299 及上述问题）；`repo:NVIDIA/open-gpu-kernel-modules "0xC5" "notify" in:title,body` 返回 0 个；GraphQL discussion search `repo:NVIDIA/open-gpu-kernel-modules 0xC5` 返回唯一 #1447。GitHub code search 的 0xC5 返回空，未把索引结果当成完整源码审计。早先 gh CLI 带冒号查询 osapi.c:2198 语法报错，已改用 REST 正常查询；一次未引号的 tree URL 被 zsh 通配规则拒绝，随后补引号成功。源码结论采用实际取得的 blob，而非这些失败查询。
