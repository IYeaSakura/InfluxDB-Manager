"""Static helpers for InfluxDB-related operations (port of InfluxDbHelper.cs)."""
from __future__ import annotations

import re

from .models import InfluxDbTimeUnits

SECONDS_UNIT = "s"
MILLISECONDS_UNIT = "ms"
MICROSECONDS_UNIT = "u"

# Regex used to validate time interval strings: 1h, 15m, 30s, etc.
INTERVAL_REGEX = re.compile(r"([0-9\.]+)(.)")

_UNIT_TO_ENUM = {
    "u": InfluxDbTimeUnits.Microseconds,
    "ms": InfluxDbTimeUnits.Milliseconds,
    "s": InfluxDbTimeUnits.Seconds,
    "m": InfluxDbTimeUnits.Minutes,
    "h": InfluxDbTimeUnits.Hours,
    "d": InfluxDbTimeUnits.Days,
    "w": InfluxDbTimeUnits.Weeks,
}

_ENUM_TO_UNIT = {
    InfluxDbTimeUnits.Days: "d",
    InfluxDbTimeUnits.Hours: "h",
    InfluxDbTimeUnits.Microseconds: "u",
    InfluxDbTimeUnits.Milliseconds: "ms",
    InfluxDbTimeUnits.Minutes: "m",
    InfluxDbTimeUnits.Seconds: "s",
    InfluxDbTimeUnits.Weeks: "w",
}


def is_time_interval_valid(time_interval: str) -> bool:
    """Determine whether or not an InfluxDB time interval string is valid:
    "1h", "30m", "15s", etc."""
    if not time_interval or not time_interval.strip():
        return False

    time_interval = time_interval.strip()

    # Make sure the leading character is a number
    if not time_interval[0].isdigit():
        return False

    # Make sure the last character is a valid time unit character
    if time_interval[-1] not in ("s", "u", "m", "h", "d", "w"):
        return False

    # Otherwise parse with regex — should be exactly one match with two groups
    matches = INTERVAL_REGEX.findall(time_interval)
    if len(matches) != 1:
        return False
    raw_value, units = matches[0]

    # Validate numeric value (uint)
    try:
        if float(raw_value) < 0:
            return False
    except ValueError:
        return False

    # Validate units
    return convert_time_unit(units) is not InfluxDbTimeUnits.None_


def convert_time_unit(unit: str, throw_if_invalid: bool = False) -> InfluxDbTimeUnits:
    """Convert a string time unit ("s", "m", "h", "d", etc.) into an
    InfluxDbTimeUnits value."""
    if unit is None:
        raise ValueError("unit cannot be None")
    result = _UNIT_TO_ENUM.get(unit.lower())
    if result is not None:
        return result
    if throw_if_invalid:
        raise ValueError("invalid time unit string: " + unit)
    return InfluxDbTimeUnits.None_


def time_unit_to_str(unit: InfluxDbTimeUnits) -> str:
    """Convert an InfluxDbTimeUnits value into its InfluxDB time unit string."""
    if unit in _ENUM_TO_UNIT:
        return _ENUM_TO_UNIT[unit]
    raise ValueError(f"Unsupported time unit value: {unit}")
