# -*- coding: utf-8 -*-
"""Unit tests for core/query_tools.py (pagination, editing, line protocol)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from net.sakurain.influxdbstudio.core import query_tools as qt
from net.sakurain.influxdbstudio.core.client import HttpInfluxDbClient
from net.sakurain.influxdbstudio.core.models import (
    InfluxDbConnection,
    InfluxDbSeries,
)


def test_can_paginate_plain_select():
    assert qt.can_paginate('SELECT * FROM "m" WHERE time > now() - 1d')


def test_can_paginate_rejects_explicit_limit():
    assert not qt.can_paginate('SELECT * FROM "m" LIMIT 5')
    assert not qt.can_paginate('SELECT * FROM "m" LIMIT 5 OFFSET 10')
    assert not qt.can_paginate('SELECT * FROM "m" SLIMIT 3')


def test_can_paginate_rejects_non_select_and_into():
    assert not qt.can_paginate("SHOW MEASUREMENTS")
    assert not qt.can_paginate('SELECT * INTO "backup" FROM "m"')


def test_paginate_query_appends_limit_offset():
    q = qt.paginate_query('SELECT * FROM "m";', 100, 200)
    assert q == 'SELECT * FROM "m" LIMIT 100 OFFSET 200'


def test_build_count_query_basic():
    q = qt.build_count_query('SELECT * FROM "m" WHERE time > now() - 1d')
    assert q == 'SELECT COUNT(*) FROM "m" WHERE time > now() - 1d'


def test_build_count_query_stops_at_group_by():
    assert qt.build_count_query(
        'SELECT MEAN("v") FROM "m" GROUP BY time(1h)') is None


def test_build_count_query_none_for_show():
    assert qt.build_count_query("SHOW MEASUREMENTS") is None


def test_timestamp_to_ns_epoch_and_rfc3339():
    assert qt.timestamp_to_ns(123) == 123
    assert qt.timestamp_to_ns("1970-01-01T00:00:00Z") == 0
    assert qt.timestamp_to_ns("1970-01-01T00:00:00.123456789Z") == 123456789
    assert qt.timestamp_to_ns("1970-01-01T08:00:00+08:00") == 0
    assert qt.timestamp_to_ns("not-a-time") is None
    assert qt.timestamp_to_ns(None) is None


def test_parse_edited_value_typing():
    assert qt.parse_edited_value("42") == 42
    assert qt.parse_edited_value("-3.5") == -3.5
    assert qt.parse_edited_value("true") is True
    assert qt.parse_edited_value("FALSE") is False
    assert qt.parse_edited_value("hello world") == "hello world"
    assert qt.parse_edited_value("") == ""


def test_build_overwrite_point():
    from datetime import datetime, timezone
    columns = ["time", "nmunicateAddr", "currentA", "frozenDensity"]
    row = ["2026-09-27T16:00:00.000000001Z", "042760236", 0.5, 3]
    point = qt.build_overwrite_point(
        "curveData3761", columns, {"nmunicateAddr"}, row,
        {"currentA": 0.9, "frozenDensity": 4})
    assert point is not None
    assert point.Tags == {"nmunicateAddr": "042760236"}
    assert point.Fields == {"currentA": 0.9, "frozenDensity": 4}
    # nanosecond precision must survive (1ns after the second)
    seconds = int(datetime(2026, 9, 27, 16, 0, 0, tzinfo=timezone.utc).timestamp())
    assert point.TimeStampNs == seconds * 1_000_000_000 + 1


def test_build_overwrite_point_ignores_time_and_tags():
    columns = ["time", "t1", "v1"]
    row = ["2026-09-27T16:00:00Z", "a", 1]
    point = qt.build_overwrite_point("m", columns, {"t1"}, row,
                                     {"time": 0, "t1": "x", "v1": 2})
    assert point.Fields == {"v1": 2}
    assert point.Tags == {"t1": "a"}


def test_build_overwrite_point_requires_time():
    point = qt.build_overwrite_point("m", ["v1"], set(), [1], {"v1": 2})
    assert point is None


def test_point_to_line_uses_raw_ns():
    conn = InfluxDbConnection.create(name="c", host="h", port=1)
    client = HttpInfluxDbClient(conn)
    point = qt.build_overwrite_point(
        "curveData3761", ["time", "v1"], set(),
        ["1970-01-01T00:00:00.000000001Z", 1], {"v1": 2})
    line = client._point_to_line(point)
    assert line == "curveData3761 v1=2i 1"


def test_point_to_line_escapes():
    conn = InfluxDbConnection.create(name="c", host="h", port=1)
    client = HttpInfluxDbClient(conn)
    point = qt.build_overwrite_point(
        "my meas", ["time", "tag a", "s"], set(),
        ["1970-01-01T00:00:00Z", "x,y", "he said \"hi\""],
        {"s": 'he said "hi"'})
    point.Tags = {"tag a": "x,y"}
    line = client._point_to_line(point)
    assert line.startswith("my\\ meas,tag\\ a=x\\,y ")
    assert 's="he said \\"hi\\""' in line
    assert line.endswith(" 0")


def test_parse_count_value():
    series = [InfluxDbSeries("m", ["time", "count"], None,
                             [["1970-01-01T00:00:00Z", 691681]])]
    assert qt.parse_count_value(series) == 691681
    assert qt.parse_count_value([]) is None


def test_ns_to_rfc3339_full_precision():
    assert qt.ns_to_rfc3339(0) == "1970-01-01T00:00:00.000000000Z"
    assert qt.ns_to_rfc3339(123456789) == "1970-01-01T00:00:00.123456789Z"
    seconds = 1767225600  # 2026-01-01T00:00:00Z
    assert qt.ns_to_rfc3339(seconds * 1_000_000_000 + 1) == \
        "2026-01-01T00:00:00.000000001Z"


def test_build_delete_statement_basic():
    stmt = qt.build_delete_statement(
        "curveData3761", ["time", "v1"], set(),
        ["2026-09-27T16:00:00.000000001Z", 3])
    assert stmt == ('DELETE FROM "curveData3761" '
                    "WHERE time = '2026-09-27T16:00:00.000000001Z'")


def test_build_delete_statement_with_tags():
    stmt = qt.build_delete_statement(
        "m", ["time", "addr", "v1"], {"addr"},
        ["2026-09-27T16:01:00Z", "042760237", 4])
    assert stmt == ('DELETE FROM "m" '
                    "WHERE time = '2026-09-27T16:01:00.000000000Z' "
                    "AND \"addr\" = '042760237'")


def test_build_delete_statement_escapes_quotes():
    stmt = qt.build_delete_statement(
        "m", ["time", "tag"], {"tag"},
        ["2026-09-27T16:01:00Z", "o'clock"])
    assert "'o\\'clock'" in stmt


def test_build_delete_statement_missing_time():
    assert qt.build_delete_statement("m", ["v1"], set(), [1]) is None
    assert qt.build_delete_statement("m", ["time"], set(), [None]) is None
    assert qt.build_delete_statement("m", ["time"], set(), []) is None


def test_strip_line_comments_and_select_detection():
    assert qt.strip_line_comments("-- header\nSELECT 1\n  -- tail\n") == "SELECT 1"
    assert qt.is_select_query("-- header\nSELECT * FROM m")
    assert qt.can_paginate("-- header\nSELECT * FROM m")
    assert qt.build_count_query("-- header\nSELECT * FROM m WHERE x = 1") == \
        "SELECT COUNT(*) FROM m WHERE x = 1"
    # 字符串内的 -- 不受影响（只处理整行注释）
    assert qt.strip_line_comments("SELECT 'a--b'") == "SELECT 'a--b'"
