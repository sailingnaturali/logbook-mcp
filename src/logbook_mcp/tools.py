"""MCP tool implementations for logbook-mcp.

Async functions over a LogbookClient; contracts in SPEC.md.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx

from logbook_mcp.client import LogbookClient

if TYPE_CHECKING:
    from timezonefinder import TimezoneFinder

_tf: "TimezoneFinder | None" = None


def _get_timezone_finder() -> "TimezoneFinder":
    """Lazy-init TimezoneFinder — it loads ~50MB of shapefile data."""
    global _tf
    if _tf is None:
        from timezonefinder import TimezoneFinder
        _tf = TimezoneFinder()
    return _tf


def _format_position(lat: float | None, lon: float | None) -> str | None:
    if lat is None or lon is None:
        return None
    lat_part = f"{abs(lat):.1f}" if lat == 0 else f"{abs(lat):.1f} {'North' if lat > 0 else 'South'}"
    lon_part = f"{abs(lon):.1f}" if lon == 0 else f"{abs(lon):.1f} {'East' if lon > 0 else 'West'}"
    return f"{lat_part}, {lon_part}"


def _entry_timezone(position: dict | None, fallback_tz: str) -> zoneinfo.ZoneInfo:
    """Timezone at the entry's own position, else the configured fallback."""
    if position:
        tz_name = _get_timezone_finder().timezone_at(
            lat=position["latitude"], lng=position["longitude"]
        )
        if tz_name:
            return zoneinfo.ZoneInfo(tz_name)
    return zoneinfo.ZoneInfo(fallback_tz)


def _time_display(datetime_iso: str, position: dict | None, fallback_tz: str) -> str:
    """Vessel-local HH:MM for an entry timestamp (same display as signalk-mcp)."""
    dt = datetime.fromisoformat(datetime_iso.replace("Z", "+00:00"))
    return dt.astimezone(_entry_timezone(position, fallback_tz)).strftime("%H:%M")
