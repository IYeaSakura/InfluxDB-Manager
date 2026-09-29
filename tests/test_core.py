"""Core layer unit tests — no network, no GUI required."""
from __future__ import annotations

import json
import os
from datetime import datetime

import pytest

from net.sakurain.influxdbstudio.core import helper
from net.sakurain.influxdbstudio.core.client import HttpInfluxDbClient, InfluxDbApiResponse
from net.sakurain.influxdbstudio.core.models import (
    InfluxDbBackfillParams,
    InfluxDbConnection,
    InfluxDbCqParams,
    InfluxDbFillTypes,
    InfluxDbPoint,
    InfluxDbSeries,
)
from net.sakurain.influxdbstudio.core.settings import AppSettings
from net.sakurain.influxdbstudio import i18n


# ---------------------------------------------------------------------------
# InfluxDbHelper
# ---------------------------------------------------------------------------

class TestTimeIntervalValidation:
    @pytest.mark.parametrize("value", ["1h", "30m", "15s", "2d", "1w", "10u", "500ms", "45s"])
    def test_valid(self, value):
        assert helper.is_time_interval_valid(value)

    @pytest.mark.parametrize("value", ["", None, "h", "1x", "m1", "-5m", "1", "abc"])
    def test_invalid(self, value):
        assert not helper.is_time_interval_valid(value)

    def test_csharp_parity_loose_match(self):
        # Same as the C# regex behavior: only the FIRST value+unit pair is
        # examined, so trailing junk after a valid pair is accepted.
        assert helper.is_time_interval_valid("1hm")

    def test_units(self):
        assert helper.convert_time_unit("h") .name == "Hours"
        assert helper.convert_time_unit("ms").name == "Milliseconds"
        assert helper.convert_time_unit("q").name == "None_"
        assert helper.time_unit_to_str(helper.InfluxDbTimeUnits.Days) == "d"


# ---------------------------------------------------------------------------
# Query statement generation (InfluxData.Net template parity)
# ---------------------------------------------------------------------------

def _make_client():
    conn = InfluxDbConnection.create(name="test", host="localhost", port=8086)
    return HttpInfluxDbClient(conn)


def _capture_post(client, responses=None):
    captured = []

    def fake_post(query, database=None):
        captured.append((query, database))
        return InfluxDbApiResponse(" ", 200, True)

    client._post_query = fake_post
    return captured


