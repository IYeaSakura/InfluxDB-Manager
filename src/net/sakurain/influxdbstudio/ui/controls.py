"""Tab content controls (ports of the C# Controls/* classes).

Each control mirrors its WinForms counterpart: a ``RequestControl`` base with
``execute_request()`` and concrete subclasses for queries, measurement
exploration, users, retention policies, continuous queries, running queries,
diagnostics and stats.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIntValidator, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import query_tools
from ..core.async_utils import run_async
from ..core.client import InfluxDbClient
from ..core.models import (
    InfluxDbContinuousQuery,
    InfluxDbGrant,
    InfluxDbPoint,
    InfluxDbPrivileges,
    InfluxDbRetentionPolicy,
    InfluxDbRunningQuery,
    InfluxDbSeries,
    InfluxDbUser,
)
from ..i18n import tr
from .common import (
    CHECK_MARK,
    confirm,
    create_sql_editor,
    display_error,
    display_exception,
)


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class RequestControl(QWidget):
    """Base class for controls that can be hosted in a tab and executed."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.influx_client: Optional[InfluxDbClient] = None
        self.database: Optional[str] = None

    def execute_request(self) -> None:
        pass

    def _run(self, fn, on_success=None, on_error=None) -> None:
        """Run ``fn`` in the background, deliver result on the GUI thread,
        and display unexpected errors like the C# version does."""
        def err(ex):
            display_exception(ex, parent=self)
            if on_error is not None:
                on_error(ex)
        run_async(fn, on_success, err)


# ---------------------------------------------------------------------------
# Results table with CSV/JSON export (QueryResultsControl)
# ---------------------------------------------------------------------------

class _GridDelegate(QStyledItemDelegate):
    """Blocks the editor for cells that are not editable field columns."""

    def __init__(self, control: "QueryResultsControl"):
        super().__init__(control.table)
        self._control = control

    def createEditor(self, parent, option, index):
        if not self._control.is_editable_cell(index.row(), index.column()):
            return None
        return super().createEditor(parent, option, index)


