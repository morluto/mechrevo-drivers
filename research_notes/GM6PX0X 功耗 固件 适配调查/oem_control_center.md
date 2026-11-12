# GM6PX0X 原始 OEM 控制中心定向补证

日期：2026-10-15；这是唯一追加轮，已停止新查询。目标限定为 GM6PX0X / i9-12900HX / BIOS N.1.09MRO07 与 Semcosm 所用 GCUService/控制台包的身份对应。未下载控制中心归档、固件、OEM EXE 或 DLL；仅远程只读网页、公开 API 和固定 Git 源码，未执行软件或访问真实 EC/功耗。官方网页 JS 和 API 响应在内存解析，只有本笔记写入本地。

## 1. Semcosm 的 GCUService 能否匹配本机固件？

### Takeaway
能定位作者使用的软件版本、二进制哈希及实际商品 DMI 名称，但作者明确承认 GM6PX0X 到包内平台目录的映射仍待确定。因此无法闭合本机 CPU/BIOS/ROM-ID → dispatcher → profile → 单位/前置模式。

### Cited Findings
- 固定提交 `cae0afbaa704d253e29a268cc2d5f7fa4167106b` 的报告记载 `GCUService.exe` SHA-256 为 `e2095ea378382e00f910c3bb9c031990b6002f262f932f838f9f7be80ea767c8`，构建时间 2025-08-08 06:54:16 UTC，PDB 路径含 `CCU_49ver/MyControlCenter`。— [报告 L1-7](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/windows-control-center/GCUService_reverse_report.md#L1)
- 软件包分析记载本地 source archive 名称 `ControlCenter_5.17.51.33_Mechrevo.zip`、外层 EXE 和同版本 msixbundle；没有在该文件提供这个归档的原始下载 URL/归档 SHA-256。— [包布局 L9-26](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/windows-control-center-analysis.md#L9)
- 作者写明本机 product_name=`Kuangshi16Pro Series GM6PX0X`、board=`GM6PX0X`，但包内 fan-table 目录不包含 GM6PX0X，使用 `PH6PGEx`、`PH6PG7x` 等命名；其明确的下一步是确认厂商软件如何映射。— [Machine-Mapping Clue L182-192](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/windows-control-center-analysis.md#L182)
- 作者建议在 Windows 监测实际读取哪个 UserFanTables 目录，说明这个 dispatcher 尚未公开闭环。— [下一步 L215-217](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/windows-control-center-analysis.md#L215)
- 作者把 vendor EXE、installer archive、extracted tree 和 runtime capture 全部留作 Git 忽略内容；仓库提供逆向报告，不提供可由本次直接逐字节复核的原始安装包。— [存储范围 L1-19](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/windows-control-center/README.md#L1)

### Inferences
- 该 GCUService 哈希可用于将来比对已取得的合法 OEM 包，但不能证明包来自官方，更不能证明它为 N.1.09MRO07/12900HX 的正确版本。
- 未闭合的 model-family dispatcher 是比“再找一个功率常量”更实质的缺口。当前没有依据把 PH6PGEx/PH6PG7x 或 130/130/200 模板移植到本机。

### Gaps
- 已检查作者的 Windows README、软件包分析、GCUService/GCUBridge/GamingCenter3_Cross/ACPIDriverDll 逆向报告；没有在这些已检查文件中找到 CPU=i9-12900HX、BIOS=N.1.09MRO07、EC/ROM-ID 与上述软件包的完整对应，不把该结论扩大为全仓库或全互联网不存在。
- GitHub Code Search 精确查询 `ControlCenter_5.17.51.33_Mechrevo` 和上述 GCUService SHA-256 均返回空列表；GitHub 索引有覆盖限制，空结果不证明原始包不存在。

## 2. 官方下载目录给出的最强精确关系是什么？

### Takeaway
找到官方精确商品“旷世 16 Pro”及关联驱动目录。官方目录当前列出的控制台是 5.17.49.19/5.17.51.34；没有返回 Semcosm 的 5.17.51.33，也未给出本机 BIOS/ROM-ID 对应。

### Cited Findings
- 官方下载网页的公开配置为 `apiBaseUrl=https://gwapi.mechrevo.com/api/v1/client`。页面加载的 JS 公开定义 `getDriverList → GET /drivers`、`getDriverFilterOptions → GET /drivers/filter_options`；并非猜测 API 路径。— [官方下载页](https://www.mechrevo.com/cn/downloads)、[官方接口定义 JS](https://www.mechrevo.com/cn/_nuxt/rYgFv1jz.js)
- 官方下载分类接口返回：应用软件→控制台 `gO0SxK`，游戏笔记本→旷世 `r78SxV`。— [分类 API](https://gwapi.mechrevo.com/api/v1/client/home/download_categories)
- 对官方旷世系列查询，12 个展示商品中有 `name=旷世 16 Pro`、`id=gxZSDX`、`slug=kuang-shi-16-pro`；精确商品详情再次返回同名和 ID，但 `params=null`，没有提供 `product_skus` 字段，没有板号/CPU/BIOS/ROM-ID 身份条目。— [系列商品 API](https://gwapi.mechrevo.com/api/v1/client/display_products?q%5Bproduct_serial_id_is%5D=r78SxV&limit=999)、[精确商品 API](https://gwapi.mechrevo.com/api/v1/client/display_products/gxZSDX)
- 只针对 `gxZSDX` 的驱动关联查询返回 `status=SUCCESS`、`total=72`、`limit=100`；全部 72 个对象中的 title 没有“控制”、“BIOS”或“EC”条目。已看到的主板项按 IQ/PQ/PX/PR-AR 分组。— [精确商品驱动 API](https://gwapi.mechrevo.com/api/v1/client/drivers?q%5Bby_display_product%5D=gxZSDX&limit=100)
- 该商品的官方 filter_options 原文摘要：`categories=[{name:IQ,id:491},{name:PQ,id:490},{name:PR/AR,id:59},{name:PX,id:487}]`、`authors=[]`、`tags=[]`。这展示商品关联覆盖多平台，未给 GM6PX0X/12900HX/MRO07 交叉身份。— [精确商品筛选 API](https://gwapi.mechrevo.com/api/v1/client/drivers/filter_options?q%5Bby_display_product%5D=gxZSDX)
- 官方控制台分类返回 25 个对象，其中 `id=Lws3kp`，title=40系常规控制台、sub_title=5.17.49.19，source_url 指向 `MECHREVO2026/CCU/ControlCenter_5.17.49.19_Mechrevo.zip`；`id=EmsXzq`，title=40系双显三模机型、sub_title=5.17.51.34，source_url 指向 `MECHREVO2026/CCU/ControlCenter_5.17.51.34_Mechrevo.zip`。没有 5.17.51.33。这里只核对目录元数据，没有下载这两份归档。— [官方控制台列表 API](https://gwapi.mechrevo.com/api/v1/client/drivers?q%5Bdriver_product_serial_id_is%5D=gO0SxK&limit=100)

### Inferences
- 现在有可信官方来源及明确版本差异，比第三方转载下载地址更有价值；但是“40 系常规/双显三模”仍然不是精确 CPU/BIOS whitelist。无法从这两个目录标题决定本机应该使用哪一个软件包。
- 官方精确商品在当前目录中没有关联控制台项，不能从名称相同就自动推导应安装 5.17.51.34，更不能证明 Semcosm 5.17.51.33 的 profile 对本机适用。

### Gaps
- 官方精确商品/API 没有暴露旧 GM6PX0X + 12900HX 的 SKU 与 BIOS/EC 映射；未提交机器序列号，也未借其他型号推断。
- 未下载当前 5.17.49.19/5.17.51.34：与目标旧版本/固件身份尚不匹配，下载不能替代匹配证据。本轮没有创建 oem-static 归档目录。

## 3. 结论、路由纠正与本轮范围

### Takeaway
这次追加补足“官方精确商品入口”和“作者明确承认 dispatcher 未解”的来源证据，仍不能批准 EC TDP。下一步需要精确 OEM 软件包/厂商映射资料或已有正确 Windows 安装的只读静态材料，不应继续泛搜相近机型功率表。

### Cited Findings
- 社区项目 `converged_apply_power_limits()` L688-720 仅在两个后端均 available/can_apply、请求同时含 standard 字段与 AMW0 字段时拆分 PL1/PL2→standard、PL4/TCC→AMW0；L723-742 仍可通过 primary/fallback 整组交 AMW0。先前笔记里的绝对路由句已同步改正。— [固定源码 L665-754](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/src/backends/converged/backend.c#L665)
- 作者硬件验证文档明确 PL1/PL2 的证明来自 turbostat、intel-rapl 与 MSR 一致，并且 PL4 仍未完全通过标准 Intel 遥测证实。这仍然不能证明某个实测结果使用了 EC PL1/PL2 写入。— [硬件证据边界](https://github.com/Semcosm/kuangshi16pro-series-gm6px0x-laptop-control-center/blob/cae0afbaa704d253e29a268cc2d5f7fa4167106b/kuangshi16pro-lcc/docs/hardware-validation.md#L218)

### Inferences
- 后续若取得原始包，先比对 GCUService 哈希、版本、ROM-ID/ProjectID 选择分支、UserFanTables 路径和 AC/DC 条件，再核对 PL4 单位/倍数及模式位。身份不匹配时不调用硬件。
- 搜索授权只用于取证，未授权 BIOS 更新、force 加载、修改 EC 白名单或厂商 daemon 抢写。本轮只有研究笔记变化。

### Gaps
本次查询严格收敛为：
- Semcosm 固定提交 Windows 报告和软件包布局；实际 GitHub Code Search 的包名/hash 两组查询。
- Web 精确词：`ControlCenter_5.17.51.33_Mechrevo`、`ControlCenter_5.17.51.33_Mechrevo.zip site:driver.mechrevo.com`、`GM6PX0X ControlCenter`、`GM6PX0X GCUService`、`旷世16Pro 5.17`、`N.1.09MRO07 控制中心`。
- 官方公开目录：home/download_categories、控制台分类、旷世展示系列，以及唯一精确商品 gxZSDX 的详情/驱动/filter_options；没有继续扩展其他商品或版本，没有二进制下载。
- 官方 `/drivers?q[key]=GM6PX0X`、`q[key]=旷世16Pro`、`q[key]=ControlCenter_5.17.51.33` 均 total=0；由于 key 的公开语义可能偏向用户搜索/序列号，这只能记录查询结果，不能用来证明官方绝无相关包。