class TestStatementGeneration:
    def test_create_database(self):
        client = _make_client()
        captured = _capture_post(client)
        client.create_database("mydb")
        assert captured[0][0] == 'CREATE DATABASE "mydb"'

    def test_drop_database(self):
        client = _make_client()
        captured = _capture_post(client)
        client.drop_database("mydb")
        assert captured[0][0] == 'DROP DATABASE "mydb"'

    def test_create_retention_policy(self):
        client = _make_client()
        captured = _capture_post(client)
        client.create_retention_policy("mydb", "myrp", "1d", 2, is_default=True)
        assert captured[0][0] == "CREATE RETENTION POLICY myrp ON mydb DURATION 1d REPLICATION 2"
        assert captured[1][0] == 'ALTER RETENTION POLICY "myrp" ON "mydb" DEFAULT'

    def test_alter_retention_policy(self):
        client = _make_client()
        captured = _capture_post(client)
        client.alter_retention_policy("mydb", "myrp", "30d", 1, is_default=True)
        assert captured[0][0] == "ALTER RETENTION POLICY myrp ON mydb DURATION 30d REPLICATION 1"
        assert captured[1][0] == 'ALTER RETENTION POLICY "myrp" ON "mydb" DEFAULT'

    def test_drop_series(self):
        client = _make_client()
        captured = _capture_post(client)
        client.drop_series("mydb", "cpu")
        assert captured[0][0] == 'DROP SERIES FROM "cpu"'

    def test_continuous_query(self):
        client = _make_client()
        captured = _capture_post(client)
        params = InfluxDbCqParams(
            Name="my_cq", Database="mydb",
            SubQueries=["MEAN(value)"], Destination="dst", Source="src",
            Interval="30m", FillType=InfluxDbFillTypes.Previous,
            Tags=["host", "region"],
            ResampleEveryInterval="1h", ResampleForInterval="90m")
        client.create_continuous_query(params)
        query, _db = captured[0]
        assert query == (
            "CREATE CONTINUOUS QUERY my_cq ON mydb "
            "RESAMPLE EVERY 1h FOR 90m "
            "BEGIN SELECT MEAN(value) INTO \"dst\" FROM src "
            "GROUP BY time(30m) , host, region fill(previous) END;"
        )

    def test_continuous_query_no_resample_no_fill(self):
        client = _make_client()
        captured = _capture_post(client)
        params = InfluxDbCqParams(
            Name="cq2", Database="mydb",
            SubQueries=["MEAN(value)"], Destination="dst", Source="src",
            Interval="1h", FillType=InfluxDbFillTypes.Null)
        client.create_continuous_query(params)
        query, _db = captured[0]
        assert query == (
            "CREATE CONTINUOUS QUERY cq2 ON mydb "
            "BEGIN SELECT MEAN(value) INTO \"dst\" FROM src "
            "GROUP BY time(1h)   END;"
        )

    def test_backfill(self):
        client = _make_client()
        captured = _capture_post(client)
        params = InfluxDbBackfillParams(
            SubQueries=["MEAN(value)"], Destination="dst", Source="src",
            Interval="1h", FromTime=datetime(2026, 1, 1, 0, 0, 0),
            ToTime=datetime(2026, 2, 1, 0, 0, 0),
            Filters=["host = 'a'", "region = 'b'"],
            FillType=InfluxDbFillTypes.None_)
        client.backfill("mydb", params)
        query, db = captured[0]
        assert db == "mydb"
        assert query == (
            "SELECT MEAN(value) INTO \"dst\" FROM src "
            "WHERE host = 'a' AND region = 'b' AND "
            "time >= '2026-01-01 00:00:00' AND time < '2026-02-01 00:00:00' "
            "GROUP BY time(1h)  fill(none)"
        )

    def test_create_user_admin(self):
        client = _make_client()
        captured = _capture_post(client)
        client.create_user("bob", "p@ss'word", True)
        assert captured[0][0] == (
            "CREATE USER \"bob\" WITH PASSWORD 'p@ss\\'word' WITH ALL PRIVILEGES")

    def test_grant_privilege(self):
        client = _make_client()
        captured = _capture_post(client)
        from net.sakurain.influxdbstudio.core.models import InfluxDbPrivileges
        client.grant_privilege("bob", InfluxDbPrivileges.All, "mydb")
        assert captured[0][0] == 'GRANT ALL ON "mydb" TO "bob"'
        client.revoke_privilege("bob", InfluxDbPrivileges.Read, "mydb")
        assert captured[1][0] == 'REVOKE READ ON "mydb" FROM "bob"'


# ---------------------------------------------------------------------------
# Line protocol
# ---------------------------------------------------------------------------

class TestLineProtocol:
    def test_point_format(self):
        client = _make_client()
        point = InfluxDbPoint(
            "cpu load", {"host": "server 1", "dc": "us west"},
            {"value": 0.64, "count": 3, "ok": True, "name": "x"},
            datetime(2026, 1, 1, tzinfo=None))
        line = client._point_to_line(point)
        assert line.startswith("cpu\\ load,")
        assert "host=server\\ 1" in line
        assert "dc=us\\ west" in line
        assert 'value=0.64' in line
        assert "count=3i" in line
        assert "ok=true" in line
        assert 'name="x"' in line


# ---------------------------------------------------------------------------
# Series model
# ---------------------------------------------------------------------------

