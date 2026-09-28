# -*- coding: utf-8 -*-
"""真实 Windows 平台截图验证：标题/图标、脚本页自动恢复、注释灰色、
蓝色选中、分页栏、脏标记、删除标记、常显保存/回滚按钮条。

查询使用 FakeClient（渲染与真实客户端完全一致），生产库零访问。
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

qapp = QApplication(sys.argv)
qapp.setApplicationName("InfluxDB Manager")

import net.sakurain.influxdbstudio.app as app_module
import net.sakurain.influxdbstudio.core.settings as settings_module
from net.sakurain.influxdbstudio.core.client import InfluxDbClient
from net.sakurain.influxdbstudio.core.models import (
    InfluxDbConnection, InfluxDbFieldKey, InfluxDbSeries)
from net.sakurain.influxdbstudio.core.settings import AppSettings
from net.sakurain.influxdbstudio.i18n import set_language
from net.sakurain.influxdbstudio.ui import main_window

set_language("zh_CN")

_CFG_TMP = Path(tempfile.mkdtemp(prefix="influxdbmanager_shot_"))
settings_module._settings_path = lambda: str(_CFG_TMP / "settings.json")


class FakeClient(InfluxDbClient):
    def __init__(self, connection):
        self.connection = connection
        self.queries = []

    def query(self, database, query):
        self.queries.append(query)
        q = query.strip().upper()
        if q.startswith("SELECT COUNT("):
            return [InfluxDbSeries("m", ["time", "count_v"], None,
                                   [["1970-01-01T00:00:00Z", 250]])]
        if q.startswith("SELECT"):
            import re
            rows = [["2026-09-27T16:00:00.000000001Z", "042760236",
                     "0.5", 3], ["2026-09-27T16:01:00Z", "042760237",
                                 "0.7", 4]] * 75
            m = re.search(r"\blimit\s+(\d+)", query, re.IGNORECASE)
            o = re.search(r"\boffset\s+(\d+)", query, re.IGNORECASE)
            if m:
                n = int(m.group(1))
                off = int(o.group(1)) if o else 0
                rows = rows[off:off + n]
            return [InfluxDbSeries("curveData3761",
                                   ["time", "nmunicateAddr", "currentA",
                                    "frozenDensity"], None, rows)]
        # 注释行开头的查询（脚本注释头）剥掉注释后再判断
        from net.sakurain.influxdbstudio.core import query_tools
        stripped = query_tools.strip_line_comments(query).strip().upper()
        if stripped.startswith("SELECT"):
            return self.query(database, query_tools.strip_line_comments(query))
        return []

    def get_field_keys(self, database, measurement):
        return [InfluxDbFieldKey(Name="currentA", Type="string"),
                InfluxDbFieldKey(Name="frozenDensity", Type="integer")]

    def get_tag_keys(self, database, measurement):
        return ["nmunicateAddr"]


conn = InfluxDbConnection.create(
    name="zn_data", host="10.82.10.103", port=31123, username="sa",
    password="sa", database="zn_data")

settings = AppSettings(version="shot")
settings.connections = [conn]
settings.query_scripts = [
    {"Name": "日报查询", "ConnectionId": conn.Id, "Database": "zn_data",
     "Text": "-- 昨日曲线数据\nSELECT * FROM \"curveData3761\""},
    {"Name": "zn_data (2)", "ConnectionId": conn.Id, "Database": "zn_data",
     "Text": 'SELECT * FROM "curveData3761" LIMIT 5'},
]
settings.active_query_tab = 0
app_module.settings = settings

# 让恢复路径拿到 FakeClient
main_window.create_client = lambda *a, **k: FakeClient(conn)

win = main_window.MainWindow(show_connections_on_load=False)
win.setWindowTitle("InfluxDB Manager")
win.resize(1360, 860)
win.show()

# 等脚本页自动恢复
QTest.qWait(300)
assert win.tabs.count() == 2, f"tabs={win.tabs.count()}"
assert win.tabs.tabText(0) == "日报查询", win.tabs.tabText(0)
assert win.tabs.currentIndex() == 0

qc = win.tabs.widget(0)._request_control
assert "-- 昨日曲线数据" in qc.get_editor_text()

# 执行查询（FakeClient）→ 分页栏 + 结果网格
qc.execute_request()
for _ in range(100):
    QTest.qWait(100)
    qapp.processEvents()
    grid = qc.results_tabs.currentWidget() if qc.results_tabs.count() else None
    if (not qc._loading and grid is not None and grid._edit_meta_loaded
            and grid.table.rowCount() > 0):
        break

grid = qc.results_tabs.currentWidget() if qc.results_tabs.count() else None
print("debug: loading=", qc._loading, "tabs=", qc.results_tabs.count(),
      "label=", repr(qc.results_label.text()),
      "rows=", grid.table.rowCount() if grid is not None else -1,
      "meta=", grid._edit_meta_loaded if grid is not None else None,
      "client=", type(qc.influx_client).__name__)
assert grid is not None and grid.table.rowCount() > 0, "结果未就绪"

# 编辑一个单元格（脏标记）+ 选中若干行做删除标记 + 蓝色选中
item = grid.table.item(0, 3)
item.setText("__编辑__")
grid.table.clearSelection()
grid.table.item(2, 1).setSelected(True)
grid.table.item(3, 1).setSelected(True)
grid.table.item(4, 2).setSelected(True)
grid.stage_delete_selected()
# 再留一个普通蓝色选中单元格
grid.table.item(6, 2).setSelected(True)

qapp.processEvents()
QTest.qWait(200)

SHOTS = Path(__file__).resolve().parent / "e2e_screenshots"
SHOTS.mkdir(exist_ok=True)
win.grab().save(str(SHOTS / "manager_main_window.png"))
print("saved:", SHOTS / "manager_main_window.png")
print("title:", win.windowTitle())
print("edit_bar visible:", qc.edit_bar_widget.isVisible(),
      "save enabled:", qc.btn_grid_save.isEnabled(),
      "| text:", qc.btn_grid_save.text())
print("deleted rows:", sorted(grid._deleted_rows),
      "| dirty cells:", grid._dirty_cell_count())
print("tabs restored:", [win.tabs.tabText(i) for i in range(win.tabs.count())])
print("生产库零访问零写入（FakeClient 仅本地渲染）")
