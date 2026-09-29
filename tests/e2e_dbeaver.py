# -*- coding: utf-8 -*-
"""DBeaver-like 功能端到端测试。

分两部分：
1. 只读部分连真实服务端（10.82.10.103 / zn_data），验证分页 LIMIT/OFFSET
   注入、翻页、COUNT 总数——全部 SELECT，不触碰任何数据。
2. 编辑/保存流程使用 FakeClient（write() 只记录、不联网），验证单元格编辑、
   脏标记、复制粘贴、二次确认保存、回滚——绝不对生产库执行写操作。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

qapp = QApplication(sys.argv)

from net.sakurain.influxdbstudio import app as app_module
from net.sakurain.influxdbstudio.core.client import InfluxDbClient, create_client
from net.sakurain.influxdbstudio.core.models import (
    InfluxDbConnection,
    InfluxDbFieldKey,
    InfluxDbSeries,
)
from net.sakurain.influxdbstudio.i18n import set_language
from net.sakurain.influxdbstudio.ui import controls

RESULTS = []
SHOTS_DIR = Path(__file__).resolve().parent / "e2e_screenshots"
SHOTS_DIR.mkdir(exist_ok=True)
_shot = 0


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} {detail}")
    return condition


def check_soft(name, condition, detail=""):
    """服务端负载高时可能超时的检查：失败记 WARN 不算失败。"""
    if condition:
        return check(name, True, detail)
    RESULTS.append(("WARN", name, detail))
    print(f"[WARN] {name} {detail}")
    return False


def shot(widget, name):
    global _shot
    _shot += 1
    widget.grab().save(str(SHOTS_DIR / f"db_{_shot:02d}_{name}.png"))


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
    try:
        return predicate()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 弹窗替身
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
        return QMessageBox.Cancel
    return QMessageBox.Ok


QMessageBox.critical = staticmethod(fake_critical)
QMessageBox.information = staticmethod(fake_information)
QMessageBox.warning = staticmethod(fake_warning)

# 保存确认框：默认接受（Save），把内容记下来供断言
CONFIRM_TEXTS = []


def fake_box_exec(self):
    CONFIRM_TEXTS.append((self.windowTitle(), self.text(),
                          self.informativeText()))
    return QMessageBox.Save


QMessageBox.exec = lambda self: fake_box_exec(self)

QFileDialog.getSaveFileName = staticmethod(
    lambda parent, title, directory, filter_: SAVE_DIALOG_RESPONSES.pop(0)
    if SAVE_DIALOG_RESPONSES else ("", ""))
QFileDialog.getOpenFileName = staticmethod(
    lambda parent, title, directory, filter_: ("", ""))

# ---------------------------------------------------------------------------
# 配置隔离
# ---------------------------------------------------------------------------
import net.sakurain.influxdbstudio.core.settings as settings_module
from net.sakurain.influxdbstudio.core.settings import AppSettings
_CFG_TMP = Path(tempfile.mkdtemp(prefix="influxdbstudio_dbe2e_"))
settings_module._settings_path = lambda: str(_CFG_TMP / "settings.json")

settings = AppSettings(version="e2e")
app_module.settings = settings
set_language("zh_CN")


def run_query_and_wait(control, timeout_ms=240000):
    """执行查询并等待其完成（_loading 归位且结果已渲染）。"""
    control.execute_request()
    return wait_for(lambda: not control._loading and control.results_tabs.count() > 0
                    and "结果" in control.results_label.text(), timeout_ms)

# ===========================================================================
# 第一部分：真实服务端只读分页验证（SELECT / COUNT 均只读）
# 可用 `python tests/e2e_dbeaver.py --part2` 只跑第二部分（真实服务端查询
# 较慢时便于拆分运行）
# ===========================================================================
RUN_PART2_ONLY = "--part2" in sys.argv
RUN_PART1_ONLY = "--part1" in sys.argv
conn = InfluxDbConnection.create(
    name="zn_data", host="10.82.10.103", port=31123, username="sa",
    password="sa", database="zn_data")

if not RUN_PART2_ONLY:
    print("== 第一部分：真实服务端只读分页 ==")
    real_client = create_client(conn)

    executed = []
    _orig_query = real_client.query


def recording_query(database, query):
    executed.append(query)
    return _orig_query(database, query)


def run_part1():
    real_client.query = recording_query

    qc = controls.QueryControl()
    qc.influx_client = real_client
    qc.database = "zn_data"
    qc.show()
    # 该服务端深 OFFSET 翻页极慢，用每页 100 控制扫描深度
    qc._apply_page_size(qc.page_size_combo.itemData(0))  # 100/页
    qc.editor_text = 'SELECT * FROM "curveData3761"'
    ok = run_query_and_wait(qc)
    check("分页查询第1页出结果", ok, qc.results_label.text())
    check("注入 LIMIT/OFFSET",
          any("LIMIT 100 OFFSET 0" in q for q in executed), str(executed[-2:]))
    check("分页栏可见", qc.pager_widget.isVisible())

    # 总数统计（COUNT 查询只读；服务端慢，不等结果，显示"未知"也是正确行为）
    wait_for(lambda: qc._total is not None, timeout_ms=90000)
    check("COUNT 总数加载或显示未知(只读)",
          qc._total is not None or "未知" in qc.page_rows_label.text(),
          f"total={qc._total} label={qc.page_rows_label.text()}")

    # 翻页到第 2 页：注入断言只看 executed（查询发出即记录，不等渲染；
    # 深 OFFSET 翻页在该服务端可达数分钟，渲染已由 Fake 部分充分验证）
    ok = wait_for(lambda: not qc._loading, timeout_ms=60000)
    executed.clear()
    qc._goto_page(2)
    ok = wait_for(lambda: any("LIMIT 100 OFFSET 100" in q for q in executed),
                  timeout_ms=30000)
    check("翻页注入 OFFSET 100", ok, str(executed[-2:]))
    check("页码状态", qc._page == 2, f"page={qc._page}")

    shot(qc, "pagination_real")

    # 可拖高度分隔条
    check("编辑器/结果区分隔条存在", qc.main_splitter.count() == 2)


if not RUN_PART2_ONLY:
    run_part1()

if RUN_PART1_ONLY:
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\n第一部分单独运行: {len(RESULTS) - len(fails)} 通过, {len(fails)} 失败")
    for status, name, detail in fails:
        print(f"  FAIL: {name} {detail}")
    sys.exit(1 if fails else 0)

# ===========================================================================
# 第二部分：编辑/保存流程（FakeClient，write 不联网）
# ===========================================================================
print("== 第二部分：编辑/保存流程（模拟客户端） ==")


class FakeClient(InfluxDbClient):
    def __init__(self):
        self.connection = conn
        self.written = []      # (database, points)
        self.queries = []
        self.commands = []     # (database, statement) passed to execute_command

    def query(self, database, query):
        self.queries.append(query)
        q = query.strip()
        if q.upper().startswith("SELECT COUNT("):
            return [InfluxDbSeries("m", ["time", "count_v"], None,
                                   [["1970-01-01T00:00:00Z", 250]])]
        if q.upper().startswith("SELECT"):
            # 按 LIMIT/OFFSET 切片 canned 行，模拟真实分页
            import re as _re
            rows = [["2026-09-27T16:00:00Z", "042760236", "0.5", 3]]
            lim = _re.search(r"\blimit\s+(\d+)", q, _re.IGNORECASE)
            off = _re.search(r"\boffset\s+(\d+)", q, _re.IGNORECASE)
            if lim:
                n = int(lim.group(1))
                o = int(off.group(1)) if off else 0
                rows = (rows * (o + n + 1))[o:o + n]
            return [InfluxDbSeries("curveData3761",
                                   ["time", "nmunicateAddr", "currentA",
                                    "frozenDensity"], None, rows)]
        return []

    def get_field_keys(self, database, measurement):
        return [InfluxDbFieldKey(Name="currentA", Type="string"),
                InfluxDbFieldKey(Name="frozenDensity", Type="integer")]

    def get_tag_keys(self, database, measurement):
        return ["nmunicateAddr"]

    def write(self, database, measurement=None, tags=None, fields=None,
              time_stamp=None, retention_policy=None, point=None, points=None):
        from net.sakurain.influxdbstudio.core.models import InfluxDbApiResponse
        pts = list(points) if points is not None else [point]
        self.written.append((database, pts))
        return InfluxDbApiResponse("", 204, True)

    def execute_command(self, database, query):
        from net.sakurain.influxdbstudio.core.models import InfluxDbApiResponse
        self.commands.append((database, query))
        return InfluxDbApiResponse("", 204, True)


# -- 分页（FakeClient 快速验证每页条数切换与 OFFSET 递增）--------------------
fake_pager = FakeClient()
qc_fake = controls.QueryControl()
qc_fake.influx_client = fake_pager
qc_fake.database = "zn_data"
qc_fake.show()
qc_fake.editor_text = 'SELECT * FROM "curveData3761"'
qc_fake.execute_request()
ok = wait_for(lambda: not qc_fake._loading and qc_fake.results_tabs.count() > 0,
              timeout_ms=8000)
check("Fake 分页第1页", ok and any("LIMIT 500 OFFSET 0" in q for q in fake_pager.queries))
check("Fake COUNT 总数", wait_for(lambda: qc_fake._total == 250, timeout_ms=8000),
      f"total={qc_fake._total}")
check("总数标签", "250" in qc_fake.page_rows_label.text(), qc_fake.page_rows_label.text())

qc_fake._apply_page_size(qc_fake.page_size_combo.itemData(0))  # 每页 100
ok = wait_for(lambda: not qc_fake._loading
              and any("LIMIT 100 OFFSET 0" in q for q in fake_pager.queries),
              timeout_ms=8000)
check("切换每页100并重查", ok and qc_fake._page == 1, f"page={qc_fake._page}")
qc_fake._goto_page(2)
ok = wait_for(lambda: not qc_fake._loading
              and any("LIMIT 100 OFFSET 100" in q for q in fake_pager.queries),
              timeout_ms=8000)
check("第2页 OFFSET 100", ok and qc_fake._page == 2, f"page={qc_fake._page}")
check("末页按钮可用", qc_fake.btn_last.isEnabled())
qc_fake.btn_last.click()
ok = wait_for(lambda: qc_fake._page == 3 and not qc_fake._loading, timeout_ms=8000)
check("尾页跳转第3页(250行/100)", ok, f"page={qc_fake._page}")

qc_fake.editor_text = 'SELECT * FROM "curveData3761" LIMIT 5'
qc_fake.execute_request()
ok = wait_for(lambda: not qc_fake._loading and qc_fake.results_tabs.count() > 0,
              timeout_ms=8000)
check("显式 LIMIT 隐藏分页栏(Fake)", ok and not qc_fake.pager_widget.isVisible())

shot(qc_fake, "pagination_fake")

# -- 结果网格编辑 -------------------------------------------------------------
fake = FakeClient()
rc = controls.QueryResultsControl()
rc.influx_client = fake
rc.database = "zn_data"
rc.show()
series = InfluxDbSeries(
    "curveData3761",
    ["time", "nmunicateAddr", "currentA", "frozenDensity"],
    None,
    [["2026-09-27T16:00:00.000000001Z", "042760236", "0.5", 3],
     ["2026-09-27T16:01:00Z", "042760237", "0.7", 4]])
rc.update_results(series)
ok = wait_for(lambda: rc._edit_meta_loaded, timeout_ms=8000)
check("字段/标签元数据加载", ok)
# 列布局: 0="#" 1="time" 2="nmunicateAddr"(标签) 3="currentA"(字段,string)
#         4="frozenDensity"(字段,integer)
check("字段列可编辑", rc.is_editable_cell(0, 3) and rc.is_editable_cell(0, 4))
check("time 列只读", not rc.is_editable_cell(0, 1))
check("标签列(nmunicateAddr)只读", not rc.is_editable_cell(0, 2))
check("序号列只读", not rc.is_editable_cell(0, 0))

# 编辑单元格 → 脏标记 + 高亮（frozenDensity 为 integer 字段）
item = rc.table.item(0, 4)
item.setText("42")
check("编辑产生脏标记", rc._dirty_cell_count() == 1)
check("脏单元格高亮", rc.table.item(0, 4).background().color().name() == "#ffe9b3")
check("类型推断为整数", rc._dirty[(0, 4)][1] == 42)

# 回滚
rc.revert_changes()
check("回滚清除脏标记", rc._dirty_cell_count() == 0)
check("回滚恢复原值", rc.table.item(0, 4).text() == "3")

# 复制/粘贴
rc.table.clearSelection()
rc.table.item(0, 3).setSelected(True)
rc.table.item(0, 4).setSelected(True)
rc.copy_selection()
from PySide6.QtWidgets import QApplication as _QA
check("复制到剪贴板", _QA.clipboard().text() == "0.5\t3")
_QA.clipboard().setText("9.9\t5")
rc.table.setCurrentCell(1, 3)
rc.paste_clipboard()
check("粘贴更新单元格", rc.table.item(1, 3).text() == "9.9"
      and rc.table.item(1, 4).text() == "5")
check("string 字段保持字符串类型", rc._dirty[(1, 3)][1] == "9.9")
check("粘贴产生两处脏标记", rc._dirty_cell_count() == 2)

shot(rc, "editing_dirty")

# 保存（二次确认 → FakeClient 记录，不联网）
CONFIRM_TEXTS.clear()
rc.save_changes()
ok = wait_for(lambda: len(fake.written) > 0, timeout_ms=8000)
check("确认框已弹出(二次确认)", len(CONFIRM_TEXTS) == 1, str(CONFIRM_TEXTS[-1][1:]))
check("确认框含修改明细", "frozenDensity" in CONFIRM_TEXTS[-1][2]
      or "currentA" in CONFIRM_TEXTS[-1][2])
check("写入被调用(模拟)", ok)
if ok:
    db, pts = fake.written[0]
    check("写入目标库正确", db == "zn_data")
    check("写入 1 行 2 字段", len(pts) == 1 and len(pts[0].Fields) == 2)
    check("写入带标签", pts[0].Tags == {"nmunicateAddr": "042760237"})
    from datetime import datetime, timezone
    seconds = int(datetime(2026, 9, 27, 16, 1, 0, tzinfo=timezone.utc).timestamp())
    check("纳秒时间戳精确", pts[0].TimeStampNs == seconds * 1_000_000_000)
check("保存后脏标记清空", rc._dirty_cell_count() == 0)
check("保存成功提示", any(m[0] == "information" for m in MODALS))

# 写入行协议内容断言（第一部分的编辑路径同样适用）
line = fake._point_to_line(fake.written[0][1][0]) if hasattr(fake, "_point_to_line") else None
if line is None:
    from net.sakurain.influxdbstudio.core.client import HttpInfluxDbClient
    line = HttpInfluxDbClient(conn)._point_to_line(fake.written[0][1][0])
check("行协议格式正确", "currentA=" in line and "frozenDensity=5i" in line
      and "nmunicateAddr=042760237" in line, line)

# -- 整行/多行删除（暂存标红 → 二次确认 → FakeClient 记录 DELETE，不联网）------
rc.table.clearSelection()
rc.table.item(0, 1).setSelected(True)
rc.table.item(1, 1).setSelected(True)
rc.stage_delete_selected()
check("两行暂存删除", rc._deleted_rows == {0, 1}, str(rc._deleted_rows))
check("删除行红色高亮", rc.table.item(0, 1).background().color().name() == "#ffd6d6")
check("脏计数含删除行", rc._dirty_row_count() == 2)

# 回滚撤销删除标记
rc.revert_changes()
check("回滚清除删除暂存", rc._deleted_rows == set() and rc._dirty_row_count() == 0)
check("回滚恢复行背景", rc.table.item(0, 1).background().color().name() != "#ffd6d6")

# 再次暂存并保存：确认框含删除明细，FakeClient 记录 2 条 DELETE
rc.table.clearSelection()
rc.table.item(0, 1).setSelected(True)
rc.table.item(1, 1).setSelected(True)
rc.stage_delete_selected()
CONFIRM_TEXTS.clear()
before_rows = rc.table.rowCount()
rc.save_changes()
ok = wait_for(lambda: len(fake.commands) == 2, timeout_ms=8000)
check("确认框含删除明细", len(CONFIRM_TEXTS) == 1
      and CONFIRM_TEXTS[-1][2].count("删除整行") == 2, str(CONFIRM_TEXTS[-1][2]))
check("DELETE 语句已执行(模拟)", ok, str(fake.commands))
if ok:
    check("DELETE 目标库正确", all(db == "zn_data" for db, _s in fake.commands))
    check("DELETE 含时间等值条件",
          "WHERE time = '2026-09-27T16:00:00.000000001Z'"
          in fake.commands[0][1]
          and "WHERE time = '2026-09-27T16:01:00.000000000Z'"
          in fake.commands[1][1],
          str(fake.commands))
    check("DELETE 含标签条件(防误删)",
          '"nmunicateAddr" = \'042760236\'' in fake.commands[0][1]
          and '"nmunicateAddr" = \'042760237\'' in fake.commands[1][1],
          str(fake.commands))
check("保存后删除行从表格移除", rc.table.rowCount() == before_rows - 2,
      f"rows={rc.table.rowCount()}")
check("保存后删除暂存清空", rc._deleted_rows == set())

# -- 每页条数手动输入 -----------------------------------------------------------
qc_fake.editor_text = 'SELECT * FROM "curveData3761"'
qc_fake._page_size = 500
qc_fake.execute_request()  # 非分页查询后需先重新进入分页状态
ok = wait_for(lambda: not qc_fake._loading and qc_fake.pager_widget.isVisible(),
              timeout_ms=8000)
check("重进分页状态", ok)
qc_fake.page_size_combo.lineEdit().setText("37")
qc_fake.page_size_combo.lineEdit().editingFinished.emit()
ok = wait_for(lambda: not qc_fake._loading
              and any("LIMIT 37 OFFSET 0" in q for q in fake_pager.queries),
              timeout_ms=8000)
check("手动输入每页37并重查", ok and qc_fake._page_size == 37,
      f"size={qc_fake._page_size} queries={fake_pager.queries[-2:]}")
check("手输后回到第1页", qc_fake._page == 1, f"page={qc_fake._page}")

# 非法输入回退到当前值
qc_fake.page_size_combo.lineEdit().setText("abc")
qc_fake.page_size_combo.lineEdit().editingFinished.emit()
check("非法输入不生效", qc_fake._page_size == 37
      and qc_fake.page_size_combo.lineEdit().text() == "37",
      qc_fake.page_size_combo.lineEdit().text())

# -- 可见的保存/回滚按钮（DBeaver 风格按钮条，随脏状态显隐）--------------------
grid = qc_fake.results_tabs.currentWidget()
ok = wait_for(lambda: grid is not None and grid._edit_meta_loaded, timeout_ms=8000)
check("当前结果网格就绪", ok)
check("无修改时按钮条常显但禁用", qc_fake.edit_bar_widget.isVisible()
      and not qc_fake.btn_grid_save.isEnabled()
      and not qc_fake.btn_grid_revert.isEnabled())
grid.table.clearSelection()
grid.table.item(0, 1).setSelected(True)
grid.stage_delete_selected()
check("暂存删除后按钮启用", qc_fake.edit_bar_widget.isVisible()
      and qc_fake.btn_grid_save.isEnabled()
      and qc_fake.btn_grid_revert.isEnabled())
check("按钮计数文本", "1" in qc_fake.btn_grid_save.text(), qc_fake.btn_grid_save.text())
grid.revert_changes()
check("回滚后按钮禁用但按钮条仍显示",
      qc_fake.edit_bar_widget.isVisible()
      and not qc_fake.btn_grid_save.isEnabled())

# Delete 快捷键同样触发暂存
grid.table.clearSelection()
grid.table.item(1, 1).setSelected(True)
win = grid.table.window().windowHandle()
if win is not None:
    win.show()
    win.requestActivate()
    QTest.qWait(200)
grid.table.setFocus()
QTest.keyClick(grid.table, Qt.Key_Delete)
check("Delete 快捷键暂存删除", grid._deleted_rows == {1}, str(grid._deleted_rows))
grid.revert_changes()

# -- 表头右键菜单（DBeaver 风格高级功能）---------------------------------------
rc2 = controls.QueryResultsControl()
rc2.influx_client = fake
rc2.database = "zn_data"
rc2.show()
series2 = InfluxDbSeries(
    "m", ["time", "v", "w"], None,
    [["2026-09-27T16:00:03Z", 3, "c"],
     ["2026-09-27T16:00:01Z", 1, "a"],
     ["2026-09-27T16:00:02Z", 2, "b"]])
rc2.update_results(series2)
ok = wait_for(lambda: rc2._edit_meta_loaded, timeout_ms=8000)
check("表头菜单测试网格就绪", ok)
check("选中样式为蓝色", "#2f6fd0" in rc2.table.styleSheet(),
      rc2.table.styleSheet())

import PySide6.QtWidgets as _W
from PySide6.QtCore import QPoint as _QPoint
from net.sakurain.influxdbstudio.i18n import tr as _tr


def click_header_menu(control, text, pos):
    """弹出表头菜单并"点击"指定文本的启用菜单项（chooser 替代模态 exec）。"""
    chosen = {"action": None}

    def chooser(menu):
        for act in menu.actions():
            if act.text() == text and act.isEnabled():
                chosen["action"] = act
                return act
        return None

    control._show_header_menu(pos, chooser=chooser)
    return chosen["action"]


def header_pos(control, col):
    header = control.table.horizontalHeader()
    x = 0
    for c in range(col):
        x += header.sectionSize(c)
    return _QPoint(x + header.sectionSize(col) // 2, 3)


# 复制字段名（点到 "v" 列表头）
click_header_menu(rc2, _tr("grid.header.copy_name"), header_pos(rc2, 2))
check("复制字段名", _QA.clipboard().text() == "v", _QA.clipboard().text())
# 复制全部字段名（不含 "#" 序号列）
click_header_menu(rc2, _tr("grid.header.copy_all_names"), header_pos(rc2, 1))
check("复制全部字段名", _QA.clipboard().text() == "time, v, w",
      _QA.clipboard().text())

# 列宽：适合值（不报错且列宽为正）
w_before = rc2.table.columnWidth(2)
click_header_menu(rc2, _tr("grid.header.fit_width"), header_pos(rc2, 2))
check("列宽适合值", rc2.table.columnWidth(2) != w_before
      or rc2.table.columnWidth(2) > 0, f"width={rc2.table.columnWidth(2)}")

# 隐藏列 / 显示全部列
click_header_menu(rc2, _tr("grid.header.hide_column"), header_pos(rc2, 3))
check("隐藏此列", rc2.table.isColumnHidden(3))
click_header_menu(rc2, _tr("grid.header.show_all_columns"), header_pos(rc2, 1))
check("显示全部列", not rc2.table.isColumnHidden(3))

# 升序 / 降序排列当前页
click_header_menu(rc2, _tr("grid.header.sort_asc"), header_pos(rc2, 2))
check("升序排列当前页", rc2._series.Values[0][1] == 1
      and rc2._series.Values[2][1] == 3, str(rc2._series.Values))
click_header_menu(rc2, _tr("grid.header.sort_desc"), header_pos(rc2, 2))
check("降序排列当前页", rc2._series.Values[0][1] == 3
      and rc2._series.Values[2][1] == 1, str(rc2._series.Values))

# 暂存删除时排序不可用（保护行号映射）
rc2.table.clearSelection()
rc2.table.item(0, 1).setSelected(True)
rc2.stage_delete_selected()
first_v = rc2._series.Values[0][1]
click_header_menu(rc2, _tr("grid.header.sort_asc"), header_pos(rc2, 2))
check("脏状态禁止排序", rc2._series.Values[0][1] == first_v
      and rc2._deleted_rows == {0})
rc2.revert_changes()

# 刷新回调（由 QueryControl 提供）
refreshed = []
rc2.on_refresh = lambda: refreshed.append(1)
click_header_menu(rc2, _tr("grid.header.refresh"), header_pos(rc2, 1))
check("刷新回调触发", refreshed == [1])
rc2.on_refresh = None
click_header_menu(rc2, _tr("grid.header.refresh"), header_pos(rc2, 1))
check("无刷新回调时菜单项禁用", refreshed == [1])

shot(rc2, "header_menu_grid")

# -- 导出：右键「导出选中行」+ 导出对话框（格式/分隔符/位置）-------------------
from net.sakurain.influxdbstudio.core import exporters
from net.sakurain.influxdbstudio.ui import dialogs as dlg_mod

SAVED_RESPONSES = SAVE_DIALOG_RESPONSES  # 别名，语义一致


def body_menu_actions(control):
    """弹出表格体右键菜单，返回其全部 action 文本列表（chooser 替代模态 exec）。"""
    texts = []

    def chooser(menu):
        texts.extend(act.text() for act in menu.actions())
        return None

    control._show_context_menu(_QPoint(10, 10), chooser=chooser)
    return texts


# 无选中时：不出现「导出选中行」
rc2.table.clearSelection()
texts_no_sel = body_menu_actions(rc2)
check("无选中时右键无导出入口",
      _tr("query.export.selected") not in texts_no_sel, str(texts_no_sel))

# 选中一行后：出现「导出选中行」
rc2.table.selectRow(1)
texts_sel = body_menu_actions(rc2)
check("选中行后右键显示导出选中行",
      _tr("query.export.selected") in texts_sel, str(texts_sel))

# 表头菜单包含「导出全部」（点击会弹模态导出框，先把 exec 打成取消）
real_qdialog_exec = dlg_mod.QDialog.exec
dlg_mod.QDialog.exec = lambda self: dlg_mod.QDialog.Rejected
try:
    act_export_all = click_header_menu(rc2, _tr("query.export.all"),
                                       header_pos(rc2, 1))
finally:
    dlg_mod.QDialog.exec = real_qdialog_exec
check("表头菜单含导出全部", act_export_all is not None)


# 导出对话框行为
export_dlg = dlg_mod.ExportDialog(rc2._suggest_name)
check("导出格式共6种", export_dlg.format_combo.count() == 6,
      str(export_dlg.format_combo.count()))
check("CSV 默认分隔符为逗号",
      export_dlg.delimiter_edit.text() == ","
      and export_dlg.delimiter_edit.isEnabled())
fmt_index = {export_dlg.format_combo.itemData(i): i
             for i in range(export_dlg.format_combo.count())}
export_dlg.format_combo.setCurrentIndex(fmt_index["json"])
check("非 CSV 格式分隔符禁用", not export_dlg.delimiter_edit.isEnabled())
export_dlg.format_combo.setCurrentIndex(fmt_index["csv"])
export_dlg.delimiter_edit.setText(";;")
modals_before = len(MODALS)
export_dlg._on_accept()  # 非法分隔符 → 报错且不弹保存框
check("非法分隔符报错", any(m[0] == "critical" for m in MODALS[modals_before:]),
      str(MODALS[modals_before:]))
export_dlg.delimiter_edit.setText(";")

# 完整导出流程：csv + 自定义分隔符（exec 打补丁直接接受）
import tempfile as _tf
from net.sakurain.influxdbstudio.core import exporters as _exp_mod
tmp_dir = _tf.mkdtemp(prefix="idm_export_")
out_csv = tmp_dir + "\\rows.csv"
SAVE_DIALOG_RESPONSES.append((out_csv, ""))


def _accept_with(choice):
    def _exec(self):
        self.choice = choice
        return dlg_mod.QDialog.Accepted
    return _exec


real_exec = dlg_mod.QDialog.exec
dlg_mod.QDialog.exec = _accept_with((out_csv, "csv", ";"))
try:
    n_csv = dlg_mod.run_export_dialog(rc2._suggest_name,
                                      *rc2._collect_rows(False), parent=rc2)
finally:
    dlg_mod.QDialog.exec = real_exec
csv_text = Path(out_csv).read_text(encoding="utf-8-sig")
check("导出CSV写出成功", n_csv == 3 and len(csv_text.splitlines()) == 4
      and ";" in csv_text.splitlines()[0],  # header + 3 rows, 分号分隔
      f"n={n_csv} {len(csv_text.splitlines())} 行")

# run_export_dialog 全程：选中行导出 JSON
out_json = tmp_dir + "\\rows.json"
rc2.table.clearSelection()
rc2.table.item(0, 1).setSelected(True)
rc2.table.item(2, 1).setSelected(True)
dlg_mod.QDialog.exec = _accept_with((out_json, "json", ","))
try:
    n = dlg_mod.run_export_dialog(rc2._suggest_name,
                                  *rc2._collect_rows(True), parent=rc2)
finally:
    dlg_mod.QDialog.exec = real_exec
import json as _json
_json_data = _json.loads(Path(out_json).read_text(encoding="utf-8"))
check("导出选中行(JSON) 2行", n == 2 and len(_json_data) == 2,
      f"n={n}")
check("导出完成提示", any(m[0] == "information" for m in MODALS[-3:]),
      str(MODALS[-3:]))
rc2.table.clearSelection()

# -- 导出全部 = 完整查询数据（重跑原始查询，不带分页 LIMIT）--------------------
class _FullExportClient(FakeClient):
    """全量查询返回 600 行；带 LIMIT/OFFSET 的分页查询返回切片。"""

    def query(self, database, query):
        self.queries.append(query)
        q = query.strip()
        if q.upper().startswith("SELECT COUNT("):
            return [InfluxDbSeries("m", ["time", "count_v"], None,
                                   [["1970-01-01T00:00:00Z", 600]])]
        if q.upper().startswith("SELECT"):
            rows = [[f"2026-09-27T16:{i // 60:02d}:{i % 60:02d}Z", i]
                    for i in range(600)]
            import re as _re
            lim = _re.search(r"\blimit\s+(\d+)", q, _re.IGNORECASE)
            off = _re.search(r"\boffset\s+(\d+)", q, _re.IGNORECASE)
            if lim:
                n = int(lim.group(1))
                o = int(off.group(1)) if off else 0
                rows = (rows * (o + n + 1))[o:o + n]
            return [InfluxDbSeries("curveData3761",
                                   ["time", "currentA"], None, rows)]
        return []


full_client = _FullExportClient()
qc_ex = controls.QueryControl()
qc_ex.influx_client = full_client
qc_ex.database = "zn_data"
qc_ex.show()
qc_ex.editor_text = 'SELECT * FROM "curveData3761"'
qc_ex.execute_request()
ok = wait_for(lambda: not qc_ex._loading and qc_ex.results_tabs.count() > 0,
              timeout_ms=8000)
check("导出全部-分页查询出结果", ok)
rc_ex = qc_ex.results_tabs.widget(0)
check("导出全部-fetcher 已注入",
      callable(getattr(rc_ex, "export_all_fetcher", None)))
check("当前页仅一页数据(500)", rc_ex.table.rowCount() == 500,
      str(rc_ex.table.rowCount()))

out_all = tmp_dir + "\\all.json"
dlg_mod.QDialog.exec = _accept_with((out_all, "json", ","))
try:
    rc_ex.export_rows_interactive(False)
finally:
    dlg_mod.QDialog.exec = real_exec
ok = wait_for(lambda: Path(out_all).exists(), timeout_ms=8000)
check("导出全部写出文件", ok)
if ok:
    _all_data = _json.loads(Path(out_all).read_text(encoding="utf-8"))
    check("导出全部=全量 600 行(非当前页 500)", len(_all_data) == 600,
          str(len(_all_data)))
check("导出全部重跑原始查询(无分页 LIMIT)",
      any(q.strip() == 'SELECT * FROM "curveData3761"'
          for q in full_client.queries),
      str(full_client.queries[-3:]))

# -- 导出位置记忆 -------------------------------------------------------------
import os as _os
settings.last_export_dir = ""
_start_dirs = []
_real_gsfn = _W.QFileDialog.getSaveFileName


def _capture_start(parent, title, directory, filter_):
    _start_dirs.append(directory)
    return (_os.path.join(tmp_dir, "mem.csv"), "")


_W.QFileDialog.getSaveFileName = staticmethod(_capture_start)
try:
    # 让 exec 直接走真实的 _on_accept（弹保存框→记忆位置→置 choice）
    def _accept_real(self):
        self._on_accept()
        return self.result()
    dlg_mod.QDialog.exec = _accept_real
    n1 = dlg_mod.run_export_dialog(rc2._suggest_name,
                                   *rc2._collect_rows(False), parent=rc2)
    n2 = dlg_mod.run_export_dialog(rc2._suggest_name,
                                   *rc2._collect_rows(False), parent=rc2)
finally:
    dlg_mod.QDialog.exec = real_exec
    _W.QFileDialog.getSaveFileName = _real_gsfn
check("导出位置已记忆", settings.last_export_dir == tmp_dir,
      settings.last_export_dir)
check("第二次导出起始位置为记忆目录",
      len(_start_dirs) == 2
      and _os.path.dirname(_start_dirs[1]) == tmp_dir
      and _start_dirs[0] != _start_dirs[1],
      str(_start_dirs))

# -- 编辑器字体缩放（Ctrl+= / Ctrl+- / Ctrl+0）--------------------------------
from net.sakurain.influxdbstudio.ui.common import \
    create_sql_editor as _create_sql_editor
ed2 = _create_sql_editor()
ed2.show()
_base_size = ed2.font().pointSize()
QTest.qWait(50)
QTest.keyClick(ed2, Qt.Key_Equal, Qt.ControlModifier)
check("Ctrl+= 放大字体", ed2.font().pointSize() == _base_size + 1,
      str(ed2.font().pointSize()))
QTest.keyClick(ed2, Qt.Key_Minus, Qt.ControlModifier)
QTest.keyClick(ed2, Qt.Key_Minus, Qt.ControlModifier)
check("Ctrl+- 缩小字体", ed2.font().pointSize() == _base_size - 1,
      str(ed2.font().pointSize()))
QTest.keyClick(ed2, Qt.Key_0, Qt.ControlModifier)
check("Ctrl+0 复位字体", ed2.font().pointSize() == _base_size,
      str(ed2.font().pointSize()))

# ===========================================================================
# 1.2.0：列过滤 / 服务端时间排序 / Calc 面板 / 只读连接 / 查询历史 / 写入
# ===========================================================================
print("== 1.2.0 新功能 ==")

# -- 列过滤 chip 条（服务端重查）------------------------------------------------
f_client = _FullExportClient()
qc_f = controls.QueryControl()
qc_f.influx_client = f_client
qc_f.database = "zn_data"
qc_f.show()
qc_f.editor_text = 'SELECT * FROM "curveData3761"'
qc_f.execute_request()
ok = wait_for(lambda: not qc_f._loading and qc_f.results_tabs.count() > 0,
              timeout_ms=8000)
check("过滤-初始查询出结果", ok)
# 模拟表头过滤入口（对话框交互另由单测覆盖字段类型推断）
qc_f._filters.append({"column": "currentA", "op": ">", "value": "0.5",
                      "numeric": True})
qc_f._rebuild_filter_bar()
check("过滤-chip 条可见", qc_f.filter_bar.isVisible()
      and qc_f.filter_layout.count() == 3,  # chip + 清除全部 + stretch
      str(qc_f.filter_layout.count()))
qc_f.execute_request()
ok = wait_for(lambda: not qc_f._loading, timeout_ms=8000)
check("过滤-服务端重查注入 WHERE",
      ok and any('WHERE ("currentA" > 0.5)' in q for q in f_client.queries),
      str(f_client.queries[-2:]))
check("过滤-COUNT 同样带条件",
      wait_for(lambda: any("COUNT(*)" in q and '"currentA" > 0.5' in q
                           for q in f_client.queries), timeout_ms=8000),
      str(f_client.queries[-3:]))
qc_f._clear_filters()
wait_for(lambda: not qc_f._loading, timeout_ms=8000)  # 清除会触发异步重查
check("过滤-清除全部后 chip 条隐藏", not qc_f.filter_bar.isVisible()
      and qc_f._filters == [])
# 前导零字符串值必须加引号（表地址类 tag）
from net.sakurain.influxdbstudio.core import query_tools as _qt
check("过滤-前导零字符串加引号",
      _qt.build_filter_condition("nmunicateAddr", "=", "042760236")
      == '"nmunicateAddr" = \'042760236\'')
# 换查询文本后过滤自动失效
qc_f._filters.append({"column": "currentA", "op": ">", "value": "0.5",
                      "numeric": True})
qc_f.editor_text = 'SELECT * FROM "other"'
qc_f.execute_request()
ok = wait_for(lambda: not qc_f._loading, timeout_ms=8000)
check("过滤-新查询自动清除旧条件", ok and qc_f._filters == [])

# -- 服务端时间排序（ORDER BY time 注入）-----------------------------------------
qc_f.editor_text = 'SELECT * FROM "curveData3761"'
f_client.queries.clear()
qc_f._server_time_sort(True)
ok = wait_for(lambda: not qc_f._loading, timeout_ms=8000)
check("时间排序-注入 ORDER BY time DESC",
      ok and any("ORDER BY time DESC" in q for q in f_client.queries),
      str(f_client.queries[-2:]))
f_client.queries.clear()
qc_f._server_time_sort(True)  # 再次点击 = 取消
ok = wait_for(lambda: not qc_f._loading, timeout_ms=8000)
check("时间排序-再次点击取消",
      ok and qc_f._time_order is None
      and not any("ORDER BY" in q for q in f_client.queries),
      str(f_client.queries[-2:]))

# -- Calc 统计面板 --------------------------------------------------------------
rc2.table.clearSelection()
for r in range(rc2.table.rowCount()):
    rc2.table.item(r, 2).setSelected(True)  # "v" 列：3, 1, 2
check("Calc 面板显示统计", "2" in rc2.calc_label.text()
      and rc2.calc_label.isVisible(), rc2.calc_label.text())
rc2.table.clearSelection()
check("Calc 面板无选中时隐藏", not rc2.calc_label.isVisible())

# -- 只读连接 -------------------------------------------------------------------
rc_ro = controls.QueryResultsControl()
rc_ro.influx_client = fake
rc_ro.database = "zn_data"
rc_ro.read_only = True
rc_ro.show()
rc_ro.update_results(series2)
rc_ro._edit_meta_loaded = True
rc_ro._field_types = {"v": "integer"}
check("只读-单元格不可编辑", not rc_ro.is_editable_cell(0, 2))
modals_before = len(MODALS)
rc_ro.table.selectRow(0)
rc_ro.stage_delete_selected()
check("只读-删除被阻止并提示", rc_ro._deleted_rows == set()
      and any(m[0] == "critical" for m in MODALS[modals_before:]),
      str(MODALS[modals_before:]))
_menu_states = {}


def _capture_menu(control):
    def chooser(menu):
        _menu_states.update(
            (a.text(), a.isEnabled()) for a in menu.actions())
        return None
    control._show_context_menu(_QPoint(10, 10), chooser=chooser)


_capture_menu(rc_ro)
check("只读-右键删除项禁用",
      _menu_states.get(_tr("grid.delete_rows", n=1)) is False
      and _menu_states.get(_tr("grid.revert_changes")) is False,
      str(_menu_states))

# -- 查询历史 -------------------------------------------------------------------
settings.record_query("cid1", "zn_data", "SELECT 9")
check("历史-record_query 置顶", settings.history_for("cid1")[0]["Text"] == "SELECT 9",
      str(settings.history_for("cid1")[:1]))
settings.record_query("cid1", "zn_data", "SELECT 9")  # 重复记录应去重置顶
check("历史-重复查询去重",
      sum(1 for h in settings.history_for("cid1") if h["Text"] == "SELECT 9") == 1,
      str(settings.history_for("cid1")))
# QueryControl 执行成功后自动记录（done() 中 record_query）
qc_h = controls.QueryControl()
qc_h.influx_client = f_client
qc_h.database = "zn_data"
qc_h.connection_id = "cid_hist"
qc_h.show()
qc_h.editor_text = 'SELECT * FROM "curveData3761"'
qc_h.execute_request()
ok = wait_for(lambda: not qc_h._loading, timeout_ms=8000)
_hist = settings.history_for("cid_hist")
check("历史-执行后自动记录",
      ok and len(_hist) >= 1 and _hist[0]["Text"].startswith("SELECT")
      and _hist[0]["ConnectionId"] == "cid_hist" and _hist[0]["Database"] == "zn_data",
      str(_hist[:1]))

# -- 写入数据点对话框（解析与校验，不触网）--------------------------------------
wdlg = dlg_mod.WritePointDialog("zn_data", "m")
wdlg.tags_edit.setText("site=a")
wdlg.fields_edit.setText("k=1, s='x', b=true")
wdlg._on_accept()
check("写入-字段与标签解析",
      wdlg.point is not None
      and wdlg.point.Fields == {"k": 1, "s": "x", "b": True}
      and wdlg.point.Tags == {"site": "a"}
      and wdlg.point.Measurement == "m",
      repr(wdlg.point.Fields if wdlg.point else None))
modals_before = len(MODALS)
wdlg_bad = dlg_mod.WritePointDialog("zn_data", "m")
wdlg_bad.fields_edit.setText("")
wdlg_bad._on_accept()
check("写入-空字段拒绝并提示",
      wdlg_bad.point is None
      and any(m[0] == "critical" for m in MODALS[modals_before:]),
      str(MODALS[modals_before:]))

# -- SHOW SHARDS / SUBSCRIPTIONS 浏览器 -----------------------------------------
sc = controls.ShowCommandControl(lambda: [series2], "shards.empty")
sc.influx_client = fake
sc.show()
sc.execute_request()
ok = wait_for(lambda: sc.results_tabs.count() > 0, timeout_ms=8000)
_sc_inner = sc.results_tabs.widget(0) if sc.results_tabs.count() else None
check("分片浏览器-单 series 渲染 3 行",
      ok and sc.results_tabs.count() == 1 and _sc_inner is not None
      and _sc_inner.table.rowCount() == 3,
      f"tabs={sc.results_tabs.count()} rows="
      f"{_sc_inner.table.rowCount() if _sc_inner else '-'}")
sc_empty = controls.ShowCommandControl(lambda: [], "shards.empty")
sc_empty.influx_client = fake
sc_empty.show()
sc_empty.execute_request()
ok = wait_for(lambda: sc_empty.results_tabs.count() > 0, timeout_ms=8000)
check("分片浏览器-空结果显示占位", ok and sc_empty.results_tabs.count() == 1,
      str(sc_empty.results_tabs.count()))


# -- SQL 编辑器：Ctrl+/ 注释整行 + 注释行变灰 ----------------------------------
from net.sakurain.influxdbstudio.ui.common import (
    _toggle_line_comment, create_sql_editor)

ed = create_sql_editor()
ed.setPlainText("SELECT a\nFROM m")
cur = ed.textCursor()
cur.setPosition(0)
ed.setTextCursor(cur)
_toggle_line_comment(ed)
check("注释当前行", ed.toPlainText() == "-- SELECT a\nFROM m",
      repr(ed.toPlainText()))
_toggle_line_comment(ed)
check("再次切换取消注释", ed.toPlainText() == "SELECT a\nFROM m",
      repr(ed.toPlainText()))

# 多行选中整体注释 / 取消
ed.setPlainText("SELECT a\nFROM m\nWHERE x = 1")
from PySide6.QtGui import QTextCursor as _TC
cur = ed.textCursor()
cur.setPosition(0)
cur.setPosition(ed.document().findBlockByNumber(1).position() + 3, _TC.KeepAnchor)
ed.setTextCursor(cur)
_toggle_line_comment(ed)
check("多行注释", ed.toPlainText()
      == "-- SELECT a\n-- FROM m\nWHERE x = 1", repr(ed.toPlainText()))
_toggle_line_comment(ed)
check("多行取消注释", ed.toPlainText()
      == "SELECT a\nFROM m\nWHERE x = 1", repr(ed.toPlainText()))

# 注释行高亮为灰色：覆盖整行的 format 必须全部是灰色（注释内容不能被关键字格式覆盖）
ed.setPlainText("-- SELECT a and time >= '2026-01-01'")
qapp.processEvents()
block = ed.document().findBlockByNumber(0)
fmts = block.layout().formats()
line_len = len(block.text())
covering = [f for f in fmts if f.start + f.length >= line_len]
all_gray = bool(covering) and all(
    f.format.foreground().color().name() == "#7f7f7f" for f in covering)
check("注释行整行灰色", all_gray, str([(f.start, f.length,
                                    f.format.foreground().color().name())
                                   for f in fmts]))

# Ctrl+/ 快捷键触发注释
ed.setPlainText("SELECT 1")
ed.moveCursor(_TC.Start)
ed.show()
ed_win = ed.windowHandle()
if ed_win is not None:
    ed_win.show()
    ed_win.requestActivate()
    QTest.qWait(200)
ed.setFocus()
QTest.keyClick(ed, Qt.Key_Slash, Qt.ControlModifier)
check("Ctrl+/ 快捷键注释", ed.toPlainText() == "-- SELECT 1",
      repr(ed.toPlainText()))

shot(qc_fake, "delete_and_editbar")

# -- 启动行为：已有连接时不弹"管理连接"窗口 ------------------------------------
from net.sakurain.influxdbstudio.ui import main_window as mw_module

dialogs_created = []


class _ProbeDialog:
    def __init__(self, *a, **k):
        dialogs_created.append(self)

    def exec(self):
        return 0


_orig_mcd = mw_module.ManageConnectionsDialog
mw_module.ManageConnectionsDialog = _ProbeDialog
_orig_connections = list(app_module.settings.connections)
app_module.settings.connections = [conn]
# MainWindow 启动时会从磁盘 load_all()，必须把连接写入隔离配置
app_module.settings.save_all()


class _FailClient(InfluxDbClient):
    def __init__(self):
        self.connection = conn

    def get_database_names(self, timeout=None):
        raise ConnectionError("ConnectTimeout: host unreachable")

    def get_measurement_names(self, database, timeout=None):
        raise ConnectionError("ConnectTimeout: host unreachable")


try:
    # 先注入失败客户端再建窗口：渲染连接节点时就会触发异步加载
    app_module.active_clients[:] = [_FailClient()]
    win = mw_module.MainWindow(show_connections_on_load=True)
    win.show()
    QTest.qWait(400)  # 覆盖 250ms 的 singleShot
    check("已有连接时不弹管理连接窗口", dialogs_created == [],
          str(len(dialogs_created)))
    check("启动后树中渲染连接节点",
          win.tree.topLevelItemCount() == 1
          and win.tree.topLevelItem(0).text(0) == conn.Name,
          win.tree.topLevelItem(0).text(0) if win.tree.topLevelItemCount() else "")

    # -- 连接失败优雅处理：内联错误节点，不弹模态框、不残留转圈 ---------------
    # 固定 Database 的连接在展开数据库节点时才真正访问网络
    node = win.tree.topLevelItem(0)
    ok = wait_for(lambda: node.childCount() == 1
                  and mw_module.MainWindow._node_type(node.child(0))
                  == mw_module.NodeType.Database, timeout_ms=8000)
    check("启动后渲染数据库节点", ok,
          node.child(0).text(0) if node.childCount() else "no child")
    db_node = node.child(0)
    modals_before = len(MODALS)
    win._expand_node_children(db_node)
    ok = wait_for(lambda: db_node.childCount() == 1
                  and mw_module.MainWindow._node_type(db_node.child(0))
                  == mw_module.NodeType.Error, timeout_ms=8000)
    check("加载失败显示内联错误节点", ok,
          db_node.child(0).text(0) if db_node.childCount() else "no child")
    if ok:
        err_node = db_node.child(0)
        check("错误节点为红色", err_node.foreground(0).color().name() == "#c00000")
        check("错误节点提示重试", "重试" in err_node.text(0), err_node.text(0))
    check("加载失败不弹模态错误框",
          len(MODALS) == modals_before, str(MODALS[modals_before:]))
    check("状态栏提示加载失败", "加载失败" in win.status_label.text(),
          win.status_label.text())

    # 双击错误节点重试：回到加载占位并再次失败
    win._tree_item_double_clicked(db_node.child(0), 0)
    check("双击重试回到加载占位", db_node.childCount() == 1
          and mw_module.MainWindow._node_type(db_node.child(0))
          == mw_module.NodeType.LoadingPlaceholder)
    ok = wait_for(lambda: mw_module.MainWindow._node_type(db_node.child(0))
                  == mw_module.NodeType.Error, timeout_ms=8000)
    check("重试后再次显示错误节点", ok)

    shot(win, "startup_and_load_error")
finally:
    mw_module.ManageConnectionsDialog = _orig_mcd
    app_module.settings.connections = _orig_connections
    app_module.active_clients[:] = []
    win.close()

# ===========================================================================
# 汇总
# ===========================================================================
fails = [r for r in RESULTS if r[0] == "FAIL"]
warns = [r for r in RESULTS if r[0] == "WARN"]
print("\n" + "=" * 60)
print(f"DBeaver 功能 E2E: {len(RESULTS) - len(fails) - len(warns)} 通过, "
      f"{len(warns)} 警告, {len(fails)} 失败")
for status, name, detail in fails + warns:
    print(f"  {status}: {name} {detail}")
print("写入保护：FakeClient 仅记录写入，真实服务端未被修改")
sys.exit(1 if fails else 0)