class QueryResultsControl(RequestControl):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._results_count = 0
        self._last_result: Optional[InfluxDbSeries] = None
        self._series: Optional[InfluxDbSeries] = None
        self._columns: List[str] = []
        self._field_types: Dict[str, str] = {}
        self._tag_columns: set = set()
        self._edit_meta_loaded = False
        self._edit_meta_loading = False
        # (row, col) -> (original_text, typed_value) for cells edited by the user
        self._dirty: Dict[tuple, tuple] = {}
        # result-row indices staged for deletion (whole-row, DBeaver style)
        self._deleted_rows: set = set()
        # called whenever the dirty state (edits or staged deletes) changes
        self.on_dirty_changed = None
        # called to re-run the query (set by QueryControl)
        self.on_refresh = None
        self._guard = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Vertical)
        layout.addWidget(self.splitter)

        self.tags_edit = QLineEdit()
        self.tags_edit.setReadOnly(True)
        self.splitter.addWidget(self.tags_edit)

        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectItems)
        self.table.setEditTriggers(
            QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemChanged.connect(self._on_item_changed)
        # DBeaver-like blue selection
        self.table.setStyleSheet(
            "QTableWidget::item:selected {"
            " background-color: #2f6fd0; color: #ffffff; }")
        header = self.table.horizontalHeader()
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_header_menu)
        self.splitter.addWidget(self.table)
        self._delegate = _GridDelegate(self)
        self.table.setItemDelegate(self._delegate)

        self.splitter.setSizes([0, 400])
        self._sync_tag_panel()
        self._save_shortcut = QShortcut(QKeySequence.Save, self.table)
        self._save_shortcut.activated.connect(self.save_changes)
        self._delete_shortcut = QShortcut(QKeySequence.Delete, self.table)
        self._delete_shortcut.activated.connect(self.stage_delete_selected)

    def _notify_dirty(self) -> None:
        if callable(self.on_dirty_changed):
            self.on_dirty_changed()

    # -- header context menu (DBeaver-like) --------------------------------------

    def _show_header_menu(self, pos, chooser=None) -> None:
        """Show the header context menu; ``chooser(menu)`` replaces the modal
        ``exec`` (used by tests to pick an action programmatically)."""
        header = self.table.horizontalHeader()
        col = header.logicalIndexAt(pos)
        menu = QMenu(self)
        act_copy_name = menu.addAction(tr("grid.header.copy_name"))
        act_copy_all = menu.addAction(tr("grid.header.copy_all_names"))
        act_copy_name.setEnabled(col >= 0)
        menu.addSeparator()
        clean = not self._dirty and not self._deleted_rows
        act_sort_asc = menu.addAction(tr("grid.header.sort_asc"))
        act_sort_desc = menu.addAction(tr("grid.header.sort_desc"))
        act_sort_asc.setEnabled(clean and col > 0)
        act_sort_desc.setEnabled(clean and col > 0)
        menu.addSeparator()
        act_fit = menu.addAction(tr("grid.header.fit_width"))
        act_fit.setEnabled(col >= 0)
        act_hide = menu.addAction(tr("grid.header.hide_column"))
        act_hide.setEnabled(col > 0)
        act_show_all = menu.addAction(tr("grid.header.show_all_columns"))
        menu.addSeparator()
        act_refresh = menu.addAction(tr("grid.header.refresh"))
        act_refresh.setEnabled(self.on_refresh is not None)
        menu.addSeparator()
        act_export = menu.addAction(tr("query.export.all"))
        if chooser is not None:
            action = chooser(menu)
        else:
            action = menu.exec(header.viewport().mapToGlobal(pos))
        if action is act_copy_name:
            item = self.table.horizontalHeaderItem(col)
            if item is not None:
                QApplication.clipboard().setText(item.text())
        elif action is act_copy_all:
            names = [self.table.horizontalHeaderItem(c).text()
                     for c in range(1, self.table.columnCount())
                     if self.table.horizontalHeaderItem(c) is not None]
            QApplication.clipboard().setText(", ".join(names))
        elif action is act_sort_asc:
            self.sort_by_column(col, True)
        elif action is act_sort_desc:
            self.sort_by_column(col, False)
        elif action is act_fit:
            self.table.resizeColumnToContents(col)
        elif action is act_hide:
            self.table.hideColumn(col)
        elif action is act_show_all:
            for c in range(self.table.columnCount()):
                self.table.showColumn(c)
        elif action is act_refresh:
            if callable(self.on_refresh):
                self.on_refresh()
        elif action is act_export:
            self.export_rows_interactive(False)

    def sort_by_column(self, col: int, ascending: bool) -> None:
        """Sort the loaded rows of this page by a column (client-side).

        Disabled while edits/deletes are staged (row indexes must stay stable
        so dirty cells map to the right points). The underlying series rows are
        reordered together with the table, keeping row -> point mapping intact.
        """
        if self._series is None or self._dirty or self._deleted_rows:
            return
        if col <= 0 or col - 1 >= len(self._columns):
            return
        values = list(self._series.Values)
        idx = col - 1

        def key(i: int):
            v = values[i][idx] if idx < len(values[i]) else None
            if v is None:
                return (2, 0.0, "")
            try:
                return (0, float(v), "")
            except (TypeError, ValueError):
                return (1, 0.0, str(v))

        perm = sorted(range(len(values)), key=key, reverse=not ascending)
        self._series.Values = [values[i] for i in perm]
        self.table.setRowCount(0)
        self._results_count = 0
        self.update_results(self._series, clear=True)

    def _sync_tag_panel(self) -> None:
        visible = bool(self.tags_edit.text())
        self.tags_edit.setVisible(visible)
        self.splitter.setSizes([28 if visible else 0, 400])

    # -- context menu ---------------------------------------------------------

    def _show_context_menu(self, pos, chooser=None) -> None:
        """Show the grid body context menu; ``chooser(menu)`` replaces the
        modal ``exec`` (used by tests to pick an action programmatically)."""
        menu = QMenu(self)
        has_selection = len(self.table.selectedItems()) > 0
        act_copy = menu.addAction(tr("grid.copy"))
        act_paste = menu.addAction(tr("grid.paste"))
        act_copy.setEnabled(has_selection)
        act_paste.setEnabled(self._edit_meta_loaded and bool(
            QApplication.clipboard().text()))
        menu.addSeparator()
        selected_rows = {i.row() for i in self.table.selectedItems()}
        selected_rows = {r for r in selected_rows
                       if self._series is not None
                       and 0 <= r < len(self._series.Values)}
        act_delete = menu.addAction(
            tr("grid.delete_rows", n=len(selected_rows)))
        act_delete.setEnabled(bool(selected_rows))
        menu.addSeparator()
        dirty_rows = self._dirty_row_count()
        act_save = menu.addAction(tr("grid.save_changes", n=dirty_rows))
        act_revert = menu.addAction(tr("grid.revert_changes"))
        act_save.setEnabled(dirty_rows > 0)
        act_revert.setEnabled(dirty_rows > 0)
        menu.addSeparator()
        # 仅当选中了行（单行或多行）时显示导出入口；「导出全部」固定在编辑栏按钮上
        act_export_sel = None
        if has_selection:
            act_export_sel = menu.addAction(tr("query.export.selected"))
        if chooser is not None:
            action = chooser(menu)
        else:
            action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action is act_copy:
            self.copy_selection()
        elif action is act_paste:
            self.paste_clipboard()
        elif action is act_delete:
            self.stage_delete_selected()
        elif action is act_save:
            self.save_changes()
        elif action is act_revert:
            self.revert_changes()
        elif act_export_sel is not None and action is act_export_sel:
            self.export_rows_interactive(True)

    # -- cell editing (DBeaver-like) -------------------------------------------

    def is_editable_cell(self, row: int, col: int) -> bool:
        if col <= 0 or not self._edit_meta_loaded or self._series is None:
            return False
        if col - 1 >= len(self._columns):
            return False
        name = self._columns[col - 1]
        return name in self._field_types

    def _dirty_row_count(self) -> int:
        edited = {row for row, _col in self._dirty}
        return len(edited | self._deleted_rows)

    def _dirty_cell_count(self) -> int:
        return len(self._dirty)

    def _default_brush(self):
        return QTableWidgetItem().background()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._guard:
            return
        row, col = item.row(), item.column()
        if not self.is_editable_cell(row, col):
            return
        name = self._columns[col - 1]
        typed = query_tools.coerce_edited_value(
            item.text(), self._field_types.get(name))
        normalized = query_tools.format_cell_value(typed)
        key = (row, col)
        if key not in self._dirty:
            original = ""
            if self._series is not None and row < len(self._series.Values):
                values = self._series.Values[row]
                if col - 1 < len(values):
                    original = _cell_text(values[col - 1])
            self._dirty[key] = (original, typed)
        else:
            original = self._dirty[key][0]
            self._dirty[key] = (original, typed)
        if item.text() != normalized:
            self._guard = True
            item.setText(normalized)
            self._guard = False
        item.setBackground(QColor("#ffe9b3"))  # DBeaver-style dirty mark
        self._notify_dirty()

    # -- row deletion (staged, applied on save) ---------------------------------

    def stage_delete_selected(self) -> None:
        """Mark all fully/partially selected result rows for deletion."""
        rows = {i.row() for i in self.table.selectedItems()}
        rows = {r for r in rows
                if self._series is not None and 0 <= r < len(self._series.Values)}
        if not rows:
            return
        self._deleted_rows |= rows
        self._mark_deleted_rows()
        self._notify_dirty()

    def _mark_deleted_rows(self) -> None:
        brush = QColor("#ffd6d6")  # light red = staged for deletion
        self._guard = True
        try:
            for row in self._deleted_rows:
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item is not None:
                        item.setBackground(brush)
        finally:
            self._guard = False

    def _restore_row_backgrounds(self) -> None:
        self._guard = True
        try:
            for row in self._deleted_rows:
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item is None:
                        continue
                    dirty = any(r == row for (r, _c) in self._dirty)
                    item.setBackground(
                        QColor("#ffe9b3") if dirty else self._default_brush())
        finally:
            self._guard = False

    def copy_selection(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return
        rows = sorted({i.row() for i in items})
        cols = sorted({i.column() for i in items})
        lines = []
        for r in rows:
            cells = []
            for c in cols:
                it = self.table.item(r, c)
                cells.append(it.text() if it else "")
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))

    def paste_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if not text or not self._edit_meta_loaded:
            return
        start = self.table.currentIndex()
        if not start.isValid():
            return
        self._guard_paste = True
        try:
            for dr, line in enumerate(text.splitlines()):
                if not line:
                    continue
                for dc, value in enumerate(line.split("\t")):
                    row = start.row() + dr
                    col = start.column() + dc
                    if row >= self.table.rowCount() or col >= self.table.columnCount():
                        continue
                    if not self.is_editable_cell(row, col):
                        continue
                    item = self.table.item(row, col)
                    if item is None:
                        continue
                    item.setText(value)  # triggers _on_item_changed
        finally:
            self._guard_paste = False

    def revert_changes(self) -> None:
        self._guard = True
        try:
            for (row, col), (original, _typed) in list(self._dirty.items()):
                item = self.table.item(row, col)
                if item is not None:
                    item.setText(original)
                    item.setBackground(self._default_brush())
        finally:
            self._guard = False
            self._dirty.clear()
            self._restore_row_backgrounds()
            self._deleted_rows.clear()
            self._notify_dirty()

    def save_changes(self) -> None:
        """Second-confirmation save: overwrites + staged row deletions."""
        if (not self._dirty and not self._deleted_rows) or self._series is None:
            return
        per_row: Dict[int, Dict[str, Any]] = {}
        originals: Dict[tuple, str] = {}
        for (row, col), (original, typed) in self._dirty.items():
            per_row.setdefault(row, {})[self._columns[col - 1]] = typed
            originals[(row, col)] = original
        points: List[InfluxDbPoint] = []
        preview: List[str] = []
        for row in sorted(per_row):
            changes = per_row[row]
            point = query_tools.build_overwrite_point(
                self._series.Name, self._columns, self._tag_columns,
                self._series.Values[row], changes)
            if point is None:
                display_error(tr("grid.save.bad_row", row=row + 1), parent=self)
                return
            points.append(point)
            time_text = ""
            values = self._series.Values[row]
            if values:
                time_text = _cell_text(values[0])
            for col_name, new_value in changes.items():
                col = self._columns.index(col_name) + 1
                old_text = originals.get((row, col), "")
                preview.append(tr("grid.save.preview_line",
                                  row=row + 1, time=time_text,
                                  field=col_name, old=old_text,
                                  new=query_tools.format_cell_value(new_value)))
        delete_stmts: List[tuple] = []  # (row, time_text, statement)
        for row in sorted(self._deleted_rows):
            values = self._series.Values[row]
            if row in per_row:
                display_error(tr("grid.save.bad_row", row=row + 1), parent=self)
                return
            stmt = query_tools.build_delete_statement(
                self._series.Name, self._columns, self._tag_columns, values)
            if stmt is None:
                display_error(tr("grid.save.bad_row", row=row + 1), parent=self)
                return
            time_text = _cell_text(values[0]) if values else ""
            delete_stmts.append((row, time_text, stmt))
            preview.append(tr("grid.save.preview_delete",
                              row=row + 1, time=time_text))
        if not points and not delete_stmts:
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr("grid.save.confirm.title"))
        box.setIcon(QMessageBox.Question)
        shown = preview[:20]
        more = len(preview) - len(shown)
        detail = "\n".join(shown)
        if more > 0:
            detail += "\n" + tr("grid.save.confirm.more", n=more)
        box.setText(tr("grid.save.confirm.text",
                       rows=len(points), cells=len(preview) - len(delete_stmts),
                       deletes=len(delete_stmts)))
        box.setInformativeText(detail)
        box.setStandardButtons(QMessageBox.Save | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec() != QMessageBox.Save:
            return
        client = self.influx_client
        database = self.database
        n_points = len(points)
        n_deletes = len(delete_stmts)

        def work():
            if n_points:
                client.write(database, points=points)
            for _row, _time_text, stmt in delete_stmts:
                client.execute_command(database, stmt)
            return None

        def done(_response):
            self._dirty.clear()
            self._deleted_rows.clear()
            # remove deleted rows from the table (bottom-up keeps indexes valid)
            self._guard = True
            try:
                for row in sorted((r for r, _t, _s in delete_stmts),
                                  reverse=True):
                    self.table.removeRow(row)
            finally:
                self._guard = False
            # clear dirty highlights
            self._guard = True
            try:
                for r in range(self.table.rowCount()):
                    for c in range(self.table.columnCount()):
                        item = self.table.item(r, c)
                        if item is not None:
                            item.setBackground(self._default_brush())
            finally:
                self._guard = False
            self._notify_dirty()
            QMessageBox.information(
                self, tr("grid.save.success.title"),
                tr("grid.save.success", rows=n_points, deletes=n_deletes))

        self._run(work, done)

    # -- rendering ------------------------------------------------------------

    def clear_results(self) -> None:
        self._results_count = 0
        self.tags_edit.clear()
        self._dirty.clear()
        self._deleted_rows.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self._sync_tag_panel()
        self._notify_dirty()

    def _load_edit_meta(self) -> None:
        """Fetch field/tag keys so only true field columns are editable."""
        if self._edit_meta_loaded or self._edit_meta_loading:
            return
        if (self.influx_client is None or not self.database
                or self._series is None or not self._series.Name):
            self._edit_meta_loaded = True
            return
        self._edit_meta_loading = True

        def work():
            # returns (List[InfluxDbFieldKey], List[str])
            return (self.influx_client.get_field_keys(self.database,
                                                      self._series.Name),
                    self.influx_client.get_tag_keys(self.database,
                                                    self._series.Name))

        def done(result):
            self._edit_meta_loading = False
            self._edit_meta_loaded = True
            fields, tags = result
            self._field_types = {f.Name: getattr(f, "Type", "")
                                 for f in fields if f.Name in self._columns}
            self._tag_columns = set(tags) & set(self._columns)

        def failed(_ex):
            self._edit_meta_loading = False
            self._edit_meta_loaded = True  # stay read-only on error

        self._run(work, done, failed)

    def update_results(self, result: InfluxDbSeries, clear: bool = False) -> int:
        if result is None:
            raise ValueError("result cannot be None")
        self._last_result = result
        self._series = result
        self._dirty.clear()
        self._deleted_rows.clear()
        self._edit_meta_loaded = False
        self._edit_meta_loading = False
        self._field_types = {}
        self._tag_columns = set()
        if clear:
            self.clear_results()

        if result.Tags:
            self.tags_edit.setText(", ".join(f"{k} = {v}" for k, v in result.Tags.items()))
        else:
            self.tags_edit.clear()
        self._sync_tag_panel()

        self._columns = list(result.Columns)
        columns = ["#"] + self._columns
        start_row = self.table.rowCount() if not clear else 0
        self.table.setRowCount(start_row + len(result.Values))
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        self._guard = True
        try:
            for i, row_values in enumerate(result.Values):
                row = start_row + i
                num_item = QTableWidgetItem(str(self._results_count + 1))
                self.table.setItem(row, 0, num_item)
                self._results_count += 1
                for x, value in enumerate(row_values):
                    item = QTableWidgetItem(_cell_text(value))
                    item.setData(Qt.UserRole, row_values)
                    self.table.setItem(row, x + 1, item)
        finally:
            self._guard = False

        self._resize_columns()
        self._load_edit_meta()
        return self._results_count

    def _resize_columns(self) -> None:
        count = self.table.columnCount()
        if count <= 0:
            return
        width = max(96, int((self.table.width() - 12) / count))
        header = self.table.horizontalHeader()
        for i in range(count):
            self.table.setColumnWidth(i, width)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_columns()

    # -- export -----------------------------------------------------------------

    def _suggest_name(self, ext: str) -> str:
        name = f"{self.influx_client.connection.Name}_{self.database}"
        return f"{name}.{ext}"

    def _collect_rows(self, only_selected: bool) -> Tuple[List[str], List[list]]:
        columns = [self.table.horizontalHeaderItem(i).text()
                   for i in range(1, self.table.columnCount())]
        selected_rows = {i.row() for i in self.table.selectedItems()}
        rows: List[list] = []
        for row in range(self.table.rowCount()):
            if only_selected and row not in selected_rows:
                continue
            values = [self.table.item(row, col).text() if self.table.item(row, col) else ""
                      for col in range(1, self.table.columnCount())]
            rows.append(values)
        return columns, rows

    def export_rows_interactive(self, only_selected: bool = False) -> None:
        from .dialogs import run_export_dialog
        try:
            columns, rows = self._collect_rows(only_selected)
            run_export_dialog(self._suggest_name, columns, rows, parent=self)
        except Exception as ex:
            display_exception(ex, parent=self)


# ---------------------------------------------------------------------------
# Query control (QueryControl)
# ---------------------------------------------------------------------------

class QueryControl(RequestControl):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._results_count = 0
        # pagination state (DBeaver-like); page is 1-based
        self._page = 1
        self._page_size = query_tools.DEFAULT_PAGE_SIZE
        self._total: Optional[int] = None
        self._paginating = False
        self._loading = False
        # Query script identity (persisted across launches by the main window)
        self.script_name = ""
        self.script_connection_id = ""
        self.script_database: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        # Vertical splitter between the SQL editor and the results area,
        # so the user can drag the divider to resize both (like DBeaver).
        self.main_splitter = QSplitter(Qt.Vertical)
        layout.addWidget(self.main_splitter)

        self.editor = create_sql_editor(self)
        self.main_splitter.addWidget(self.editor)

        results_panel = QWidget()
        results_layout = QVBoxLayout(results_panel)
        results_layout.setContentsMargins(0, 2, 0, 0)

        self.results_label = QLabel()
        results_layout.addWidget(self.results_label)

        # -- pagination bar ---------------------------------------------------
        pager = QHBoxLayout()
        pager.setContentsMargins(4, 0, 4, 0)
        pager.addWidget(QLabel(tr("grid.page.size") + ":"))
        self.page_size_combo = QComboBox()
        for size in query_tools.PAGE_SIZE_CHOICES:
            self.page_size_combo.addItem(str(size), size)
        self.page_size_combo.addItem(tr("grid.page.all"), -1)
        self.page_size_combo.setCurrentIndex(1)  # DEFAULT_PAGE_SIZE
        # Editable like DBeaver: pick a preset or type an arbitrary page size.
        self.page_size_combo.setEditable(True)
        self.page_size_combo.setInsertPolicy(QComboBox.NoInsert)
        self.page_size_combo.lineEdit().setValidator(
            QIntValidator(1, 1_000_000, self.page_size_combo))
        self.page_size_combo.activated.connect(self._page_size_picked)
        self.page_size_combo.lineEdit().editingFinished.connect(
            self._page_size_typed)
        pager.addWidget(self.page_size_combo)
        self.btn_first = QPushButton("|<")
        self.btn_prev = QPushButton("<")
        self.btn_next = QPushButton(">")
        self.btn_last = QPushButton(">|")
        for btn in (self.btn_first, self.btn_prev, self.btn_next, self.btn_last):
            btn.setFixedWidth(40)
            pager.addWidget(btn)
        self.btn_first.clicked.connect(lambda: self._goto_page(1))
        self.btn_prev.clicked.connect(lambda: self._goto_page(self._page - 1))
        self.btn_next.clicked.connect(lambda: self._goto_page(self._page + 1))
        self.btn_last.clicked.connect(self._goto_last_page)
        self.page_rows_label = QLabel()
        pager.addWidget(self.page_rows_label, 1)
        self.pager_widget = QWidget()
        self.pager_widget.setLayout(pager)
        self.pager_widget.setVisible(False)
        results_layout.addWidget(self.pager_widget)

        # -- visible save/revert bar (DBeaver-like) -----------------------------
        edit_bar = QHBoxLayout()
        edit_bar.setContentsMargins(4, 2, 4, 0)
        self.btn_grid_save = QPushButton()
        self.btn_grid_revert = QPushButton()
        self.btn_grid_export = QPushButton(tr("query.export.all"))
        self.btn_grid_save.clicked.connect(self._save_current_grid)
        self.btn_grid_revert.clicked.connect(self._revert_current_grid)
        self.btn_grid_export.clicked.connect(self._export_current_grid)
        edit_bar.addWidget(self.btn_grid_save)
        edit_bar.addWidget(self.btn_grid_revert)
        edit_bar.addWidget(self.btn_grid_export)
        edit_bar.addStretch(1)
        self.edit_bar_widget = QWidget()
        self.edit_bar_widget.setLayout(edit_bar)
        self.edit_bar_widget.setVisible(False)
        results_layout.addWidget(self.edit_bar_widget)

        self.results_tabs = QTabWidget()
        self.results_tabs.currentChanged.connect(
            lambda _i: self._sync_edit_bar())
        results_layout.addWidget(self.results_tabs, 1)
        self.main_splitter.addWidget(results_panel)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 3)
        self.main_splitter.setSizes([220, 420])

    def _current_results_control(self):
        widget = self.results_tabs.currentWidget()
        return widget if isinstance(widget, QueryResultsControl) else None

    def _save_current_grid(self) -> None:
        control = self._current_results_control()
        if control is not None:
            control.save_changes()

    def _revert_current_grid(self) -> None:
        control = self._current_results_control()
        if control is not None:
            control.revert_changes()

    def _export_current_grid(self) -> None:
        control = self._current_results_control()
        if control is not None:
            control.export_rows_interactive(False)

    def _sync_edit_bar(self) -> None:
        control = self._current_results_control()
        # The bar always shows once a results grid exists (DBeaver-like);
        # the buttons are only enabled while there is something to save/revert.
        self.edit_bar_widget.setVisible(control is not None)
        if control is None:
            return
        n = control._dirty_row_count()
        self.btn_grid_save.setEnabled(n > 0)
        self.btn_grid_revert.setEnabled(n > 0)
        self.btn_grid_save.setText(tr("grid.save_changes", n=n))
        self.btn_grid_revert.setText(tr("grid.revert_changes"))

    # EditorText equivalent
    def get_editor_text(self) -> str:
        return self.editor.toPlainText()

    def set_editor_text(self, text: str) -> None:
        self.editor.setPlainText(text)

    editor_text = property(get_editor_text, set_editor_text)

    # -- pagination ------------------------------------------------------------

    def _current_query(self) -> str:
        return self.editor.toPlainText().strip()

    def _page_size_picked(self, index: int) -> None:
        self._apply_page_size(self.page_size_combo.itemData(index))

    def _page_size_typed(self) -> None:
        text = self.page_size_combo.lineEdit().text().strip()
        if text == tr("grid.page.all"):
            self._apply_page_size(-1)
            return
        try:
            size = int(text)
        except ValueError:
            size = None
        if size is None or not 1 <= size <= 1_000_000:
            # revert the box to the current effective page size
            self._show_page_size_in_combo()
            return
        self._apply_page_size(size)

    def _apply_page_size(self, size) -> None:
        if size != self._page_size:
            self._page_size = size
            self._page = 1
            self._show_page_size_in_combo()
            if self._paginating:
                self.execute_request()

    def _show_page_size_in_combo(self) -> None:
        if self._page_size > 0:
            self.page_size_combo.lineEdit().setText(str(self._page_size))
        else:
            self.page_size_combo.lineEdit().setText(tr("grid.page.all"))

    def _update_pager(self) -> None:
        visible = self._paginating and self._page_size > 0
        self.pager_widget.setVisible(visible)
        if not visible:
            return
        offset = (self._page - 1) * self._page_size
        start = offset + 1 if self._results_count else 0
        end = offset + self._results_count
        text = tr("grid.page.rows", start=start, end=end)
        if self._total is not None:
            text += " / " + tr("grid.page.total", n=self._total)
        else:
            text += " / " + tr("grid.page.total_unknown")
        self.page_rows_label.setText(text)
        self.btn_first.setEnabled(self._page > 1 and not self._loading)
        self.btn_prev.setEnabled(self._page > 1 and not self._loading)
        has_next = (self._total is not None and end < self._total) \
            or (self._total is None and self._results_count >= self._page_size)
        self.btn_next.setEnabled(has_next and not self._loading)
        last_page = (self._total + self._page_size - 1) // self._page_size \
            if self._total else None
        self.btn_last.setEnabled(last_page is not None and self._page < last_page
                                 and not self._loading)

    def _goto_page(self, page: int) -> None:
        page = max(1, page)
        if page != self._page:
            self._page = page
            self.execute_request()

    def _goto_last_page(self) -> None:
        if self._total and self._page_size > 0:
            self._goto_page((self._total + self._page_size - 1) // self._page_size)

    # -- execution -------------------------------------------------------------

    def execute_request(self) -> None:
        if self.influx_client is None:
            display_error("No InfluxDB client available.", parent=self)
            return
        if self._loading:
            return
        self._results_count = 0
        query = self._current_query()
        is_aggregate = "group by" in query.lower()
        while self.results_tabs.count():
            self.results_tabs.removeTab(0)
        self._sync_edit_bar()

        # Pagination: plain SELECTs without their own LIMIT get LIMIT/OFFSET.
        self._paginating = self._page_size > 0 and query_tools.can_paginate(query)
        effective_query = query
        if self._paginating:
            effective_query = query_tools.paginate_query(
                query, self._page_size, (self._page - 1) * self._page_size)
        else:
            self._page = 1
            self._total = None

        # Immediate feedback: the query runs on a worker thread, so show a
        # running indicator instead of looking frozen.
        self.results_label.setText(tr("query.running"))
        self._update_pager()
        self._loading = True

        started = time.perf_counter()

        def work():
            return self.influx_client.query(self.database, effective_query)

        def done(results):
            self._loading = False
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if results:
                tab_count = 0
                tab_label = tr("query.group") if is_aggregate else tr("query.results")
                for result in results:
                    tab_count += 1
                    control = QueryResultsControl()
                    control.influx_client = self.influx_client
                    control.database = self.database
                    control.on_dirty_changed = self._sync_edit_bar
                    control.on_refresh = self.execute_request
                    self.results_tabs.addTab(control, f"{tab_label} {tab_count}")
                    self._results_count += control.update_results(result)
            self.results_label.setText(tr(
                "query.results_label", count=self._results_count, ms=elapsed_ms))
            self._update_pager()
            self._maybe_load_total(query)

        def failed(_ex):
            self._loading = False
            self.results_label.setText("")
            self._update_pager()

        self._run(work, done, failed)

    def _maybe_load_total(self, query: str) -> None:
        """Fetch the total row count once — read-only COUNT(*) query."""
        if not self._paginating or self._total is not None:
            return
        count_query = query_tools.build_count_query(query)
        if not count_query:
            self._update_pager()
            return

        def work():
            return self.influx_client.query(self.database, count_query)

        def done(series_list):
            total = query_tools.parse_count_value(series_list)
            if total is not None and total >= 0:
                self._total = total
            self._update_pager()

        def failed(_ex):
            self._update_pager()

        self._run(work, done, failed)


# ---------------------------------------------------------------------------
# Measurement controls (MeasurementControl and family)
# ---------------------------------------------------------------------------

class MeasurementControl(RequestControl):
    """Base for the measurement-scoped explorers (series/tag keys/tag values/
    field keys) with CSV/JSON export."""

    export_file_name_stem = ""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.measurement: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.table = QTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table)

    # -- export context menu ------------------------------------------------------

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        has_selection = len(self.table.selectedItems()) > 0
        act_export_all = menu.addAction(tr("query.export.all"))
        act_export_sel = None
        if has_selection:
            act_export_sel = menu.addAction(tr("query.export.selected"))
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action is act_export_all:
            self.export_rows_interactive(False)
        elif act_export_sel is not None and action is act_export_sel:
            self.export_rows_interactive(True)

    def _suggest_name(self, ext: str) -> str:
        return f"{self.measurement}_{self.export_file_name_stem}.{ext}"

    def _collect_rows(self, only_selected: bool):
        columns = [self.table.horizontalHeaderItem(i).text()
                   for i in range(1, self.table.columnCount())]
        selected_rows = {i.row() for i in self.table.selectedItems()}
        rows = []
        for row in range(self.table.rowCount()):
            if only_selected and row not in selected_rows:
                continue
            values = [self.table.item(row, col).text() if self.table.item(row, col) else ""
                      for col in range(1, self.table.columnCount())]
            rows.append(values)
        return columns, rows

    def export_rows_interactive(self, only_selected: bool = False) -> None:
        from .dialogs import run_export_dialog
        try:
            columns, rows = self._collect_rows(only_selected)
            run_export_dialog(self._suggest_name, columns, rows, parent=self)
        except Exception as ex:
            display_exception(ex, parent=self)

    # -- execution ------------------------------------------------------------------

    def execute_request(self) -> None:
        if self.influx_client is None:
            display_error("No InfluxDB client available.", parent=self)
            return
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self._run(self.fetch_data, self.populate)

    def fetch_data(self) -> Any:
        """Runs on a worker thread; returns data for ``populate``."""
        return None

    def populate(self, data: Any) -> None:
        """Runs on the GUI thread; fills the table."""
        pass

    def _set_columns(self, headers: List[str]) -> None:
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

    def _add_row(self, cells: List[str], payload: Any) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        first = QTableWidgetItem(str(row + 1))
        first.setData(Qt.UserRole, payload)
        self.table.setItem(row, 0, first)
        for i, text in enumerate(cells):
            self.table.setItem(row, i + 1, QTableWidgetItem(text))

    def _resize_columns(self) -> None:
        count = self.table.columnCount()
        if count <= 0:
            return
        width = max(96, int((self.table.width() - 12) / count))
        for i in range(count):
            self.table.setColumnWidth(i, width)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_columns()


