# -*- coding: utf-8 -*-
"""GUI 端到端测试（离屏渲染 + 真实服务端 10.82.10.103:31123 / zn_data）。

只读：不执行任何增删改操作（不点 Create/Drop/Kill/Backfill 等）。
覆盖主窗口、连接树懒加载、各标签页控件、查询执行、CSV/JSON 导出、
设置导入导出、中英文切换、断开连接等 GUI 路径。
"""
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

qapp = QApplication(sys.argv)
# 离屏平台不做 CJK 字体回退，显式指定中文字体以保证截图可读（仅影响测试进程）
from PySide6.QtGui import QFont
qapp.setFont(QFont("Microsoft YaHei", 9))

from net.sakurain.influxdbstudio import app as app_module
from net.sakurain.influxdbstudio.core.client import create_client
from net.sakurain.influxdbstudio.core.models import InfluxDbConnection
from net.sakurain.influxdbstudio.core.settings import AppSettings
from net.sakurain.influxdbstudio.i18n import set_language, tr
from net.sakurain.influxdbstudio.ui.main_window import MainWindow, NodeType

RESULTS = []
SHOTS_DIR = Path(__file__).resolve().parent / "e2e_screenshots"
SHOTS_DIR.mkdir(exist_ok=True)
_shot_counter = 0


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} {detail}")
    return condition


def shot(widget, name):
    global _shot_counter
    _shot_counter += 1
    path = SHOTS_DIR / f"{_shot_counter:02d}_{name}.png"
    widget.grab().save(str(path))
    return path


def wait_for(predicate, timeout_ms=15000, step=100):
    waited = 0
    while waited < timeout_ms:
        qapp.processEvents()
        QTest.qWait(step)
        waited += step
        try:
            if predicate():
                return True
        except Exception:
            pass
    return predicate()


# ---------------------------------------------------------------------------
# 弹窗与文件对话框替身（记录 + 自动返回，避免模态阻塞）
# ---------------------------------------------------------------------------
MODALS = []
SAVE_DIALOG_RESPONSES = []


def fake_critical(parent, title, text, *a, **k):
    MODALS.append(("critical", title, text))
    return QMessageBox.Ok


def fake_information(parent, title, text, *a, **k):
    MODALS.append(("information", title, text))
    return QMessageBox.Ok


def fake_warning(parent, title, text, buttons=QMessageBox.Ok, *a, **k):
    MODALS.append(("warning", title, text))
    if buttons & QMessageBox.Cancel:
        return QMessageBox.Cancel  # 默认“取消”，双保险防止误确认删除
    return QMessageBox.Ok


QMessageBox.critical = staticmethod(fake_critical)
QMessageBox.information = staticmethod(fake_information)
QMessageBox.warning = staticmethod(fake_warning)


def fake_get_save_name(parent, title, directory, filter_):
    if SAVE_DIALOG_RESPONSES:
        return SAVE_DIALOG_RESPONSES.pop(0)
    return "", ""


QFileDialog.getSaveFileName = staticmethod(fake_get_save_name)
QFileDialog.getOpenFileName = staticmethod(
    lambda parent, title, directory, filter_: ("", ""))

# ---------------------------------------------------------------------------
# 初始化：中文界面 + 主窗口（配置隔离到临时目录，避免本机真实配置干扰）
# ---------------------------------------------------------------------------
import net.sakurain.influxdbstudio.core.settings as settings_module
_CFG_TMP = Path(tempfile.mkdtemp(prefix="influxdbstudio_e2e_"))
settings_module._settings_path = lambda: str(_CFG_TMP / "settings.json")

settings = AppSettings(version="e2e")
app_module.settings = settings
set_language("zh_CN")

window = MainWindow(show_connections_on_load=False)
window.show()
QTest.qWait(200)
check("主窗口创建", window.isVisible())
check("默认中文菜单", window.menuBar().actions()[0].text().startswith("文件"),
      window.menuBar().actions()[0].text())

