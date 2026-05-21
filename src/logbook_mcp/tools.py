"""MCP tool implementations for logbook-mcp."""

from __future__ import annotations

from datetime import datetime, timezone

from logbook_mcp.db import LogbookDB


def _format_position(lat: float | None, lon: float | None) -> str | None:
    if lat is None or lon is None:
        return None
    lat_dir = "North" if lat >= 0 else "South"
    lon_dir = "East" if lon >= 0 else "West"
    return f"{abs(lat):.4f} {lat_dir}, {abs(lon):.4f} {lon_dir}"


def mark_moment(
    db: LogbookDB,
    text: str,
    position: dict | None = None,
) -> dict:
    """Record a marked moment with optional position.

    Args:
        db: Open LogbookDB.
        text: Free-form description.
        position: Optional dict with 'longitude' and 'latitude'.

    Returns:
        Dict with the saved moment's id, text, timestamp, and position.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    lon = position["longitude"] if position else None
    lat = position["latitude"] if position else None

    moment_id = db.execute(
        "INSERT INTO marked_moments (text, timestamp, longitude, latitude) VALUES (?, ?, ?, ?)",
        (text, timestamp, lon, lat),
    )
    return {
        "id": moment_id,
        "text": text,
        "timestamp": timestamp,
        "position": position,
        "position_display": _format_position(lat, lon),
    }