class SeriesControl(MeasurementControl):
    export_file_name_stem = "series"

    def fetch_data(self):
        return self.influx_client.get_series_names(self.database, self.measurement)

    def populate(self, series_names) -> None:
        series_names = list(series_names or [])
        if not series_names:
            return
        column_names: List[str] = []
        rows: List[Dict[str, str]] = []
        for series_name in series_names:
            values: Dict[str, str] = {}
            rows.append(values)
            for pair in series_name.split(","):
                pair = pair.strip()
                if not pair:
                    continue
                parsed = pair.split("=")
                name = parsed[0].strip()
                if name == self.measurement or len(parsed) == 1:
                    continue  # ignore measurement name
                value = parsed[1].strip()
                if name not in column_names:
                    column_names.append(name)
                values[name] = value
        self._set_columns(["#"] + column_names)
        for values in rows:
            self._add_row([values.get(name, "") for name in column_names], values)
        self._resize_columns()


class TagKeysControl(MeasurementControl):
    export_file_name_stem = "tag_keys"

    def fetch_data(self):
        return self.influx_client.get_tag_keys(self.database, self.measurement)

    def populate(self, tag_keys) -> None:
        tag_keys = list(tag_keys or [])
        if not tag_keys:
            return
        self._set_columns(["#", tr("tag_keys.column.tag_key")])
        for tag_key in tag_keys:
            self._add_row([tag_key], tag_key)
        self._resize_columns()


