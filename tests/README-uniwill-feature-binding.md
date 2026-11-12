# Uniwill 特征未绑定回归

`tuxedo_io` 初始化时可能暂时没有活动 Uniwill 接口，但设备节点仍会注册。
旧实现的型号、双风扇、性能档位和 TDP 路径会使用未绑定的 `uw_feats`。
本轮修复在依赖特征的入口拒绝该状态；常量、接口名、合法空操作、
未知命令 `ENOTTY` 和既有参数/复制错误顺序保持。

`test_uniwill_feature_binding.py` 提取真实生产函数、命令头和结构声明，
用 C fixture 模拟接口、EC 和用户空间复制，不加载模块或写硬件。
14 个测试方法均执行普通与 DEBUG 构建，覆盖首次识别失败、晚绑定、
失败重识别、NULL provider、传输错误、无效参数及历史命令。
当前 provider 返回静态对象，NULL provider 是防御边界测试；失败重识别保留
此前发布的静态元数据。这不解决 transport 的并发解绑，也不统一底层错误码。

从项目根目录运行，先按项目规范开启文件跟踪，并准备已有的 `.local-tests` 目录：

```sh
python -B -m unittest discover -s tests -p test_uniwill_feature_binding.py -v
python -B scripts/verify.py --domain driver
```

`UNIWILL_TEST_TMPDIR` 可指定临时输出目录。通过 `UNIWILL_FEATURE_IO_SOURCE`
指定旧 `tuxedo_io.c` 可复用新测试验证敏感性，默认读取当前源码；
测试子进程禁用 core dump，并设置执行超时。

2026-10-18 从固定提交 `c76b738` 的干净归档加入本轮保护及两个新测试：
专用 14 项、完整驱动域 496 项均通过，零跳过；旧源码在七个边界场景的
普通/DEBUG 构建中共触发 14 次预期子测试失败。候选未包含既有摄像头 WIP。
内核 `7.2.9-arch1-1` 与 `7.2.7-arch1-1` 的 `W=1 -j2` 构建各产生 28 个模块。
各有五条未改动文件的未使用变量警告，不能称为零警告构建。

该候选未安装或加载；上述结果不证明风扇噪声、散热、睡眠恢复或其他型号通过实机验收。
公开收据见 [driver-console-hardening.json](../docs/verification/driver-console-hardening.json)，
完整日志、旧源码负例和模块散列留在收据指定的本地证据目录。
