"""Application settings (port of AppSettings.cs).

Settings are persisted as JSON under the per-user config directory
(``platformdirs``). The export format is compatible with the C# version:
PascalCase keys, ``Connections`` list with ``Id/Name/Host/Port/Database/
Username/Password/UseSsl``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List, Optional


def _now_iso() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

try:
    from platformdirs import user_config_dir
except ImportError:  # pragma: no cover - platformdirs is a hard dependency
    user_config_dir = None

from .models import InfluxDbConnection
from . import secrets

# Time/date format strings (same semantics as the C# version)
TIME_FORMAT_12_HOUR = "hh:mm:ss tt"
TIME_FORMAT_24_HOUR = "HH:mm:ss"
DATE_FORMAT_DAY = "d/MM/yyyy"
DATE_FORMAT_MONTH = "M/dd/yyyy"

APP_NAME = "InfluxDBStudio"

# UI language codes
LANG_ZH_CN = "zh_CN"
LANG_EN_US = "en_US"
SUPPORTED_LANGUAGES = [LANG_ZH_CN, LANG_EN_US]


def _config_dir() -> str:
    if user_config_dir is not None:
        base = user_config_dir(APP_NAME)
    else:
        base = os.path.join(os.path.expanduser("~"), ".net.sakurain.influxdbstudio")
    os.makedirs(base, exist_ok=True)
    return base


def _settings_path() -> str:
    return os.path.join(_config_dir(), "settings.json")


class AppSettings:
    def __init__(self, version: str = ""):
        self.version = version
        self.time_format = TIME_FORMAT_12_HOUR
        self.date_format = DATE_FORMAT_MONTH
        self.allow_untrusted_ssl = False
        self.language = LANG_ZH_CN  # 默认中文
        self.connections: List[InfluxDbConnection] = []
        # Open query script tabs, restored on next launch
        # (each: {"Name", "ConnectionId", "Database", "Text"})
        self.query_scripts: List[dict] = []
        self.active_query_tab = -1
        # Last directory used for result export (remembered across launches)
        self.last_export_dir = ""
        # Executed queries, most recent first
        # (each: {"ConnectionId", "Database", "Text", "Time"})
        self.query_history: List[dict] = []

    # -- persistence ---------------------------------------------------------

    def load_all(self) -> None:
        path = _settings_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        self.time_format = data.get("TimeFormat", TIME_FORMAT_12_HOUR)
        self.date_format = data.get("DateFormat", DATE_FORMAT_MONTH)
        self.allow_untrusted_ssl = bool(data.get("AllowUntrustedSsl", False))
        self.language = data.get("Language", LANG_ZH_CN)
        if self.language not in SUPPORTED_LANGUAGES:
            self.language = LANG_ZH_CN
        self.load_connections(data.get("Connections") or [])
        scripts = data.get("QueryScripts")
        if isinstance(scripts, list):
            self.query_scripts = [s for s in scripts if isinstance(s, dict)]
        self.active_query_tab = int(data.get("ActiveQueryTab", -1) or -1)
        self.last_export_dir = data.get("LastExportDir", "") or ""
        history = data.get("QueryHistory")
        if isinstance(history, list):
            self.query_history = [h for h in history if isinstance(h, dict)]

    def save_all(self) -> None:
        data = {
            "Version": self.version,
            "TimeFormat": self.time_format,
            "DateFormat": self.date_format,
            "AllowUntrustedSsl": self.allow_untrusted_ssl,
            "Language": self.language,
            # Passwords are encrypted at rest (DPAPI on Windows); in-memory
            # connections always hold plaintext.
            "Connections": [
                {**c.to_dict(), "Password": secrets.protect(c.Password or "")}
                for c in self.connections
            ],
            "QueryScripts": self.query_scripts,
            "ActiveQueryTab": self.active_query_tab,
            "LastExportDir": self.last_export_dir,
            "QueryHistory": self.query_history,
        }
        try:
            with open(_settings_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def load_connections(self, items) -> None:
        self.connections = []
        for item in items:
            try:
                if isinstance(item, dict) and item.get("Password"):
                    item = {**item,
                            "Password": secrets.unprotect(item["Password"])}
                self.connections.append(InfluxDbConnection.from_dict(item))
            except Exception:
                continue

    def save_connections(self) -> None:
        self.save_all()

    # -- import/export (C#-compatible JSON) -------------------------------------

    def to_export_json(self) -> str:
        return json.dumps({
            "Version": self.version,
            "TimeFormat": self.time_format,
            "DateFormat": self.date_format,
            "AllowUntrustedSsl": self.allow_untrusted_ssl,
            "Language": self.language,
            "Connections": [c.to_dict() for c in self.connections],
        }, indent=2)

    @classmethod
    def from_export_json(cls, json_text: str, version: str = "") -> "AppSettings":
        data = json.loads(json_text)
        settings = cls(version=version)
        settings.time_format = data.get("TimeFormat", TIME_FORMAT_12_HOUR)
        settings.date_format = data.get("DateFormat", DATE_FORMAT_MONTH)
        settings.allow_untrusted_ssl = bool(data.get("AllowUntrustedSsl", False))
        language = data.get("Language")
        if language in SUPPORTED_LANGUAGES:
            settings.language = language
        settings.load_connections(data.get("Connections") or [])
        return settings

    # -- helpers ----------------------------------------------------------------

    def set_time_format_12h(self) -> None:
        self.time_format = TIME_FORMAT_12_HOUR
        self.save_all()

    def set_time_format_24h(self) -> None:
        self.time_format = TIME_FORMAT_24_HOUR
        self.save_all()

    def set_date_format_month_first(self) -> None:
        self.date_format = DATE_FORMAT_MONTH
        self.save_all()

    def set_date_format_day_first(self) -> None:
        self.date_format = DATE_FORMAT_DAY
        self.save_all()

    def set_allow_untrusted_ssl(self, allow: bool) -> None:
        self.allow_untrusted_ssl = allow
        self.save_all()

    def set_language(self, language: str) -> None:
        if language in SUPPORTED_LANGUAGES:
            self.language = language
            self.save_all()

    def set_last_export_dir(self, path: str) -> None:
        """Remember the directory of an exported file (``path`` is the
        full file path chosen in the save dialog)."""
        directory = os.path.dirname(os.path.abspath(path))
        if directory and directory != self.last_export_dir:
            self.last_export_dir = directory
            self.save_all()

    # -- query history (1.2.0) ------------------------------------------------

    HISTORY_LIMIT = 200

    def record_query(self, connection_id: str, database: str,
                     text: str) -> None:
        """Push an executed query onto the history (deduped, most recent
        first, capped at ``HISTORY_LIMIT``)."""
        text = (text or "").strip()
        if not text:
            return
        entry = {
            "ConnectionId": connection_id or "",
            "Database": database or "",
            "Text": text,
            "Time": _now_iso(),
        }
        self.query_history = [
            h for h in self.query_history
            if not (h.get("ConnectionId") == entry["ConnectionId"]
                    and h.get("Database") == entry["Database"]
                    and h.get("Text") == text)
        ]
        self.query_history.insert(0, entry)
        del self.query_history[self.HISTORY_LIMIT:]
        self.save_all()

    def history_for(self, connection_id: str) -> List[dict]:
        """History entries for one connection, most recent first."""
        return [h for h in self.query_history
                if h.get("ConnectionId") == (connection_id or "")]

    def format_time_value(self, dt) -> str:
        """Format a datetime according to the current time/date settings."""
        if self.time_format == TIME_FORMAT_12_HOUR:
            return dt.strftime("%I:%M:%S %p")
        return dt.strftime("%H:%M:%S")

    def format_date_time_value(self, dt) -> str:
        """Format a datetime using the date format + time format (C# CustomFormat
        equivalent: ``{date} @ {time}``)."""
        date_part = (dt.strftime("%m/%d/%Y") if self.date_format == DATE_FORMAT_MONTH
                     else dt.strftime("%d/%m/%Y"))
        return f"{date_part} @ {self.format_time_value(dt)}"
