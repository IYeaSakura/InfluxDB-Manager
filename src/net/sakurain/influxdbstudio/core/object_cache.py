"""Object-name cache for SQL autocomplete (1.4.0).

Collects measurement names plus tag/field keys for one database and keeps
them in a short-TTL in-memory cache, so the completer can refresh without
hammering the server. All reads are plain SELECT/SHOW (read-only).
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

TTL_SECONDS = 300

# key: (id(client), database) -> (monotonic timestamp, sorted names)
_cache: Dict[Tuple[int, str], Tuple[float, List[str]]] = {}


def invalidate(client=None, database: Optional[str] = None) -> None:
    """Drop cached names; with no arguments clears everything."""
    global _cache
    if client is None:
        _cache = {}
        return
    keys = [k for k in _cache if k[0] == id(client)
            and (database is None or k[1] == database)]
    for k in keys:
        _cache.pop(k, None)


def cached_object_names(client, database: str, force: bool = False) -> List[str]:
    """Measurements + tag keys + field keys for ``database``, cached.

    Returns the previous cache content (possibly empty) when the refresh
    fails, so the completer degrades gracefully on network errors.
    """
    key = (id(client), database or "")
    now = time.monotonic()
    entry = _cache.get(key)
    if not force and entry is not None and now - entry[0] < TTL_SECONDS:
        return entry[1]
    names = set()
    try:
        names.update(client.get_measurement_names(database))
    except Exception as ex:  # noqa: BLE001 - degrade to cache/partial
        log.debug("measurement names fetch failed: %s", ex)
    for statement, column in (("SHOW TAG KEYS", "tagKey"),
                              ("SHOW FIELD KEYS", "fieldKey")):
        try:
            for series in client.query(database, statement):
                if column not in (series.Columns or []):
                    continue
                idx = series.Columns.index(column)
                for row in series.Values or []:
                    if idx < len(row) and row[idx]:
                        names.add(str(row[idx]))
        except Exception as ex:  # noqa: BLE001
            log.debug("%s fetch failed: %s", statement, ex)
    merged = sorted(names, key=str.lower)
    _cache[key] = (now, merged)
    return merged