class TestSeries:
    def test_column_index(self):
        series = InfluxDbSeries("m", ["time", "value"], {}, [[1, 2]])
        assert series.get_column_index("value") == 1
        assert series.get_column_index("missing") == -1


# ---------------------------------------------------------------------------
# Settings (C# JSON compatibility)
# ---------------------------------------------------------------------------

class TestSettings:
    def test_export_import_round_trip(self):
        settings = AppSettings(version="1.0.0")
        settings.connections.append(InfluxDbConnection.create(
            name="local", host="localhost", port=8086,
            username="root", password="secret", database="mydb"))
        text = settings.to_export_json()
        loaded = AppSettings.from_export_json(text)
        assert len(loaded.connections) == 1
        c = loaded.connections[0]
        assert c.Name == "local" and c.Host == "localhost" and c.Port == 8086
        assert c.Username == "root" and c.Password == "secret"
        assert c.Database == "mydb"

    def test_cs_compatible_keys(self):
        """The export JSON must keep the C# PascalCase key names so settings
        files can move between the .NET and Python versions."""
        settings = AppSettings(version="1.0.0")
        data = json.loads(settings.to_export_json())
        assert "TimeFormat" in data
        assert "DateFormat" in data
        assert "AllowUntrustedSsl" in data
        assert "Connections" in data

    def test_default_language_is_chinese(self):
        assert AppSettings().language == "zh_CN"

    def test_query_scripts_round_trip(self, tmp_path, monkeypatch):
        import net.sakurain.influxdbstudio.core.settings as sm
        monkeypatch.setattr(sm, "_settings_path",
                            lambda: str(tmp_path / "settings.json"))
        settings = AppSettings(version="1.0.0")
        settings.query_scripts = [
            {"Name": "日报查询", "ConnectionId": "id-1",
             "Database": "zn_data", "Text": "SELECT * FROM \"m\""},
            {"Name": "script (2)", "ConnectionId": "id-1",
             "Database": "", "Text": ""},
        ]
        settings.active_query_tab = 1
        settings.save_all()
        loaded = AppSettings()
        loaded.load_all()
        assert loaded.query_scripts == settings.query_scripts
        assert loaded.active_query_tab == 1
        # 空列表与缺字段也能安全往返
        settings.query_scripts = []
        settings.active_query_tab = -1
        settings.save_all()
        loaded2 = AppSettings()
        loaded2.load_all()
        assert loaded2.query_scripts == []
        assert loaded2.active_query_tab == -1


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

class TestI18n:
    def test_default_chinese(self):
        assert i18n.get_language() == "zh_CN"
        assert i18n.tr("menu.file") == "文件(&F)"

    def test_switch_to_english(self):
        i18n.set_language("en_US")
        try:
            assert i18n.tr("menu.file") == "&File"
            assert i18n.tr("drop.database.confirm", name="x") == "Drop database: x?"
        finally:
            i18n.set_language("zh_CN")


# ---------------------------------------------------------------------------
# Resource path resolution (source tree + frozen/PyInstaller layout)
# ---------------------------------------------------------------------------

class TestResourcePaths:
    def test_icons_dir_contains_tree_icons(self):
        from net.sakurain.influxdbstudio.ui.common import icons_dir, icon_path
        assert os.path.isdir(icons_dir())
        assert os.path.isfile(icon_path("Connection"))
        assert os.path.isfile(icon_path("Refresh"))

    def test_app_icon_png_exists(self):
        from net.sakurain.influxdbstudio.ui.common import resource_path
        p = resource_path("sakurain.png")
        assert os.path.isfile(p)

    def test_frozen_mode_uses_meipass(self, monkeypatch):
        from net.sakurain.influxdbstudio.ui import common
        monkeypatch.setattr(common.sys, "frozen", True, raising=False)
        monkeypatch.setattr(common.sys, "_MEIPASS", r"C:\tmp\_MEI12345",
                            raising=False)
        try:
            assert common.resources_dir() == os.path.join(
                r"C:\tmp\_MEI12345", "net", "sakurain", "influxdbstudio",
                "resources")
            assert common.resource_path("sakurain.png") == os.path.join(
                r"C:\tmp\_MEI12345", "net", "sakurain", "influxdbstudio",
                "resources", "sakurain.png")
        finally:
            monkeypatch.undo()


