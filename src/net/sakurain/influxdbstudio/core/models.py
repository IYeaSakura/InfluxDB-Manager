"""Data models — Python equivalents of the C# CymaticLabs.InfluxDB.Data model classes."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class InfluxDbPrivileges(IntEnum):
    None_ = 0
    Read = 1
    Write = 2
    All = 4

    @property
    def display_name(self) -> str:
        return "None" if self is InfluxDbPrivileges.None_ else self.name


class InfluxDbFillTypes(IntEnum):
    Null = 0
    Previous = 1
    None_ = 2

    @property
    def display_name(self) -> str:
        return "None" if self is InfluxDbFillTypes.None_ else self.name


class InfluxDbTimeUnits(IntEnum):
    None_ = 0
    Microseconds = 1
    Milliseconds = 2
    Seconds = 3
    Minutes = 4
    Hours = 5
    Days = 6
    Weeks = 7


class InfluxDbTimePrecisions(IntEnum):
    None_ = 0
    Microseconds = 1
    Milliseconds = 2
    Seconds = 3


# ---------------------------------------------------------------------------
# Connection / responses
# ---------------------------------------------------------------------------

@dataclass
class InfluxDbConnection:
    """InfluxDB connection configuration."""
    Id: str = ""
    Name: str = ""
    Host: str = ""
    Port: int = 8086
    Database: Optional[str] = None
    Username: Optional[str] = None
    Password: Optional[str] = None
    UseSsl: bool = False
    # 1.2.0: read-only connections block every data-modifying UI action
    ReadOnly: bool = False

    @property
    def http_connection_string(self) -> str:
        scheme = "https" if self.UseSsl else "http"
        return f"{scheme}://{self.Host}:{self.Port}"

    @classmethod
    def create(cls, name: str, host: str, port: int, username: str = None,
               password: str = None, use_ssl: bool = False, database: str = None):
        return cls(Id=str(uuid.uuid4()), Name=name, Host=host, Port=port,
                   Database=database, Username=username, Password=password,
                   UseSsl=use_ssl)

    @classmethod
    def from_dict(cls, data: dict) -> "InfluxDbConnection":
        return cls(
            Id=data.get("Id") or data.get("id") or "",
            Name=data.get("Name") or data.get("name") or "",
            Host=data.get("Host") or data.get("host") or "",
            Port=int(data.get("Port") or data.get("port") or 8086),
            Database=data.get("Database") or data.get("database"),
            Username=data.get("Username") or data.get("username"),
            Password=data.get("Password") or data.get("password"),
            UseSsl=bool(data.get("UseSsl") if data.get("UseSsl") is not None
                        else data.get("useSsl", False)),
            ReadOnly=bool(data.get("ReadOnly", False)),
        )

    def to_dict(self) -> dict:
        # Keys match the C# JSON (PascalCase) so exported settings files stay
        # compatible between the .NET and Python versions.
        return {
            "Id": self.Id,
            "Name": self.Name,
            "Host": self.Host,
            "Port": self.Port,
            "Database": self.Database,
            "Username": self.Username,
            "Password": self.Password,
            "UseSsl": self.UseSsl,
            "ReadOnly": self.ReadOnly,
        }


@dataclass
class InfluxDbApiResponse:
    Body: str
    StatusCode: int
    Success: bool


@dataclass
class InfluxDbPingResponse:
    Success: bool
    ResponseTime: float  # milliseconds
    Version: str


# ---------------------------------------------------------------------------
# Series & query results
# ---------------------------------------------------------------------------

class InfluxDbSeries:
    """A single InfluxDB result series (name, columns, tags, values)."""

    def __init__(self, name: Optional[str], columns: List[str],
                 tags: Optional[Dict[str, str]], values: List[List[Any]]):
        if columns is None:
            raise ValueError("columns cannot be None")
        self.Name = name
        self.Columns = list(columns)
        self.Tags = dict(tags) if tags else {}
        self.Values = values or []
        self._column_index = {}
        for i, col in enumerate(self.Columns):
            if col not in self._column_index:
                self._column_index[col] = i

    def get_column_index(self, name: str) -> int:
        return self._column_index.get(name, -1)


@dataclass
class InfluxDbTagValue:
    Name: str
    Value: str


@dataclass
class InfluxDbFieldKey:
    Name: str
    Type: str


@dataclass
class InfluxDbRetentionPolicy:
    Name: str = ""
    Database: str = ""
    Duration: str = ""
    ShardGroupDuration: str = ""
    ReplicationCopies: int = 1
    Default: bool = False


@dataclass
class InfluxDbContinuousQuery:
    Name: str
    Query: str


@dataclass
class InfluxDbRunningQuery:
    PID: int
    Database: str
    Duration: str
    Query: str


# ---------------------------------------------------------------------------
# Users & privileges
# ---------------------------------------------------------------------------

@dataclass
class InfluxDbUser:
    Name: str
    IsAdmin: bool


@dataclass
class InfluxDbGrant:
    Database: str
    Privilege: InfluxDbPrivileges = InfluxDbPrivileges.None_


# ---------------------------------------------------------------------------
# Diagnostics / stats
# ---------------------------------------------------------------------------

@dataclass
class InfluxDbDiagnostics:
    Branch: str = ""
    BuildVersion: str = ""
    Commit: str = ""
    CurrentTime: str = ""
    GoArch: str = ""
    GoMaxProc: Any = ""
    GoOs: str = ""
    GoVersion: str = ""
    Hostname: str = ""
    PID: Any = ""
    Started: str = ""
    Uptime: str = ""  # raw uptime string from server


@dataclass
class InfluxDbStats:
    CQ: Optional[List[InfluxDbSeries]] = None
    Database: Optional[List[InfluxDbSeries]] = None
    Engine: Optional[List[InfluxDbSeries]] = None
    Httpd: Optional[List[InfluxDbSeries]] = None
    QueryExecutor: Optional[List[InfluxDbSeries]] = None
    Runtime: Optional[List[InfluxDbSeries]] = None
    Shard: Optional[List[InfluxDbSeries]] = None
    Subscriber: Optional[List[InfluxDbSeries]] = None
    Tsm1Cache: Optional[List[InfluxDbSeries]] = None
    Tsm1Filestore: Optional[List[InfluxDbSeries]] = None
    Tsm1Wal: Optional[List[InfluxDbSeries]] = None
    WAL: Optional[List[InfluxDbSeries]] = None
    Write: Optional[List[InfluxDbSeries]] = None

    #: series-name -> attribute mapping used when parsing SHOW STATS results
    SERIES_ATTR_MAP = {
        "cq": "CQ",
        "database": "Database",
        "engine": "Engine",
        "httpd": "Httpd",
        "queryExecutor": "QueryExecutor",
        "runtime": "Runtime",
        "shard": "Shard",
        "subscriber": "Subscriber",
        "tsm1_cache": "Tsm1Cache",
        "tsm1_filestore": "Tsm1Filestore",
        "tsm1_wal": "Tsm1Wal",
        "wal": "WAL",
        "write": "Write",
    }

    def groups(self) -> Dict[str, Optional[List[InfluxDbSeries]]]:
        return {name: getattr(self, attr) for name, attr in (
            ("CQ", "CQ"), ("Database", "Database"), ("Engine", "Engine"),
            ("Httpd", "Httpd"), ("QueryExecutor", "QueryExecutor"),
            ("Runtime", "Runtime"), ("Shard", "Shard"), ("Subscriber", "Subscriber"),
            ("Tsm1Cache", "Tsm1Cache"), ("Tsm1Filestore", "Tsm1Filestore"),
            ("Tsm1Wal", "Tsm1Wal"), ("WAL", "WAL"), ("Write", "Write"))}


# ---------------------------------------------------------------------------
# Write points / CQ & backfill params
# ---------------------------------------------------------------------------

class InfluxDbPoint:
    def __init__(self, measurement: str, tags: Optional[Dict[str, Any]] = None,
                 fields: Optional[Dict[str, Any]] = None,
                 time_stamp: Optional[datetime] = None,
                 time_stamp_ns: Optional[int] = None):
        if not measurement:
            raise ValueError("measurement cannot be blank")
        self.Measurement = measurement
        self.Tags = tags or {}
        self.Fields = fields or {}
        self.TimeStamp = time_stamp or datetime.now(timezone.utc)
        # Raw nanosecond epoch; takes precedence over TimeStamp (which only
        # has microsecond precision and would land on a different timestamp).
        self.TimeStampNs = time_stamp_ns


@dataclass
class InfluxDbCqParams:
    Name: str = ""
    Database: str = ""
    SubQueries: List[str] = field(default_factory=list)
    Destination: str = ""
    Source: str = ""
    Interval: str = ""
    Tags: Optional[List[str]] = None
    FillType: InfluxDbFillTypes = InfluxDbFillTypes.Null
    ResampleEveryInterval: Optional[str] = None
    ResampleForInterval: Optional[str] = None


@dataclass
class InfluxDbBackfillParams:
    SubQueries: List[str] = field(default_factory=list)
    Destination: str = ""
    Source: str = ""
    Interval: str = ""
    FromTime: Optional[datetime] = None
    ToTime: Optional[datetime] = None
    Filters: Optional[List[str]] = None
    Tags: Optional[List[str]] = None
    FillType: InfluxDbFillTypes = InfluxDbFillTypes.Null
