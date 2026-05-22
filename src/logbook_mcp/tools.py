"""MCP tool implementations for logbook-mcp."""

from __future__ import annotations

from datetime import datetime, timezone

from logbook_mcp.db import LogbookDB


def _utc_now_iso() -> str:
    """ISO 8601 UTC timestamp with Z suffix (logbook convention)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_position(lat: float | None, lon: float | None) -> str | None:
    if lat is None or lon is None:
        return None
    lat_part = f"{abs(lat):.4f}" if lat == 0 else f"{abs(lat):.4f} {'North' if lat > 0 else 'South'}"
    lon_part = f"{abs(lon):.4f}" if lon == 0 else f"{abs(lon):.4f} {'East' if lon > 0 else 'West'}"
    return f"{lat_part}, {lon_part}"


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
        Dict with id, entry_display, text, timestamp, position, position_display.
    """
    timestamp = _utc_now_iso()
    lon = position["longitude"] if position else None
    lat = position["latitude"] if position else None

    moment_id = db.insert(
        "INSERT INTO marked_moments (text, timestamp, longitude, latitude) VALUES (?, ?, ?, ?)",
        (text, timestamp, lon, lat),
    )
    return {
        "id": moment_id,
        "entry_display": f"Entry {moment_id}",
        "text": text,
        "timestamp": timestamp,
        "position": {"longitude": lon, "latitude": lat} if position else None,
        "position_display": _format_position(lat, lon),
    }