# ---------------------------------------------------------------------------
# Server-side filter / ORDER BY injection (1.2.0)
# ---------------------------------------------------------------------------

class TestFilterAndOrderInjection:
    def test_inject_new_where(self):
        from net.sakurain.influxdbstudio.core import query_tools
        out = query_tools.inject_conditions(
            'SELECT * FROM "m"', ['"a" = \'1\''])
        assert out == 'SELECT * FROM "m" WHERE ("a" = \'1\')'

    def test_inject_and_existing_where(self):
        from net.sakurain.influxdbstudio.core import query_tools
        out = query_tools.inject_conditions(
            'SELECT * FROM "m" WHERE time > now() - 1h', ['"a" = \'1\''])
        assert out == ('SELECT * FROM "m" WHERE time > now() - 1h '
                       'AND ("a" = \'1\')')

    def test_inject_keeps_trailing_limit(self):
        from net.sakurain.influxdbstudio.core import query_tools
        out = query_tools.inject_conditions(
            'SELECT * FROM "m" WHERE a = 1 LIMIT 100', ['b = 2'])
        assert out == 'SELECT * FROM "m" WHERE a = 1 AND (b = 2) LIMIT 100'

    def test_inject_rejects_group_by_and_into(self):
        from net.sakurain.influxdbstudio.core import query_tools
        assert query_tools.inject_conditions(
            'SELECT mean(v) FROM "m" GROUP BY time(1h)', ['a=1']) is None
        assert query_tools.inject_conditions(
            'SELECT v INTO "n" FROM "m"', ['a=1']) is None

    def test_inject_strips_semicolon(self):
        from net.sakurain.influxdbstudio.core import query_tools
        out = query_tools.inject_conditions(
            'SELECT * FROM "m";', ['a=1'])
        assert out == 'SELECT * FROM "m" WHERE (a=1)'

    def test_filter_condition_numeric_field(self):
        from net.sakurain.influxdbstudio.core import query_tools
        assert query_tools.build_filter_condition(
            "currentA", ">", "0.5", numeric=True) == '"currentA" > 0.5'

    def test_filter_condition_tag_quotes_leading_zero(self):
        from net.sakurain.influxdbstudio.core import query_tools
        out = query_tools.build_filter_condition(
            "nmunicateAddr", "=", "042760236")
        assert out == '"nmunicateAddr" = \'042760236\''

    def test_filter_condition_time_expression(self):
        from net.sakurain.influxdbstudio.core import query_tools
        assert query_tools.build_filter_condition(
            "time", ">", "now() - 1h") == '"time" > now() - 1h'

    def test_filter_condition_time_rfc3339_quoted(self):
        from net.sakurain.influxdbstudio.core import query_tools
        out = query_tools.build_filter_condition(
            "time", ">=", "2026-09-27T16:00:00Z")
        assert out == '"time" >= \'2026-09-27T16:00:00Z\''

    def test_order_by_time_injection(self):
        from net.sakurain.influxdbstudio.core import query_tools
        out = query_tools.inject_order_by_time(
            'SELECT * FROM "m" WHERE a = 1', True)
        assert out == 'SELECT * FROM "m" WHERE a = 1 ORDER BY time DESC'

    def test_order_by_time_rejects_existing(self):
        from net.sakurain.influxdbstudio.core import query_tools
        assert query_tools.inject_order_by_time(
            'SELECT * FROM "m" ORDER BY time ASC', False) is None


# ---------------------------------------------------------------------------
# Query history + ReadOnly connection (1.2.0)
# ---------------------------------------------------------------------------