class TagValuesControl(MeasurementControl):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.tag_keys_combo = QComboBox()
        self.tag_keys_combo.currentIndexChanged.connect(lambda _i: self.execute_request())
        self.layout().insertWidget(0, self.tag_keys_combo)

    @property
    def export_file_name_stem(self) -> str:  # type: ignore[override]
        return f"tag_values_{self.tag_keys_combo.currentText()}"

    @export_file_name_stem.setter
    def export_file_name_stem(self, value) -> None:  # ignore base init assignment
        pass

    def fetch_data(self):
        if self.tag_keys_combo.count() == 0:
            tag_keys = self.influx_client.get_tag_keys(self.database, self.measurement)
            return ("keys", list(tag_keys or []))
        return ("values", self.tag_keys_combo.currentText())

    def populate(self, data) -> None:
        kind, payload = data
        if kind == "keys":
            if payload:
                self.tag_keys_combo.addItems(payload)
                self.tag_keys_combo.setCurrentIndex(0)
        else:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            selected_tag = payload
            if not selected_tag:
                return
            self._run(
                lambda: self.influx_client.get_tag_values(
                    self.database, self.measurement, selected_tag),
                self._populate_values)

    def _populate_values(self, tag_values) -> None:
        self._set_columns(["#", tr("tag_values.column.tag_value")])
        for tv in tag_values or []:
            self._add_row([tv.Value], {"Name": tv.Name, "Value": tv.Value})
        self._resize_columns()


