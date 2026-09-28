# -*- coding: utf-8 -*-
"""InfluxQL helpers for the DBeaver-like result grid.

Supports:
- detecting SELECT queries that can be paginated / edited,
- injecting ``LIMIT ... OFFSET ...`` for paging,
- building a ``SELECT COUNT(*)`` total-count query,
- building overwrite points (InfluxDB has no UPDATE; writing a point with the
  same measurement + tags + timestamp overwrites the fields),
- RFC3339 timestamp conversion preserving nanosecond precision.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set

from .models import InfluxDbPoint

_WORD_LIMIT = re.compile(r"\blimit\b", re.IGNORECASE)
_WORD_OFFSET = re.compile(r"\boffset\b", re.IGNORECASE)
_WORD_INTO = re.compile(r"\binto\b", re.IGNORECASE)
_WORD_GROUP = re.compile(r"\bgroup\s+by\b", re.IGNORECASE)
_WORD_ORDER = re.compile(r"\border\s+by\b", re.IGNORECASE)
_WORD_SLIMIT = re.compile(r"\bslimit\b|\bsoffset\b", re.IGNORECASE)
_FROM_CLAUSE_END = re.compile(
    r"\b(group\s+by|order\s+by|limit|offset|slimit|soffset)\b", re.IGNORECASE)

DEFAULT_PAGE_SIZE = 500
PAGE_SIZE_CHOICES = [100, 500, 1000, 5000, 10000]


def _strip_trailing_semicolon(query: str) -> str:
    q = query.rstrip()
    while q.endswith(";"):
        q = q[:-1].rstrip()
    return q


def strip_line_comments(query: str) -> str:
    """Remove whole-line ``--`` comments (leading whitespace + ``--``)."""
    lines = [ln for ln in query.splitlines()
             if not ln.lstrip().startswith("--")]
    return "\n".join(lines)


def is_select_query(query: str) -> bool:
    """True for plain SELECT statements (not SHOW/etc.).

    Whole-line ``--`` comments are ignored so an editor script that starts
    with a commented header still paginates and counts correctly.
    """
    q = strip_line_comments(_strip_trailing_semicolon(query)).lstrip(" \t\r\n(")
    return q[:6].lower() == "select"


def is_writing_select(query: str) -> bool:
    """True for SELECT ... INTO (writes into another measurement)."""
    return is_select_query(query) and _WORD_INTO.search(query) is not None


def has_explicit_limit(query: str) -> bool:
    """True if the query already carries LIMIT/OFFSET/SLIMIT of its own."""
    return (_WORD_LIMIT.search(query) is not None
            or _WORD_OFFSET.search(query) is not None
            or _WORD_SLIMIT.search(query) is not None)


def can_paginate(query: str) -> bool:
    """Paginate plain SELECTs that do not manage their own LIMIT/OFFSET."""
    return is_select_query(query) and not is_writing_select(query) \
        and not has_explicit_limit(query)


def paginate_query(query: str, limit: int, offset: int) -> str:
    """Return ``query`` with ``LIMIT limit OFFSET offset`` appended."""
    if limit <= 0:
        return _strip_trailing_semicolon(query)
    return f"{_strip_trailing_semicolon(query)} LIMIT {int(limit)} OFFSET {int(offset)}"


def build_count_query(query: str) -> Optional[str]:
    """Build ``SELECT COUNT(*) FROM ... [WHERE ...]`` for a plain SELECT.

    Returns None when a total count cannot be derived (no FROM clause,
    SELECT INTO, or GROUP BY which would produce per-group counts).
    """
    if not is_select_query(query) or is_writing_select(query):
        return None
    if _WORD_GROUP.search(query):
        return None
    m = re.search(r"\bfrom\b", query, re.IGNORECASE)
    if m is None:
        return None
    rest = query[m.end():]
    end = _FROM_CLAUSE_END.search(rest)
    from_where = rest[: end.start()] if end else rest
    from_where = _strip_trailing_semicolon(from_where).strip()
    if not from_where:
        return None
    return f"SELECT COUNT(*) FROM {from_where}"


def parse_count_value(series_list: Sequence) -> Optional[int]:
    """Extract the total count out of a COUNT(*) response."""
    for series in series_list or []:
        for row in getattr(series, "Values", []) or []:
            for value in row:
                if isinstance(value, (int, float)):
                    return int(value)
    return None


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

_RFC3339_NS = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})?$")


def timestamp_to_ns(value: Any) -> Optional[int]:
    """Convert an InfluxDB time value to nanoseconds since epoch.

    Accepts RFC3339 strings (fractional seconds up to 9 digits preserved)
    or integer epochs (assumed nanoseconds, matching the HTTP API default).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    s = str(value).strip()
    if not s:
        return None
    m = _RFC3339_NS.match(s)
    if m is None:
        return None
    year, mon, day, hh, mm, ss = (int(m.group(i)) for i in range(1, 7))
    frac = (m.group(7) or "").ljust(9, "0")
    nanos = int(frac) if frac else 0
    tzs = m.group(8) or "Z"
    if tzs == "Z":
        tz = timezone.utc
    else:
        sign = 1 if tzs[0] == "+" else -1
        digits = tzs[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(digits[:2]),
                                      minutes=int(digits[2:4])))
    dt = datetime(year, mon, day, hh, mm, ss, 0, tzinfo=tz)
    seconds = int(dt.timestamp())
    return seconds * 1_000_000_000 + nanos