class TestQueryHistory:
    def test_record_dedupes_and_caps(self):
        import net.sakurain.influxdbstudio.core.settings as sm
        s = sm.AppSettings()
        s.record_query("c1", "db1", "SELECT 1")
        s.record_query("c1", "db1", "SELECT 2")
        s.record_query("c1", "db1", "SELECT 1")  # moves to front
        assert [h["Text"] for h in s.query_history] == ["SELECT 1", "SELECT 2"]
        assert s.query_history[0]["ConnectionId"] == "c1"
        for i in range(250):
            s.record_query("c1", "db1", f"SELECT {i}")
        assert len(s.query_history) == s.HISTORY_LIMIT

    def test_history_for_filters_by_connection(self):
        import net.sakurain.influxdbstudio.core.settings as sm
        s = sm.AppSettings()
        s.record_query("c1", "db1", "SELECT 1")
        s.record_query("c2", "db1", "SELECT 2")
        assert [h["Text"] for h in s.history_for("c1")] == ["SELECT 1"]
        assert len(s.history_for("c2")) == 1

    def test_blank_text_not_recorded(self):
        import net.sakurain.influxdbstudio.core.settings as sm
        s = sm.AppSettings()
        s.record_query("c1", "db1", "   ")
        assert s.query_history == []

    def test_history_roundtrip_in_settings_json(self, tmp_path, monkeypatch):
        import net.sakurain.influxdbstudio.core.settings as sm
        monkeypatch.setattr(sm, "_settings_path",
                            lambda: str(tmp_path / "s.json"))
        s = sm.AppSettings()
        s.record_query("c1", "db1", "SELECT 1")
        s2 = sm.AppSettings()
        s2.load_all()
        assert [h["Text"] for h in s2.query_history] == ["SELECT 1"]


class TestReadOnlyConnection:
    def test_readonly_roundtrip(self):
        from net.sakurain.influxdbstudio.core.models import InfluxDbConnection
        c = InfluxDbConnection.create(name="n", host="h", port=8086)
        c.ReadOnly = True
        d = InfluxDbConnection.from_dict(c.to_dict())
        assert d.ReadOnly is True

    def test_readonly_defaults_false_and_csharp_compatible(self):
        from net.sakurain.influxdbstudio.core.models import InfluxDbConnection
        d = InfluxDbConnection.from_dict({"Id": "x", "Name": "n"})
        assert d.ReadOnly is False
        # C#-era exports (no ReadOnly key) still load
        assert "UseSsl" in d.to_dict() and "ReadOnly" in d.to_dict()


# ---------------------------------------------------------------------------
# 1.3.0: CSV import
# ---------------------------------------------------------------------------