class FieldKeysControl(MeasurementControl):
    export_file_name_stem = "field_keys"

    def fetch_data(self):
        return self.influx_client.get_field_keys(self.database, self.measurement)

    def populate(self, field_keys) -> None:
        field_keys = list(field_keys or [])
        if not field_keys:
            return
        self._set_columns(["#", tr("field_keys.column.field_key"),
                           tr("field_keys.column.field_type")])
        for fk in field_keys:
            self._add_row([fk.Name, fk.Type], {"Name": fk.Name, "Type": fk.Type})
        self._resize_columns()


# ---------------------------------------------------------------------------
# Users control (InfluxDbUsersControl)
# ---------------------------------------------------------------------------

class InfluxDbUsersControl(RequestControl):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.selected_user: Optional[InfluxDbUser] = None
        self.selected_privilege_grant: Optional[InfluxDbGrant] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        # -- users list ----------------------------------------------------------
        users_layout = QVBoxLayout()
        users_layout.addWidget(QLabel(tr("users.title")))

        self.users_table = QTableWidget()
        self.users_table.setColumnCount(2)
        self.users_table.setHorizontalHeaderLabels(
            [tr("users.column.user"), tr("users.column.admin")])
        self.users_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.users_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.users_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.users_table.itemSelectionChanged.connect(self._user_selection_changed)
        users_layout.addWidget(self.users_table)

        users_buttons = QHBoxLayout()
        self.create_user_button = QPushButton(tr("users.create"))
        self.edit_user_button = QPushButton(tr("users.edit"))
        self.change_password_button = QPushButton(tr("users.change_password"))
        self.drop_user_button = QPushButton(tr("users.drop"))
        self.create_user_button.clicked.connect(self.create_user)
        self.edit_user_button.clicked.connect(self.edit_user)
        self.change_password_button.clicked.connect(self.change_password)
        self.drop_user_button.clicked.connect(self.drop_user)
        for b in (self.create_user_button, self.edit_user_button,
                  self.change_password_button, self.drop_user_button):
            users_buttons.addWidget(b)
        users_layout.addLayout(users_buttons)
        layout.addLayout(users_layout, 1)

        # -- privileges list ------------------------------------------------------
        grants_layout = QVBoxLayout()
        grants_layout.addWidget(QLabel(tr("users.privileges")))

        self.grants_table = QTableWidget()
        self.grants_table.setColumnCount(4)
        self.grants_table.setHorizontalHeaderLabels([
            tr("users.column.database"), tr("users.column.read"),
            tr("users.column.write"), tr("users.column.all")])
        self.grants_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.grants_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.grants_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.grants_table.itemSelectionChanged.connect(self._grant_selection_changed)
        grants_layout.addWidget(self.grants_table)

        grants_buttons = QHBoxLayout()
        self.grant_privilege_button = QPushButton(tr("users.grant_privilege"))
        self.edit_privilege_button = QPushButton(tr("users.edit_privilege"))
        self.grant_privilege_button.clicked.connect(self.grant_privilege)
        self.edit_privilege_button.clicked.connect(self.edit_privilege)
        grants_buttons.addWidget(self.grant_privilege_button)
        grants_buttons.addWidget(self.edit_privilege_button)
        grants_layout.addLayout(grants_buttons)
        layout.addLayout(grants_layout, 1)

        self._update_ui_state()

    # -- selection ------------------------------------------------------------

    def _selected_row(self, table: QTableWidget):
        rows = sorted({i.row() for i in table.selectedItems()})
        return rows[0] if rows else -1

    def _user_selection_changed(self) -> None:
        row = self._selected_row(self.users_table)
        if row < 0:
            self.selected_user = None
            self.selected_privilege_grant = None
            self.grants_table.setRowCount(0)
        else:
            item = self.users_table.item(row, 0)
            self.selected_user = item.data(Qt.UserRole) if item else None
            self._bind_to_privileges(self.selected_user)
        self._update_ui_state()

    def _grant_selection_changed(self) -> None:
        row = self._selected_row(self.grants_table)
        if row < 0:
            self.selected_privilege_grant = None
        else:
            item = self.grants_table.item(row, 0)
            self.selected_privilege_grant = item.data(Qt.UserRole) if item else None
        self._update_ui_state()

    def _update_ui_state(self) -> None:
        user = self.selected_user
        self.edit_user_button.setEnabled(user is not None)
        self.change_password_button.setEnabled(user is not None)
        self.drop_user_button.setEnabled(user is not None)
        grant = self.selected_privilege_grant
        self.grant_privilege_button.setEnabled(user is not None)
        self.edit_privilege_button.setEnabled(grant is not None)

    # -- rendering -------------------------------------------------------------

    def execute_request(self) -> None:
        self._run(self.influx_client.get_users, self._populate_users)

    def _populate_users(self, users) -> None:
        self.users_table.setRowCount(0)
        for user in users or []:
            row = self.users_table.rowCount()
            self.users_table.insertRow(row)
            name_item = QTableWidgetItem(user.Name)
            name_item.setData(Qt.UserRole, user)
            self.users_table.setItem(row, 0, name_item)
            self.users_table.setItem(row, 1, QTableWidgetItem(
                CHECK_MARK if user.IsAdmin else ""))
        if self.selected_user is not None:
            for row in range(self.users_table.rowCount()):
                item = self.users_table.item(row, 0)
                if item and item.text() == self.selected_user.Name:
                    self.users_table.selectRow(row)
                    break

    def _bind_to_privileges(self, user: InfluxDbUser) -> None:
        self.grants_table.setRowCount(0)
        if user is None:
            return
        if user.IsAdmin:
            self.grants_table.setEnabled(False)
            return
        self.grants_table.setEnabled(True)
        self._run(lambda: self.influx_client.get_privileges(user.Name),
                  self._populate_grants)

    def _populate_grants(self, privileges) -> None:
        for p in privileges or []:
            row = self.grants_table.rowCount()
            self.grants_table.insertRow(row)
            db_item = QTableWidgetItem(p.Database)
            db_item.setData(Qt.UserRole, p)
            self.grants_table.setItem(row, 0, db_item)
            self.grants_table.setItem(row, 1, QTableWidgetItem(
                CHECK_MARK if p.Privilege == InfluxDbPrivileges.Read else ""))
            self.grants_table.setItem(row, 2, QTableWidgetItem(
                CHECK_MARK if p.Privilege == InfluxDbPrivileges.Write else ""))
            self.grants_table.setItem(row, 3, QTableWidgetItem(
                CHECK_MARK if p.Privilege == InfluxDbPrivileges.All else ""))
        if self.selected_privilege_grant is not None:
            database = self.selected_privilege_grant.Database
            for row in range(self.grants_table.rowCount()):
                item = self.grants_table.item(row, 0)
                if item and item.text() == database:
                    self.grants_table.selectRow(row)
                    break

    # -- user commands ------------------------------------------------------------

    def create_user(self) -> None:
        from .dialogs import CreateUserDialog
        dialog = CreateUserDialog(self)
        dialog.clear_create_values()
        if dialog.exec() != CreateUserDialog.Accepted:
            return
        user = dialog.create_user_from_dialog()
        if user is None:
            return
        for row in range(self.users_table.rowCount()):
            if self.users_table.item(row, 0).text() == user.Name:
                display_error(tr("users.create_error", name=user.Name),
                              tr("error"), self)
                return

        def work():
            return self.influx_client.create_user(user.Name, dialog.password_text(),
                                                  user.IsAdmin)

        def done(response):
            if response.Success:
                self.selected_user = user
                self.execute_request()
            else:
                display_error(response.Body, parent=self)
            self._update_ui_state()

        self._run(work, done)

    def edit_user(self) -> None:
        from .dialogs import EditUserDialog
        user = self.selected_user
        if user is None:
            return
        dialog = EditUserDialog(self)
        dialog.bind_to_user(user)
        if dialog.exec() != EditUserDialog.Accepted:
            return
        updated = dialog.create_user_from_dialog()
        if user.IsAdmin == updated.IsAdmin:
            return

        def work():
            if updated.IsAdmin:
                return self.influx_client.grant_administrator(updated.Name)
            return self.influx_client.revoke_administrator(updated.Name)

        def done(response):
            if response.Success:
                self.execute_request()
            else:
                display_error(response.Body, parent=self)
            self._update_ui_state()

        self._run(work, done)

    def change_password(self) -> None:
        from .dialogs import UserPasswordDialog
        user = self.selected_user
        if user is None:
            return
        dialog = UserPasswordDialog(self)
        dialog.bind_to_user(user)
        if dialog.exec() != UserPasswordDialog.Accepted:
            return
        self._run(
            lambda: self.influx_client.set_password(user.Name, dialog.password_text()),
            lambda response: (not response.Success
                              and display_error(response.Body, parent=self)))

    def drop_user(self) -> None:
        user = self.selected_user
        if user is None:
            return
        if not confirm(self, tr("drop.user.confirm", name=user.Name),
                       tr("drop.user.title")):
            return

        def done(response):
            if response.Success:
                self.selected_user = None
                self.execute_request()
            else:
                display_error(response.Body, parent=self)
            self._update_ui_state()

        self._run(lambda: self.influx_client.drop_user(user.Name), done)

    def grant_privilege(self) -> None:
        from .dialogs import GrantPrivilegeDialog
        user = self.selected_user
        if user is None:
            return
        dialog = GrantPrivilegeDialog(self)
        dialog.influx_client = self.influx_client
        dialog.bind_to_user(user)

        def bind_dbs(db_names):
            dialog.bind_databases(db_names)
            if dialog.exec() != GrantPrivilegeDialog.Accepted:
                return
            database = dialog.selected_database()
            privilege = dialog.selected_privilege()
            if not database:
                display_error(tr("users.grant.blank_db"), parent=self)
                return
            if privilege == InfluxDbPrivileges.None_:
                return

            def done(response):
                if response.Success:
                    self.execute_request()
                else:
                    display_error(response.Body, parent=self)
                self._update_ui_state()

            self._run(lambda: self.influx_client.grant_privilege(
                user.Name, privilege, database), done)

        self._run(lambda: self.influx_client.get_database_names(), bind_dbs)

    def edit_privilege(self) -> None:
        from .dialogs import EditPrivilegeDialog
        user = self.selected_user
        grant = self.selected_privilege_grant
        if user is None or grant is None:
            return
        dialog = EditPrivilegeDialog(self)
        dialog.bind_to_grant(user.Name, grant)
        if dialog.exec() != EditPrivilegeDialog.Accepted:
            return
        database = dialog.database
        privilege = dialog.selected_privilege()
        if not database:
            display_error(tr("users.grant.blank_db"), parent=self)
            return

        def work():
            if privilege == InfluxDbPrivileges.None_:
                return self.influx_client.revoke_privilege(
                    user.Name, grant.Privilege, database)
            return self.influx_client.grant_privilege(user.Name, privilege, database)

        def done(response):
            if response.Success:
                self.execute_request()
            else:
                display_error(response.Body, parent=self)
            self._update_ui_state()

        self._run(work, done)


