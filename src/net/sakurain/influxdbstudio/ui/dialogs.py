"""Dialog windows (ports of the C# Dialogs/* classes)."""
from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDateTimeEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import exporters
from ..core.client import InfluxDbClient, create_client
from ..core.helper import is_time_interval_valid
from ..core.models import (
    InfluxDbBackfillParams,
    InfluxDbConnection,
    InfluxDbCqParams,
    InfluxDbFillTypes,
    InfluxDbPoint,
    InfluxDbPrivileges,
    InfluxDbRetentionPolicy,
    InfluxDbUser,
)
from ..i18n import tr
from .common import (
    confirm_yes_no,
    create_sql_editor,
    display_error,
    display_exception,
    icon_path,
    resource_path,
)


def _info_label(tip_key: str) -> QLabel:
    label = QLabel("ⓘ")
    label.setToolTip(tr(tip_key))
    return label


def _form_row(form: QFormLayout, label_key: str, widget: QWidget, tip_key: str = None):
    if tip_key:
        box = QHBoxLayout()
        box.addWidget(widget, 1)
        box.addWidget(_info_label(tip_key))
        container = QWidget()
        container.setLayout(box)
        form.addRow(tr(label_key), container)
    else:
        form.addRow(tr(label_key), widget)


# ---------------------------------------------------------------------------
# Connection settings dialog (ConnectionDialog)
# ---------------------------------------------------------------------------