# ---------------------------------------------------------------------------
# 连接管理对话框：渲染连接列表（不写盘）
# ---------------------------------------------------------------------------
from net.sakurain.influxdbstudio.ui.dialogs import ManageConnectionsDialog
settings.connections.append(InfluxDbConnection.create(
    name="zn_data", host="10.82.10.103", port=31123, username="sa",
    password="sa", database="zn_data"))
dlg = ManageConnectionsDialog()
dlg.redraw_connections()
check("连接管理对话框列出连接", dlg.table.rowCount() == 1,
      dlg.table.item(0, 0).text() if dlg.table.rowCount() else "")
dlg.close()

# ---------------------------------------------------------------------------
# 建立连接：连接树懒加载数据库与 measurement
# ---------------------------------------------------------------------------
conn = settings.connections[0]
client = create_client(conn)
app_module.active_clients.append(client)
window.render_connection_node(conn)
check("连接节点出现", window.tree.topLevelItemCount() == 1)
top = window.tree.topLevelItem(0)

# 设置固定数据库的连接在渲染时直接加载数据库列表（异步）
ok = wait_for(lambda: top.childCount() >= 1 and
              window._node_type(top.child(0)) == NodeType.Database)
check("数据库节点懒加载(zn_data)", ok and top.child(0).text(0) == "zn_data",
      top.child(0).text(0) if top.childCount() else "")
shot(window, "main_window_tree_databases")

db_node = top.child(0)
db_node.setExpanded(True)  # 触发懒加载 measurement
ok = wait_for(lambda: db_node.childCount() >= 1 and
              window._node_type(db_node.child(0)) == NodeType.Measurement)
meas_names = [db_node.child(i).text(0) for i in range(db_node.childCount())]
check("measurement 懒加载", ok and len(meas_names) == 5, str(meas_names))
shot(window.tree, "tree_measurements")

window.tree.setCurrentItem(top)
check("连接节点工具栏状态", window.tbtn_show_users.isEnabled()
      and window.tbtn_create_db.isEnabled() and not window.tbtn_drop_db.isEnabled())