# ---------------------------------------------------------------------------
# Edited value typing
# ---------------------------------------------------------------------------

def parse_edited_value(text: str) -> Any:
    """Interpret an edited cell string, preserving the InfluxDB field type."""
    s = text.strip()
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return text


def coerce_edited_value(text: str, field_type: Optional[str]) -> Any:
    """Coerce an edited string to the column's declared InfluxDB field type.

    Keeps e.g. string-typed fields as strings even when the text looks
    numeric (avoids field-type-conflict write errors).
    """
    t = (field_type or "").lower()
    s = text.strip()
    if t in ("string",):
        return text
    if t in ("integer", "int"):
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return text
    if t in ("float",):
        try:
            return float(s)
        except ValueError:
            return text
    if t in ("boolean", "bool"):
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False
        return text
    return parse_edited_value(text)


def format_cell_value(value: Any) -> str:
    """How an edited value is rendered back into the cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ---------------------------------------------------------------------------
# Overwrite points
# ---------------------------------------------------------------------------

def build_overwrite_point(measurement: str,
                          columns: Sequence[str],
                          tag_columns: Set[str],
                          row_values: Sequence[Any],
                          changes: Dict[str, Any],
                          ) -> Optional[InfluxDbPoint]:
    """Build a point that overwrites the edited fields of one result row.

    ``columns`` are the result series columns (without the leading "#").
    ``tag_columns`` must contain exactly the columns that are InfluxDB tags
    (looked up via SHOW TAG KEYS); tags and time identify the point.
    ``changes`` maps column name -> new (typed) value, field columns only.
    Returns None when the row time cannot be determined.
    """
    col_index = {name: i for i, name in enumerate(columns)}
    time_idx = col_index.get("time")
    if time_idx is None or time_idx >= len(row_values):
        return None
    ns = timestamp_to_ns(row_values[time_idx])
    if ns is None:
        return None
    tags: Dict[str, Any] = {}
    for name in tag_columns:
        i = col_index.get(name)
        if i is not None and i < len(row_values) and row_values[i] is not None:
            tags[name] = row_values[i]
    fields: Dict[str, Any] = {}
    for name, new_value in changes.items():
        if name == "time" or name in tag_columns:
            continue
        if name not in col_index:
            continue
        fields[name] = new_value
    if not fields:
        return None
    return InfluxDbPoint(measurement, tags, fields,
                         datetime.fromtimestamp(ns / 1e9, tz=timezone.utc),
                         time_stamp_ns=ns)


# ---------------------------------------------------------------------------
# Row deletion
# ---------------------------------------------------------------------------

def ns_to_rfc3339(ns: int) -> str:
    """Format nanoseconds since epoch as RFC3339 with full ns precision."""
    seconds, frac = divmod(int(ns), 1_000_000_000)
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{frac:09d}Z"


def _escape_InfluxQL_string(value: Any) -> str:
    # InfluxQL single-quoted strings escape ' as \' (same as the C# client)
    return str(value).replace("'", "\\'")


def build_delete_statement(measurement: str,
                           columns: Sequence[str],
                           tag_columns: Set[str],
                           row_values: Sequence[Any],
                           ) -> Optional[str]:
    """Build ``DELETE FROM "m" WHERE time = '...' [AND "tag"='v' ...]``.

    Tags present in the result row are added as equality conditions so only
    the intended point (not every point sharing the timestamp) is removed.
    Returns None when the row time is missing.
    """
    col_index = {name: i for i, name in enumerate(columns)}
    time_idx = col_index.get("time")
    if time_idx is None or time_idx >= len(row_values):
        return None
    ns = timestamp_to_ns(row_values[time_idx])
    if ns is None:
        return None
    m = measurement.replace('"', '\\"')
    where = [f"time = '{ns_to_rfc3339(ns)}'"]
    for name in sorted(tag_columns):
        i = col_index.get(name)
        if i is None or i >= len(row_values) or row_values[i] is None:
            continue
        key = name.replace('"', '\\"')
        where.append(f'"{key}" = \'{_escape_InfluxQL_string(row_values[i])}\'')
    return f'DELETE FROM "{m}" WHERE ' + " AND ".join(where)