class ConnectionDialog(QDialog):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("conn.dialog.title"))
        self.connection_id: Optional[str] = None

        form = QFormLayout(self)

        self.name_edit = QLineEdit()
        _form_row(form, "conn.dialog.name", self.name_edit)

        self.host_edit = QLineEdit()
        _form_row(form, "conn.dialog.host", self.host_edit)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(8086)
        _form_row(form, "conn.dialog.port", self.port_spin)

        self.database_edit = QLineEdit()
        _form_row(form, "conn.dialog.database", self.database_edit)

        self.username_edit = QLineEdit()
        _form_row(form, "conn.dialog.username", self.username_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        _form_row(form, "conn.dialog.password", self.password_edit)

        self.use_ssl_check = QCheckBox(tr("conn.dialog.use_ssl"))
        form.addRow("", self.use_ssl_check)

        # 1.2.0: read-only connection blocks every data-modifying action
        self.read_only_check = QCheckBox(tr("conn.dialog.read_only"))
        form.addRow("", self.read_only_check)

        buttons = QDialogButtonBox(Qt.Horizontal)
        self.test_button = buttons.addButton(tr("test"), QDialogButtonBox.ActionRole)
        self.ping_button = buttons.addButton(tr("ping"), QDialogButtonBox.ActionRole)
        buttons.addButton(QDialogButtonBox.Save)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.test_button.clicked.connect(self.test_connection)
        self.ping_button.clicked.connect(self.ping_connection)
        form.addRow(buttons)

    # -- properties -----------------------------------------------------------

    def connection_name(self) -> str:
        return self.name_edit.text()

    def set_connection_name(self, value: str) -> None:
        self.name_edit.setText(value or "")

    def host(self) -> str:
        return self.host_edit.text()

    def set_host(self, value: str) -> None:
        self.host_edit.setText(value or "")

    def port(self) -> int:
        return self.port_spin.value()

    def set_port(self, value: int) -> None:
        self.port_spin.setValue(value if value else 8086)

    def database(self) -> str:
        return self.database_edit.text()

    def set_database(self, value: str) -> None:
        self.database_edit.setText(value or "")

    def username(self) -> str:
        return self.username_edit.text()

    def set_username(self, value: str) -> None:
        self.username_edit.setText(value or "")

    def password(self) -> str:
        return self.password_edit.text()

    def set_password(self, value: str) -> None:
        self.password_edit.setText(value or "")

    def use_ssl(self) -> bool:
        return self.use_ssl_check.isChecked()

    def set_use_ssl(self, value: bool) -> None:
        self.use_ssl_check.setChecked(bool(value))

    def read_only(self) -> bool:
        return self.read_only_check.isChecked()

    def set_read_only(self, value: bool) -> None:
        self.read_only_check.setChecked(bool(value))

    # -- commands ---------------------------------------------------------------

    def reset_values(self) -> None:
        self.connection_id = None
        self.set_connection_name("New Connection")
        self.set_host("localhost")
        self.set_port(8086)
        self.set_database("")
        self.set_username("")
        self.set_password("")
        self.set_use_ssl(False)
        self.set_read_only(False)

    def bind_to_connection(self, connection: InfluxDbConnection) -> None:
        self.connection_id = connection.Id
        self.set_connection_name(connection.Name)
        self.set_host(connection.Host)
        self.set_port(connection.Port)
        self.set_database(connection.Database)
        self.set_username(connection.Username)
        self.set_password(connection.Password)
        self.set_use_ssl(connection.UseSsl)
        self.set_read_only(connection.ReadOnly)

    def create_connection(self) -> InfluxDbConnection:
        return InfluxDbConnection.create(
            name=self.connection_name(), host=self.host(), port=self.port(),
            username=self.username() or None, password=self.password() or None,
            use_ssl=self.use_ssl(),
            database=self.database() or None)

    def update_connection_from_dialog(self, connection: InfluxDbConnection) -> None:
        connection.Id = self.connection_id
        connection.Name = self.connection_name()
        connection.Host = self.host()
        connection.Port = self.port()
        connection.Database = self.database() or None
        connection.Username = self.username() or None
        connection.Password = self.password() or None
        connection.UseSsl = self.use_ssl()
        connection.ReadOnly = self.read_only()

    # -- test / ping ---------------------------------------------------------------

    def _make_client(self) -> InfluxDbClient:
        from ..app import settings
        return create_client(self.create_connection(),
                             allow_untrusted_ssl=settings.allow_untrusted_ssl)

    def test_connection(self) -> None:
        from ..core.async_utils import run_async
        try:
            client = self._make_client()

            def work():
                if client.connection.Database:
                    client.get_measurement_names(client.connection.Database)
                else:
                    client.get_database_names()

            def done(_result):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, tr("conn.dialog.success"),
                                        tr("conn.dialog.test_success"))

            def err(ex):
                display_exception(ex, tr("conn.dialog.failure"), self)

            run_async(work, done, err)
        except Exception as ex:
            display_exception(ex, tr("conn.dialog.failure"), self)

    def ping_connection(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        from ..core.async_utils import run_async
        try:
            client = self._make_client()

            def done(response):
                if not response.Success:
                    display_error(tr("conn.dialog.ping_error"),
                                  tr("conn.dialog.failure"), self)
                    return
                QMessageBox.information(
                    self, tr("conn.dialog.pong"),
                    tr("conn.dialog.ping_result", ms=response.ResponseTime,
                       version=response.Version))

            run_async(client.ping, done,
                      lambda ex: display_exception(ex, tr("conn.dialog.failure"), self))
        except Exception as ex:
            display_exception(ex, tr("conn.dialog.failure"), self)


# ---------------------------------------------------------------------------
# Manage connections dialog (ManageConnectionsDialog)
# ---------------------------------------------------------------------------

class ManageConnectionsDialog(QDialog):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("conn.manage.title"))
        self.resize(420, 280)

        self.connection_dialog = ConnectionDialog(self)

        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(
            [tr("conn.manage.column.name"), tr("conn.manage.column.host")])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(self._item_double_clicked)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.create_button = QPushButton(tr("conn.manage.create"))
        self.edit_button = QPushButton(tr("conn.manage.edit"))
        self.remove_button = QPushButton(tr("conn.manage.remove"))
        self.connect_button = QPushButton(tr("conn.manage.connect"))
        self.create_button.clicked.connect(self.create_connection)
        self.edit_button.clicked.connect(self.edit_connection)
        self.remove_button.clicked.connect(self.remove_connection)
        self.connect_button.clicked.connect(self.accept)
        for b in (self.create_button, self.edit_button, self.remove_button,
                  self.connect_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._selection_changed()

    def _selected_row(self) -> int:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return rows[0] if rows else -1

    def selected_connection(self) -> Optional[InfluxDbConnection]:
        row = self._selected_row()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _selection_changed(self) -> None:
        selected = self.selected_connection()
        enabled = selected is not None
        self.edit_button.setEnabled(enabled)
        self.remove_button.setEnabled(enabled)
        connect_enabled = enabled
        if selected is not None:
            from ..app import active_clients
            for client in active_clients:
                if client.connection.Id == selected.Id:
                    connect_enabled = False
                    break
        self.connect_button.setEnabled(connect_enabled)

    def _item_double_clicked(self, item: QTableWidgetItem) -> None:
        if self.connect_button.isEnabled():
            self.accept()

    def redraw_connections(self) -> None:
        from ..app import settings
        self.table.setRowCount(0)
        for c in settings.connections:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(c.Name)
            name_item.setData(Qt.UserRole, c)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(f"{c.Host}:{c.Port}"))
        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def create_connection(self) -> None:
        self.connection_dialog.reset_values()
        if self.connection_dialog.exec() == QDialog.Accepted:
            from ..app import settings
            connection = self.connection_dialog.create_connection()
            # Ensure this is not a duplicate by name
            for c in settings.connections:
                if c.Name == connection.Name:
                    display_error(tr("conn.exists", name=c.Name),
                                  tr("conn.exists.title"), self)
                    return
            settings.connections.append(connection)
            settings.save_connections()
            self.redraw_connections()

    def edit_connection(self) -> None:
        from ..app import settings
        connection = self.selected_connection()
        if connection is None:
            return
        self.connection_dialog.bind_to_connection(connection)
        if self.connection_dialog.exec() == QDialog.Accepted:
            self.connection_dialog.update_connection_from_dialog(connection)
            settings.save_connections()
            self.connection_updated(connection)
            self.redraw_connections()

    def remove_connection(self) -> None:
        from ..app import settings
        connection = self.selected_connection()
        if connection is None:
            return
        if not confirm_yes_no(self, tr("conn.manage.confirm_delete",
                                       name=connection.Name), tr("delete")):
            return
        for c in list(settings.connections):
            if c.Id == connection.Id:
                settings.connections.remove(c)
                break
        settings.save_connections()
        self.connection_removed(connection)
        self.redraw_connections()

    # -- hooks the main window overrides --------------------------------------

    def connection_updated(self, connection: InfluxDbConnection) -> None:
        pass

    def connection_removed(self, connection: InfluxDbConnection) -> None:
        pass