# ---------------------------------------------------------------------------
# Retention policy control (RetentionPolicyControl)
# ---------------------------------------------------------------------------

class RetentionPolicyControl(RequestControl):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.selected_database: Optional[str] = None
        self.selected_policy: Optional[InfluxDbRetentionPolicy] = None
        self._policies: List[InfluxDbRetentionPolicy] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        top = QHBoxLayout()
        top.addWidget(QLabel(tr("rp.database")))
        self.database_combo = QComboBox()
        self.database_combo.currentIndexChanged.connect(self._database_changed)
        top.addWidget(self.database_combo, 1)
        layout.addLayout(top)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            tr("rp.column.name"), tr("rp.column.duration"),
            tr("rp.column.shard_group"), tr("rp.column.replication"),
            tr("rp.column.default")])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.create_button = QPushButton(tr("rp.create"))
        self.alter_button = QPushButton(tr("rp.alter"))
        self.drop_button = QPushButton(tr("rp.drop"))
        self.create_button.clicked.connect(self.show_create_policy)
        self.alter_button.clicked.connect(self.show_alter_policy)
        self.drop_button.clicked.connect(self.show_drop_policy)
        for b in (self.create_button, self.alter_button, self.drop_button):
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self._update_ui_state()

    def _selected_row(self) -> int:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return rows[0] if rows else -1

    def _database_changed(self) -> None:
        if self.database_combo.count() == 0 or self.database_combo.currentIndex() < 0:
            return
        self.selected_database = self.database_combo.currentText()
        self._bind_selected_policy()

    def _selection_changed(self) -> None:
        row = self._selected_row()
        if row < 0:
            self.selected_policy = None
        else:
            item = self.table.item(row, 0)
            self.selected_policy = item.data(Qt.UserRole) if item else None
        self._update_ui_state()

    def _update_ui_state(self) -> None:
        has_selection = self._selected_row() >= 0
        self.alter_button.setEnabled(has_selection)
        self.drop_button.setEnabled(self.table.rowCount() > 1 and has_selection)

    # -- rendering -------------------------------------------------------------

    def execute_request(self) -> None:
        self.table.setRowCount(0)
        self.database_combo.clear()

        def done(db_names):
            configured = self.influx_client.connection.Database
            if configured:
                self.database_combo.addItem(configured)
            else:
                self.database_combo.addItems(list(db_names or []))
            if self.selected_database is None:
                if self.database_combo.count() > 0:
                    self.database_combo.setCurrentIndex(0)
                    self.selected_database = self.database_combo.currentText()
            else:
                index = self.database_combo.findText(self.selected_database)
                if index >= 0:
                    self.database_combo.setCurrentIndex(index)

        self._run(lambda: self.influx_client.get_database_names(), done)

    def _bind_selected_policy(self) -> None:
        self.table.setRowCount(0)
        if not self.selected_database:
            return
        self._run(
            lambda: self.influx_client.get_retention_policies(self.selected_database),
            self._populate_policies)

    def _populate_policies(self, policies) -> None:
        self._policies = list(policies or [])
        for rp in self._policies:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(rp.Name)
            name_item.setData(Qt.UserRole, rp)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(rp.Duration))
            self.table.setItem(row, 2, QTableWidgetItem(rp.ShardGroupDuration))
            self.table.setItem(row, 3, QTableWidgetItem(str(rp.ReplicationCopies)))
            self.table.setItem(row, 4, QTableWidgetItem(CHECK_MARK if rp.Default else ""))
        if self.selected_policy is not None:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item and item.text() == self.selected_policy.Name:
                    self.table.selectRow(row)
                    break
        self._update_ui_state()

    # -- commands -----------------------------------------------------------------

    def show_create_policy(self) -> None:
        from .dialogs import RetentionPolicyDialog
        dialog = RetentionPolicyDialog(self)
        dialog.reset_policy_values()
        if dialog.exec() != RetentionPolicyDialog.Accepted:
            return

        def done(response):
            if not response.Success:
                display_error(response.Body, parent=self)
            self.execute_request()

        self._run(lambda: self.influx_client.create_retention_policy(
            self.selected_database, dialog.policy_name(), dialog.policy_duration(),
            dialog.policy_replication(), dialog.policy_default()), done)

    def show_alter_policy(self) -> None:
        from .dialogs import RetentionPolicyDialog
        policy = self.selected_policy
        if policy is None or not self.selected_database:
            return
        prev_is_default = policy.Default
        dialog = RetentionPolicyDialog(self)
        dialog.reset_policy_values()
        dialog.bind_to_policy(policy)
        if dialog.exec() != RetentionPolicyDialog.Accepted:
            return

        def work():
            response = self.influx_client.alter_retention_policy(
                self.selected_database, dialog.policy_name(),
                dialog.policy_duration(), dialog.policy_replication(),
                dialog.policy_default())
            if not response.Success:
                return response
            if prev_is_default and not dialog.policy_default():
                policies = self.influx_client.get_retention_policies(
                    self.selected_database)
                rp = next((r for r in policies if r.Name.lower() == "autogen"), None)
                if rp is None:
                    rp = next((r for r in policies if r.Name != policy.Name), None)
                if rp is not None:
                    self.influx_client.alter_retention_policy(
                        self.selected_database, rp.Name, rp.Duration,
                        rp.ReplicationCopies, True)
            return response

        def done(response):
            if not response.Success:
                display_error(response.Body, parent=self)
            self.execute_request()

        self._run(work, done)

    def show_drop_policy(self) -> None:
        policy = self.selected_policy
        if policy is None or not self.selected_database:
            return
        was_default = policy.Default
        if not confirm(self, tr("drop.rp.confirm", name=policy.Name), tr("drop.title")):
            return

        def work():
            response = self.influx_client.drop_retention_policy(
                self.selected_database, policy.Name)
            if not response.Success:
                return response
            if was_default:
                policies = self.influx_client.get_retention_policies(
                    self.selected_database)
                rp = next((r for r in policies if r.Name.lower() == "autogen"), None)
                if rp is None:
                    rp = next((r for r in policies if r.Name != policy.Name), None)
                if rp is not None:
                    self.influx_client.alter_retention_policy(
                        self.selected_database, rp.Name, rp.Duration,
                        rp.ReplicationCopies, True)
            return response

        def done(response):
            if not response.Success:
                display_error(response.Body, parent=self)
            self.execute_request()

        self._run(work, done)


