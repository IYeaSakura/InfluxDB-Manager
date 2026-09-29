# Changelog

## 1.1.0 — 2026-09-29

向后兼容的功能版本。

### 新增

- 结果导出：结果网格支持导出 CSV / XLSX / XML / Markdown / JSON / HTML 六种格式（CSV 支持自定义分隔符，默认 `,`，UTF-8 BOM 兼容 Excel）
- 导出全部：在后台重新执行原始查询（不带分页 LIMIT），导出**完整查询结果**而非当前页数据；执行期间 GUI 不卡死（等待光标提示）
- 导出选中行：表格右键菜单仅在选中行时出现，导出所选行
- 导出位置记忆：自动记住上次导出目录，下次导出直接定位到该目录（持久化于 settings.json）
- SQL 编辑器字体缩放：Ctrl+= 放大、Ctrl+- 缩小、Ctrl+0 复位

## 1.0.0 — 2026-09-28

InfluxDB Manager 首个正式版本。参考原项目 InfluxDB Studio（CymaticLabs，MIT），使用 Python/PySide6 完全重构，并新增大量功能。

### 新增（相对原 C# 版本）

- DBeaver 风格结果网格：单元格覆写编辑（覆写点语义，二次保存确认）、整行/多行删除、蓝色选中样式、复制字段名、表头右键菜单（排序/复制/导出等）、数据分页（每页可配，后台 COUNT 总数）
- 查询体验：Ctrl+Enter 运行、Ctrl+/ 注释整行（注释行变灰）、异步查询不卡 UI（状态栏进度提示）
- 查询脚本页：保存、重命名、重启后自动恢复上次打开的查询页
- 界面：中/英双语（默认中文）、关于对话框、连接失败优雅处理（树内红色错误节点，双击重试，无模态框转圈）、启动时已有连接直接渲染树
- 品牌：应用更名为 InfluxDB Manager，sakurain 图标（窗口 + 任务栏，AppUserModelID `net.sakurain.InfluxDBManager`）

### 继承（自原项目，Python 重写）

- 连接管理（增删改/克隆/测试连接）、数据库树懒加载
- 保留策略、连续查询、用户与权限管理
- Show Queries / Stats / Diagnostics / Series / Tag & Field Keys
- 回填（Backfill）构造器
- 设置导入导出（与原 C# 版 JSON 格式互通）

### 技术

- Python 3.9+，PySide6，httpx，platformdirs
- 包名统一为 `net.sakurain.*`，入口 `main.py` / `python -m net.sakurain.influxdbstudio`
- 测试：57 项单元测试 + 82 项 e2e（FakeClient 写入隔离，生产库零写入）
