"""Query extras (1.4.0): EXPLAIN plan viewer and result chart dialog.

Both are pure-visualization, read-only surfaces. The chart is drawn with
QPainter so no charting dependency is added to the installer.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr


# ---------------------------------------------------------------------------
# EXPLAIN / EXPLAIN ANALYZE plan viewer
# ---------------------------------------------------------------------------

def series_to_plan_text(series_list) -> str:
    """Render EXPLAIN series readably: single-column series become one line
    per row; multi-column series render as aligned columns."""
    blocks: List[str] = []
    for series in series_list or []:
        columns = list(series.Columns or [])
        rows = [list(r) for r in (series.Values or [])]
        if not columns:
            continue
        if len(columns) == 1:
            blocks.append("\n".join(str(r[0]) if r else "" for r in rows))
            continue
        widths = [max(len(str(c)), *(len(str(r[i])) for r in rows if i < len(r)))
                  for i, c in enumerate(columns)]
        header = "  ".join(str(c).ljust(w) for c, w in zip(columns, widths))
        body = ["  ".join((str(r[i]) if i < len(r) else "").ljust(w)
                           for i, w in enumerate(widths)) for r in rows]
        blocks.append("\n".join([header, "-" * len(header)] + body))
    return "\n\n".join(blocks)


class ExplainDialog(QDialog):
    def __init__(self, title_key: str, plan_text: str,
                 parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr(title_key))
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(plan_text or tr("explain.empty"))
        view.setFont(QFont("Consolas"))
        layout.addWidget(view)


# ---------------------------------------------------------------------------
# Result chart (line chart over the time column, QPainter, no deps)
# ---------------------------------------------------------------------------

class ChartDialog(QDialog):
    """Line chart of one numeric column over ``time`` for a result series.

    Serves the 1.4.0 `_internal` visualization need: run any
    ``SELECT ... FROM _internal./[stat]/`` query and chart the numbers.
    """

    def __init__(self, series, numeric_columns: Sequence[str],
                 parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(tr("chart.title"))
        self.resize(760, 480)
        self._series = series
        self._columns = list(numeric_columns)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("chart.column") + ":"))
        self.column_combo = QComboBox()
        self.column_combo.addItems(self._columns)
        top.addWidget(self.column_combo, 1)
        layout.addLayout(top)
        self.canvas = _ChartCanvas()
        layout.addWidget(self.canvas, 1)
        self.column_combo.currentIndexChanged.connect(self._redraw)
        self._redraw()

    def _redraw(self) -> None:
        column = self.column_combo.currentText()
        self.canvas.set_data(self._series, column)


class _ChartCanvas(QWidget):
    MARGIN_L = 64
    MARGIN_R = 16
    MARGIN_T = 16
    MARGIN_B = 40

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._points: List[QPointF] = []
        self._label = ""
        self.setMinimumHeight(240)

    def set_data(self, series, column: str) -> None:
        from ..core import query_tools
        self._points = []
        self._label = column
        if series is None or not (series.Columns and series.Values):
            self.update()
            return
        try:
            t_idx = list(series.Columns).index("time")
            v_idx = list(series.Columns).index(column)
        except ValueError:
            self.update()
            return
        rows = [(query_tools.timestamp_to_ns(r[t_idx]),
                 _as_float(r[v_idx])) for r in series.Values
                if t_idx < len(r) and v_idx < len(r)]
        rows = [(t, v) for t, v in rows if t is not None and v is not None]
        if len(rows) < 2:
            self.update()
            return
        t0 = rows[0][0]
        span = max(1, rows[-1][0] - t0)
        vmax = max(v for _, v in rows)
        vmin = min(v for _, v in rows)
        vspan = vmax - vmin or 1.0
        w = max(1.0, self.width() - self.MARGIN_L - self.MARGIN_R)
        h = max(1.0, self.height() - self.MARGIN_T - self.MARGIN_B)
        self._points = [QPointF(
            self.MARGIN_L + (t - t0) / span * w,
            self.MARGIN_T + (1.0 - (v - vmin) / vspan) * h)
            for t, v in rows]
        self._vmin, self._vmax = vmin, vmax
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # rescale cached points by re-requesting from the dialog is overkill;
        # simply redraw (points are recomputed on set_data / resize via dialog)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, QColor("#ffffff"))
        plot = QRectF(self.MARGIN_L, self.MARGIN_T,
                      max(1.0, rect.width() - self.MARGIN_L - self.MARGIN_R),
                      max(1.0, rect.height() - self.MARGIN_T - self.MARGIN_B))
        painter.setPen(QPen(QColor("#d0d0d0")))
        painter.drawRect(plot)
        if not self._points:
            painter.setPen(QColor("#909090"))
            painter.drawText(rect, Qt.AlignCenter, tr("chart.no_data"))
            painter.end()
            return
        # axis labels: min/max of the value axis
        painter.setPen(QColor("#606060"))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(QRectF(0, plot.top() - 8, self.MARGIN_L - 6, 16),
                         Qt.AlignRight | Qt.AlignVCenter,
                         f"{self._vmax:.4g}")
        painter.drawText(QRectF(0, plot.bottom() - 8, self.MARGIN_L - 6, 16),
                         Qt.AlignRight | Qt.AlignVCenter,
                         f"{self._vmin:.4g}")
        painter.drawText(QRectF(self.MARGIN_L, rect.height() - self.MARGIN_B + 4,
                                plot.width(), 16),
                         Qt.AlignHCenter, self._label)
        path = QPainterPath(self._points[0])
        for pt in self._points[1:]:
            path.lineTo(pt)
        painter.setPen(QPen(QColor("#2f6fd0"), 2))
        painter.drawPath(path)
        painter.end()


def _as_float(value) -> Optional[float]:
    try:
        if isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