# ---------------------------------------------------------------------------
# Continuous queries control (ContinuousQueryControl)
# ---------------------------------------------------------------------------

def format_cq_query(query: str) -> str:
    query = query.replace(" BEGIN", "\nBEGIN")
    query = query.replace(" RESAMPLE", "\nRESAMPLE")
    query = query.replace(" SELECT", "\n\tSELECT")
    query = query.replace(" END", "\nEND")
    return query


class ContinuousQueryControl(RequestControl):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.selected_cq: Optional[InfluxDbContinuousQuery] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.table = QTableWidget()
        self.table.setColumnCount(1)
        self.table.setHorizontalHeaderLabels([tr("cq.title")])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)

        self.editor = create_sql_editor(self)
        self.editor.setReadOnly(True)
        layout.addWidget(self.editor, 1)

        buttons = QHBoxLayout()
        self.create_cq_button = QPushButton(tr("cq.create"))
        self.drop_cq_button = QPushButton(tr("cq.drop"))
        self.backfill_button = QPushButton(tr("cq.run_backfill"))
        self.create_cq_button.clicked.connect(self.create_continuous_query)
        self.drop_cq_button.clicked.connect(self.drop_continuous_query)
        self.backfill_button.clicked.connect(self.run_backfill)
        for b in (self.create_cq_button, self.drop_cq_button, self.backfill_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._update_ui_state()

    def _selected_row(self) -> int:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return rows[0] if rows else -1

    def _selection_changed(self) -> None:
        row = self._selected_row()
        if row < 0:
            self.selected_cq = None
            self.editor.setPlainText("")
        else:
            item = self.table.item(row, 0)
            self.selected_cq = item.data(Qt.UserRole) if item else None
            self.editor.setPlainText(
                format_cq_query(self.selected_cq.Query) if self.selected_cq else "")
        self._update_ui_state()

    def _update_ui_state(self) -> None:
        enabled = self._selected_row() >= 0
        self.drop_cq_button.setEnabled(enabled)

    def execute_request(self) -> None:
        self.table.setRowCount(0)
        self.editor.setPlainText("")
        if not self.database:
            return

        def done(cq_list):
            for cq in cq_list or []:
                row = self.table.rowCount()
                self.table.insertRow(row)
                item = QTableWidgetItem(cq.Name)
                item.setData(Qt.UserRole, cq)
                self.table.setItem(row, 0, item)
            if self.selected_cq is not None:
                for row in range(self.table.rowCount()):
                    item = self.table.item(row, 0)
                    if item and item.text() == self.selected_cq.Name:
                        self.table.selectRow(row)
                        break

        self._run(lambda: self.influx_client.get_continuous_queries(self.database), done)

    def create_continuous_query(self) -> None:
        from .dialogs import CreateContinuousQueryDialog
        dialog = CreateContinuousQueryDialog(self)
        dialog.reset_cq_form()
        dialog.influx_client = self.influx_client
        dialog.database = self.database

        def bind_sources(measurement_names):
            dialog.bind_influx_data_sources(measurement_names)
            if dialog.exec() != CreateContinuousQueryDialog.Accepted:
                return
            cq_params = dialog.cq_result

            def done(response):
                if response.Success:
                    self.execute_request()
                else:
                    display_error(response.Body, parent=self)
                self._update_ui_state()

            self._run(lambda: self.influx_client.create_continuous_query(cq_params), done)

        self._run(lambda: self.influx_client.get_measurement_names(self.database),
                  bind_sources)

    def drop_continuous_query(self) -> None:
        if self.selected_cq is None or self.database is None:
            return
        if not confirm(self, tr("drop.cq.confirm", name=self.selected_cq.Name),
                       tr("drop.title")):
            return

        def done(response):
            if response.Success:
                self.selected_cq = None
                self.execute_request()
            else:
                display_error(response.Body, parent=self)
            self._update_ui_state()

        self._run(lambda: self.influx_client.drop_continuous_query(
            self.database, self.selected_cq.Name), done)

    def run_backfill(self) -> None:
        from ..app import run_backfill_command
        run_backfill_command()


# ---------------------------------------------------------------------------
# Running queries control (RunningQueriesControl)
# ---------------------------------------------------------------------------

class RunningQueriesControl(RequestControl):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.selected_query: Optional[InfluxDbRunningQuery] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            tr("rq.column.pid"), tr("rq.column.duration"),
            tr("rq.column.database"), tr("rq.column.query")])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)

        self.editor = create_sql_editor(self)
        self.editor.setReadOnly(True)
        layout.addWidget(self.editor, 1)

        buttons = QHBoxLayout()
        self.kill_query_button = QPushButton(tr("rq.kill_query"))
        self.kill_query_button.clicked.connect(self.kill_query)
        buttons.addWidget(self.kill_query_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._update_ui_state()

    def _selected_row(self) -> int:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return rows[0] if rows else -1

    def _selection_changed(self) -> None:
        row = self._selected_row()
        if row < 0:
            self.editor.setPlainText("")
            self.selected_query = None
        else:
            item = self.table.item(row, 0)
            self.selected_query = item.data(Qt.UserRole) if item else None
            self.editor.setPlainText(
                self.selected_query.Query if self.selected_query else "")
        self._update_ui_state()

    def _update_ui_state(self) -> None:
        self.kill_query_button.setEnabled(self._selected_row() >= 0)

    def execute_request(self) -> None:
        if self.influx_client is None:
            display_error("No InfluxDB client available.", parent=self)
            return

        def done(queries):
            self.table.setRowCount(0)
            for q in queries or []:
                row = self.table.rowCount()
                self.table.insertRow(row)
                pid_item = QTableWidgetItem(str(q.PID))
                pid_item.setData(Qt.UserRole, q)
                self.table.setItem(row, 0, pid_item)
                self.table.setItem(row, 1, QTableWidgetItem(q.Duration))
                self.table.setItem(row, 2, QTableWidgetItem(q.Database))
                self.table.setItem(row, 3, QTableWidgetItem(q.Query))
            if self.selected_query is not None:
                pid = str(self.selected_query.PID)
                for row in range(self.table.rowCount()):
                    item = self.table.item(row, 0)
                    if item and item.text() == pid:
                        self.table.selectRow(row)
                        self.selected_query = item.data(Qt.UserRole)
                        break
            self._update_ui_state()

        self._run(self.influx_client.get_running_queries, done)

    def kill_query(self) -> None:
        row = self._selected_row()
        if row < 0:
            return
        item = self.table.item(row, 0)
        running = item.data(Qt.UserRole) if item else None
        if running is None:
            return

        def done(response):
            if not response.Success and "query interrupted" not in response.Body:
                display_error(response.Body, parent=self)
            else:
                self.table.removeRow(row)
            self._update_ui_state()

        self._run(lambda: self.influx_client.kill_query(running.PID), done)


# ---------------------------------------------------------------------------
# Diagnostics control (DiagnosticsControl)
# ---------------------------------------------------------------------------

_UPTIME_PART_RE = re.compile(r"(\d+(?:\.\d+)?)(ns|us|µs|ms|h|m|s|d)")


def _parse_uptime(uptime: str) -> str:
    """Parse a Go-style duration ("1h34m20.5s") into the C# TimeSpan display
    format "{d}d {h}h {m}m {s}s {ms}ms". Falls back to the raw string."""
    if not uptime:
        return "-"
    total_ms = 0.0
    matched = False
    factors = {"ns": 1e-6, "us": 1e-3, "µs": 1e-3, "ms": 1.0,
               "s": 1000.0, "m": 60000.0, "h": 3600000.0, "d": 86400000.0}
    for value, unit in _UPTIME_PART_RE.findall(uptime):
        matched = True
        total_ms += float(value) * factors[unit]
    if not matched:
        return uptime
    total_ms = int(total_ms)
    days, rem = divmod(total_ms, 86400000)
    hours, rem = divmod(rem, 3600000)
    minutes, rem = divmod(rem, 60000)
    seconds, millis = divmod(rem, 1000)
    return f"{days}d {hours}h {minutes}m {seconds}s {millis}ms"


class DiagnosticsControl(RequestControl):
    FIELDS = [
        ("diag.pid", "PID"),
        ("diag.current_time", "CurrentTime"),
        ("diag.started", "Started"),
        ("diag.uptime", "Uptime"),
        ("diag.branch", "Branch"),
        ("diag.commit", "Commit"),
        ("diag.build_version", "BuildVersion"),
        ("diag.go_arch", "GoArch"),
        ("diag.go_max_procs", "GoMaxProc"),
        ("diag.go_os", "GoOs"),
        ("diag.go_version", "GoVersion"),
        ("diag.hostname", "Hostname"),
    ]

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 8, 8, 8)
        self._value_labels: Dict[str, QLabel] = {}
        for row, (label_key, attr) in enumerate(self.FIELDS):
            grid.addWidget(QLabel(tr(label_key)), row, 0, Qt.AlignRight)
            value = QLabel("-")
            self._value_labels[attr] = value
            grid.addWidget(value, row, 1, Qt.AlignLeft)
        grid.setColumnStretch(1, 1)

    def execute_request(self) -> None:
        if self.influx_client is None:
            display_error("No InfluxDB client available.", parent=self)
            return
        self._run(self.influx_client.get_diagnostics, self._populate)

    def _populate(self, diagnostics) -> None:
        blank = "-"
        values = {
            "PID": str(diagnostics.PID) if diagnostics.PID != "" else blank,
            "CurrentTime": diagnostics.CurrentTime or blank,
            "Started": diagnostics.Started or blank,
            "Uptime": _parse_uptime(diagnostics.Uptime),
            "Branch": diagnostics.Branch or blank,
            "Commit": diagnostics.Commit or blank,
            "BuildVersion": diagnostics.BuildVersion or blank,
            "GoArch": diagnostics.GoArch or blank,
            "GoMaxProc": str(diagnostics.GoMaxProc) if diagnostics.GoMaxProc != "" else blank,
            "GoOs": diagnostics.GoOs or blank,
            "GoVersion": diagnostics.GoVersion or blank,
            "Hostname": diagnostics.Hostname or blank,
        }
        for attr, label in self._value_labels.items():
            label.setText(values.get(attr, blank))