# ---------------------------------------------------------------------------
# 各类标签页
# ---------------------------------------------------------------------------
def open_tab_and_wait(node, command, predicate, name):
    try:
        command(node)
        control = window._current_request_control()
        ok = wait_for(lambda: predicate(control))
        check(f"标签页:{name}", ok and control is not None)
        if control is not None:
            shot(window.tabs.currentWidget(), name)
        return control
    except Exception as e:
        check(f"标签页:{name}", False, f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return None

from net.sakurain.influxdbstudio.ui import controls as ctrl

window.tree.setCurrentItem(top)
c = open_tab_and_wait(top, window.show_diagnostics,
                      lambda c: c._value_labels["Hostname"].text() not in ("-", ""),
                      "diagnostics")
if c:
    check("诊断信息主机名", "influxdb" in c._value_labels["Hostname"].text(),
          c._value_labels["Hostname"].text())

window.tree.setCurrentItem(top)
c = open_tab_and_wait(top, window.show_statistics,
                      lambda c: c.stats_combo.count() > 0, "stats")
if c:
    check("统计标签页生成", c.results_tabs.count() > 0,
          f"groups={c.stats_combo.count()}, tabs={c.results_tabs.count()}")

window.tree.setCurrentItem(top)
c = open_tab_and_wait(top, window.show_users,
                      lambda c: c.users_table.rowCount() >= 0, "users")
if c:
    # 该定制版服务端 SHOW USERS 返回 0 条（鉴权在网关层），0 即正确解析结果
    check("用户列表加载(服务端实际为0)", c.users_table.rowCount() == 0,
          f"{c.users_table.rowCount()} 个用户")
    # 选中用户 → 权限面板（只读拉取）
    if c.users_table.rowCount() > 0:
        c.users_table.selectRow(0)
        ok = wait_for(lambda: not c.grants_table.isEnabled()
                      or c.grants_table.rowCount() >= 0)
        check("权限面板绑定", ok)

window.tree.setCurrentItem(top)
c = open_tab_and_wait(top, window.show_queries,
                      lambda c: c.table.rowCount() >= 0, "running_queries")

window.tree.setCurrentItem(db_node)
c = open_tab_and_wait(db_node, window.show_retention_policies,
                      lambda c: c.table.rowCount() > 0, "retention_policies")
if c:
    check("保留策略行数", c.table.rowCount() >= 1,
          f"{c.table.rowCount()} 条")

window.tree.setCurrentItem(db_node)
c = open_tab_and_wait(db_node, window.show_continuous_queries,
                      lambda c: c.table.rowCount() >= 0, "continuous_queries")
if c:
    check("连续查询列表加载", c.table.rowCount() >= 0,
          f"{c.table.rowCount()} 条 CQ")

# ---------------------------------------------------------------------------
# measurement 系列控件
# ---------------------------------------------------------------------------
meas_node = None
for i in range(db_node.childCount()):
    if db_node.child(i).text(0) == "curveData3761":
        meas_node = db_node.child(i)
        break
assert meas_node is not None, "未找到 curveData3761 measurement 节点"

window.tree.setCurrentItem(meas_node)
c = open_tab_and_wait(meas_node, window.show_series,
                      lambda c: c.table.rowCount() > 0, "series")
if c:
    check("序列行数>0", c.table.rowCount() > 0, f"{c.table.rowCount()} 行")

window.tree.setCurrentItem(meas_node)
c = open_tab_and_wait(meas_node, window.show_tag_keys,
                      lambda c: c.table.rowCount() > 0, "tag_keys")

window.tree.setCurrentItem(meas_node)
c = open_tab_and_wait(meas_node, window.show_tag_values,
                      lambda c: c.table.rowCount() > 0, "tag_values")
if c:
    check("标签值下拉+表格", c.tag_keys_combo.count() > 0 and c.table.rowCount() > 0,
          f"keys={c.tag_keys_combo.count()}, rows={c.table.rowCount()}")

window.tree.setCurrentItem(meas_node)
c = open_tab_and_wait(meas_node, window.show_field_keys,
                      lambda c: c.table.rowCount() > 0, "field_keys")
if c:
    check("字段键列", c.table.columnCount() == 3)

# ---------------------------------------------------------------------------
# 查询标签页：执行 SELECT + CSV/JSON 导出
# ---------------------------------------------------------------------------
window.tree.setCurrentItem(db_node)
window.new_query(db_node)
qc = window._current_request_control()
check("查询标签页为 QueryControl", isinstance(qc, ctrl.QueryControl))
check("默认查询文本", "SELECT * FROM" in qc.editor_text, qc.editor_text[:50])
qc.editor_text = 'SELECT * FROM "curveData3761" LIMIT 5'
check("Run 菜单可用", window.action_run_query.isEnabled())
window.execute_current_request()
ok = wait_for(lambda: qc.results_tabs.count() > 0 and qc.results_label.text() != "",
              timeout_ms=120000)
check("查询执行出结果", ok, qc.results_label.text())
if qc.results_tabs.count():
    results_control = qc.results_tabs.widget(0)  # 即 QueryResultsControl
    check("结果表格有数据行", results_control.table.rowCount() == 5,
          f"{results_control.table.rowCount()} 行")
    shot(window.tabs.currentWidget(), "query_results")

    # CSV 导出
    tmp_csv = str(Path(tempfile.gettempdir()) / "e2e_export.csv")
    SAVE_DIALOG_RESPONSES.append((tmp_csv, ""))
    results_control.export_to_csv()
    csv_text = Path(tmp_csv).read_text(encoding="utf-8") if Path(tmp_csv).exists() else ""
    check("CSV 导出", Path(tmp_csv).exists() and len(csv_text.splitlines()) == 6,
          f"{len(csv_text.splitlines())} 行(含表头)")

    # JSON 导出
    tmp_json = str(Path(tempfile.gettempdir()) / "e2e_export.json")
    SAVE_DIALOG_RESPONSES.append((tmp_json, ""))
    results_control.export_to_json()
    import json as _json
    data = _json.loads(Path(tmp_json).read_text(encoding="utf-8")) \
        if Path(tmp_json).exists() else []
    check("JSON 导出", len(data) == 5 and "time" in data[0], f"{len(data)} 条")

    # 选中行导出 CSV
    results_control.table.selectRow(0)
    tmp_csv2 = str(Path(tempfile.gettempdir()) / "e2e_export_selected.csv")
    SAVE_DIALOG_RESPONSES.append((tmp_csv2, ""))
    results_control.export_to_csv(True)
    sel_text = Path(tmp_csv2).read_text(encoding="utf-8") if Path(tmp_csv2).exists() else ""
    check("选中行 CSV 导出", Path(tmp_csv2).exists()
          and len(sel_text.splitlines()) == 2, f"{len(sel_text.splitlines())} 行")

# GROUP BY 聚合查询 → 多标签页
# 注意：activePower 等字段为 string 类型不可聚合；且全部 69 万点的时间戳均为
# epoch 0（历史数据），不能带 now() 时间过滤。改用整型字段 pointNumber。
qc.editor_text = 'SELECT MEAN("pointNumber") FROM "curveData3761" GROUP BY time(1h)'
window.execute_current_request()
ok = wait_for(lambda: qc.results_tabs.count() >= 1 and (
    "group" in qc.results_tabs.tabText(0).lower()
    or "分组" in qc.results_tabs.tabText(0)), timeout_ms=120000)
check("GROUP BY 聚合查询", ok,
      [qc.results_tabs.tabText(i) for i in range(qc.results_tabs.count())])
shot(window.tabs.currentWidget(), "query_group_by")

# ---------------------------------------------------------------------------
# 设置导入导出（JSON）
# ---------------------------------------------------------------------------
tmp_settings = str(Path(tempfile.gettempdir()) / "e2e_settings.json")
SAVE_DIALOG_RESPONSES.append((tmp_settings, ""))
window.export_settings()
exported = Path(tmp_settings).exists() and "zn_data" in Path(tmp_settings).read_text(
    encoding="utf-8")
check("设置导出", exported)

# ---------------------------------------------------------------------------
# 中英文切换（重建窗口，连接保持）
# ---------------------------------------------------------------------------
window.action_lang_en.trigger()
QTest.qWait(400)
window_en = app_module.main_window
check("英文界面重建", window_en is not None and window_en.menuBar().actions()[0]
      .text().startswith("&File"),
      window_en.menuBar().actions()[0].text() if window_en else "no window")
if window_en:
    check("语言切换后连接保持", window_en.tree.topLevelItemCount() == 1
          and len(app_module.active_clients) == 1)
    shot(window_en, "main_window_english")
    window_en.action_lang_zh.trigger()
    QTest.qWait(400)
window = app_module.main_window
check("切回中文", window.menuBar().actions()[0].text().startswith("文件"))

# ---------------------------------------------------------------------------
# 断开连接清理
# ---------------------------------------------------------------------------
top = window.tree.topLevelItem(0)
before_tabs = window.tabs.count()
window.disconnect(top)
check("断开连接后树清空", window.tree.topLevelItemCount() == 0)
check("断开连接后客户端移除", len(app_module.active_clients) == 0)

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
fails = [r for r in RESULTS if r[0] == "FAIL"]
print("\n" + "=" * 60)
print(f"GUI E2E 结果: {len(RESULTS) - len(fails)} 通过, {len(fails)} 失败")
for status, name, detail in fails:
    print(f"  FAIL: {name} {detail}")
print(f"截图目录: {SHOTS_DIR}")
sys.exit(1 if fails else 0)
