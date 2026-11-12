# 原生界面验收 · 2026-11-09

本轮重新设计了概览、控制、传感器和型号目录。界面使用近黑或浅灰底色、无纹理面板、清晰的无衬线文字；实时读数优先显示，性能档位和日常控制依次展开。导航保持可见，窄窗自动换行。

## 原生截图

以下图片由实际 eframe / OpenGL 窗口生成。预览程序直接使用生产 `DesktopApp`，明确显示“模拟数据”；数值不代表实机性能或兼容性。趋势在采样不足时保留积累状态。

| 视图 | 尺寸 | 截图 |
| --- | --- | --- |
| 深色概览 | 1280×900 | [查看](screenshots/overview-dark.png) |
| 浅色概览 | 1280×900 | [查看](screenshots/overview-light.png) |
| 设备控制 | 1280×900 | [查看](screenshots/controls-dark.png) |
| 传感器 | 1280×900 | [查看](screenshots/sensors-dark.png) |
| 型号目录 | 1280×900 | [查看](screenshots/catalog-dark.png) |
| 窄窗概览 | 640×900 | [查看](screenshots/overview-narrow.png) |
| 最小窗口，160% 文字 | 360×280 | [查看](screenshots/minimum-160-percent.png) |
| 当前 Linux 环境，无对应硬件读数 | 1280×900 | [查看](screenshots/native-system.png) |
| 改版前，相同 Linux 环境 | 1280×900 | [查看](screenshots/before-native-system.png) |

已逐张检查排版、中文字体、文字对比、选中与禁用状态。另在原生窗口实际点击侧栏、展开传感器来源并滚动到底，确认内容更新与导航固定。最小窗口需要滚动阅读；没有压缩文字或隐藏导航来容纳全部内容。

## 自动验证

当前源码资源校验的 34 项 Python 测试通过，清单中没有缺失资源。已同步移除旧字体的必需资源引用。Arch 打包的 7 项测试因环境没有 `makepkg` 跳过，不能计为通过；固定旧发布的配方和历史许可证证据保持原样。

GUI 共 47 项测试通过：31 项状态、数据与主题测试，1 项关闭写事务生命周期测试，15 项渲染与交互测试。布局测试包含四种 DPI、160% 文字、长标识、空数据、错误状态、两套主题和 OEM 编辑控件。其中主矩阵覆盖 80 种布局，另有代表性桌面与 OEM 布局检查。

本轮修复了固定导航后最小窗口的滚动区溢出、底部内容遮挡，以及空传感器测试数据被标成真实硬件的问题。原有预览、显式应用、回读与关闭事务保护测试继续通过。

```sh
cargo test --manifest-path console/Cargo.toml -p mechrevo-console-gui --features screenshot --locked
cargo fmt --manifest-path console/Cargo.toml -p mechrevo-console-gui --check

# 在图形桌面生成相同类型的原生截图
EFRAME_SCREENSHOT_TO=/tmp/mechrevo-overview.png \
  cargo run --manifest-path console/Cargo.toml -p mechrevo-console-gui \
  --features screenshot --example ui_preview -- --width 1280 --height 900
```

`ui_preview` 支持 `--light`、`--section controls|sensors|catalog`、`--width`、`--height` 和 `--scale`。其后台拒绝所有控制操作，不访问硬件。生产程序不加载测试数据。

验证环境为 Linux、Rust 1.99.1。此次没有 Windows 实机或机械革命硬件写入验收，也没有发布新的 AUR 包；现有打包配方仍固定到原发布提交。界面改版不扩大硬件支持范围。