# ---------------------------------------------------------------------------
# Stats control (StatsControl)
# ---------------------------------------------------------------------------

class StatsControl(RequestControl):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.selected_statistic: Optional[str] = None
        self._current_statistics = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.stats_combo = QComboBox()
        self.stats_combo.currentIndexChanged.connect(self._statistic_changed)
        layout.addWidget(self.stats_combo)

        self.results_tabs = QTabWidget()
        layout.addWidget(self.results_tabs, 1)

    def _statistic_changed(self) -> None:
        last = self.selected_statistic
        self.selected_statistic = self.stats_combo.currentText() or None
        if last != self.selected_statistic:
            self._bind_selected_stats()

    def execute_request(self) -> None:
        if self.influx_client is None:
            display_error("No InfluxDB client available.", parent=self)
            return
        self.stats_combo.clear()
        while self.results_tabs.count():
            self.results_tabs.removeTab(0)
        self._run(self.influx_client.get_stats, self._populate)

    def _populate(self, stats) -> None:
        self._current_statistics = stats
        for name, group in stats.groups().items():
            if not group:
                continue  # no results / not supported
            self.stats_combo.addItem(name)
        if self.selected_statistic:
            index = self.stats_combo.findText(self.selected_statistic)
            if index >= 0:
                self.stats_combo.setCurrentIndex(index)
                self._bind_selected_stats()
        elif self.stats_combo.count() > 0:
            self.stats_combo.setCurrentIndex(0)

    def _bind_selected_stats(self) -> None:
        while self.results_tabs.count():
            self.results_tabs.removeTab(0)
        if not self.selected_statistic or self.stats_combo.currentIndex() < 0:
            return
        stats = self._current_statistics
        if stats is None:
            return
        stat_results = stats.groups().get(self.selected_statistic)
        if not stat_results:
            return
        tab_count = 0
        for series in stat_results:
            tab_count += 1
            control = QueryResultsControl()
            control.influx_client = self.influx_client
            self.results_tabs.addTab(control, f"{series.Name} {tab_count}")
            control.update_results(series)