# ---------------------------------------------------------------------------
# Create database dialog (CreateDatabaseDialog)
# ---------------------------------------------------------------------------

class CreateDatabaseDialog(QDialog):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("db.create.title"))

        layout = QVBoxLayout(self)
        self.connection_label = QLabel()
        layout.addWidget(self.connection_label)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        form.addRow(tr("db.create.name"), self.name_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("create"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_connection_name(self, value: str) -> None:
        self.connection_label.setText(tr("db.create.on_connection", name=value))

    def database_name(self) -> str:
        return self.name_edit.text()

    def set_database_name(self, value: str) -> None:
        self.name_edit.setText(value or "")
        self.name_edit.setFocus()


# ---------------------------------------------------------------------------
# User dialogs
# ---------------------------------------------------------------------------

class CreateUserDialog(QDialog):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("users.create.title"))

        form = QFormLayout(self)
        self.username_edit = QLineEdit()
        form.addRow(tr("users.create.username"), self.username_edit)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addRow(tr("users.create.password"), self.password_edit)
        self.admin_check = QCheckBox(tr("users.create.admin"))
        form.addRow("", self.admin_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("create"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def clear_create_values(self) -> None:
        self.username_edit.clear()
        self.password_edit.clear()
        self.admin_check.setChecked(False)

    def password_text(self) -> str:
        return self.password_edit.text()

    def create_user_from_dialog(self) -> Optional[InfluxDbUser]:
        if not self.username_edit.text().strip():
            display_error(tr("users.blank_name"), tr("users.bad_name_title"), self)
            return None
        if not self.password_edit.text().strip():
            display_error(tr("users.blank_password"), tr("users.bad_password_title"), self)
            return None
        return InfluxDbUser(self.username_edit.text(), self.admin_check.isChecked())


class EditUserDialog(QDialog):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("users.edit.title"))

        form = QFormLayout(self)
        self.username_value = QLabel()
        form.addRow(tr("users.create.username"), self.username_value)
        self.admin_check = QCheckBox(tr("users.edit.admin"))
        form.addRow("", self.admin_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("save"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def bind_to_user(self, user: InfluxDbUser) -> None:
        self.username_value.setText(user.Name)
        self.admin_check.setChecked(user.IsAdmin)

    def create_user_from_dialog(self) -> InfluxDbUser:
        return InfluxDbUser(self.username_value.text(), self.admin_check.isChecked())


class UserPasswordDialog(QDialog):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("users.password.title"))

        form = QFormLayout(self)
        self.username_value = QLabel()
        form.addRow(tr("users.create.username"), self.username_value)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addRow(tr("users.password.new"), self.password_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("save"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def bind_to_user(self, user: InfluxDbUser) -> None:
        self.username_value.setText(user.Name)
        self.password_edit.clear()

    def password_text(self) -> str:
        return self.password_edit.text()


class GrantPrivilegeDialog(QDialog):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("users.grant.title"))
        self.influx_client: Optional[InfluxDbClient] = None
        self.user: Optional[InfluxDbUser] = None

        form = QFormLayout(self)
        self.username_value = QLabel()
        form.addRow(tr("users.create.username"), self.username_value)
        self.database_combo = QComboBox()
        form.addRow(tr("users.grant.database"), self.database_combo)
        self.privilege_combo = QComboBox()
        self.privilege_combo.addItem(tr("users.column.read"), InfluxDbPrivileges.Read)
        self.privilege_combo.addItem(tr("users.column.write"), InfluxDbPrivileges.Write)
        self.privilege_combo.addItem(tr("users.column.all"), InfluxDbPrivileges.All)
        form.addRow(tr("users.grant.privilege"), self.privilege_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("create"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def bind_to_user(self, user: InfluxDbUser) -> None:
        self.user = user
        self.username_value.setText(user.Name)

    def bind_databases(self, db_names) -> None:
        self.database_combo.clear()
        for db in db_names or []:
            self.database_combo.addItem(db)
        if self.database_combo.count() > 0:
            self.database_combo.setCurrentIndex(0)

    def selected_database(self) -> Optional[str]:
        return self.database_combo.currentText() or None

    def selected_privilege(self) -> InfluxDbPrivileges:
        return self.privilege_combo.currentData()


class EditPrivilegeDialog(QDialog):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("users.edit_privilege.title"))
        self.username: str = ""
        self.database: str = ""

        form = QFormLayout(self)
        self.username_value = QLabel()
        form.addRow(tr("users.create.username"), self.username_value)
        self.database_value = QLabel()
        form.addRow(tr("users.grant.database"), self.database_value)
        self.privilege_combo = QComboBox()
        self.privilege_combo.addItem(tr("users.privilege.none"), InfluxDbPrivileges.None_)
        self.privilege_combo.addItem(tr("users.column.read"), InfluxDbPrivileges.Read)
        self.privilege_combo.addItem(tr("users.column.write"), InfluxDbPrivileges.Write)
        self.privilege_combo.addItem(tr("users.column.all"), InfluxDbPrivileges.All)
        form.addRow(tr("users.grant.privilege"), self.privilege_combo)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("save"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def bind_to_grant(self, username: str, grant: InfluxDbGrant) -> None:
        self.username = username
        self.database = grant.Database
        self.username_value.setText(username)
        self.database_value.setText(grant.Database)
        index = self.privilege_combo.findData(grant.Privilege)
        if index >= 0:
            self.privilege_combo.setCurrentIndex(index)

    def selected_privilege(self) -> InfluxDbPrivileges:
        return self.privilege_combo.currentData()


# ---------------------------------------------------------------------------
# Retention policy dialog (RetentionPolicyDialog)
# ---------------------------------------------------------------------------

class RetentionPolicyDialog(QDialog):
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("rp.dialog.create_title"))
        self._is_creating = True

        form = QFormLayout(self)
        self.name_edit = QLineEdit()
        form.addRow(tr("rp.dialog.name"), self.name_edit)

        duration_box = QHBoxLayout()
        self.duration_edit = QLineEdit()
        duration_box.addWidget(self.duration_edit, 1)
        duration_box.addWidget(_info_label("rp.tip.duration"))
        duration_container = QWidget()
        duration_container.setLayout(duration_box)
        form.addRow(tr("rp.dialog.duration"), duration_container)

        self.replication_spin = QSpinBox()
        self.replication_spin.setRange(1, 99)
        self.replication_spin.setValue(1)
        form.addRow(tr("rp.dialog.replication"), self.replication_spin)

        self.default_check = QCheckBox(tr("rp.dialog.default"))
        form.addRow("", self.default_check)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setText(tr("create"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)

    @property
    def is_creating(self) -> bool:
        return self._is_creating

    @is_creating.setter
    def is_creating(self, value: bool) -> None:
        self._is_creating = value
        self.name_edit.setReadOnly(not value)
        self.ok_button.setText(tr("create") if value else tr("update"))

    def policy_name(self) -> str:
        return self.name_edit.text()

    def policy_duration(self) -> str:
        return self.duration_edit.text()

    def policy_replication(self) -> int:
        return self.replication_spin.value()

    def policy_default(self) -> bool:
        return self.default_check.isChecked()

    def reset_policy_values(self) -> None:
        self.is_creating = True
        self.name_edit.clear()
        self.duration_edit.clear()
        self.replication_spin.setValue(1)
        self.default_check.setChecked(False)

    def bind_to_policy(self, policy: InfluxDbRetentionPolicy) -> None:
        self.name_edit.setReadOnly(False)
        self.name_edit.setText(policy.Name)
        self.duration_edit.setText(policy.Duration)
        self.replication_spin.setValue(policy.ReplicationCopies)
        self.default_check.setChecked(policy.Default)
        self.is_creating = False

    def accept(self) -> None:
        if not self._validate():
            return
        super().accept()

    def _validate(self) -> bool:
        if not self.name_edit.text().strip():
            display_error(tr("rp.blank_name"), parent=self)
            return False
        duration = self.duration_edit.text()
        if not duration.strip():
            display_error(tr("rp.blank_duration"), parent=self)
            return False
        if not is_time_interval_valid(duration.strip()):
            display_error(tr("rp.invalid_duration"), parent=self)
            return False
        return True


# ---------------------------------------------------------------------------
# Create continuous query dialog (CreateContinuousQueryDialog)
# ---------------------------------------------------------------------------

class CreateContinuousQueryDialog(QDialog):
    PLACEHOLDER = "#edit your query / downsamplers here"

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("cq.dialog.title"))
        self.influx_client: Optional[InfluxDbClient] = None
        self.database: str = ""
        self.cq_result: Optional[InfluxDbCqParams] = None

        form = QFormLayout(self)
        self.name_edit = QLineEdit()
        form.addRow(tr("cq.dialog.name"), self.name_edit)

        self.database_value = QLabel()
        form.addRow(tr("cq.dialog.database"), self.database_value)

        self.destination_combo = QComboBox()
        self.destination_combo.setEditable(True)
        _form_row(form, "cq.dialog.destination", self.destination_combo,
                  "cq.tip.destination")

        self.source_combo = QComboBox()
        self.source_combo.setEditable(True)
        _form_row(form, "cq.dialog.source", self.source_combo, "cq.tip.source")

        self.interval_edit = QLineEdit()
        _form_row(form, "cq.dialog.interval", self.interval_edit, "cq.tip.interval")

        self.fill_type_combo = QComboBox()
        for fill in (InfluxDbFillTypes.Null, InfluxDbFillTypes.Previous,
                     InfluxDbFillTypes.None_):
            self.fill_type_combo.addItem(fill.display_name, fill)
        _form_row(form, "cq.dialog.fill_type", self.fill_type_combo, "cq.tip.fill_type")

        self.tags_edit = QLineEdit()
        _form_row(form, "cq.dialog.tags", self.tags_edit, "cq.tip.tags")

        self.resample_check = QCheckBox(tr("cq.dialog.resample"))
        form.addRow("", self.resample_check)
        self.resample_every_edit = QLineEdit()
        self.resample_for_edit = QLineEdit()
        _form_row(form, "cq.dialog.resample_every", self.resample_every_edit,
                  "cq.tip.resample_every")
        _form_row(form, "cq.dialog.resample_for", self.resample_for_edit,
                  "cq.tip.resample_for")
        self.resample_check.toggled.connect(self._resample_toggled)
        self._resample_toggled(False)

        layout = QVBoxLayout()
        layout.addLayout(form)

        sub_label = QLabel(tr("cq.dialog.subquery") + "  " + "ⓘ")
        sub_label.setToolTip(tr("cq.tip.subquery"))
        layout.addWidget(sub_label)
        self.query_editor = create_sql_editor(self, placeholder=self.PLACEHOLDER)
        layout.addWidget(self.query_editor, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText(tr("create"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setLayout(layout)
        self.resize(520, 560)

    def _resample_toggled(self, checked: bool) -> None:
        self.resample_every_edit.setEnabled(checked)
        self.resample_for_edit.setEnabled(checked)

    def new_query(self) -> None:
        self.query_editor.setPlainText(self.PLACEHOLDER)

    def reset_cq_form(self) -> None:
        self.name_edit.clear()
        self.database_value.clear()
        self.destination_combo.clear()
        self.source_combo.clear()
        self.interval_edit.clear()
        self.fill_type_combo.setCurrentIndex(0)
        self.tags_edit.clear()
        self.resample_check.setChecked(False)
        self.resample_every_edit.clear()
        self.resample_for_edit.clear()
        self.cq_result = None
        self.new_query()

    def bind_influx_data_sources(self, measurement_names) -> None:
        if not self.database:
            return
        self.database_value.setText(self.database)
        self.destination_combo.clear()
        self.source_combo.clear()
        for measurement in measurement_names or []:
            self.destination_combo.addItem(measurement)
            self.source_combo.addItem(measurement)

    def _combo_value(self, combo: QComboBox) -> str:
        value = combo.currentText()
        return value.strip() if value else ""

    def _validate(self) -> bool:
        if not self.name_edit.text().strip():
            display_error(tr("cq.blank_name"), parent=self)
            return False
        destination = self._combo_value(self.destination_combo)
        source = self._combo_value(self.source_combo)
        if not destination:
            display_error(tr("cq.blank_destination"), parent=self)
            return False
        if not source:
            display_error(tr("cq.blank_source"), parent=self)
            return False
        if destination == source:
            if not confirm_yes_no(self, tr("cq.same_source_destination"),
                                  tr("confirm")):
                return False
        interval = self.interval_edit.text()
        if not interval.strip():
            display_error(tr("cq.blank_interval"), parent=self)
            return False
        if not is_time_interval_valid(interval.strip()):
            display_error(tr("cq.invalid_interval"), parent=self)
            return False
        if self.resample_check.isChecked():
            every = self.resample_every_edit.text()
            if every.strip() and not is_time_interval_valid(every.strip()):
                display_error(tr("cq.invalid_resample_every"), parent=self)
                return False
            for_ = self.resample_for_edit.text()
            if for_.strip() and not is_time_interval_valid(for_.strip()):
                display_error(tr("cq.invalid_resample_for"), parent=self)
                return False
        query_text = self.query_editor.toPlainText()
        if not query_text or query_text == self.PLACEHOLDER:
            display_error(tr("cq.blank_subquery"), parent=self)
            return False
        return True

    def create_cq_params_from_values(self) -> Optional[InfluxDbCqParams]:
        if not self._validate():
            return None
        tags = [t.strip() for t in self.tags_edit.text().split(",")
                if t.strip()] or None
        self.cq_result = InfluxDbCqParams(
            Name=self.name_edit.text(),
            Database=self.database_value.text(),
            Destination=self._combo_value(self.destination_combo),
            Source=self._combo_value(self.source_combo),
            SubQueries=[self.query_editor.toPlainText().strip()],
            Interval=self.interval_edit.text(),
            FillType=self.fill_type_combo.currentData(),
            Tags=tags,
            ResampleEveryInterval=self.resample_every_edit.text() or None,
            ResampleForInterval=self.resample_for_edit.text() or None,
        )
        return self.cq_result

    def accept(self) -> None:
        if self.create_cq_params_from_values() is None:
            return
        super().accept()


# ---------------------------------------------------------------------------
# Backfill dialog (BackfillDialog)
# ---------------------------------------------------------------------------

class BackfillDialog(QDialog):
    PLACEHOLDER = "#edit your query / downsamplers here"

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("bf.dialog.title"))
        self.influx_client: Optional[InfluxDbClient] = None
        self.database: str = ""
        self.backfill_result: Optional[InfluxDbBackfillParams] = None

        form = QFormLayout()
        self.database_value = QLabel()
        form.addRow(tr("cq.dialog.database"), self.database_value)

        self.destination_combo = QComboBox()
        self.destination_combo.setEditable(True)
        _form_row(form, "bf.dialog.destination", self.destination_combo,
                  "bf.tip.destination")

        self.source_combo = QComboBox()
        self.source_combo.setEditable(True)
        _form_row(form, "bf.dialog.source", self.source_combo, "bf.tip.source")

        self.interval_edit = QLineEdit()
        _form_row(form, "bf.dialog.interval", self.interval_edit, "bf.tip.interval")

        self.fill_type_combo = QComboBox()
        for fill in (InfluxDbFillTypes.Null, InfluxDbFillTypes.Previous,
                     InfluxDbFillTypes.None_):
            self.fill_type_combo.addItem(fill.display_name, fill)
        _form_row(form, "bf.dialog.fill_type", self.fill_type_combo, "cq.tip.fill_type")

        self.filters_edit = QLineEdit()
        _form_row(form, "bf.dialog.filters", self.filters_edit, "bf.tip.filters")

        self.tags_edit = QLineEdit()
        _form_row(form, "bf.dialog.tags", self.tags_edit, "cq.tip.tags")

        now = datetime.now()
        self.from_edit = QDateTimeEdit(now)
        self.to_edit = QDateTimeEdit(now)
        form.addRow(tr("bf.dialog.from"), self.from_edit)
        form.addRow(tr("bf.dialog.to"), self.to_edit)

        layout = QVBoxLayout()
        layout.addLayout(form)

        sub_label = QLabel(tr("bf.dialog.subquery") + "  " + "ⓘ")
        sub_label.setToolTip(tr("cq.tip.subquery"))
        layout.addWidget(sub_label)
        self.query_editor = create_sql_editor(self, placeholder=self.PLACEHOLDER)
        layout.addWidget(self.query_editor, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.run_button = self.buttons.button(QDialogButtonBox.Ok)
        self.run_button.setText(tr("run"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setLayout(layout)
        self.resize(520, 600)

    def _apply_date_time_format(self) -> None:
        from ..app import settings
        time_fmt = "hh:mm:ss AP" if settings.time_format.endswith("tt") else "HH:mm:ss"
        date_fmt = "MM/dd/yyyy" if settings.date_format.startswith("M") else "dd/MM/yyyy"
        display = f"{date_fmt} @ {time_fmt}"
        self.from_edit.setDisplayFormat(display)
        self.to_edit.setDisplayFormat(display)

    def new_query(self) -> None:
        self.query_editor.setPlainText(self.PLACEHOLDER)

    def reset_backfill_form(self) -> None:
        self.database_value.clear()
        self.destination_combo.clear()
        self.source_combo.clear()
        self.interval_edit.clear()
        self.fill_type_combo.setCurrentIndex(0)
        self.filters_edit.clear()
        self.tags_edit.clear()
        self._apply_date_time_format()
        self.backfill_result = None
        self.new_query()

    def bind_influx_data_sources(self, measurement_names) -> None:
        if not self.database:
            return
        self.database_value.setText(self.database)
        self.destination_combo.clear()
        self.source_combo.clear()
        for measurement in measurement_names or []:
            self.destination_combo.addItem(measurement)
            self.source_combo.addItem(measurement)

    def _combo_value(self, combo: QComboBox) -> str:
        value = combo.currentText()
        return value.strip() if value else ""

    def _validate(self) -> bool:
        destination = self._combo_value(self.destination_combo)
        source = self._combo_value(self.source_combo)
        if not destination:
            display_error(tr("bf.blank_destination"), parent=self)
            return False
        if not source:
            display_error(tr("bf.blank_source"), parent=self)
            return False
        if destination == source:
            if not confirm_yes_no(self, tr("bf.same_source_destination"),
                                  tr("confirm")):
                return False
        interval = self.interval_edit.text()
        if not interval.strip():
            display_error(tr("bf.blank_interval"), parent=self)
            return False
        if not is_time_interval_valid(interval.strip()):
            display_error(tr("bf.invalid_interval"), parent=self)
            return False
        from_time = self.from_edit.dateTime().toPython()
        to_time = self.to_edit.dateTime().toPython()
        if from_time >= to_time:
            display_error(tr("bf.invalid_time_range"), parent=self)
            return False
        query_text = self.query_editor.toPlainText()
        if not query_text or query_text == self.PLACEHOLDER:
            display_error(tr("bf.blank_subquery"), parent=self)
            return False
        return True

    def create_backfill_params_from_values(self) -> Optional[InfluxDbBackfillParams]:
        if not self._validate():
            return None
        filters = [f.strip() for f in self.filters_edit.text().split(",")
                   if f.strip()] or None
        tags = [t.strip() for t in self.tags_edit.text().split(",")
                if t.strip()] or None
        self.backfill_result = InfluxDbBackfillParams(
            Destination=self._combo_value(self.destination_combo),
            Source=self._combo_value(self.source_combo),
            SubQueries=[self.query_editor.toPlainText().strip()],
            Interval=self.interval_edit.text(),
            FillType=self.fill_type_combo.currentData(),
            FromTime=self.from_edit.dateTime().toPython(),
            ToTime=self.to_edit.dateTime().toPython(),
            Filters=filters,
            Tags=tags,
        )
        return self.backfill_result

    def accept(self) -> None:
        if self.create_backfill_params_from_values() is None:
            return
        super().accept()


# ---------------------------------------------------------------------------
# About dialog (AboutDialog)
# ---------------------------------------------------------------------------

class AboutDialog(QDialog):
    def __init__(self, version: str, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("about.title"))

        layout = QVBoxLayout(self)
        logo = QLabel()
        pixmap = QPixmap(resource_path("sakurain.png"))
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaledToWidth(96, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)

        title = QLabel("InfluxDB Manager")
        title.setAlignment(Qt.AlignCenter)
        f = title.font()
        f.setPointSize(f.pointSize() + 6)
        f.setBold(True)
        title.setFont(f)
        layout.addWidget(title)

        version_label = QLabel(tr("about.version", version=version))
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)

        description = QLabel(tr("about.description"))
        description.setWordWrap(True)
        layout.addWidget(description)

        link = QLabel(f'<a href="https://github.com/IYeaSakura/InfluxDB-Manager">'
                      f'{tr("about.project_page")}</a>')
        link.setOpenExternalLinks(True)
        layout.addWidget(link)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.resize(420, 320)


# ---------------------------------------------------------------------------
# Export dialog (format + CSV delimiter + save location)
# ---------------------------------------------------------------------------

class ExportDialog(QDialog):
    """Pick export format (and CSV delimiter), then the save location.

    ``suggest_name`` maps an extension to a default file name. On accept the
    chosen ``(path, fmt, delimiter)`` is available as :attr:`choice`.
    """

    def __init__(self, suggest_name, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("export.dialog.title"))
        self._suggest_name = suggest_name
        self.choice = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.format_combo = QComboBox()
        for key, label, _ext in exporters.FORMATS:
            self.format_combo.addItem(label, key)
        self.format_combo.currentIndexChanged.connect(self._sync_delimiter)
        form.addRow(tr("export.format"), self.format_combo)
        self.delimiter_edit = QLineEdit(exporters.DEFAULT_DELIMITER)
        self.delimiter_edit.setMaxLength(4)
        self.delimiter_edit.setToolTip(tr("export.delimiter.tip"))
        tip_box = QWidget()
        tip_h = QHBoxLayout(tip_box)
        tip_h.setContentsMargins(0, 0, 0, 0)
        tip_h.addWidget(self.delimiter_edit, 1)
        tip_h.addWidget(_info_label("export.delimiter.tip"))
        form.addRow(tr("export.delimiter"), tip_box)
        layout.addLayout(form)
        self._sync_delimiter()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sync_delimiter(self, *_args) -> None:
        self.delimiter_edit.setEnabled(self.format_combo.currentData() == "csv")

    def _on_accept(self) -> None:
        fmt = self.format_combo.currentData()
        delimiter = self.delimiter_edit.text() or exporters.DEFAULT_DELIMITER
        if fmt == "csv" and len(delimiter) != 1:
            display_error(tr("export.bad_delimiter"), parent=self)
            return
        ext = exporters.extension(fmt)
        filters = ";;".join(
            f"{label} (*.{ex})" for _k, label, ex in exporters.FORMATS)
        # Start in the last used export directory (remembered across launches).
        from ..app import settings
        suggested = self._suggest_name(ext)
        start_dir = getattr(settings, "last_export_dir", "")
        start = os.path.join(start_dir, suggested) if start_dir else suggested
        path, _sel = QFileDialog.getSaveFileName(
            self, tr("export.dialog.title"), start, filters)
        if not path:
            return
        if not path.lower().endswith("." + ext):
            path += "." + ext
        settings.set_last_export_dir(path)
        self.choice = (path, fmt, delimiter)
        self.accept()


def pick_export_choice(suggest_name, parent: QWidget = None):
    """Show the export dialog and return ``(path, fmt, delimiter)``,
    or None when cancelled. Does not write any file."""
    dialog = ExportDialog(suggest_name, parent=parent)
    if dialog.exec() != QDialog.Accepted or dialog.choice is None:
        return None
    return dialog.choice


def run_export_dialog(suggest_name, columns, rows,
                      parent: QWidget = None) -> Optional[int]:
    """Show the export dialog and write the file on accept.

    Returns the number of exported rows, or None when cancelled.
    """
    choice = pick_export_choice(suggest_name, parent=parent)
    if choice is None:
        return None
    path, fmt, delimiter = choice
    exporters.export_rows(path, fmt, columns, rows, delimiter)
    QMessageBox.information(
        parent, tr("export.success.title"),
        tr("export.success", n=len(rows), path=path))
    return len(rows)


# ---------------------------------------------------------------------------
# Server-side column filter dialog (1.2.0)
# ---------------------------------------------------------------------------

class FilterDialog(QDialog):
    """Pick an operator and value for one column; ``condition`` is
    ``(column, op, value)`` on accept."""

    OPERATORS = ["=", "!=", ">", ">=", "<", "<=", "=~", "!~"]

    def __init__(self, column: str, parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("filter.dialog.title"))
        self.column = column
        self.condition = None

        form = QFormLayout(self)
        form.addRow(tr("filter.column"), QLabel(column))
        self.op_combo = QComboBox()
        self.op_combo.addItems(self.OPERATORS)
        self.op_combo.setCurrentIndex(0)
        form.addRow(tr("filter.op"), self.op_combo)
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText(tr("filter.value.tip"))
        form.addRow(tr("filter.value"), self.value_edit)
        tip = _info_label("filter.value.tip")
        form.addRow("", tip)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_accept(self) -> None:
        value = self.value_edit.text().strip()
        if not value:
            display_error(tr("filter.invalid"), parent=self)
            return
        self.condition = (self.column, self.op_combo.currentText(), value)
        self.accept()


# ---------------------------------------------------------------------------
# Query history dialog (1.2.0)
# ---------------------------------------------------------------------------

class QueryHistoryDialog(QDialog):
    """Browse the executed queries of the current connection; double-click
    (or 回填) loads the selected entry into the editor."""

    def __init__(self, entries: list, connection_id: str,
                 parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("history.dialog.title"))
        self.resize(560, 360)
        self.connection_id = connection_id
        self.selected_entry = None
        self._entries = list(entries)

        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            tr("history.column.time"), tr("history.column.database"),
            tr("history.column.query")])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemDoubleClicked.connect(lambda _i: self._load())
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.load_button = QPushButton(tr("history.load"))
        self.delete_button = QPushButton(tr("history.delete"))
        self.clear_button = QPushButton(tr("history.clear"))
        close_button = QPushButton(tr("history.close"))
        self.load_button.clicked.connect(self._load)
        self.delete_button.clicked.connect(self._delete_selected)
        self.clear_button.clicked.connect(self._clear)
        close_button.clicked.connect(self.reject)
        for b in (self.load_button, self.delete_button, self.clear_button,
                  close_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self._reload()

    def _reload(self) -> None:
        self.table.setRowCount(0)
        for entry in self._entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(
                str(entry.get("Time", ""))))
            self.table.setItem(row, 1, QTableWidgetItem(
                str(entry.get("Database", ""))))
            text = str(entry.get("Text", ""))
            self.table.setItem(row, 2, QTableWidgetItem(
                text[:200] + ("…" if len(text) > 200 else "")))
        self.table.resizeColumnsToContents()

    def _current_entry(self):
        row = self.table.currentRow()
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def _load(self) -> None:
        entry = self._current_entry()
        if entry is None:
            return
        self.selected_entry = entry
        self.accept()

    def _persist(self) -> None:
        from ..app import settings
        keep_ids = {id(e) for e in self._entries}
        settings.query_history = [
            h for h in settings.query_history if id(h) in keep_ids]
        settings.save_all()

    def _delete_selected(self) -> None:
        entry = self._current_entry()
        if entry is None:
            return
        self._entries.remove(entry)
        self._persist()
        self._reload()

    def _clear(self) -> None:
        self._entries = []
        self._persist()
        self._reload()


# ---------------------------------------------------------------------------
# Write point dialog (1.2.0) — the C# version's never-implemented feature
# ---------------------------------------------------------------------------

class WritePointDialog(QDialog):
    """Compose a single point (measurement + tags + fields + time) and
    preview its line protocol before writing."""

    def __init__(self, database: str, measurement: str = "",
                 parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("write.dialog.title"))
        self.point = None
        self.database = database

        form = QFormLayout(self)
        self.measurement_edit = QLineEdit(measurement)
        form.addRow(tr("write.measurement"), self.measurement_edit)
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText(tr("write.tags.tip"))
        form.addRow(tr("write.tags"), self.tags_edit)
        self.fields_edit = QLineEdit()
        self.fields_edit.setPlaceholderText(tr("write.fields.tip"))
        form.addRow(tr("write.fields"), self.fields_edit)
        self.time_edit = QLineEdit()
        self.time_edit.setPlaceholderText(tr("write.time.tip"))
        form.addRow(tr("write.time"), self.time_edit)
        self.rp_edit = QLineEdit()
        form.addRow(tr("write.rp"), self.rp_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr("write.next"))
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    # -- parsing ----------------------------------------------------------------

    @staticmethod
    def _parse_kv(text: str) -> dict:
        """Parse ``k=v, k2=v2`` into a dict (values stay strings)."""
        result = {}
        text = (text or "").strip()
        if not text:
            return result
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                raise ValueError(part)
            key, _, value = part.partition("=")
            key = key.strip().strip('"')
            if not key:
                raise ValueError(part)
            result[key] = value.strip().strip("'").strip('"')
        return result

    def _on_accept(self) -> None:
        from ..core import query_tools
        measurement = self.measurement_edit.text().strip()
        if not measurement:
            display_error(tr("write.no_measurement"), parent=self)
            return
        try:
            tags = self._parse_kv(self.tags_edit.text())
        except ValueError as ex:
            display_error(tr("write.bad_kv", part=str(ex)), parent=self)
            return
        try:
            fields_raw = self._parse_kv(self.fields_edit.text())
        except ValueError as ex:
            display_error(tr("write.bad_kv", part=str(ex)), parent=self)
            return
        if not fields_raw:
            display_error(tr("write.no_fields"), parent=self)
            return
        fields = {k: query_tools.parse_edited_value(v)
                  for k, v in fields_raw.items()}
        time_text = self.time_edit.text().strip()
        time_stamp = None
        ns = None
        if time_text:
            ns = query_tools.timestamp_to_ns(time_text)
            if ns is None:
                display_error(tr("write.bad_time"), parent=self)
                return
            from datetime import datetime, timezone
            time_stamp = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
        self.point = InfluxDbPoint(
            measurement, tags, fields, time_stamp, time_stamp_ns=ns)
        self.accept()

    def retention_policy(self) -> Optional[str]:
        return self.rp_edit.text().strip() or None