class TestCsvImport:
    CSV_TEXT = (
        "time,device,temp,humidity,note\n"
        "2026-09-29T00:00:00Z,a,21.5,60,ok\n"
        "2026-09-29T00:01:00Z,b,22,61,\n"
        "2026-09-29T00:02:00Z,a,not-a-number,62,ok\n"
    )

    def _write(self, tmp_path, text=None):
        p = tmp_path / "data.csv"
        p.write_text(text if text is not None else self.CSV_TEXT,
                     encoding="utf-8")
        return str(p)

    def test_read_rows_with_header(self, tmp_path):
        from net.sakurain.influxdbstudio.core import csv_import
        headers, rows = csv_import.read_rows(self._write(tmp_path))
        assert headers == ["time", "device", "temp", "humidity", "note"]
        assert len(rows) == 3

    def test_read_rows_without_header(self, tmp_path):
        from net.sakurain.influxdbstudio.core import csv_import
        path = self._write(tmp_path, "1,2\n3,4\n")
        headers, rows = csv_import.read_rows(path, has_header=False)
        assert headers == ["column_1", "column_2"]
        assert rows == [["1", "2"], ["3", "4"]]

    def test_read_rows_custom_delimiter(self, tmp_path):
        from net.sakurain.influxdbstudio.core import csv_import
        path = self._write(tmp_path, "a;b\n1;2\n")
        headers, _ = csv_import.read_rows(path, ";")
        assert headers == ["a", "b"]

    def test_guess_mapping(self):
        from net.sakurain.influxdbstudio.core import csv_import
        headers = ["time", "device", "temp", "note"]
        sample = [["2026-09-29T00:00:00Z", "a", "21.5", "x"]]
        assert csv_import.guess_mapping(headers, sample) == [
            csv_import.ROLE_TIME, csv_import.ROLE_TAG,
            csv_import.ROLE_FIELD, csv_import.ROLE_TAG,
        ]

    def test_parse_points_types_and_tags(self, tmp_path):
        from net.sakurain.influxdbstudio.core import csv_import
        headers, rows = csv_import.read_rows(self._write(tmp_path))
        mapping = [csv_import.ROLE_TIME, csv_import.ROLE_TAG,
                   csv_import.ROLE_FIELD, csv_import.ROLE_FIELD,
                   csv_import.ROLE_IGNORE]
        result = csv_import.parse_points(headers, rows, mapping, "weather")
        # middle row has empty note column ignored; all 3 rows parse
        assert len(result.points) == 3
        p0 = result.points[0]
        assert p0.Measurement == "weather"
        assert p0.Tags == {"device": "a"}
        assert p0.Fields["temp"] == 21.5
        assert p0.Fields["humidity"] == 60
        assert "note" not in p0.Fields
        assert p0.TimeStampNs is not None

    def test_parse_points_field_string_forces_string(self, tmp_path):
        from net.sakurain.influxdbstudio.core import csv_import
        path = self._write(tmp_path, "code\n042760236\n")
        headers, rows = csv_import.read_rows(path)
        result = csv_import.parse_points(
            headers, rows, [csv_import.ROLE_FIELD_STRING], "m")
        assert result.points[0].Fields["code"] == "042760236"

    def test_parse_points_bad_time_is_error_not_crash(self):
        from net.sakurain.influxdbstudio.core import csv_import
        headers = ["time", "v"]
        rows = [["not-a-time", "1"], ["2026-09-29T00:00:00Z", "2"]]
        result = csv_import.parse_points(
            headers, rows, [csv_import.ROLE_TIME, csv_import.ROLE_FIELD], "m")
        assert len(result.points) == 1
        assert len(result.errors) == 1
        assert result.errors[0].line == 1

    def test_parse_points_requires_measurement_and_field(self):
        from net.sakurain.influxdbstudio.core import csv_import
        r1 = csv_import.parse_points(["v"], [["1"]],
                                     [csv_import.ROLE_FIELD], "")
        assert not r1.ok
        r2 = csv_import.parse_points(["v"], [["1"]],
                                     [csv_import.ROLE_TAG], "m")
        assert not r2.ok

    def test_batches_split(self):
        from net.sakurain.influxdbstudio.core import csv_import
        from net.sakurain.influxdbstudio.core.models import InfluxDbPoint
        pts = [InfluxDbPoint("m", fields={"v": i}) for i in range(7)]
        chunks = csv_import.batches(pts, 3)
        assert [len(c) for c in chunks] == [3, 3, 1]
        # falsy size falls back to the default (single batch here)
        assert [len(c) for c in csv_import.batches(pts, 0)] == [7]
        assert [len(c) for c in csv_import.batches(pts, 1)] == [1] * 7


# ---------------------------------------------------------------------------
# 1.3.0: ranged DELETE
# ---------------------------------------------------------------------------

