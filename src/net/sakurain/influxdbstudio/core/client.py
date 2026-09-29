"""InfluxDB 1.x HTTP client (sync).

Python equivalent of the C# ``InfluxDbClient`` abstract class and its
``InfluxDataNetClient`` implementation. All InfluxQL statement templates are
ported verbatim from InfluxData.Net (QueryStatements.cs / *QueryBuilder.cs)
so the queries sent to the server are byte-for-byte the same as the .NET
version.

The client is synchronous and blocking; the UI layer runs it on background
threads (see ``net.sakurain.influxdbstudio.core.async_utils``).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import httpx

from .helper import is_time_interval_valid
from .models import (
    InfluxDbApiResponse,
    InfluxDbBackfillParams,
    InfluxDbConnection,
    InfluxDbContinuousQuery,
    InfluxDbCqParams,
    InfluxDbDiagnostics,
    InfluxDbFieldKey,
    InfluxDbFillTypes,
    InfluxDbGrant,
    InfluxDbPingResponse,
    InfluxDbPoint,
    InfluxDbPrivileges,
    InfluxDbRetentionPolicy,
    InfluxDbRunningQuery,
    InfluxDbSeries,
    InfluxDbStats,
    InfluxDbTagValue,
    InfluxDbUser,
)

log = logging.getLogger("net.sakurain.influxdbstudio.client")

DEFAULT_TIMEOUT = 30.0
# Budget for tree lazy-loading. Kept at the default request timeout: slower
# servers must be allowed to answer, while unreachable hosts still fail fast
# (connection refused is immediate) instead of leaving the tree spinning.
TREE_LOAD_TIMEOUT = 30.0


class InfluxDbApiError(Exception):
    """Raised when the InfluxDB API returns an error response."""

    def __init__(self, message: str, status_code: int = 0, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


def _escape_single_quotes(value: str) -> str:
    return value.replace("'", "\\'")


class InfluxDbClient:
    """Base InfluxDB client. Concrete transport lives in ``HttpInfluxDbClient``."""

    def __init__(self, connection: InfluxDbConnection):
        if connection is None:
            raise ValueError("connection cannot be None")
        self.connection = connection

    # -- Databases ---------------------------------------------------------

    def get_database_names(self, timeout: Optional[float] = None) -> List[str]:
        raise NotImplementedError

    def create_database(self, database: str) -> InfluxDbApiResponse:
        raise NotImplementedError

    def drop_database(self, database: str) -> InfluxDbApiResponse:
        raise NotImplementedError

    # -- Retention Policies -------------------------------------------------

    def get_retention_policies(self, database: str) -> List[InfluxDbRetentionPolicy]:
        raise NotImplementedError

    def create_retention_policy(self, database: str, policy_name: str, duration: str,
                                replication: int, is_default: bool = False) -> InfluxDbApiResponse:
        raise NotImplementedError

    def alter_retention_policy(self, database: str, policy_name: str, duration: str,
                               replication: int, is_default: bool = False) -> InfluxDbApiResponse:
        raise NotImplementedError

    def drop_retention_policy(self, database: str, policy_name: str) -> InfluxDbApiResponse:
        raise NotImplementedError

    # -- Measurements -------------------------------------------------------

    def get_measurement_names(self, database: str,
                              timeout: Optional[float] = None) -> List[str]:
        raise NotImplementedError

    def drop_measurement(self, database: str, measurement: str) -> InfluxDbApiResponse:
        raise NotImplementedError

    def get_tag_keys(self, database: str, measurement: str) -> List[str]:
        raise NotImplementedError

    def get_tag_values(self, database: str, measurement: str, tag: str) -> List[InfluxDbTagValue]:
        raise NotImplementedError

    def get_field_keys(self, database: str, measurement: str) -> List[InfluxDbFieldKey]:
        raise NotImplementedError

    # -- Series -------------------------------------------------------------

    def get_series_names(self, database: str, measurement: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    def drop_series(self, database: str, measurement: Optional[str] = None) -> InfluxDbApiResponse:
        raise NotImplementedError

    # -- Query --------------------------------------------------------------

    def get_running_queries(self) -> List[InfluxDbRunningQuery]:
        raise NotImplementedError

    def kill_query(self, pid: int) -> InfluxDbApiResponse:
        raise NotImplementedError

    def query(self, database: str, query: str) -> List[InfluxDbSeries]:
        raise NotImplementedError

    def execute_command(self, database: str, query: str) -> InfluxDbApiResponse:
        """Run a data-modifying InfluxQL statement (DELETE / DROP ...)."""
        raise NotImplementedError

    def get_continuous_queries(self, database: str) -> List[InfluxDbContinuousQuery]:
        raise NotImplementedError

    def create_continuous_query(self, cq_params: InfluxDbCqParams) -> InfluxDbApiResponse:
        raise NotImplementedError

    def drop_continuous_query(self, database: str, cq_name: str) -> InfluxDbApiResponse:
        raise NotImplementedError

    def backfill(self, database: str, backfill_params: InfluxDbBackfillParams) -> InfluxDbApiResponse:
        raise NotImplementedError

    # -- Write --------------------------------------------------------------

    def write(self, database: str, measurement: str = None,
              tags: Dict[str, Any] = None, fields: Dict[str, Any] = None,
              time_stamp: datetime = None, retention_policy: str = None,
              point: InfluxDbPoint = None, points: Iterable[InfluxDbPoint] = None
              ) -> InfluxDbApiResponse:
        raise NotImplementedError

    # -- Server -------------------------------------------------------------

    def ping(self) -> InfluxDbPingResponse:
        raise NotImplementedError

    def get_diagnostics(self) -> InfluxDbDiagnostics:
        raise NotImplementedError

    def get_stats(self) -> InfluxDbStats:
        raise NotImplementedError

    def get_shards(self) -> List[InfluxDbSeries]:
        """Raw ``SHOW SHARDS`` series (read-only)."""
        raise NotImplementedError

    def get_subscriptions(self) -> List[InfluxDbSeries]:
        """Raw ``SHOW SUBSCRIPTIONS`` series (read-only)."""
        raise NotImplementedError

    # -- Users --------------------------------------------------------------

    def get_users(self) -> List[InfluxDbUser]:
        raise NotImplementedError

    def create_user(self, username: str, password: str, is_admin: bool) -> InfluxDbApiResponse:
        raise NotImplementedError

    def drop_user(self, username: str) -> InfluxDbApiResponse:
        raise NotImplementedError

    def set_password(self, username: str, password: str) -> InfluxDbApiResponse:
        raise NotImplementedError

    def get_privileges(self, username: str) -> List[InfluxDbGrant]:
        raise NotImplementedError

    def grant_administrator(self, username: str) -> InfluxDbApiResponse:
        raise NotImplementedError

    def revoke_administrator(self, username: str) -> InfluxDbApiResponse:
        raise NotImplementedError

    def grant_privilege(self, username: str, privilege: InfluxDbPrivileges,
                        database: str) -> InfluxDbApiResponse:
        raise NotImplementedError

    def revoke_privilege(self, username: str, privilege: InfluxDbPrivileges,
                         database: str) -> InfluxDbApiResponse:
        raise NotImplementedError


class HttpInfluxDbClient(InfluxDbClient):
    """InfluxDB client speaking the 1.x HTTP API (query/write/ping endpoints)."""

    def __init__(self, connection: InfluxDbConnection, allow_untrusted_ssl: bool = False,
                 timeout: float = DEFAULT_TIMEOUT):
        super().__init__(connection)
        self._timeout = timeout
        verify: Any = not allow_untrusted_ssl
        if allow_untrusted_ssl:
            # Disable certificate verification entirely (matches the C#
            # SslIgnoreValidator behavior).
            verify = False
        self._client = httpx.Client(
            base_url=connection.http_connection_string,
            timeout=timeout,
            verify=verify,
            auth=(connection.Username, connection.Password) if connection.Username else None,
        )

    # -- transport primitives ------------------------------------------------

    def _request_params(self) -> Dict[str, str]:
        params: Dict[str, str] = {}
        if self.connection.Username:
            params["u"] = self.connection.Username
        if self.connection.Password:
            params["p"] = self.connection.Password
        return params

    def _get_query(self, query: str, database: Optional[str] = None,
                   timeout: Optional[float] = None) -> List[InfluxDbSeries]:
        params = self._request_params()
        params["q"] = query
        if database:
            params["db"] = database
        kwargs: dict = {"params": params}
        if timeout is not None:
            kwargs["timeout"] = timeout
        resp = self._client.get("/query", **kwargs)
        return self._parse_query_response(resp)

    def _post_query(self, query: str, database: Optional[str] = None) -> InfluxDbApiResponse:
        params = self._request_params()
        if database:
            params["db"] = database
        resp = self._client.post("/query", params=params, data={"q": query})
        body = resp.text or ""
        self._raise_for_api_error(resp, body)
        return InfluxDbApiResponse(body, resp.status_code, resp.status_code < 300)

    @staticmethod
    def _raise_for_api_error(resp: httpx.Response, body: str) -> None:
        try:
            data = resp.json()
        except Exception:
            if resp.status_code >= 400:
                raise InfluxDbApiError(
                    f"InfluxDB API error ({resp.status_code}): {body}",
                    resp.status_code, body)
            return
        if isinstance(data, dict):
            for result in data.get("results") or []:
                if isinstance(result, dict) and result.get("error"):
                    raise InfluxDbApiError(str(result["error"]), resp.status_code, body)

    @staticmethod
    def _parse_query_response(resp: httpx.Response) -> List[InfluxDbSeries]:
        body = resp.text or ""
        self_ok = resp.status_code < 400
        try:
            data = resp.json()
        except Exception:
            if not self_ok:
                raise InfluxDbApiError(
                    f"InfluxDB API error ({resp.status_code}): {body}",
                    resp.status_code, body)
            return []
        results = (data or {}).get("results") or []
        series: List[InfluxDbSeries] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            if result.get("error"):
                raise InfluxDbApiError(str(result["error"]), resp.status_code, body)
            for s in result.get("series") or []:
                series.append(InfluxDbSeries(
                    name=s.get("name"),
                    columns=s.get("columns") or [],
                    tags=s.get("tags") or {},
                    values=s.get("values") or [],
                ))
        return series

    # -- Databases -----------------------------------------------------------

    def get_database_names(self, timeout: Optional[float] = None) -> List[str]:
        series = self._get_query("SHOW DATABASES", timeout=timeout)
        names: List[str] = []
        for s in series:
            for row in s.Values:
                if row:
                    names.append(str(row[0]))
        return names

    def create_database(self, database: str) -> InfluxDbApiResponse:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        return self._post_query(f'CREATE DATABASE "{database}"')

    def drop_database(self, database: str) -> InfluxDbApiResponse:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        return self._post_query(f'DROP DATABASE "{database}"')

    # -- Retention Policies ---------------------------------------------------

    def get_retention_policies(self, database: str) -> List[InfluxDbRetentionPolicy]:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        series = self._get_query(f"SHOW RETENTION POLICIES ON {database}")
        policies: List[InfluxDbRetentionPolicy] = []
        for s in series:
            idx = {c: i for i, c in enumerate(s.Columns)}
            for row in s.Values:
                def val(col):
                    i = idx.get(col)
                    return row[i] if i is not None and i < len(row) else None
                policies.append(InfluxDbRetentionPolicy(
                    Name=val("name"),
                    Database=database,
                    Duration=val("duration"),
                    ShardGroupDuration=val("shardGroupDuration"),
                    ReplicationCopies=int(val("replication") or 1),
                    Default=bool(val("default")),
                ))
        return policies

    def create_retention_policy(self, database: str, policy_name: str, duration: str,
                                replication: int, is_default: bool = False) -> InfluxDbApiResponse:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        if not policy_name or not policy_name.strip():
            raise ValueError("policy_name cannot be blank")
        if not duration or not duration.strip():
            raise ValueError("duration cannot be blank")
        if replication <= 0:
            replication = 1
        response = self._post_query(
            f"CREATE RETENTION POLICY {policy_name} ON {database} "
            f"DURATION {duration} REPLICATION {replication}")
        # The default flag requires a second query (as in the C# version)
        if response.Success and is_default:
            self._post_query(f'ALTER RETENTION POLICY "{policy_name}" ON "{database}" DEFAULT')
        return response

    def alter_retention_policy(self, database: str, policy_name: str, duration: str,
                               replication: int, is_default: bool = False) -> InfluxDbApiResponse:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        if not policy_name or not policy_name.strip():
            raise ValueError("policy_name cannot be blank")
        if not duration or not duration.strip():
            raise ValueError("duration cannot be blank")
        if replication <= 0:
            replication = 1
        response = self._post_query(
            f"ALTER RETENTION POLICY {policy_name} ON {database} "
            f"DURATION {duration} REPLICATION {replication}")
        if response.Success and is_default:
            self._post_query(f'ALTER RETENTION POLICY "{policy_name}" ON "{database}" DEFAULT')
        return response

    def drop_retention_policy(self, database: str, policy_name: str) -> InfluxDbApiResponse:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        if not policy_name or not policy_name.strip():
            raise ValueError("policy_name cannot be blank")
        return self._post_query(f"DROP RETENTION POLICY {policy_name} ON {database}")

    # -- Measurements ---------------------------------------------------------

    def get_measurement_names(self, database: str,
                              timeout: Optional[float] = None) -> List[str]:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        series = self._get_query("SHOW MEASUREMENTS ", database, timeout=timeout)
        names: List[str] = []
        for s in series:
            for row in s.Values:
                if row:
                    names.append(str(row[0]))
        return names

    def drop_measurement(self, database: str, measurement: str) -> InfluxDbApiResponse:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        if not measurement or not measurement.strip():
            raise ValueError("measurement cannot be blank")
        return self._post_query(f'DROP MEASUREMENT "{measurement}"', database)

    def get_tag_keys(self, database: str, measurement: str) -> List[str]:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        if not measurement or not measurement.strip():
            raise ValueError("measurement cannot be blank")
        series = self._get_query(f'SHOW TAG KEYS FROM "{measurement}"', database)
        keys: List[str] = []
        for s in series:
            idx = s.get_column_index("tagKey")
            if idx < 0:
                continue
            for row in s.Values:
                if idx < len(row) and row[idx] is not None:
                    keys.append(str(row[idx]))
        return keys

    def get_tag_values(self, database: str, measurement: str, tag: str) -> List[InfluxDbTagValue]:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        if not measurement or not measurement.strip():
            raise ValueError("measurement cannot be blank")
        if not tag or not tag.strip():
            raise ValueError("tag cannot be blank")
        series = self._get_query(
            f'SHOW TAG VALUES FROM "{measurement}" WITH KEY = "{tag}"', database)
        values: List[InfluxDbTagValue] = []
        for s in series:
            key_idx = s.get_column_index("key")
            val_idx = s.get_column_index("value")
            if key_idx < 0 or val_idx < 0:
                continue
            for row in s.Values:
                values.append(InfluxDbTagValue(
                    str(row[key_idx]) if key_idx < len(row) and row[key_idx] is not None else "",
                    str(row[val_idx]) if val_idx < len(row) and row[val_idx] is not None else "",
                ))
        return values

    def get_field_keys(self, database: str, measurement: str) -> List[InfluxDbFieldKey]:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        if not measurement or not measurement.strip():
            raise ValueError("measurement cannot be blank")
        series = self._get_query(f'SHOW FIELD KEYS FROM "{measurement}"', database)
        keys: List[InfluxDbFieldKey] = []
        for s in series:
            name_idx = s.get_column_index("fieldKey")
            type_idx = s.get_column_index("fieldType")
            if name_idx < 0:
                continue
            for row in s.Values:
                keys.append(InfluxDbFieldKey(
                    str(row[name_idx]) if name_idx < len(row) and row[name_idx] is not None else "",
                    str(row[type_idx]) if 0 <= type_idx < len(row) and row[type_idx] is not None else "",
                ))
        return keys

    # -- Series ---------------------------------------------------------------

    def get_series_names(self, database: str, measurement: Optional[str] = None) -> List[str]:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        query = "SHOW SERIES"
        if measurement:
            query += f' FROM "{measurement}"'
        series = self._get_query(query, database)
        names: List[str] = []
        for s in series:
            for row in s.Values:
                if row:
                    names.append(str(row[0]))
        return names

    def drop_series(self, database: str, measurement: Optional[str] = None) -> InfluxDbApiResponse:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        query = f'DROP SERIES FROM "{measurement}"' if measurement else "DROP SERIES"
        return self._post_query(query, database)

    # -- Query ----------------------------------------------------------------

    def get_running_queries(self) -> List[InfluxDbRunningQuery]:
        series = self._get_query("SHOW QUERIES", "_internal")
        if not series or not series[0].Values:
            return []
        queries: List[InfluxDbRunningQuery] = []
        for r in series[0].Values:
            try:
                pid = int(r[0])
            except (TypeError, ValueError):
                continue
            queries.append(InfluxDbRunningQuery(
                pid,
                str(r[2]) if len(r) > 2 and r[2] is not None else "",
                str(r[3]) if len(r) > 3 and r[3] is not None else "",
                str(r[1]) if len(r) > 1 and r[1] is not None else "",
            ))
        return queries

    def kill_query(self, pid: int) -> InfluxDbApiResponse:
        return self._post_query(f"KILL QUERY {pid}")

    def query(self, database: str, query: str) -> List[InfluxDbSeries]:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        if not query or not query.strip():
            raise ValueError("query cannot be blank")
        return self._get_query(query, database)

    def execute_command(self, database: str, query: str) -> InfluxDbApiResponse:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        if not query or not query.strip():
            raise ValueError("query cannot be blank")
        return self._post_query(query, database)

    def get_continuous_queries(self, database: str) -> List[InfluxDbContinuousQuery]:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        series = self._get_query("SHOW CONTINUOUS QUERIES")
        cqs: List[InfluxDbContinuousQuery] = []
        for s in series:
            if s.Name != database or not s.Values:
                continue
            for row in s.Values:
                if len(row) >= 2 and row[0]:
                    cqs.append(InfluxDbContinuousQuery(str(row[0]), str(row[1])))
        return cqs

    @staticmethod
    def _build_fill(fill_type: InfluxDbFillTypes) -> str:
        if fill_type == InfluxDbFillTypes.Null:
            return ""
        name = "previous" if fill_type == InfluxDbFillTypes.Previous else "none"
        return f"fill({name})"

    @staticmethod
    def _build_tags(tags: Optional[List[str]]) -> str:
        return "" if not tags else ", " + ", ".join(tags)

    @staticmethod
    def _build_resample(every: Optional[str], for_: Optional[str]) -> str:
        if not every and not for_:
            return ""
        every_param = f"EVERY {every}" if every else ""
        for_param = f"FOR {for_}" if for_ else ""
        return f"RESAMPLE {every_param} {for_param} "

    def create_continuous_query(self, cq_params: InfluxDbCqParams) -> InfluxDbApiResponse:
        if cq_params is None:
            raise ValueError("cq_params cannot be None")
        if not cq_params.Name or not cq_params.Name.strip():
            raise ValueError("cq_params.Name cannot be blank")
        if not cq_params.Database or not cq_params.Database.strip():
            raise ValueError("cq_params.Database cannot be blank")
        if not cq_params.Destination or not cq_params.Destination.strip():
            raise ValueError("cq_params.Destination cannot be blank")
        if not cq_params.Source or not cq_params.Source.strip():
            raise ValueError("cq_params.Source cannot be blank")
        if not cq_params.Interval or not cq_params.Interval.strip():
            raise ValueError("cq_params.Interval cannot be blank")
        if not cq_params.SubQueries or not cq_params.SubQueries[0]:
            raise ValueError("cq_params.SubQueries needs at least one query.")

        if not is_time_interval_valid(cq_params.Interval):
            raise ValueError("cq_params.Interval is invalid: " + cq_params.Interval)
        if cq_params.ResampleEveryInterval and not is_time_interval_valid(cq_params.ResampleEveryInterval):
            raise ValueError("cq_params.ResampleEveryInterval is invalid: " + cq_params.ResampleEveryInterval)
        if cq_params.ResampleForInterval and not is_time_interval_valid(cq_params.ResampleForInterval):
            raise ValueError("cq_params.ResampleForInterval is invalid: " + cq_params.ResampleForInterval)

        downsamplers = ", ".join(cq_params.SubQueries)
        tags = self._build_tags(cq_params.Tags)
        fill_type = self._build_fill(cq_params.FillType)
        resample = self._build_resample(cq_params.ResampleEveryInterval, cq_params.ResampleForInterval)

        sub_query = (f"SELECT {downsamplers} INTO \"{cq_params.Destination}\" "
                     f"FROM {cq_params.Source} GROUP BY time({cq_params.Interval}) "
                     f"{tags} {fill_type}")
        query = (f"CREATE CONTINUOUS QUERY {cq_params.Name} ON {cq_params.Database} "
                 f"{resample}BEGIN {sub_query} END;")
        return self._post_query(query)

    def drop_continuous_query(self, database: str, cq_name: str) -> InfluxDbApiResponse:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        if not cq_name or not cq_name.strip():
            raise ValueError("cq_name cannot be blank")
        return self._post_query(f"DROP CONTINUOUS QUERY {cq_name} ON {database}")

    def backfill(self, database: str, backfill_params: InfluxDbBackfillParams) -> InfluxDbApiResponse:
        if backfill_params is None:
            raise ValueError("backfill_params cannot be None")
        if not backfill_params.Destination or not backfill_params.Destination.strip():
            raise ValueError("backfill_params.Destination cannot be blank")
        if not backfill_params.Source or not backfill_params.Source.strip():
            raise ValueError("backfill_params.Source cannot be blank")
        if not backfill_params.Interval or not backfill_params.Interval.strip():
            raise ValueError("backfill_params.Interval cannot be blank")
        if not backfill_params.SubQueries or not backfill_params.SubQueries[0]:
            raise ValueError("backfill_params.SubQueries needs at least one query.")
        if not is_time_interval_valid(backfill_params.Interval):
            raise ValueError("backfill_params.Interval is invalid: " + backfill_params.Interval)

        downsamplers = ", ".join(backfill_params.SubQueries)
        filters = ""
        if backfill_params.Filters:
            filters = " AND ".join(backfill_params.Filters) + " AND"
        time_from = backfill_params.FromTime.strftime("%Y-%m-%d %H:%M:%S")
        time_to = backfill_params.ToTime.strftime("%Y-%m-%d %H:%M:%S")
        tags = self._build_tags(backfill_params.Tags)
        fill_type = self._build_fill(backfill_params.FillType)

        query = (f"SELECT {downsamplers} INTO \"{backfill_params.Destination}\" "
                 f"FROM {backfill_params.Source} WHERE {filters} "
                 f"time >= '{time_from}' AND time < '{time_to}' "
                 f"GROUP BY time({backfill_params.Interval}) {tags} {fill_type}")
        return self._post_query(query, database)

    # -- Write ------------------------------------------------------------------

    @staticmethod
    def _escape_measurement(name: str) -> str:
        return name.replace(",", "\\,").replace(" ", "\\ ")

    @staticmethod
    def _escape_tag_value(value: Any) -> str:
        return str(value).replace(",", "\\,").replace(" ", "\\ ").replace("=", "\\=")

    @staticmethod
    def _format_field_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return f"{value}i"
        if isinstance(value, float):
            return repr(value)
        s = str(value)
        return '"' + s.replace('"', '\\"') + '"'

    def _point_to_line(self, point: InfluxDbPoint) -> str:
        parts = [self._escape_measurement(point.Measurement)]
        if point.Tags:
            tags = ",".join(
                f"{self._escape_tag_value(k)}={self._escape_tag_value(v)}"
                for k, v in sorted(point.Tags.items()))
            parts.append("," + tags)
        fields = ",".join(
            f"{self._escape_tag_value(k)}={self._format_field_value(v)}"
            for k, v in sorted(point.Fields.items()))
        parts.append(" " + fields)
        # nanosecond precision timestamp (InfluxDB /write default)
        ts_ns = point.TimeStampNs
        if ts_ns is None:
            ts_ns = int(point.TimeStamp.timestamp() * 1e9)
        parts.append(f" {ts_ns}")
        return "".join(parts)

    def write(self, database: str, measurement: str = None,
              tags: Dict[str, Any] = None, fields: Dict[str, Any] = None,
              time_stamp: datetime = None, retention_policy: str = None,
              point: InfluxDbPoint = None, points: Iterable[InfluxDbPoint] = None
              ) -> InfluxDbApiResponse:
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        if point is None and points is None:
            point = InfluxDbPoint(measurement, tags, fields, time_stamp)
        pts = list(points) if points is not None else [point]
        if not pts:
            raise ValueError("points cannot be null or empty")

        body = "\n".join(self._point_to_line(p) for p in pts)
        params = self._request_params()
        params["db"] = database
        if retention_policy:
            params["rp"] = retention_policy
        resp = self._client.post("/write", params=params, content=body.encode("utf-8"))
        body_text = resp.text or ("")
        success = resp.status_code in (200, 204)
        if not success:
            raise InfluxDbApiError(
                f"InfluxDB write error ({resp.status_code}): {body_text}",
                resp.status_code, body_text)
        return InfluxDbApiResponse(body_text if body_text else " ", resp.status_code, True)

    # -- Server -------------------------------------------------------------------

    def ping(self) -> InfluxDbPingResponse:
        started = datetime.now().timestamp()
        resp = self._client.get("/ping")
        elapsed_ms = (datetime.now().timestamp() - started) * 1000.0
        version = resp.headers.get("X-Influxdb-Version", "")
        success = resp.status_code == 204
        return InfluxDbPingResponse(success, elapsed_ms, version)

    def get_diagnostics(self) -> InfluxDbDiagnostics:
        series = self._get_query("SHOW DIAGNOSTICS")
        diag = InfluxDbDiagnostics()
        for s in series:
            if not s.Values:
                continue
            row = s.Values[0]
            idx = {c: i for i, c in enumerate(s.Columns)}

            def val(col):
                i = idx.get(col)
                return row[i] if i is not None and i < len(row) else None

            if s.Name == "build":
                diag.Branch = val("Branch") or ""
                diag.BuildVersion = val("Version") or ""
                diag.Commit = val("Commit") or ""
            elif s.Name == "system":
                diag.CurrentTime = val("currentTime") or ""
                diag.PID = val("PID") if val("PID") is not None else ""
                diag.Started = val("started") or ""
                diag.Uptime = val("uptime") or ""
            elif s.Name == "network":
                diag.Hostname = val("hostname") or ""
            elif s.Name == "runtime":
                diag.GoArch = val("GOARCH") or ""
                diag.GoMaxProc = val("GOMAXPROCS") if val("GOMAXPROCS") is not None else ""
                diag.GoOs = val("GOOS") or ""
                diag.GoVersion = val("Version") or ""
        return diag

    def get_stats(self) -> InfluxDbStats:
        series = self._get_query("SHOW STATS")
        stats = InfluxDbStats()
        grouped: Dict[str, List[InfluxDbSeries]] = {}
        for s in series:
            attr = InfluxDbStats.SERIES_ATTR_MAP.get(s.Name or "")
            if attr:
                grouped.setdefault(attr, []).append(s)
        for attr, group in grouped.items():
            setattr(stats, attr, group)
        return stats

    def get_shards(self) -> List[InfluxDbSeries]:
        return self._get_query("SHOW SHARDS")

    def get_subscriptions(self) -> List[InfluxDbSeries]:
        return self._get_query("SHOW SUBSCRIPTIONS")

    # -- Users ----------------------------------------------------------------------

    def get_users(self) -> List[InfluxDbUser]:
        series = self._get_query("SHOW USERS")
        users: List[InfluxDbUser] = []
        for s in series:
            name_idx = s.get_column_index("user")
            admin_idx = s.get_column_index("admin")
            for row in s.Values:
                users.append(InfluxDbUser(
                    str(row[name_idx]) if name_idx >= 0 and name_idx < len(row) and row[name_idx] else "",
                    bool(row[admin_idx]) if admin_idx >= 0 and admin_idx < len(row) else False,
                ))
        return users

    def create_user(self, username: str, password: str, is_admin: bool) -> InfluxDbApiResponse:
        if not username or not username.strip():
            raise ValueError("username cannot be blank")
        admin_clause = " WITH ALL PRIVILEGES" if is_admin else ""
        return self._post_query(
            f"CREATE USER \"{username}\" WITH PASSWORD '{_escape_single_quotes(password)}'{admin_clause}")

    def drop_user(self, username: str) -> InfluxDbApiResponse:
        if not username or not username.strip():
            raise ValueError("username cannot be blank")
        return self._post_query(f'DROP USER "{username}"')

    def set_password(self, username: str, password: str) -> InfluxDbApiResponse:
        if not username or not username.strip():
            raise ValueError("username cannot be blank")
        return self._post_query(
            f"SET PASSWORD FOR \"{username}\" = '{_escape_single_quotes(password)}'")

    def get_privileges(self, username: str) -> List[InfluxDbGrant]:
        series = self._get_query(f'SHOW GRANTS FOR "{username}"')
        grants: List[InfluxDbGrant] = []
        for s in series:
            db_idx = s.get_column_index("database")
            priv_idx = s.get_column_index("privilege")
            for row in s.Values:
                priv_str = str(row[priv_idx]).lower() if priv_idx >= 0 and priv_idx < len(row) and row[priv_idx] else ""
                privilege = {
                    "all": InfluxDbPrivileges.All,
                    "read": InfluxDbPrivileges.Read,
                    "write": InfluxDbPrivileges.Write,
                }.get(priv_str, InfluxDbPrivileges.None_)
                grants.append(InfluxDbGrant(
                    str(row[db_idx]) if db_idx >= 0 and db_idx < len(row) and row[db_idx] else "",
                    privilege,
                ))
        return grants

    def grant_administrator(self, username: str) -> InfluxDbApiResponse:
        if not username or not username.strip():
            raise ValueError("username cannot be blank")
        return self._post_query(f'GRANT ALL PRIVILEGES TO "{username}"')

    def revoke_administrator(self, username: str) -> InfluxDbApiResponse:
        if not username or not username.strip():
            raise ValueError("username cannot be blank")
        return self._post_query(f'REVOKE ALL PRIVILEGES FROM "{username}"')

    def grant_privilege(self, username: str, privilege: InfluxDbPrivileges,
                        database: str) -> InfluxDbApiResponse:
        if not username or not username.strip():
            raise ValueError("username cannot be blank")
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        priv = "ALL" if privilege == InfluxDbPrivileges.All else privilege.name.upper()
        return self._post_query(f'GRANT {priv} ON "{database}" TO "{username}"')

    def revoke_privilege(self, username: str, privilege: InfluxDbPrivileges,
                         database: str) -> InfluxDbApiResponse:
        if not username or not username.strip():
            raise ValueError("username cannot be blank")
        if not database or not database.strip():
            raise ValueError("database cannot be blank")
        priv = "ALL" if privilege == InfluxDbPrivileges.All else privilege.name.upper()
        return self._post_query(f'REVOKE {priv} ON "{database}" FROM "{username}"')


def create_client(connection: InfluxDbConnection, allow_untrusted_ssl: bool = False) -> InfluxDbClient:
    """Factory mirroring the C# InfluxDbClientFactory."""
    return HttpInfluxDbClient(connection, allow_untrusted_ssl=allow_untrusted_ssl)
