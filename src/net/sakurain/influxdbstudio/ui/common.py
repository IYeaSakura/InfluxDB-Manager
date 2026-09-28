"""UI 公共辅助：图标加载、SQL 高亮编辑器、通用错误提示。"""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (QMessageBox, QPlainTextEdit, QWidget)

from ..i18n import tr

log = logging.getLogger("net.sakurain.influxdbstudio.ui")

CHECK_MARK = "✓"

_ICONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "icons")
_RESOURCES_DIR = os.path.dirname(_ICONS_DIR)

_icon_cache: dict = {}


def icon_path(name: str) -> str:
    return os.path.join(_ICONS_DIR, name + ".png")


def resource_path(name: str) -> str:
    """Absolute path to a file inside the package resources directory."""
    return os.path.join(_RESOURCES_DIR, name)


def load_icon(name: str):
    """Load a toolbar/tree icon as a QIcon (cached)."""
    from PySide6.QtGui import QIcon
    if name not in _icon_cache:
        _icon_cache[name] = QIcon(icon_path(name))
    return _icon_cache[name]


def display_error(message: str, caption: str = None, parent: QWidget = None) -> None:
    if caption is None:
        caption = tr("error")
    log.error("%s", message)
    QMessageBox.critical(parent, caption, message)


def display_exception(ex: BaseException, caption: str = None, parent: QWidget = None) -> None:
    """Display an unexpected exception (port of AppForm.DisplayException).

    Silently swallows InfluxDB "query interrupted" errors (KILL QUERY
    workaround, same as the C# version).
    """
    if caption is None:
        caption = tr("dialog.unexpected_error")

    # Workaround for KILL QUERY command
    response_body = getattr(ex, "response_body", "") or ""
    if "query interrupted" in response_body:
        return

    message = str(ex)
    inner = getattr(ex, "__cause__", None)
    if inner is not None:
        message = str(inner)
    log.exception("%s: %s", caption, message)
    QMessageBox.critical(parent, caption, message)


def confirm(parent: QWidget, message: str, caption: str = None) -> bool:
    if caption is None:
        caption = tr("confirm")
    ret = QMessageBox.warning(parent, caption, message,
                              QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
    return ret == QMessageBox.Ok


def confirm_yes_no(parent: QWidget, message: str, caption: str = None) -> bool:
    if caption is None:
        caption = tr("confirm")
    ret = QMessageBox.warning(parent, caption, message,
                              QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    return ret == QMessageBox.Yes


# ---------------------------------------------------------------------------
# SQL syntax highlighting editor (ScintillaNET equivalent)
# ---------------------------------------------------------------------------

_SQL_KEYWORDS = (
    "select from where group by order limit offset into as and or not "
    "create continuous query begin end resample every for fill drop "
    "show measurements series tag keys values field databases users "
    "retention policy default alter replication duration grant revoke "
    "to user with password all privileges admin kill "
    "time now true false null previous linear none"
).split()


class _SqlHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self._keyword_fmt = QTextCharFormat()
        self._keyword_fmt.setForeground(QColor("blue"))
        self._keyword_fmt.setFontWeight(QFont.Bold)

        self._string_fmt = QTextCharFormat()
        self._string_fmt.setForeground(QColor("#a31515"))

        self._number_fmt = QTextCharFormat()
        self._number_fmt.setForeground(QColor("#b00080"))

        self._comment_fmt = QTextCharFormat()
        self._comment_fmt.setForeground(QColor("#7f7f7f"))  # gray, DBeaver style

    def highlightBlock(self, text: str) -> None:
        import re
        # strings (single or double quoted)
        for m in re.finditer(r"'[^']*'|\"[^\"]*\"", text):
            self.setFormat(m.start(), m.end() - m.start(), self._string_fmt)
        # numbers
        for m in re.finditer(r"\b\d+(\.\d+)?\b", text):
            self.setFormat(m.start(), m.end() - m.start(), self._number_fmt)
        # keywords (case-insensitive)
        for m in re.finditer(r"\b[a-zA-Z_]+\b", text):
            if m.group(0).lower() in _SQL_KEYWORDS:
                self.setFormat(m.start(), m.end() - m.start(), self._keyword_fmt)
        # line comment (-- ...) applied LAST so it wins over strings/keywords/numbers
        for m in re.finditer(r"--.*$", text):
            self.setFormat(m.start(), m.end() - m.start(), self._comment_fmt)


def _toggle_line_comment(editor: QPlainTextEdit) -> None:
    """Comment/uncomment the current line (or all selected lines) with ``--``.

    Toggles as a block: when every non-blank line is commented, the comment
    prefix is removed; otherwise ``-- `` is added at the start of each line.
    The whole toggle is a single undo step.
    """
    from PySide6.QtGui import QTextCursor

    cursor = editor.textCursor()
    doc = editor.document()
    start_block = doc.findBlock(cursor.selectionStart())
    end_block = doc.findBlock(cursor.selectionEnd())
    # Selection ending exactly at the first char of a trailing line does not
    # include that line (same convention as most editors).
    if cursor.selectionEnd() > cursor.selectionStart() \
            and end_block.blockNumber() > start_block.blockNumber() \
            and end_block.position() == cursor.selectionEnd():
        end_block = end_block.previous()

    blocks = []
    block = start_block
    while block.isValid() and block.blockNumber() <= end_block.blockNumber():
        blocks.append(block)
        block = block.next()

    def content_of(line: str) -> str:
        stripped = line.lstrip()
        if stripped.startswith("--"):
            rest = stripped[2:]
            return rest[1:] if rest.startswith(" ") else rest
        return None

    infos = [(b, content_of(b.text())) for b in blocks]
    uncomment = all(c is not None for _b, c in infos
                    if _b.text().strip()) and any(_b.text().strip() for _b, _c in infos)

    edit = QTextCursor(editor.document())
    edit.beginEditBlock()
    for b, content in infos:
        line = b.text()
        if not line.strip():
            continue
        line_cursor = QTextCursor(b)
        line_cursor.movePosition(QTextCursor.StartOfBlock)
        line_cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        if uncomment:
            line_cursor.insertText(content)
        else:
            line_cursor.insertText("-- " + line)
    edit.endEditBlock()


def create_sql_editor(parent: QWidget = None, placeholder: str = None) -> QPlainTextEdit:
    """Create a monospace query editor with SQL syntax highlighting."""
    from PySide6.QtGui import QKeySequence, QShortcut

    editor = QPlainTextEdit(parent)
    font = QFont("Consolas")
    font.setStyleHint(QFont.TypeWriter)
    editor.setFont(font)
    editor.setPlaceholderText(placeholder or "")
    editor.setTabStopDistance(4 * editor.fontMetrics().horizontalAdvance(" "))
    _SqlHighlighter(editor.document())
    # Ctrl+/ (also Ctrl+# on some layouts): toggle line comment
    comment_shortcut = QShortcut(
        QKeySequence(Qt.CTRL | Qt.Key_Slash), editor)
    comment_shortcut.activated.connect(lambda: _toggle_line_comment(editor))
    return editor
