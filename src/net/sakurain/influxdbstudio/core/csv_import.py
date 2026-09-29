"""CSV import → InfluxDB points (1.3.0).

Pure parsing/mapping logic, kept UI-free so it is unit-testable. The dialog
shows a preview and collects the mapping; the heavy parse + batch write runs
on a worker thread (see ``ui/main_window.import_csv``).
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import InfluxDbPoint
from . import query_tools

log = logging.getLogger(__name__)

# Column roles
ROLE_IGNORE = "ignore"
ROLE_TIME = "time"
ROLE_TAG = "tag"
ROLE_FIELD = "field"            # type inferred per value
ROLE_FIELD_STRING = "field_string"  # forced string field

ROLES = (ROLE_IGNORE, ROLE_TIME, ROLE_TAG, ROLE_FIELD, ROLE_FIELD_STRING)

DEFAULT_BATCH_SIZE = 5000
PREVIEW_ROWS = 50


@dataclass
class RowError:
    line: int          # 1-based data line number (excluding header)
    message: str


@dataclass
class ImportResult:
    points: List[InfluxDbPoint] = field(default_factory=list)
    errors: List[RowError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def sniff_dialect(text: str, delimiter: str = "") -> csv.Dialect:
    """Pick a csv dialect; an explicit single-char delimiter wins."""
    sample = text[:8192]

    class _Dialect(csv.excel):
        pass

    if delimiter and len(delimiter) == 1:
        _Dialect.delimiter = delimiter
        return _Dialect
    try:
        detected = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        _Dialect.delimiter = detected.delimiter
    except csv.Error:
        _Dialect.delimiter = ","
    return _Dialect


def read_rows(path: str, delimiter: str = "", has_header: bool = True
              ) -> Tuple[List[str], List[List[str]]]:
    """Read the whole CSV file. Returns ``(headers, rows)``; headers are
    synthesized (``column_1..N``) when ``has_header`` is False, in which
    case every record is treated as data."""
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        text = f.read()
    if not text.strip():
        return [], []
    dialect = sniff_dialect(text, delimiter)
    reader = csv.reader(io.StringIO(text), dialect)
    records = [r for r in reader if r]
    if not records:
        return [], []
    width = max(len(r) for r in records)
    records = [r + [""] * (width - len(r)) for r in records]
    if has_header:
        headers = [h.strip() or f"column_{i + 1}" for i, h in
                   enumerate(records[0])]
        return headers, records[1:]
    return [f"column_{i + 1}" for i in range(width)], records


def guess_mapping(headers: Sequence[str],
                  sample_rows: Sequence[Sequence[str]]) -> List[str]:
    """Auto-guess a column role per header: ``time`` → time, all-numeric
    columns → field, everything else → tag."""
    mapping: List[str] = []
    for idx, name in enumerate(headers):
        lower = name.strip().lower()
        if lower == "time":
            mapping.append(ROLE_TIME)
            continue
        column_values = [(r[idx] if idx < len(r) else "") for r in sample_rows]
        non_empty = [v for v in column_values if str(v).strip()]
        if non_empty and all(_looks_numeric(v) for v in non_empty):
            mapping.append(ROLE_FIELD)
        elif non_empty:
            mapping.append(ROLE_TAG)
        else:
            mapping.append(ROLE_IGNORE)
    return mapping


def _looks_numeric(value: str) -> bool:
    try:
        float(str(value).strip())
        return True
    except (TypeError, ValueError):
        return False


def parse_points(headers: Sequence[str], rows: Sequence[Sequence[str]],
                 mapping: Sequence[str], measurement: str,
                 has_header_time: bool = True) -> ImportResult:
    """Map CSV rows to points.

    Rows with an unparseable time cell are skipped (recorded in
    ``errors``); a missing/empty time cell lets the server assign the
    timestamp. At least one field column is required.
    """
    result = ImportResult()
    measurement = (measurement or "").strip()
    if not measurement:
        result.errors.append(RowError(0, "measurement is required"))
        return result
    roles = list(mapping) + [ROLE_IGNORE] * (len(headers) - len(mapping))

    tag_idx = [(i, headers[i]) for i, r in enumerate(roles) if r == ROLE_TAG]
    field_idx = [(i, headers[i]) for i, r in enumerate(roles)
                 if r in (ROLE_FIELD, ROLE_FIELD_STRING)]
    time_cols = [i for i, r in enumerate(roles) if r == ROLE_TIME]
    time_idx = time_cols[0] if time_cols else None
    if not field_idx:
        result.errors.append(RowError(0, "no field columns mapped"))
        return result

    for line, row in enumerate(rows, start=1):
        tags: Dict[str, Any] = {}
        for i, name in tag_idx:
            value = row[i].strip() if i < len(row) else ""
            if value:
                tags[name] = value
        fields: Dict[str, Any] = {}
        for i, name in field_idx:
            raw = row[i].strip() if i < len(row) else ""
            if roles[i] == ROLE_FIELD_STRING:
                fields[name] = raw
            else:
                fields[name] = query_tools.parse_edited_value(raw)
        if not fields:
            continue
        time_stamp = None
        time_stamp_ns = None
        if time_idx is not None:
            raw_time = row[time_idx].strip() if time_idx < len(row) else ""
            if raw_time:
                time_stamp_ns = query_tools.timestamp_to_ns(raw_time)
                if time_stamp_ns is None:
                    result.errors.append(
                        RowError(line, f"bad time value: {raw_time!r}"))
                    continue
                time_stamp = datetime.fromtimestamp(
                    time_stamp_ns / 1e9, tz=timezone.utc)
        result.points.append(InfluxDbPoint(
            measurement, tags, fields, time_stamp, time_stamp_ns=time_stamp_ns))
    return result


def batches(points: Sequence[InfluxDbPoint], size: int
            ) -> List[List[InfluxDbPoint]]:
    """Split points into write batches (``size`` clamped to >= 1)."""
    size = max(1, int(size or DEFAULT_BATCH_SIZE))
    return [list(points[i:i + size]) for i in range(0, len(points), size)]
