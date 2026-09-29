"""Main application window (port of AppForm.cs)."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QSplitter,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import app
from ..core.async_utils import run_async
from ..core.client import InfluxDbClient, TREE_LOAD_TIMEOUT, create_client
from ..core.models import InfluxDbConnection
from ..core.settings import LANG_EN_US, LANG_ZH_CN
from ..i18n import tr
from . import controls
from .common import confirm, display_error, display_exception, load_icon
from .dialogs import (
    AboutDialog,
    BackfillDialog,
    CreateDatabaseDialog,
    ManageConnectionsDialog,
)


class NodeType:
    LoadingPlaceholder = 0
    Connection = 1
    Database = 2
    Measurement = 3
    Error = 4


NODE_ICONS = {
    NodeType.Connection: "Connection",
    NodeType.Database: "Database",
    NodeType.Measurement: "Measurement",
}

NODE_TYPE_ROLE = Qt.UserRole
CONNECTION_ROLE = Qt.UserRole + 1


class MainWindow(QMainWindow):
    def __init__(self, show_connections_on_load: bool = True):
        super().__init__()
        self.setWindowTitle(tr("app.title"))
        self.resize(1100, 700)

        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_central()
        self._create_statusbar()

        app.main_window = self

        # Load settings and apply them
        app.settings.load_all()
        self._apply_settings()
        self._restore_query_scripts()

        self.update_ui_state()

        if show_connections_on_load:
            if app.settings.connections:
                # Saved connections exist: render them into the tree directly
                # instead of popping the connection manager dialog.
                for connection in app.settings.connections:
                    self.render_connection_node(connection)
            else:
                QTimer.singleShot(250, self.show_connections_dialog)

    # ==========================================================================
    # UI construction
    # ==========================================================================

    def _create_actions(self):
        def act(key, icon, shortcut=None, handler=None, checkable=False):
            action = QAction(load_icon(icon), tr(key), self)
            if shortcut:
                action.setShortcut(shortcut)
            action.setCheckable(checkable)
            if handler:
                action.triggered.connect(handler)
            return action

        self.action_import_settings = act(
            "menu.file.import_settings", "Connection",
            handler=lambda _=False: self.import_settings(show_connections_dialog=True))
        self.action_export_settings = act(
            "menu.file.export_settings", "Connection",
            handler=lambda _=False: self.export_settings())
        self.action_exit = act("menu.file.exit", "Disconnect",
                               handler=lambda _=False: self.close())

        self.action_manage_connections = act(
            "menu.connections.manage", "Connection",
            handler=lambda _=False: self.show_connections_dialog())

        self.action_new_query = act("menu.query.new", "NewQuery",
                                    handler=lambda _=False: self._with_selected_node(self.new_query))
        self.action_run_query = act("menu.query.run", "RunQuery",
                                    shortcut="Ctrl+Return",
                                    handler=lambda _=False: self.execute_current_request())
        # Qt 主键区回车是 Key_Return，小键盘回车才是 Key_Enter，两者都绑定
        self.action_run_query.setShortcuts(["Ctrl+Return", "Ctrl+Enter"])
        self.action_show_queries = act("menu.query.show_queries", "ShowQueries",
                                       handler=lambda _=False: self._with_selected_node(self.show_queries))

        self.action_time_12h = act("menu.settings.time_format.12h", "Time",
                                   checkable=True)
        self.action_time_24h = act("menu.settings.time_format.24h", "Time",
                                   checkable=True)
        self.action_time_12h.triggered.connect(
            lambda _=False: app.settings.set_time_format_12h())
        self.action_time_24h.triggered.connect(
            lambda _=False: app.settings.set_time_format_24h())
        time_group = QActionGroup(self)
        time_group.addAction(self.action_time_12h)
        time_group.addAction(self.action_time_24h)
        time_group.setExclusive(True)

        self.action_date_month_first = act("menu.settings.date_format.month_first",
                                           "Date", checkable=True)
        self.action_date_day_first = act("menu.settings.date_format.day_first",
                                         "Date", checkable=True)
        self.action_date_month_first.triggered.connect(
            lambda _=False: app.settings.set_date_format_month_first())
        self.action_date_day_first.triggered.connect(
            lambda _=False: app.settings.set_date_format_day_first())
        date_group = QActionGroup(self)
        date_group.addAction(self.action_date_month_first)
        date_group.addAction(self.action_date_day_first)
        date_group.setExclusive(True)

        self.action_allow_untrusted_ssl = act(
            "menu.settings.allow_untrusted_ssl", "Info", checkable=True)
        self.action_allow_untrusted_ssl.toggled.connect(self._allow_untrusted_ssl_changed)

        self.action_lang_zh = act("menu.settings.language.zh_CN", "Info", checkable=True)
        self.action_lang_en = act("menu.settings.language.en_US", "Info", checkable=True)
        self.action_lang_zh.triggered.connect(lambda _=False: self._language_changed(LANG_ZH_CN))
        self.action_lang_en.triggered.connect(lambda _=False: self._language_changed(LANG_EN_US))
        lang_group = QActionGroup(self)
        lang_group.addAction(self.action_lang_zh)
        lang_group.addAction(self.action_lang_en)
        lang_group.setExclusive(True)

        self.action_about = act("menu.help.about", "Info",
                                handler=lambda _=False: AboutDialog(
                                    app.settings.version, self).exec())

        # -- toolbar actions -----------------------------------------------------
        self.tbtn_disconnect = act("toolbar.disconnect", "Disconnect",
                                   handler=lambda _=False: self.disconnect_selected())
        self.tbtn_show_policies = act("toolbar.show_retention_policies", "RetentionPolicy",
                                      handler=lambda _=False: self._with_selected_node(self.show_retention_policies))
        self.tbtn_show_users = act("toolbar.show_users", "Users",
                                   handler=lambda _=False: self._with_selected_node(self.show_users))
        self.tbtn_show_stats = act("toolbar.show_statistics", "Stats",
                                   handler=lambda _=False: self._with_selected_node(self.show_statistics))
        self.tbtn_show_diagnostics = act("toolbar.show_diagnostics", "Diagnostics",
                                         handler=lambda _=False: self._with_selected_node(self.show_diagnostics))
        self.tbtn_refresh = act("toolbar.refresh", "Refresh",
                                handler=lambda _=False: self.refresh_selected())
        self.tbtn_new_query = act("toolbar.new_query", "NewQuery",
                                  handler=lambda _=False: self._with_selected_node(self.new_query))
        self.tbtn_create_db = act("toolbar.create_database", "CreateDatabase",
                                  handler=lambda _=False: self._with_selected_node(self.create_database))
        self.tbtn_show_cqs = act("toolbar.show_continuous_queries", "ContinuousQuery",
                                 handler=lambda _=False: self._with_selected_node(self.show_continuous_queries))
        self.tbtn_run_backfill = act("toolbar.run_backfill", "BackFill",
                                     handler=lambda _=False: self._with_selected_node(self.run_backfill))
        self.tbtn_drop_db = act("toolbar.drop_database", "DropDatabase",
                                handler=lambda _=False: self._with_selected_node(self.drop_database))
        self.tbtn_tag_keys = act("toolbar.tag_keys", "TagKeys",
                                 handler=lambda _=False: self._with_selected_node(self.show_tag_keys))
        self.tbtn_tag_values = act("toolbar.tag_values", "TagValues",
                                   handler=lambda _=False: self._with_selected_node(self.show_tag_values))
        self.tbtn_field_keys = act("toolbar.field_keys", "FieldKeys",
                                   handler=lambda _=False: self._with_selected_node(self.show_field_keys))
        self.tbtn_show_series = act("toolbar.show_series", "ShowSeries",
                                    handler=lambda _=False: self._with_selected_node(self.show_series))
        self.tbtn_drop_series = act("toolbar.drop_series", "DropSeries",
                                    handler=lambda _=False: self._with_selected_node(self.drop_series))
        self.tbtn_drop_measurement = act("toolbar.drop_measurement", "DropMeasurement",
                                         handler=lambda _=False: self._with_selected_node(self.drop_measurement))

    def _create_menus(self):
        menu_bar = self.menuBar()

        menu_file = menu_bar.addMenu(tr("menu.file"))
        menu_file.addAction(self.action_import_settings)
        menu_file.addAction(self.action_export_settings)
        menu_file.addSeparator()
        menu_file.addAction(self.action_exit)

        menu_connections = menu_bar.addMenu(tr("menu.connections"))
        menu_connections.addAction(self.action_manage_connections)

        menu_query = menu_bar.addMenu(tr("menu.query"))
        menu_query.addAction(self.action_new_query)
        menu_query.addAction(self.action_run_query)
        menu_query.addAction(self.action_show_queries)

        menu_settings = menu_bar.addMenu(tr("menu.settings"))
        menu_time = menu_settings.addMenu(tr("menu.settings.time_format"))
        menu_time.addAction(self.action_time_12h)
        menu_time.addAction(self.action_time_24h)
        menu_date = menu_settings.addMenu(tr("menu.settings.date_format"))
        menu_date.addAction(self.action_date_month_first)
        menu_date.addAction(self.action_date_day_first)
        menu_settings.addAction(self.action_allow_untrusted_ssl)
        menu_language = menu_settings.addMenu(tr("menu.settings.language"))
        menu_language.addAction(self.action_lang_zh)
        menu_language.addAction(self.action_lang_en)

        menu_help = menu_bar.addMenu(tr("menu.help"))
        menu_help.addAction(self.action_about)

    def _create_toolbar(self):
        toolbar = QToolBar(tr("app.title"), self)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        manage = toolbar.addAction(load_icon("CreateConnection"),
                                   tr("toolbar.manage_connections"))
        manage.triggered.connect(lambda _=False: self.show_connections_dialog())

        toolbar.addAction(self.tbtn_disconnect)
        toolbar.addAction(self.tbtn_show_policies)
        toolbar.addAction(self.tbtn_show_users)
        toolbar.addAction(self.tbtn_show_stats)
        toolbar.addAction(self.tbtn_show_diagnostics)
        toolbar.addAction(self.tbtn_refresh)
        toolbar.addSeparator()
        toolbar.addAction(self.action_run_query)
        toolbar.addAction(self.tbtn_new_query)
        toolbar.addAction(self.tbtn_create_db)
        toolbar.addAction(self.tbtn_show_cqs)
        toolbar.addAction(self.tbtn_run_backfill)
        toolbar.addAction(self.tbtn_drop_db)
        toolbar.addSeparator()
        toolbar.addAction(self.tbtn_tag_keys)
        toolbar.addAction(self.tbtn_tag_values)
        toolbar.addAction(self.tbtn_field_keys)
        toolbar.addAction(self.tbtn_show_series)
        toolbar.addAction(self.tbtn_drop_series)
        toolbar.addAction(self.tbtn_drop_measurement)

    def _create_central(self):
        splitter = QSplitter(Qt.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemSelectionChanged.connect(lambda: self.update_ui_state())
        self.tree.itemExpanded.connect(self._tree_item_expanded)
        self.tree.itemDoubleClicked.connect(self._tree_item_double_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        # Right-click also selects the item under the cursor
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        splitter.addWidget(self.tree)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._tab_close_requested)
        self.tabs.currentChanged.connect(lambda _i: self.update_ui_state())
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_context_menu)
        splitter.addWidget(self.tabs)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 820])
        self.setCentralWidget(splitter)

    def _create_statusbar(self):
        self.status_label = QLabel()
        self.statusBar().addWidget(self.status_label, 1)
        self._busy_cursor_active = False
        from ..core import async_utils
        async_utils._delivery.busy_changed.connect(self._on_busy_changed)

    def _on_busy_changed(self, count: int) -> None:
        """Reflect background request activity: status text + wait cursor.

        Runs on the GUI thread (queued signal), so cursor calls are safe.
        """
        from PySide6.QtWidgets import QApplication
        if count > 0:
            suffix = f"（{count}）" if count > 1 else ""
            self.status_label.setText(tr("status.running") + suffix)
            if not self._busy_cursor_active:
                self._busy_cursor_active = True
                QApplication.setOverrideCursor(Qt.WaitCursor)
            self.action_run_query.setEnabled(False)
        else:
            self.status_label.setText("")
            if self._busy_cursor_active:
                self._busy_cursor_active = False
                QApplication.restoreOverrideCursor()
            self.update_ui_state()

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    # ==========================================================================
    # Settings
    # ==========================================================================

    def _apply_settings(self) -> None:
        from ..core.settings import DATE_FORMAT_DAY, TIME_FORMAT_12_HOUR
        self.action_time_12h.setChecked(app.settings.time_format == TIME_FORMAT_12_HOUR)
        self.action_time_24h.setChecked(not self.action_time_12h.isChecked())
        self.action_date_month_first.setChecked(app.settings.date_format != DATE_FORMAT_DAY)
        self.action_date_day_first.setChecked(not self.action_date_month_first.isChecked())
        self.action_allow_untrusted_ssl.setChecked(app.settings.allow_untrusted_ssl)
        self.action_lang_zh.setChecked(app.settings.language == LANG_ZH_CN)
        self.action_lang_en.setChecked(not self.action_lang_zh.isChecked())

    def _allow_untrusted_ssl_changed(self, checked: bool) -> None:
        app.settings.set_allow_untrusted_ssl(checked)

    def _language_changed(self, language: str) -> None:
        if app.settings.language == language:
            return
        app.settings.set_language(language)
        from ..i18n import set_language
        set_language(language)
        # Rebuild the main window in the new language; active connections are
        # preserved because the clients live in the global app state.
        new_window = MainWindow(show_connections_on_load=False)
        for client in app.active_clients:
            new_window.render_connection_node(client.connection)
        new_window.show()
        self.close()
        app.main_window = new_window

    def import_settings(self, show_connections_dialog: bool = False) -> None:
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, tr("settings.import_title"), "",
                tr("settings.json_filter"))
            if not path:
                return
            with open(path, "r", encoding="utf-8") as f:
                json_text = f.read()
            new_settings = type(app.settings).from_export_json(
                json_text, version=app.settings.version)
            app.settings = new_settings
            app.settings.save_all()
            self._apply_settings()
            if show_connections_dialog:
                self.show_connections_dialog()
        except Exception as ex:
            display_exception(ex, parent=self)

    def export_settings(self) -> None:
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, tr("settings.export_title"), "net.sakurain.influxdbstudio_settings.json",
                tr("settings.json_filter"))
            if not path:
                return
            with open(path, "w", encoding="utf-8") as f:
                f.write(app.settings.to_export_json())
        except Exception as ex:
            display_exception(ex, parent=self)

    # ==========================================================================
    # Tree helpers
    # ==========================================================================

    def _with_selected_node(self, command) -> None:
        node = self._selected_node()
        if node is not None:
            command(node)

    def _selected_node(self) -> Optional[QTreeWidgetItem]:
        items = self.tree.selectedItems()
        return items[0] if items else None

    @staticmethod
    def _node_type(node: QTreeWidgetItem) -> int:
        return node.data(0, NODE_TYPE_ROLE)

    @staticmethod
    def _make_node(text: str, node_type: int,
                   connection: Optional[InfluxDbConnection] = None) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text])
        item.setData(0, NODE_TYPE_ROLE, node_type)
        if connection is not None:
            item.setData(0, CONNECTION_ROLE, connection)
        icon = NODE_ICONS.get(node_type)
        if icon:
            item.setIcon(0, load_icon(icon))
        return item

    def _connection_of(self, node: QTreeWidgetItem) -> Optional[InfluxDbConnection]:
        current = node
        while current.parent() is not None:
            current = current.parent()
        return current.data(0, CONNECTION_ROLE)

    @staticmethod
    def _client_for(connection: InfluxDbConnection) -> Optional[InfluxDbClient]:
        for client in app.active_clients:
            if client.connection.Id == connection.Id:
                return client
        return None

    def _tree_item_expanded(self, node: QTreeWidgetItem) -> None:
        self._expand_node_children(node)

    def _tree_item_double_clicked(self, node: QTreeWidgetItem, _column: int) -> None:
        if self._node_type(node) == NodeType.Error and node.parent() is not None:
            # Retry a failed lazy-load: back to the loading placeholder.
            parent = node.parent()
            parent.takeChildren()
            parent.addChild(self._make_node(tr("loading"),
                                            NodeType.LoadingPlaceholder,
                                            self._connection_of(parent)))
            self._expand_node_children(parent)
            return
        if self._node_type(node) == NodeType.Measurement:
            self.new_query(node)

    def _tree_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        node_type = self._node_type(item)

        menu = QMenu(self)
        if node_type == NodeType.Connection:
            self._add_menu_action(menu, "ctx.connection.refresh", self.refresh_selected)
            self._add_menu_action(menu, "ctx.connection.create_database",
                                  lambda: self.create_database(item))
            self._add_menu_action(menu, "ctx.connection.show_queries",
                                  lambda: self.show_queries(item))
            self._add_menu_action(menu, "ctx.connection.show_retention_policies",
                                  lambda: self.show_retention_policies(item))
            self._add_menu_action(menu, "ctx.connection.show_users",
                                  lambda: self.show_users(item))
            self._add_menu_action(menu, "ctx.connection.show_statistics",
                                  lambda: self.show_statistics(item))
            self._add_menu_action(menu, "ctx.connection.show_diagnostics",
                                  lambda: self.show_diagnostics(item))
            self._add_menu_action(menu, "ctx.connection.show_shards",
                                  lambda: self.show_shards(item))
            self._add_menu_action(menu, "ctx.connection.show_subscriptions",
                                  lambda: self.show_subscriptions(item))
            menu.addSeparator()
            self._add_menu_action(menu, "ctx.connection.disconnect",
                                  lambda: self.disconnect(item))
        elif node_type == NodeType.Database:
            self._add_menu_action(menu, "ctx.database.refresh", self.refresh_selected)
            self._add_menu_action(menu, "ctx.database.new_query",
                                  lambda: self.new_query(item))
            self._add_menu_action(menu, "ctx.database.continuous_queries",
                                  lambda: self.show_continuous_queries(item))
            self._add_menu_action(menu, "ctx.database.run_backfill",
                                  lambda: self.run_backfill(item))
            self._add_menu_action(menu, "ctx.database.write_point",
                                  lambda: self.write_point(item))
            menu.addSeparator()
            if item.text(0) != "_internal":
                self._add_menu_action(menu, "ctx.database.drop_database",
                                      lambda: self.drop_database(item))
        elif node_type == NodeType.Measurement:
            self._add_menu_action(menu, "ctx.measurement.new_query",
                                  lambda: self.new_query(item))
            self._add_menu_action(menu, "ctx.measurement.show_series",
                                  lambda: self.show_series(item))
            self._add_menu_action(menu, "ctx.measurement.tag_keys",
                                  lambda: self.show_tag_keys(item))
            self._add_menu_action(menu, "ctx.measurement.tag_values",
                                  lambda: self.show_tag_values(item))
            self._add_menu_action(menu, "ctx.measurement.field_keys",
                                  lambda: self.show_field_keys(item))
            self._add_menu_action(menu, "ctx.measurement.write_point",
                                  lambda: self.write_point(item))
            menu.addSeparator()
            self._add_menu_action(menu, "ctx.measurement.drop_measurement",
                                  lambda: self.drop_measurement(item))
            self._add_menu_action(menu, "ctx.measurement.drop_series",
                                  lambda: self.drop_series(item))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    @staticmethod
    def _add_menu_action(menu: QMenu, key: str, handler) -> None:
        action = menu.addAction(tr(key))
        action.triggered.connect(lambda _=False: handler())

    # -- lazy loading ---------------------------------------------------------

    def _expand_node_children(self, node: QTreeWidgetItem) -> None:
        try:
            # Check for the loading placeholder node
            if node.childCount() == 0:
                return
            first = node.child(0)
            if self._node_type(first) != NodeType.LoadingPlaceholder:
                return

            connection = self._connection_of(node)
            client = self._client_for(connection)
            if client is None:
                return

            node_type = self._node_type(node)
            if node_type == NodeType.Connection:
                self._render_databases(node, client)
            elif node_type == NodeType.Database:
                self._render_measurements(node, client)
        except Exception as ex:
            display_exception(ex, parent=self)

    def _render_databases(self, connection_node: QTreeWidgetItem,
                          client: InfluxDbClient) -> None:
        def done(db_names):
            connection_node.takeChildren()
            for db_name in db_names:
                db_node = self._make_node(db_name, NodeType.Database,
                                          client.connection)
                connection_node.addChild(db_node)
                db_node.addChild(self._make_node(tr("loading"),
                                                 NodeType.LoadingPlaceholder,
                                                 client.connection))

        def failed(ex):
            self._render_load_error(connection_node, ex)

        if not client.connection.Database:
            run_async(lambda: client.get_database_names(
                          timeout=TREE_LOAD_TIMEOUT),
                      done, failed)
        else:
            done([client.connection.Database])

    def _render_measurements(self, db_node: QTreeWidgetItem,
                             client: InfluxDbClient) -> None:
        def done(measurement_names):
            db_node.takeChildren()
            for name in measurement_names:
                db_node.addChild(self._make_node(name, NodeType.Measurement,
                                                 client.connection))

        def failed(ex):
            self._render_load_error(db_node, ex)

        run_async(lambda: client.get_measurement_names(
                      db_node.text(0), timeout=TREE_LOAD_TIMEOUT),
                  done, failed)

    def _render_load_error(self, node: QTreeWidgetItem,
                           ex: BaseException) -> None:
        """Replace the loading placeholder with an inline error node.

        No modal dialog and no endless spinner: the failure is shown in the
        tree (red text, full message as tooltip) and in the status bar.
        Double-clicking the error node retries the load.
        """
        message = str(getattr(ex, "__cause__", None) or ex) or ex.__class__.__name__
        short = message.splitlines()[0][:120]
        node.takeChildren()
        err_node = self._make_node(
            tr("tree.load_failed", error=short), NodeType.Error,
            self._connection_of(node))
        err_node.setForeground(0, QBrush(QColor("#c00000")))
        err_node.setToolTip(0, message)
        node.addChild(err_node)
        connection = self._connection_of(node)
        name = connection.Name if connection is not None else node.text(0)
        app.set_status(tr("tree.load_failed_status", name=name))

    # ==========================================================================
    # Connection rendering / management
    # ==========================================================================

    def show_connections_dialog(self) -> None:
        dialog = ManageConnectionsDialog(self)

        def on_updated(connection: InfluxDbConnection) -> None:
            for i in range(self.tree.topLevelItemCount()):
                node = self.tree.topLevelItem(i)
                c = node.data(0, CONNECTION_ROLE)
                if c and c.Id == connection.Id:
                    self._render_connection_details(node, connection, update=True)
                    break

        def on_removed(connection: InfluxDbConnection) -> None:
            for i in range(self.tree.topLevelItemCount()):
                node = self.tree.topLevelItem(i)
                if node.text(0) == connection.Name:
                    self.disconnect(node)
                    break

        dialog.connection_updated = on_updated
        dialog.connection_removed = on_removed
        dialog.redraw_connections()

        if dialog.exec() == QDialog.Accepted:
            connection = dialog.selected_connection()
            if connection is not None:
                self.render_connection(connection)

    def render_connection(self, connection: InfluxDbConnection) -> None:
        try:
            self.render_connection_node(connection)
            if self._selected_node() is None:
                top = self.tree.topLevelItem(self.tree.topLevelItemCount() - 1)
                if top is not None:
                    self.tree.setCurrentItem(top)
        except Exception as ex:
            display_exception(ex, parent=self)

    def render_connection_node(self, connection: InfluxDbConnection) -> None:
        """Create the tree node and client for a connection (idempotent)."""
        client = self._client_for(connection)
        if client is None:
            client = create_client(connection,
                                   allow_untrusted_ssl=app.settings.allow_untrusted_ssl)
            app.active_clients.append(client)
        else:
            # Already active — just make sure a node exists
            for i in range(self.tree.topLevelItemCount()):
                node = self.tree.topLevelItem(i)
                c = node.data(0, CONNECTION_ROLE)
                if c and c.Id == connection.Id:
                    return

        node = self._make_node(connection.Name, NodeType.Connection, connection)
        self.tree.addTopLevelItem(node)
        self._render_connection_details(node, connection)

    def _render_connection_details(self, connection_node: QTreeWidgetItem,
                                   connection: InfluxDbConnection,
                                   update: bool = False) -> None:
        try:
            if update:
                connection_node.setText(0, connection.Name)
                connection_node.setExpanded(False)
                connection_node.takeChildren()

            client = self._client_for(connection)
            if client is None:
                return

            if connection.Database:
                self._render_databases(connection_node, client)
            else:
                connection_node.addChild(self._make_node(tr("loading"),
                                                         NodeType.LoadingPlaceholder,
                                                         connection))
        except Exception as ex:
            display_exception(ex, parent=self)

    def disconnect(self, node: QTreeWidgetItem) -> None:
        try:
            connection = node.data(0, CONNECTION_ROLE)
            client = self._client_for(connection) if connection else None

            # Remove all tabs associated with this connection
            if connection is not None:
                for i in range(self.tabs.count() - 1, -1, -1):
                    widget = self.tabs.widget(i)
                    control = getattr(widget, "_request_control", None)
                    if control is not None and \
                            control.influx_client.connection.Id == connection.Id:
                        self.tabs.removeTab(i)

            if client is not None:
                app.active_clients.remove(client)

            index = self.tree.indexOfTopLevelItem(node)
            if index >= 0:
                self.tree.takeTopLevelItem(index)
            else:
                (node.parent() or self.tree).removeChild(node) \
                    if node.parent() else None
            self.update_ui_state()
        except Exception as ex:
            display_exception(ex, parent=self)

    def disconnect_selected(self) -> None:
        node = self._selected_node()
        if node is None:
            return
        node_type = self._node_type(node)
        if node_type == NodeType.Connection:
            self.disconnect(node)
        elif node_type == NodeType.Database:
            self.disconnect(node.parent())
        elif node_type == NodeType.Measurement:
            self.disconnect(node.parent().parent())

    # ==========================================================================
    # Connection commands
    # ==========================================================================

    def refresh_selected(self) -> None:
        node = self._selected_node()
        if node is None:
            return
        node_type = self._node_type(node)
        if node_type == NodeType.Connection:
            node.takeChildren()
            node.addChild(self._make_node(tr("loading"), NodeType.LoadingPlaceholder,
                                          node.data(0, CONNECTION_ROLE)))
            self._render_databases(node, self._client_for(node.data(0, CONNECTION_ROLE)))
        elif node_type == NodeType.Database:
            node.takeChildren()
            node.addChild(self._make_node(tr("loading"), NodeType.LoadingPlaceholder,
                                          node.data(0, CONNECTION_ROLE)))
            self._render_measurements(node, self._client_for(node.data(0, CONNECTION_ROLE)))

    def create_database(self, node: QTreeWidgetItem) -> None:
        try:
            connection = node.data(0, CONNECTION_ROLE)
            dialog = CreateDatabaseDialog(self)
            dialog.set_connection_name(connection.Name)
            dialog.set_database_name(connection.Database or "")
            if dialog.exec() != QDialog.Accepted:
                return

            client = self._client_for(connection)

            def work():
                return client.get_database_names()

            def done(current_db_names):
                name = dialog.database_name()
                if not name.strip():
                    display_error(tr("db.create.blank_name"),
                                  tr("db.create.error_title"), self)
                    return
                if name in current_db_names:
                    display_error(tr("db.create.duplicate", name=name),
                                  tr("db.create.error_title"), self)
                    return

                def created(response):
                    if not response.Success:
                        display_error(response.Body, tr("db.create.error_title"), self)
                        return
                    new_node = self._make_node(name, NodeType.Database, connection)
                    node.addChild(new_node)
                    new_node.addChild(self._make_node(tr("loading"),
                                                      NodeType.LoadingPlaceholder,
                                                      connection))
                    self.tree.setCurrentItem(new_node)

                run_async(lambda: client.create_database(name), created,
                          lambda ex: display_exception(ex, parent=self))

            run_async(work, done, lambda ex: display_exception(ex, parent=self))
        except Exception as ex:
            display_exception(ex, parent=self)

    # -- query script persistence (DBeaver-like: tabs survive restarts) ---------

    def _query_tabs(self) -> List[tuple]:
        """Return [(index, wrapper, QueryControl)] for open query tabs."""
        found = []
        for i in range(self.tabs.count()):
            wrapper = self.tabs.widget(i)
            control = getattr(wrapper, "_request_control", None)
            if isinstance(control, controls.QueryControl):
                found.append((i, wrapper, control))
        return found

    def _persist_query_scripts(self) -> None:
        scripts = []
        active = -1
        for i, _w, control in self._query_tabs():
            if not control.script_name:
                continue
            scripts.append({
                "Name": control.script_name,
                "ConnectionId": control.script_connection_id,
                "Database": control.database or "",
                "Text": control.get_editor_text(),
            })
            if i == self.tabs.currentIndex():
                active = len(scripts) - 1
        app.settings.query_scripts = scripts
        app.settings.active_query_tab = active

    def _restore_query_scripts(self) -> None:
        scripts = app.settings.query_scripts
        if not scripts:
            return
        restored = 0
        for script in scripts:
            conn_id = script.get("ConnectionId", "")
            connection = next((c for c in app.settings.connections
                               if c.Id == conn_id), None)
            if connection is None:
                continue
            # Make sure the connection has a live client (idempotent); on a
            # cold start no client exists yet, otherwise restore would skip.
            self.render_connection_node(connection)
            client = self._client_for(connection)
            if client is None:
                continue
            control = controls.QueryControl()
            control.influx_client = client
            control.database = script.get("Database") or None
            control.script_name = script.get("Name", "")
            control.script_connection_id = conn_id
            control.set_editor_text(script.get("Text", ""))
            self.add_tab_with_control(control.script_name, control, "RunQuery")
            restored += 1
        if restored and 0 <= app.settings.active_query_tab < restored:
            self.tabs.setCurrentIndex(app.settings.active_query_tab)
        self.update_ui_state()

    # -- tabs ---------------------------------------------------------------------

    def add_tab_with_control(self, tab_text: str, control: controls.RequestControl,
                             icon_name: str) -> None:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(control)
        wrapper._request_control = control
        index = self.tabs.addTab(wrapper, load_icon(icon_name), tab_text)
        self.tabs.setCurrentIndex(index)
        self.update_ui_state()

    def _tab_close_requested(self, index: int) -> None:
        self.tabs.removeTab(index)
        self._persist_query_scripts()
        self.update_ui_state()

    def _tab_context_menu(self, pos) -> None:
        tab_bar = self.tabs.tabBar()
        index = tab_bar.tabAt(pos)
        menu = QMenu(self)
        wrapper = self.tabs.widget(index) if index >= 0 else None
        control = getattr(wrapper, "_request_control", None) \
            if wrapper is not None else None
        is_query = isinstance(control, controls.QueryControl)
        action_rename = None
        if is_query:
            action_rename = menu.addAction(tr("tab.ctx.rename"))
        action_close = menu.addAction(tr("tab.ctx.close"))
        action_close_others = menu.addAction(tr("tab.ctx.close_all_but_this"))
        action_close_all = menu.addAction(tr("tab.ctx.close_all"))
        action = menu.exec(tab_bar.mapToGlobal(pos))
        if action is action_rename and is_query:
            from PySide6.QtWidgets import QInputDialog
            new_name, ok = QInputDialog.getText(
                self, tr("tab.ctx.rename"), tr("tab.ctx.rename_prompt"),
                text=control.script_name or self.tabs.tabText(index))
            new_name = new_name.strip()
            if ok and new_name:
                control.script_name = new_name
                self.tabs.setTabText(index, new_name)
                self._persist_query_scripts()
        elif action is action_close and index >= 0:
            self.tabs.removeTab(index)
        elif action is action_close_others:
            for i in range(self.tabs.count() - 1, -1, -1):
                if i != index:
                    self.tabs.removeTab(i)
        elif action is action_close_all:
            while self.tabs.count():
                self.tabs.removeTab(0)
        self._persist_query_scripts()
        self.update_ui_state()

    def _current_request_control(self) -> Optional[controls.RequestControl]:
        widget = self.tabs.currentWidget()
        return getattr(widget, "_request_control", None) if widget else None

    def execute_current_request(self) -> None:
        try:
            control = self._current_request_control()
            if control is not None:
                control.execute_request()
        except Exception as ex:
            display_exception(ex, parent=self)

    # -- show commands ---------------------------------------------------------------

    def show_retention_policies(self, node: QTreeWidgetItem) -> None:
        try:
            connection = self._connection_of(node)
            client = self._client_for(connection)
            control = controls.RetentionPolicyControl()
            control.influx_client = client
            self.add_tab_with_control(connection.Name + ".policies", control,
                                      "RetentionPolicy")
            control.execute_request()
        except Exception as ex:
            display_exception(ex, parent=self)

    def show_users(self, node: QTreeWidgetItem) -> None:
        try:
            connection = self._connection_of(node)
            client = self._client_for(connection)
            control = controls.InfluxDbUsersControl()
            control.influx_client = client
            self.add_tab_with_control(connection.Name + ".users", control, "Users")
            control.execute_request()
        except Exception as ex:
            display_exception(ex, parent=self)

    def show_statistics(self, node: QTreeWidgetItem) -> None:
        try:
            connection = self._connection_of(node)
            client = self._client_for(connection)
            control = controls.StatsControl()
            control.influx_client = client
            self.add_tab_with_control(connection.Name + ".statistics", control, "Stats")
            control.execute_request()
        except Exception as ex:
            display_exception(ex, parent=self)

    def show_diagnostics(self, node: QTreeWidgetItem) -> None:
        try:
            connection = self._connection_of(node)
            client = self._client_for(connection)
            control = controls.DiagnosticsControl()
            control.influx_client = client
            self.add_tab_with_control(connection.Name + ".diagnostics", control,
                                      "Diagnostics")
            control.execute_request()
        except Exception as ex:
            display_exception(ex, parent=self)

    def show_queries(self, node: QTreeWidgetItem) -> None:
        try:
            connection = self._connection_of(node)
            client = self._client_for(connection)
            control = controls.RunningQueriesControl()
            control.influx_client = client
            self.add_tab_with_control(connection.Name + ".queries", control,
                                      "ShowQueries")
            control.execute_request()
        except Exception as ex:
            display_exception(ex, parent=self)

    def show_shards(self, node: QTreeWidgetItem) -> None:
        try:
            connection = self._connection_of(node)
            client = self._client_for(connection)
            control = controls.ShowCommandControl(
                client.get_shards, "shards.empty")
            control.influx_client = client
            self.add_tab_with_control(connection.Name + ".shards", control,
                                      "ShowShards")
            control.execute_request()
        except Exception as ex:
            display_exception(ex, parent=self)

    def show_subscriptions(self, node: QTreeWidgetItem) -> None:
        try:
            connection = self._connection_of(node)
            client = self._client_for(connection)
            control = controls.ShowCommandControl(
                client.get_subscriptions, "subscriptions.empty")
            control.influx_client = client
            self.add_tab_with_control(connection.Name + ".subscriptions",
                                      control, "ShowSubscriptions")
            control.execute_request()
        except Exception as ex:
            display_exception(ex, parent=self)

    def write_point(self, node: QTreeWidgetItem) -> None:
        """Write a single point (1.2.0) — the C# version's planned feature."""
        from .dialogs import WritePointDialog
        try:
            connection = self._connection_of(node)
            if connection.ReadOnly:
                display_error(tr("read_only.blocked"), parent=self)
                return
            client = self._client_for(connection)
            database = ""
            measurement = ""
            parent = node.parent()
            if self._node_type(node) == NodeType.Database:
                database = node.text(0)
            elif self._node_type(node) == NodeType.Measurement:
                measurement = node.text(0)
                database = parent.text(0) if parent is not None else ""
            if not database:
                display_error(tr("write.no_database"), parent=self)
                return
            dialog = WritePointDialog(database, measurement, parent=self)
            if dialog.exec() != QDialog.Accepted or dialog.point is None:
                return
            point = dialog.point
            preview = tr("write.preview",
                         measurement=point.Measurement,
                         tags=", ".join(f"{k}={v}" for k, v in
                                        sorted(point.Tags.items())) or "-",
                         fields=", ".join(f"{k}={v}" for k, v in
                                          sorted(point.Fields.items())),
                         time=point.Time or tr("write.time.now"))
            if not confirm(tr("write.confirm.title"), preview, parent=self):
                return
            rp = dialog.retention_policy()
            response = client.write(database, point=point,
                                    retention_policy=rp)
            if response.Success:
                QMessageBox.information(
                    self, tr("write.success.title"), tr("write.success"))
            else:
                display_error(response.Body or tr("write.failed"), parent=self)
        except Exception as ex:
            display_exception(ex, parent=self)

    # ==========================================================================
    # Database commands
    # ==========================================================================

    def show_continuous_queries(self, node: QTreeWidgetItem) -> None:
        try:
            connection = self._connection_of(node)
            client = self._client_for(connection)
            database = node.text(0)
            control = controls.ContinuousQueryControl()
            control.influx_client = client
            control.database = database
            self.add_tab_with_control(f"{connection.Name}.{database} CQs", control,
                                      "ContinuousQuery")
            control.execute_request()
        except Exception as ex:
            display_exception(ex, parent=self)

    def run_backfill(self, node: QTreeWidgetItem) -> None:
        try:
            connection = self._connection_of(node)
            client = self._client_for(connection)
            database = node.text(0) if self._node_type(node) == NodeType.Database \
                else client.connection.Database

            dialog = BackfillDialog(self)
            dialog.influx_client = client
            dialog.database = database

            def bind_sources(measurement_names):
                dialog.bind_influx_data_sources(measurement_names)
                if dialog.exec() != QDialog.Accepted:
                    return
                backfill_params = dialog.backfill_result

                def done(response):
                    if not response.Success:
                        display_error(response.Body, parent=self)
                    self.update_ui_state()

                run_async(lambda: client.backfill(database, backfill_params), done,
                          lambda ex: display_exception(ex, parent=self))

            dialog.reset_backfill_form()
            run_async(lambda: client.get_measurement_names(database), bind_sources,
                      lambda ex: display_exception(ex, parent=self))
        except Exception as ex:
            display_exception(ex, parent=self)

    def run_backfill_for_selected_node(self) -> None:
        node = self._selected_node()
        if node is not None:
            self.run_backfill(node)

    def drop_database(self, node: QTreeWidgetItem) -> None:
        try:
            name = node.text(0)
            if not confirm(self, tr("drop.database.confirm", name=name), tr("drop.title")):
                return
            connection = self._connection_of(node)
            if connection is None:
                display_error(tr("dialog.connection_not_found",
                                 name=node.text(0)), parent=self)
                return
            client = self._client_for(connection)

            def done(response):
                if not response.Success:
                    display_error(response.Body, tr("error.dropping_database"), self)
                    return
                (node.parent() or self.tree).removeChild(node) \
                    if node.parent() else self.tree.takeTopLevelItem(
                        self.tree.indexOfTopLevelItem(node))

            run_async(lambda: client.drop_database(name), done,
                      lambda ex: display_exception(ex, parent=self))
        except Exception as ex:
            display_exception(ex, parent=self)

    # ==========================================================================
    # Measurement commands
    # ==========================================================================

    def _show_measurement_control(self, node: QTreeWidgetItem,
                                  control: controls.MeasurementControl,
                                  suffix: str, icon_name: str) -> None:
        connection = self._connection_of(node)
        client = self._client_for(connection)
        database = node.parent().text(0)
        measurement = node.text(0)
        control.influx_client = client
        control.database = database
        control.measurement = measurement
        self.add_tab_with_control(f"{connection.Name}.{measurement}.{suffix}",
                                  control, icon_name)
        control.execute_request()

    def show_series(self, node: QTreeWidgetItem) -> None:
        try:
            self._show_measurement_control(node, controls.SeriesControl(), "series",
                                           "Series")
        except Exception as ex:
            display_exception(ex, parent=self)

    def show_tag_keys(self, node: QTreeWidgetItem) -> None:
        try:
            self._show_measurement_control(node, controls.TagKeysControl(),
                                           "tag_keys", "TagKeys")
        except Exception as ex:
            display_exception(ex, parent=self)

    def show_tag_values(self, node: QTreeWidgetItem) -> None:
        try:
            self._show_measurement_control(node, controls.TagValuesControl(),
                                           "tag_values", "TagValues")
        except Exception as ex:
            display_exception(ex, parent=self)

    def show_field_keys(self, node: QTreeWidgetItem) -> None:
        try:
            self._show_measurement_control(node, controls.FieldKeysControl(),
                                           "field_keys", "FieldKeys")
        except Exception as ex:
            display_exception(ex, parent=self)

    def new_query(self, node: QTreeWidgetItem) -> None:
        try:
            connection = self._connection_of(node)
            client = self._client_for(connection)
            database = None
            measurement = "measurement"
            node_type = self._node_type(node)
            if node_type == NodeType.Connection:
                return
            elif node_type == NodeType.Database:
                database = node.text(0)
            elif node_type == NodeType.Measurement:
                database = node.parent().text(0)
                measurement = node.text(0)

            control = controls.QueryControl()
            control.influx_client = client
            control.database = database
            control.script_connection_id = connection.Id
            control.connection_id = connection.Id
            control.read_only = connection.ReadOnly
            base = f"{connection.Name}.{database}"
            existing = {w_c.script_name for _i, _w, w_c in self._query_tabs()}
            name = base
            n = 1
            while name in existing:
                n += 1
                name = f"{base} ({n})"
            control.script_name = name
            control.editor_text = tr("query.default_editor_text",
                                     measurement=measurement)
            self.add_tab_with_control(name, control, "RunQuery")
            self._persist_query_scripts()
        except Exception as ex:
            display_exception(ex, parent=self)

    def drop_measurement(self, node: QTreeWidgetItem) -> None:
        try:
            name = node.text(0)
            db_name = node.parent().text(0)
            if not confirm(self, tr("drop.measurement.confirm", name=name),
                           tr("drop.title")):
                return
            connection = self._connection_of(node)
            client = self._client_for(connection)

            def done(response):
                if not response.Success:
                    display_error(response.Body, tr("error.dropping_measurement"), self)
                    return
                node.parent().removeChild(node)

            run_async(lambda: client.drop_measurement(db_name, name), done,
                      lambda ex: display_exception(ex, parent=self))
        except Exception as ex:
            display_exception(ex, parent=self)

    def drop_series(self, node: QTreeWidgetItem) -> None:
        try:
            name = node.text(0)
            db_name = node.parent().text(0)
            if not confirm(self, tr("drop.series.confirm", name=name), tr("drop.title")):
                return
            connection = self._connection_of(node)
            client = self._client_for(connection)

            def done(response):
                if not response.Success:
                    display_error(response.Body, tr("error.dropping_series"), self)
                    return
                node.takeChildren()

            run_async(lambda: client.drop_series(db_name, name), done,
                      lambda ex: display_exception(ex, parent=self))
        except Exception as ex:
            display_exception(ex, parent=self)

    # ==========================================================================
    # UI state
    # ==========================================================================

    def update_ui_state(self) -> None:
        node = self._selected_node()
        node_type = self._node_type(node) if node is not None \
            else NodeType.LoadingPlaceholder
        can_run_query = self._current_request_control() is not None

        # Menu
        self.action_run_query.setEnabled(can_run_query)
        self.action_new_query.setEnabled(
            node_type in (NodeType.Database, NodeType.Measurement))
        self.action_show_queries.setEnabled(node_type == NodeType.Connection)

        # Toolbar
        self.tbtn_disconnect.setEnabled(node is not None)
        self.tbtn_show_policies.setEnabled(node_type == NodeType.Connection)
        self.tbtn_show_users.setEnabled(node_type == NodeType.Connection)
        self.tbtn_show_stats.setEnabled(node_type == NodeType.Connection)
        self.tbtn_show_diagnostics.setEnabled(node_type == NodeType.Connection)
        self.tbtn_refresh.setEnabled(
            node_type in (NodeType.Connection, NodeType.Database))
        self.tbtn_new_query.setEnabled(
            node_type in (NodeType.Database, NodeType.Measurement))
        self.tbtn_create_db.setEnabled(node_type == NodeType.Connection)
        self.tbtn_show_cqs.setEnabled(node_type == NodeType.Database)
        self.tbtn_run_backfill.setEnabled(node_type == NodeType.Database)
        self.tbtn_drop_db.setEnabled(
            node_type == NodeType.Database
            and node is not None and node.text(0) != "_internal")
        self.tbtn_tag_keys.setEnabled(node_type == NodeType.Measurement)
        self.tbtn_tag_values.setEnabled(node_type == NodeType.Measurement)
        self.tbtn_field_keys.setEnabled(node_type == NodeType.Measurement)
        self.tbtn_show_series.setEnabled(node_type == NodeType.Measurement)
        self.tbtn_drop_series.setEnabled(node_type == NodeType.Measurement)
        self.tbtn_drop_measurement.setEnabled(node_type == NodeType.Measurement)

    # ==========================================================================
    # Window lifecycle
    # ==========================================================================

    def closeEvent(self, event) -> None:
        self._persist_query_scripts()
        app.settings.save_all()
        if app.main_window is self:
            app.main_window = None
        super().closeEvent(event)
