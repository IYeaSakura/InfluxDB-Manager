"""Core layer unit tests — no network, no GUI required."""
from __future__ import annotations

import json
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
