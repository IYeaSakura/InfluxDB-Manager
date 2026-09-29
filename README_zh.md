# InfluxDB Manager

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/PySide6-6.5+-41CD52?logo=qt)](https://doc.qt.io/qtforpython/)
[![InfluxDB](https://img.shields.io/badge/InfluxDB-1.x-22ADF6?logo=influxdb)](https://docs.influxdata.com/influxdb/v1/)
[![httpx](https://img.shields.io/badge/httpx-0.24+-370617?logo=python)](https://www.python-httpx.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-0078D6?logo=windows)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

InfluxDB（1.x 时序数据库）的桌面 UI 管理工具 —— **参考**原 [CymaticLabs/InfluxDBStudio](https://github.com/CymaticLabs/InfluxDBStudio)（C#/WinForms），使用 **Python/PySide6 重构**，并新增了更多功能：类 DBeaver 的结果网格编辑、数据分页、整行删除、查询脚本持久化，以及**中英双语界面（默认中文）**。

**作者**：Yuyang.Wang | **仓库**：[IYeaSakura/InfluxDB-Manager](https://github.com/IYeaSakura/InfluxDB-Manager)

[功能特性](#功能特性) | [技术栈](#技术栈) | [项目结构](#项目结构) | [快速开始](#快速开始) | [使用指南](#使用指南) | [开发指南](#开发指南) | [构建与部署](#构建与部署) | [核心设计](#核心设计) | [测试](#测试) | [常见问题](#常见问题) | [参与贡献](#参与贡献) | [许可证](#许可证)

---

## 功能特性

以下核心功能参考原项目设计，使用 Python 重新实现：

### 连接管理

- 创建、编辑、删除、克隆 InfluxDB 连接（主机、端口、凭据、数据库、SSL）
- **只读连接**：连接属性勾选「只读」后禁止编辑、删除行、写入数据点，相关右键菜单项自动禁用
- 保存前 Test / Ping 测试连接
- 应用级"允许不可信 SSL 证书"开关
- 连接树浏览：连接 -> 数据库 -> measurement，按需懒加载
- 多连接并发，每个连接独立的客户端实例

### 查询窗口

- 等宽 SQL 编辑器，语法高亮（关键字、字符串、数字、注释）
- **Ctrl+Enter** 运行（主键盘与小键盘回车均已绑定）；查询在工作线程执行，GUI 不卡死，状态栏显示运行中与响应时间
- GROUP BY 查询结果自动拆分为多个标签页
- **Ctrl+/** 对当前行或选中行切换注释；注释行灰色渲染；以 `--` 注释开头的脚本仍可正常分页与统计
- 查询脚本标签页：右键标签可重命名；所有打开的脚本（名称、连接、数据库、内容、活动页）**自动持久化，下次启动自动恢复**
- **查询历史**：每次执行成功的查询自动记录（去重置顶，上限 200 条，持久化于 settings.json）；编辑栏「查询历史」按钮打开浏览窗口，双击即可回填到编辑器，支持单条删除与清空

### 结果网格（类 DBeaver）

- **数据分页**：普通 SELECT 自动注入 `LIMIT/OFFSET`；每页条数支持下拉预设（100/500/1000/5000/10000）或手动输入（1–1,000,000）；通过只读 `COUNT(*)` 获取总行数；首页/上一页/下一页/末页导航
- **单元格覆写**：双击字段列单元格即可编辑；InfluxDB 无 UPDATE，保存时以相同 measurement + tags + 时间戳重写数据点（纳秒精度不丢失）；字符串类型字段保持字符串，避免字段类型冲突；脏单元格黄色高亮
- **整行/多行删除**：选中行后按 **Delete**（或右键菜单）暂存（红色高亮）；保存时为每行生成精确的 `DELETE FROM "m" WHERE time = '...ns 精度 RFC3339...' AND "tag" = '...'` 语句；回滚可完整撤销
- **二次确认保存**：确认框逐条列出覆写与删除明细，确认后才写入数据库；保存成功提示覆写/删除行数
- **可见的保存/回滚按钮条**：结果区上方常显，有修改时才启用；右键菜单与 Ctrl+S 同样可用
- **表头右键菜单**：复制字段名 / 复制全部字段名、升/降序排列当前页（数字感知排序，脏状态自动禁用）、**过滤此列**（见下）、time 列专属**按时间降序（重查）**（注入 `ORDER BY time DESC` 重新查询，再次点击取消）、列宽适合值、隐藏此列 / 显示全部列、刷新、导出
- **列级过滤（服务端）**：过滤对话框支持 `=` / `!=` / `>` / `>=` / `<` / `<=` / `=~` / `!~`；条件注入查询 WHERE 子句后服务端重查——生效的过滤以 chip 条显示在表格上方，点击 chip 移除单个条件，「清除全部」一键清空；分页与 `COUNT(*)` 总数始终带过滤条件（数值型 field 不加引号，tag / 字符串 / 前导零值强制加引号，`time` 列支持 `now() - 1h` 裸表达式）；切换查询文本自动清除过滤
- **Calc 统计面板**：选中数值单元格时，表格下方显示 计数 / 平均 / 合计 / 最小 / 最大
- **表格区右键菜单**：复制/粘贴、保存/回滚修改、删除选中行，选中行后出现「导出选中行」
- 选中单元格/行蓝色高亮；复制粘贴与系统剪贴板互通（TSV 格式）
- **结果导出**：支持 CSV / XLSX / XML / Markdown / JSON / HTML 六种格式；CSV 允许自定义分隔符（默认 `,`），以 UTF-8 带 BOM 写入，Excel 直接打开无乱码
- **导出全部**：在后台重新执行原始查询（不带分页 LIMIT），导出**完整查询结果**而非当前页数据；导出期间 GUI 不卡死（等待光标提示）
- **导出选中行**：仅导出所选行，从表格区右键菜单进入
- **导出位置记忆**：自动记住上次导出目录，跨启动生效
- **编辑器字体缩放**：Ctrl+= 放大、Ctrl+- 缩小、Ctrl+0 复位

### 数据库管理

- 创建 / 删除数据库
- 保留策略（Retention Policy）：查看、创建、修改、删除，含默认策略回退逻辑（与 C# 版一致）
- 连续查询（Continuous Query）：查看、创建（支持 RESAMPLE EVERY/FOR 高级语法）、删除、回填
- 回填查询（Backfill）：可视化构建并运行
- 运行中查询：`SHOW QUERIES` 浏览与 `KILL QUERY` 终止（兼容 C# 版的 "query interrupted" 错误吞没处理）
- **写入数据点**：数据库 / measurement 右键「写入数据点…」，表单录入 measurement、tags、fields、time、保留策略，行协议预览 + 二次确认后写入
- **SHOW SHARDS / SHOW SUBSCRIPTIONS**：连接右键直接浏览分片与订阅（只读）

### Measurement 探索

- Series、Tag Keys、Tag Values、Field Keys 浏览
- 探索结果导出 CSV / JSON

### 用户与权限

- 用户列表、创建、重命名、修改密码、删除
- 数据库权限授予 / 撤销（ALL、READ、WRITE），编辑与撤销已有权限

### 服务器信息

- 服务器 Diagnostics（`SHOW DIAGNOSTICS`）浏览
- 服务器 Statistics（`SHOW STATS`）浏览，人类可读格式化

### 应用设置

- 12/24 小时制时间格式与日期格式（月/日年 或 日/月年）
- 语言切换：**中文（默认）/ 英文**，实时生效
- 设置导入 / 导出（JSON 格式与 C# 版兼容，可互相导入）
- 设置通过 `platformdirs` 存储于用户目录（无需管理员权限）

---

## 技术栈

### 核心技术

| 类别 | 技术 | 版本 |
|------|------|------|
| 语言 | Python | >= 3.9 |
| GUI 框架 | PySide6（Qt for Python） | >= 6.5 |
| HTTP 客户端 | httpx | >= 0.24 |
| 配置目录 | platformdirs | >= 3.0 |
| 测试框架 | pytest | >= 7.0 |
| 打包工具 | PyInstaller | >= 6.0 |

### 设计说明

- 采用 **Qt Widgets**（非 QML），原生桌面体验，忠实还原 WinForms 布局
- 所有网络 I/O 通过 **QThread + 信号/槽** 工作线程模式执行，UI 线程永不阻塞
- **QSyntaxHighlighter** 实现 SQL 高亮；编辑器核心为 `QPlainTextEdit`
- InfluxDB HTTP API 客户端基于**纯标准库 + httpx**（query/write/ping），不依赖 InfluxDB Python 驱动

---

## 项目结构

```
InfluxDBStudio/
├── main.py                                    # 根入口：`python main.py`
├── sakurain.ico                               # 应用 / 任务栏图标
├── pyproject.toml                             # 打包元数据（setuptools）
├── LICENSE                                    # MIT（CymaticLabs 原版）
├── README.md                                  # 英文 README
├── README_zh.md                               # 本文件（中文）
├── src/
│   └── net/sakurain/influxdbstudio/           # 统一包名：net.sakurain.*
│       ├── __init__.py                        # __version__
│       ├── __main__.py                        # `python -m` 入口，应用/图标初始化
│       ├── app.py                             # 全局：settings、active clients、主窗口
│       ├── i18n.py                            # zh_CN / en_US 翻译表 + tr()
│       ├── core/                              # 后端，无 Qt 依赖（异步胶水除外）
│       │   ├── client.py                      # InfluxDbClient：HTTP query/write/ping/drop/kill
│       │   ├── models.py                      # Connection/Series/Point/RP/CQ 模型
│       │   ├── query_tools.py                 # 分页、COUNT、覆写点、DELETE 生成
│       │   ├── settings.py                    # AppSettings：JSON 持久化（C# 兼容）
│       │   ├── async_utils.py                 # run_async 工作线程辅助
│       │   └── helper.py                      # 格式化 / 校验辅助
│       ├── ui/
│       │   ├── main_window.py                 # 主窗口：菜单、工具栏、树、标签页
│       │   ├── controls.py                    # 全部数据控件（查询、网格、RP、CQ……）
│       │   ├── dialogs.py                     # 连接管理、关于、创建数据库、回填
│       │   └── common.py                      # SQL 编辑器 + 高亮、图标、错误框
│       └── resources/
│           ├── sakurain.ico                   # 应用图标（打包副本）
│           └── icons/                         # 41 个工具栏/树形 PNG 图标
├── tests/
│   ├── test_core.py                           # 单元测试：模型、语句、设置
│   ├── test_query_tools.py                    # 单元测试：分页、覆写、DELETE
│   ├── e2e_gui.py                             # GUI 端到端套件（离屏，FakeClient）
│   ├── e2e_dbeaver.py                         # 类 DBeaver 功能套件（part1 真实 / part2 模拟）
│   ├── e2e_readonly.py                        # 真实服务端只读校验
│   └── shot_feature_ui.py                     # 真实平台截图生成
└── .venv/                                     # 项目虚拟环境（已 gitignore）
```

---

## 快速开始

### 环境要求

- **Python**：3.9 或以上（推荐 3.12）
- **InfluxDB**：1.x 服务端（推荐 1.7+），HTTP 可达
- **操作系统**：Windows 10/11（主要平台），Linux 与 macOS 亦可（离屏 CI 已验证）

### 安装

```bash
# 克隆仓库
git clone https://github.com/IYeaSakura/InfluxDB-Manager.git
cd InfluxDBStudio

# 在项目根目录创建并激活虚拟环境
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS

# 以可编辑模式安装
python -m pip install -e .
```

### 运行

```bash
# 方式 1：项目根入口（无需安装即可运行）
python main.py

# 方式 2：安装后的控制台命令
influxdb-manager

# 方式 3：模块方式运行
python -m net.sakurain.influxdbstudio
```

首次启动（无已保存连接时）会自动弹出连接管理对话框；创建连接（如 `localhost:8086`，填入 InfluxDB 用户名/密码）并测试。已有保存连接时，启动直接把连接渲染进连接树，不再弹出对话框。

### 连接参数

应用将连接保存在用户级设置文件中（无需 `.env`）：

| 字段 | 说明 | 示例 |
|------|------|------|
| Name | 树中显示名称 | `prod-cluster` |
| Host | InfluxDB HTTP 主机 | `10.82.10.103` |
| Port | InfluxDB HTTP 端口 | `31123` |
| Username / Password | HTTP 认证 | `sa` / `sa` |
| Database | 默认数据库（可选） | `zn_data` |
| Use SSL | HTTPS 传输 | 关 |

---

## 使用指南

### 执行查询

1. 在树中选中数据库（或 measurement），点击工具栏**新建查询**或菜单项。
2. 输入 InfluxQL，例如 `SELECT * FROM "curveData3761"`。
3. 按 **Ctrl+Enter**。查询在后台执行；状态栏显示进度，结果网格带分页控件。

### 编辑并保存结果

1. 等待网格加载字段元数据完成（仅真正的字段列可编辑；标签、时间与序号列只读）。
2. 双击单元格，输入新值，回车。单元格变黄。
3. 删除整行：选中行后按 **Delete**（行变红）。
4. 点击**保存修改（N 行）**（或 Ctrl+S / 右键菜单）。在确认框中核对每条覆写与删除明细后确认。
5. 放弃全部修改：点击**回滚修改**。

### 大数据量分页浏览

- 在分页栏设置每页条数（选择预设或直接输入，如 `37`）。
- 使用 `|<`、`<`、`>`、`>|` 翻页；标签显示 `第 start–end 行 / 共 total 行`。
- 通过表头右键菜单按任意列对当前页升/降序排列。

### 服务端过滤与重排序

- 右键列头选择**过滤此列…**添加 WHERE 条件，查询将在服务端重查，条件以 chip 条显示在表格上方。点击 chip 移除单个条件，**清除全部**一次清空。行总数会按过滤条件重新统计。
- 右键 `time` 列头选择**按时间降序（重查）**注入 `ORDER BY time DESC`；再次选择即可取消。
- 选中数值单元格后，表格下方的 Calc 面板显示 计数 / 平均 / 合计 / 最小 / 最大。

### 复用查询

- 编辑栏的**查询历史**按钮列出当前连接执行过的所有查询（最新在前，跨启动持久化）。双击任一条目回填到编辑器，也可删除不需要的记录。

### 查询脚本持久化

- 按需打开多个查询标签页，每个标签自动获得唯一脚本名。
- 右键标签选择**重命名**，改成有意义的名称。
- 脚本自动保存（关闭标签与退出应用时），下次启动自动恢复（包括活动标签页）。

### 导出结果

- 点击网格工具栏的**导出全部**（或表头右键菜单）：在后台重新执行原始查询（不带分页 LIMIT），导出**完整查询结果**而非当前页；即使数据量巨大也不会卡死界面。
- 右键选中行选择**导出选中行**，仅导出所选内容。
- 支持 CSV / XLSX / XML / Markdown / JSON / HTML 六种格式；CSV 可自定义分隔符（默认 `,`）。
- 自动记住上次导出目录，下次导出直接定位。

---

## 开发指南

### 运行测试

```bash
# 单元测试（快速，无需服务端）
.venv\Scripts\python -m pytest tests/ -q --ignore=tests/e2e_gui.py --ignore=tests/e2e_readonly.py

# 完整 GUI 回归（离屏平台，FakeClient —— 不触碰真实服务端）
set QT_QPA_PLATFORM=offscreen          # Windows
.venv\Scripts\python tests/e2e_gui.py

# 类 DBeaver 功能套件（part2 使用 FakeClient；part1 对真实服务端只读）
.venv\Scripts\python tests/e2e_dbeaver.py --part2
.venv\Scripts\python tests/e2e_dbeaver.py --part1
```

### 常用命令

| 命令 | 说明 |
|------|------|
| `python main.py` | 从源码树启动应用 |
| `pytest tests/ -q` | 运行单元测试套件 |
| `python tests/e2e_gui.py` | 运行 40 项 GUI 回归 |
| `python tests/e2e_dbeaver.py --part1/--part2` | 运行类 DBeaver 功能套件 |
| `python tests/shot_feature_ui.py` | 生成真实平台功能截图 |

### 代码风格

- **命名**：函数/变量用 `snake_case`，类用 `PascalCase`，常量用 `SCREAMING_SNAKE_CASE`；与 C# 模型对应的公共类属性保持 PascalCase（如 `series.Values`），保证移植一致性
- **移植对齐**：行为与 InfluxQL 语句与 C# 客户端逐字节兼容，除非明确标记为增强功能
- **国际化**：所有面向用户的字符串必须经过 `tr("key", **kwargs)`；新增词条必须同时加入 `i18n.py` 的 `zh_CN` 与 `en_US` 两张表
- **线程**：网络访问只允许在 `run_async(work, done, failed)` 工作线程中；禁止阻塞 GUI 线程
- **安全**：破坏性操作（删除、覆写保存）必须弹出显式确认框

### 版本管理

- 当前版本：`1.1.0`（`net.sakurain.influxdbstudio.__version__`）
- 设置文件带 `Version` 字段；迁移逻辑应加入 `AppSettings.load_all`

---

## 构建与部署

### 构建 Windows 可执行文件

构建使用仓库内置的 PyInstaller spec（`InfluxDBManager.spec`），裁剪掉用不到的 Qt 模块（Qml/Quick/Pdf/OpenGL/3D 等）与插件，打包体积从约 120 MB 二进制精简到约 30 MB 的单文件 exe。

```bash
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\python -m PyInstaller InfluxDBManager.spec --distpath dist_slim --workpath build_slim --clean -y
```

注意：开发所用的托管 Python 运行时将 OpenSSL DLL 放在标准库目录之外，spec 已通过 `--add-binary` 显式打包 `libssl-3-x64.dll` / `libcrypto-3-x64.dll`。若使用 python.org 官方解释器构建，可从 spec 中删去这两行。

产物：`dist_slim/InfluxDBManager.exe`（单文件、无控制台窗口、sakurain 图标、内嵌版本信息 `1.1.0.0`）。窗口与 Windows 任务栏均显示 sakurain 图标（启动时显式设置 `AppUserModelID`，任务栏分组图标正确）。

### 构建 Windows 安装包

安装包使用 [Inno Setup](https://jrsoftware.org/isdl.php) 7.x 编译 `installer/setup.iss`（LZMA2/ultra64 固实压缩、安装界面中英双语、可选桌面图标）：

```bash
"path\to\ISCC.exe" installer\setup.iss
```

产物：`dist/InfluxDBManager-Setup-1.1.0.exe`（约 31 MB）。

### 构建阶段

| 阶段 | 说明 |
|------|------|
| 1. 收集 | 打包 PySide6 Qt 库（裁剪至 Core/Gui/Widgets）与资源 |
| 2. 分析 | 从 `net.sakurain.influxdbstudio.__main__` 追踪导入 |
| 3. 打包 | 先产出单文件 `InfluxDBManager.exe`，再编译 Inno Setup 安装包 |

### 首次运行说明

- 设置存储于用户配置目录（`platformdirs`），例如 Windows 下 `%APPDATA%\InfluxDBStudio\settings.json`；可执行文件无需写自身目录
- 配置目录键名有意保持与旧版本一致，升级后已有连接不丢失
- 树懒加载失败（服务端宕机、网络错误、超时）时，加载占位会被红色内联错误节点替换 —— 双击即可重试；不会出现模态错误弹窗

---

## 核心设计

### 以覆写代替更新

InfluxDB 1.x 没有 `UPDATE`，单元格修改通过重写整个数据点保存：

1. 原始行提供 measurement、标签与精确的纳秒时间戳。
2. 被编辑字段按 `SHOW FIELD KEYS` 报告的类型强制转换（字符串保持字符串，整数的行协议带 `i` 后缀）。
3. 数据点通过 `/write` API 写入；相同的 measurement + 标签 + 时间戳会替换已存储的点。

时间始终以原始纳秒贯穿全链路（`timestamp_to_ns` / `ns_to_rfc3339`），UI 往返不会破坏亚秒精度。

### 精确整行删除

被删除的行每行生成一条语句：

```sql
DELETE FROM "curveData3761"
WHERE time = '2026-09-27T16:00:00.000000001Z' AND "nmunicateAddr" = '042760236'
```

附加标签等值条件，确保只删除目标点而非同一时间戳的所有点。标签值内的单引号转义为 `\'`，与 C# 客户端一致。

### 分页注入

```
普通 SELECT（无 LIMIT/OFFSET/GROUP BY/INTO）  ->  追加 LIMIT n OFFSET m
总行数统计                                     ->  SELECT COUNT(*) FROM ... [WHERE ...]
```

判断可否分页前先剥离整行 `--` 注释，因此带注释头的脚本不会失去分页能力。自带 `LIMIT` 或 `GROUP BY` 的查询原样发送。

### 并发模型

```
GUI 线程  --信号/槽-->  run_async  -->  工作线程（httpx I/O）
GUI 线程  <--队列信号--  done(result) / failed(exception)
```

所有控件继承 `RequestControl`，封装 `run_async` 并把结果封送回 GUI 线程。长查询期间界面保持响应，状态栏显示进度。

---

## 测试

### 覆盖概览

| 套件 | 用例数 | 需要服务端 | 验证内容 |
|------|--------|-----------|----------|
| `test_core.py` + `test_query_tools.py` | 90 | 否 | 语句、行协议、设置往返、分页、DELETE 生成、注释剥离、过滤/排序注入、查询历史、只读连接 |
| `e2e_gui.py` | 40 | 否（FakeClient） | 完整 GUI 回归：树、对话框、控件、导出 |
| `e2e_dbeaver.py --part2` | 124 | 否（FakeClient） | 编辑、脏标记、整行删除、确认框、分页输入、表头菜单、排序、注释、按钮条、列过滤、时间排序、Calc 面板、查询历史、写入对话框、分片浏览 |
| `e2e_dbeaver.py --part1` | 7 | 是（只读） | 真实服务端分页、LIMIT/OFFSET 注入、COUNT 总数 |
| `e2e_readonly.py` | - | 是（只读） | 类生产服务端的只读保证 |

### 生产测试的安全保证

- 写入路径（`write`、`execute_command`）仅通过记录型 `FakeClient` 验证；测试套件绝不向真实服务端发送写入或删除
- 只读套件断言仅发出 `SELECT`/`SHOW` 语句
- 截图生成在真实平台使用 FakeClient 渲染以保证字体准确；不访问生产数据

---

## 常见问题

### 应用无法启动

**问题**：`ModuleNotFoundError: No module named 'PySide6'`

**解决**：

```bash
.venv\Scripts\python -m pip install -e .
```

请确认使用项目根目录 `.venv` 中的解释器运行 `python main.py`。

### 连接测试失败

**问题**：Ping 报错或超时。

**解决**：
- 确认 InfluxDB HTTP 端口可达：`curl http://<host>:<port>/ping`
- 检查用户名/密码；非管理员用户需要服务端启用认证
- SSL 自签名证书请在设置中开启**允许不可信 SSL**
- 确认数据库存在：在连接级别查询窗口执行 `SHOW DATABASES`

### 查询结果长时间为空

**问题**：大 measurement 上网格长时间无数据。

**解决**：深层 `OFFSET` 扫描在高负载 InfluxDB 上很慢。减小每页条数（如 100），避免在数百万行的 measurement 上直接跳末页；后台 `COUNT(*)` 完成后仍会显示总行数。等待期间窗口保持响应 —— 注意状态栏的运行指示。

### 字段编辑被拒 / 保存报类型冲突

**问题**：编辑单元格保存时服务端返回字段类型冲突。

**解决**：网格按 `SHOW FIELD KEYS` 报告的类型保留数值（例如字符串字段保持字符串）。若服务端类型在元数据加载后发生变化，重新执行查询刷新元数据后再编辑。

### Windows 任务栏图标错误

**问题**：任务栏把应用归入通用 Python 图标。

**解决**：应用启动时已设置显式 `AppUserModelID`（`net.sakurain.InfluxDBManager`）。若通过自定义包装脚本启动，请在包装器中设置相同 ID，或直接启动 PyInstaller 生成的 `InfluxDBManager.exe`。

---

## 参与贡献

欢迎贡献。请遵循以下流程：

1. Fork 本仓库
2. 创建功能分支：`git checkout -b feature/your-feature`
3. 按上述代码风格进行修改
4. 运行完整测试套件：`pytest tests/ -q` 及 GUI 套件
5. 提交：`git commit -m 'feat: add new feature'`
6. 推送：`git push origin feature/your-feature`
7. 发起 Pull Request

### 代码质量检查单

提交 PR 前请确认：

- [ ] 单元测试全部通过（`pytest tests/ -q`）
- [ ] GUI 回归通过（`e2e_gui.py`、`e2e_dbeaver.py --part2`）
- [ ] 新增用户可见字符串已同时加入 `i18n.py` 两种语言表
- [ ] 破坏性操作仍需确认框
- [ ] GUI 线程无网络 I/O
- [ ] 行为变更已同步更新 README（中英文）

---

## 更新日志

见 [CHANGELOG](CHANGELOG.md)。1.0.0 相对原版 C# 的主要新增：

- 类 DBeaver 结果网格：分页、单元格覆写、整行删除、二次确认保存、表头右键菜单
- 查询脚本标签页：重命名与跨启动自动恢复
- Ctrl+/ 行注释与灰色渲染
- 蓝色选中样式、常显保存/回滚按钮条
- 中英双语界面（默认中文）
- 更名为 **InfluxDB Manager** 并采用 sakurain 应用图标

---

## 许可证

本项目基于 MIT 许可证发布。详见 [LICENSE](LICENSE) 文件。

```
MIT License

Copyright (c) 2016 CymaticLabs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 致谢

本项目的构建离不开以下开源项目：

- [CymaticLabs/InfluxDBStudio](https://github.com/CymaticLabs/InfluxDBStudio) - 原版 C#/WinForms 应用（MIT）
- [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/) - 桌面 GUI 框架
- [httpx](https://www.python-httpx.org/) - 面向 InfluxDB API 的现代 HTTP 客户端
- [platformdirs](https://platformdirs.readthedocs.io/) - 用户级配置目录
- [pytest](https://pytest.org/) - 测试框架
- [InfluxDB 1.x](https://docs.influxdata.com/influxdb/v1/) - 本工具所管理的时序数据库

---

## 联系方式

- **作者**：Yuyang.Wang
- **网站**：[https://sakurain.net](https://sakurain.net)
- **邮箱**：[Yae_SakuRain@outlook.com](mailto:Yae_SakuRain@outlook.com)
- **GitHub**：[https://github.com/IYeaSakura](https://github.com/IYeaSakura)
- **仓库**：[https://github.com/IYeaSakura/InfluxDB-Manager](https://github.com/IYeaSakura/InfluxDB-Manager)

---

<p align="center">
  Made by Yuyang.Wang
</p>