class TestRangedDelete:
    def test_time_range_only(self):
        from net.sakurain.influxdbstudio.core import query_tools
        stmt = query_tools.build_ranged_delete("m", 1_000_000_000,
                                               2_000_000_000)
        assert stmt == ('DELETE FROM "m" WHERE '
                        "time >= '1970-01-01T00:00:01.000000000Z' "
                        "AND time < '1970-01-01T00:00:02.000000000Z'")

    def test_conditions_only(self):
        from net.sakurain.influxdbstudio.core import query_tools
        stmt = query_tools.build_ranged_delete(
            "m", conditions=['"site" = \'a\''])
        assert stmt == 'DELETE FROM "m" WHERE ("site" = \'a\')'

    def test_refuses_full_measurement_delete(self):
        from net.sakurain.influxdbstudio.core import query_tools
        assert query_tools.build_ranged_delete("m") is None
        assert query_tools.build_ranged_delete("") is None
        assert query_tools.build_ranged_delete("m", conditions=[]) is None

    def test_measurement_escaping(self):
        from net.sakurain.influxdbstudio.core import query_tools
        stmt = query_tools.build_ranged_delete('we"ird', 0, None)
        assert 'FROM "we\\"ird"' in stmt


# ---------------------------------------------------------------------------
# 1.3.0: password protection at rest
# ---------------------------------------------------------------------------

class TestSecrets:
    def test_roundtrip(self):
        from net.sakurain.influxdbstudio.core import secrets
        cipher = secrets.protect("sa")
        assert cipher != "sa"
        assert secrets.is_protected(cipher)
        assert secrets.unprotect(cipher) == "sa"

    def test_plaintext_passthrough(self):
        from net.sakurain.influxdbstudio.core import secrets
        assert secrets.protect("") == ""
        assert secrets.unprotect("plain") == "plain"
        assert not secrets.is_protected("plain")
        assert not secrets.is_protected("")

    def test_settings_roundtrip_encrypts_at_rest(self, tmp_path, monkeypatch):
        import net.sakurain.influxdbstudio.core.settings as sm
        monkeypatch.setattr(sm, "_settings_path",
                            lambda: str(tmp_path / "s.json"))
        s = sm.AppSettings()
        from net.sakurain.influxdbstudio.core.models import InfluxDbConnection
        c = InfluxDbConnection.create(name="n", host="h", port=8086,
                                      username="u", password="sa")
        s.connections = [c]
        s.save_all()
        raw = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
        stored = raw["Connections"][0]["Password"]
        assert stored != "sa" or not sm.secrets.available()
        # reload restores plaintext in memory
        s2 = sm.AppSettings()
        s2.load_all()
        assert s2.connections[0].Password == "sa"

    def test_export_stays_csharp_compatible(self, tmp_path, monkeypatch):
        """The export file keeps plaintext passwords so the C# version (and
        older releases) can import it."""
        import net.sakurain.influxdbstudio.core.settings as sm
        monkeypatch.setattr(sm, "_settings_path",
                            lambda: str(tmp_path / "s.json"))
        s = sm.AppSettings()
        from net.sakurain.influxdbstudio.core.models import InfluxDbConnection
        c = InfluxDbConnection.create(name="n", host="h", port=8086,
                                      password="sa")
        s.connections = [c]
        s.save_all()  # encrypted at rest
        exported = json.loads(s.to_export_json())
        assert exported["Connections"][0]["Password"] == "sa"
        # and an export containing our own encrypted blob still imports
        s2 = sm.AppSettings.from_export_json(s.to_export_json())
        assert s2.connections[0].Password == "sa"


# ---------------------------------------------------------------------------
# 1.3.0: connection categories
# ---------------------------------------------------------------------------

class TestConnectionCategory:
    def test_roundtrip(self):
        from net.sakurain.influxdbstudio.core.models import InfluxDbConnection
        c = InfluxDbConnection.create(name="n", host="h", port=8086)
        c.Category = "production"
        d = InfluxDbConnection.from_dict(c.to_dict())
        assert d.Category == "production"

    def test_defaults_empty_and_csharp_compatible(self):
        from net.sakurain.influxdbstudio.core.models import InfluxDbConnection
        d = InfluxDbConnection.from_dict({"Id": "x", "Name": "n"})
        assert d.Category == ""
        assert "Category" in d.to_dict()
