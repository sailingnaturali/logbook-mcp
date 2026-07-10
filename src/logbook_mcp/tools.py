"""MCP tool implementations for logbook-mcp.

Async functions over a LogbookClient; contracts in SPEC.md.
"""

from __future__ import annotations

import zoneinfo
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx

from logbook_mcp.client import LogbookClient, validate_date
from logbook_mcp.drills import compose_drill_text, parse_drill_tag, validate_drill_type

if TYPE_CHECKING:
    from timezonefinder import TimezoneFinder

# Single default for "what timezone is the vessel in when there's no GPS fix" —
# used by both tools and the server wiring (LOGBOOK_TZ overrides at startup).
FALLBACK_TZ = "America/Vancouver"

# Provenance vocabulary (one vocabulary everywhere): manual = a human composed
# the words (typed or dictated), agent = an AI agent composed them, auto =
# unattended machinery (notification/hourly/trigger entries).
ORIGINS = ("manual", "auto", "agent")

# Token principals whose entries are agent-written. "hermes" is the legacy
# pre-Poseidon token name still on 2026-06 archive entries.
DEFAULT_AGENT_AUTHORS = frozenset({"hermes", "poseidon"})


def derive_origin(
    entry: dict,
    agent_authors: frozenset[str] = DEFAULT_AGENT_AUTHORS,
    auto_authors: frozenset[str] = frozenset(),
) -> str:
    """Provenance of a logbook entry: explicit origin field, else author heuristic.

    Heuristic (pre-upstream archives): empty author = the plugin's own
    unattended writers; a known agent/auto token principal = that class;
    any other author = a person.
    """
    origin = entry.get("origin")
    if origin in ORIGINS:
        return origin
    author = entry.get("author") or ""
    if not author:
        return "auto"
    if author in agent_authors:
        return "agent"
    if author in auto_authors:
        return "auto"
    return "manual"


_tf: "TimezoneFinder | None" = None


def _get_timezone_finder() -> "TimezoneFinder":
    """Lazy-init TimezoneFinder — it loads ~50MB of shapefile data."""
    global _tf
    if _tf is None:
        from timezonefinder import TimezoneFinder
        _tf = TimezoneFinder()
    return _tf


def _format_position(lat: float | None, lon: float | None) -> str | None:
    """Human-readable '48.4 North, 123.3 West' (zero coords render bare)."""
    if lat is None or lon is None:
        return None
    lat_part = f"{abs(lat):.1f}" if lat == 0 else f"{abs(lat):.1f} {'North' if lat > 0 else 'South'}"
    lon_part = f"{abs(lon):.1f}" if lon == 0 else f"{abs(lon):.1f} {'East' if lon > 0 else 'West'}"
    return f"{lat_part}, {lon_part}"


def _position_fields(entry: dict) -> tuple[dict | None, str | None]:
    """(pos_out, position_display) for an entry.

    A partial fix (only one of lat/lon present) counts as no fix.
    """
    pos = entry.get("position") or None
    pos_out = (
        {"longitude": pos["longitude"], "latitude": pos["latitude"]}
        if pos and pos.get("latitude") is not None
        else None
    )
    display = _format_position(
        pos_out["latitude"] if pos_out else None,
        pos_out["longitude"] if pos_out else None,
    )
    return pos_out, display


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


def _auth_error(exc: httpx.HTTPStatusError, base_url: str) -> RuntimeError | None:
    if exc.response.status_code in (401, 403):
        return RuntimeError(
            f"Logbook auth failed (HTTP {exc.response.status_code}) at {base_url}: "
            "check LOGBOOK_SK_TOKEN"
        )
    return None


async def _newest_entry(
    client: LogbookClient, now: datetime
) -> tuple[dict, int]:
    """The just-created entry and its 1-based ordinal within its day.

    POST /logs returns no body, so we re-fetch the day. If the clock rolled
    past UTC midnight between write and re-fetch, the entry is in the
    previous day's file — check there before giving up.
    """
    for day in (now.date(), now.date() - timedelta(days=1)):
        entries = await client.get_entries(day.isoformat())
        if entries:
            # Identity assumption: the entry we just POSTed is the
            # newest-by-datetime in its day. This breaks if a later-dated
            # entry already exists (manual backfill, clock skew) or if a
            # concurrent auto-entry lands between POST and re-fetch —
            # revisit when signalk-autostate is installed (hourly
            # underway entries). e.get() guards a malformed entry missing
            # "datetime" from leaking KeyError past our error wrapping.
            entries.sort(key=lambda e: e.get("datetime", ""))
            newest = entries[-1]
            if not newest.get("datetime"):
                # Callers dereference entry["datetime"]; a datetime-less
                # record must become the post-write honesty error, not a
                # KeyError escaping the (httpx, ValueError) handlers.
                raise RuntimeError(
                    "Logbook entry was recorded but could not be confirmed: "
                    "newest entry has no datetime; check the log via read_entries"
                )
            return newest, len(entries)
    raise RuntimeError(
        "Logbook entry was recorded but could not be confirmed: "
        "no entries found on re-fetch"
    )


async def mark_moment(
    client: LogbookClient,
    text: str,
    position: dict | None = None,
    fallback_tz: str = FALLBACK_TZ,
    now: datetime | None = None,
    category: str | None = None,
    origin: str = "agent",
    author: str | None = None,
) -> dict:
    """Record a moment in the ship's log via signalk-logbook.

    The plugin snapshots position/heading/speed/wind/barometer server-side.
    An explicit ``position`` overrides the snapshotted fix via a follow-up PUT.
    An explicit ``author`` overrides the token principal via the same PUT.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    try:
        await client.post_entry(text, category=category, origin=origin)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise RuntimeError(
            f"Logbook unavailable: cannot reach SignalK at {client.base_url} "
            "— moment NOT recorded"
        ) from exc
    except httpx.HTTPStatusError as exc:
        auth = _auth_error(exc, client.base_url)
        if auth:
            raise auth from exc
        raise RuntimeError(
            f"Logbook write failed (HTTP {exc.response.status_code}) "
            "— moment NOT recorded"
        ) from exc

    # Past this point the moment IS recorded; errors must say so honestly.
    try:
        entry, ordinal = await _newest_entry(client, now)

        needs_put = position is not None or author is not None
        if needs_put:
            entry = {**entry}
            if position is not None:
                entry["position"] = {
                    "longitude": position["longitude"],
                    "latitude": position["latitude"],
                    "source": "manual",
                }
            if author is not None:
                # Upstream PUT takes the body wholesale, so a body-supplied
                # author replaces the token principal the POST stamped.
                entry["author"] = author
            day = entry["datetime"][:10]
            await client.put_entry(day, entry["datetime"], entry)
    except RuntimeError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(
            "Logbook entry was recorded but could not be confirmed "
            f"({exc.__class__.__name__}); check the log via read_entries"
        ) from exc

    pos_out, pos_display = _position_fields(entry)
    time_disp = _time_display(entry["datetime"], pos_out, fallback_tz)
    # One ready-to-speak string so voice agents relay it verbatim instead of
    # re-assembling (and paraphrasing) the individual fields.
    parts = [f"Entry {ordinal}", time_disp] + ([pos_display] if pos_display else [])
    confirmation = "Logged. " + ". ".join(parts) + "."
    if author is not None:
        confirmation += f" Logged as {author}."
    return {
        "id": entry["datetime"],
        "entry_display": f"Entry {ordinal}",
        "confirmation": confirmation,
        "text": entry.get("text", text),
        "timestamp": entry["datetime"],
        "time_display": time_disp,
        "position": pos_out,
        "position_display": pos_display,
        "author": entry.get("author"),
    }


async def log_drill(
    client: LogbookClient,
    drill_type: str,
    outcome: str,
    duration_minutes: int | None = None,
    participants: list[str] | None = None,
    notes: str | None = None,
    position: dict | None = None,
    fallback_tz: str = FALLBACK_TZ,
    now: datetime | None = None,
) -> dict:
    """Record a safety drill in the ship's log.

    Validation and the tag format live in drills.py; the write/confirm
    plumbing is mark_moment's. Raises ValueError before any write when the
    drill fields are invalid.
    """
    text = compose_drill_text(
        drill_type, outcome,
        duration_minutes=duration_minutes,
        participants=participants,
        notes=notes,
    )
    result = await mark_moment(
        client, text=text, position=position,
        fallback_tz=fallback_tz, now=now, category="drill",
    )
    # Echo normalized fields from the composed text (the round-trip-tested
    # source of truth), not the raw inputs.
    # compose_drill_text guarantees valid tag syntax, so the parse cannot fail.
    parsed = parse_drill_tag(text) or {}
    spoken_type = drill_type.replace("-", " ")
    confirmation = (
        f"Logged {spoken_type} drill, {outcome}. "
        f"{result['entry_display']}. {result['time_display']}."
    )
    return {
        **result,
        "confirmation": confirmation,
        "drill_type": drill_type,
        "outcome": outcome,
        "duration_minutes": parsed.get("duration_minutes"),
        "participants": parsed.get("participants"),
        "notes": parsed.get("notes"),
    }


async def read_entries(
    client: LogbookClient,
    date: str | None = None,
    fallback_tz: str = FALLBACK_TZ,
    now: datetime | None = None,
    origin: str | None = None,
    agent_authors: frozenset[str] = DEFAULT_AGENT_AUTHORS,
    auto_authors: frozenset[str] = frozenset(),
) -> dict:
    """Read a day's log entries (default: today in vessel-local time).

    ``date`` means a vessel-local calendar day. The plugin keys its day-files
    by UTC date, so one local day spans up to two UTC files — both are fetched
    and each entry is kept by its own local date (fleet conventions R2).

    Single-tz assumption: one canonical timezone per call (current GPS fix,
    else ``fallback_tz``) decides both the day window and the displayed times.
    A vessel that crossed a timezone boundary mid-day is rendered consistently
    in where-it-is-now time.
    """
    if origin is not None and origin not in ORIGINS:
        raise ValueError(f"invalid origin filter: {origin!r} (one of {', '.join(ORIGINS)})")

    if now is None:
        now = datetime.now(timezone.utc)
    fix = await client.get_position()          # degrades to None when no fix
    tz = _entry_timezone(fix, fallback_tz)
    if date is None:
        date = now.astimezone(tz).date().isoformat()
    else:
        validate_date(date)

    target = date_cls.fromisoformat(date)
    start_local = datetime(target.year, target.month, target.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    utc_days = {
        start_local.astimezone(timezone.utc).date(),
        (end_local - timedelta(microseconds=1)).astimezone(timezone.utc).date(),
    }

    raw: list[dict] = []
    try:
        for day in sorted(utc_days):
            raw.extend(await client.get_entries(day.isoformat()))
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise RuntimeError(
            f"Logbook unavailable: cannot reach SignalK at {client.base_url}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        auth = _auth_error(exc, client.base_url)
        if auth:
            raise auth from exc
        raise RuntimeError(
            f"Logbook read failed (HTTP {exc.response.status_code})"
        ) from exc
    except ValueError as exc:                  # malformed 200 body (JSONDecodeError)
        raise RuntimeError(
            f"Logbook read returned malformed data from {client.base_url}"
        ) from exc

    kept: list[dict] = []
    for e in raw:
        dt_str = e.get("datetime", "")
        if not dt_str:
            kept.append(e)                     # unplaceable — keep, don't crash
            continue
        try:
            edt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            kept.append(e)
            continue
        if edt.astimezone(tz).date() == target:
            kept.append(e)

    kept.sort(key=lambda e: e.get("datetime", ""))
    tagged = [(e, derive_origin(e, agent_authors, auto_authors)) for e in kept]
    if origin is not None:
        tagged = [(e, o) for (e, o) in tagged if o == origin]
    entries = []
    for n, (e, entry_origin) in enumerate(tagged, start=1):
        dt_str = e.get("datetime", "")
        pos_out, pos_display = _position_fields(e)
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")) if dt_str else None
        except ValueError:
            dt = None                          # kept-but-unparseable datetime
        entries.append(
            {
                "id": dt_str,
                "entry_display": f"Entry {n}",
                "time_display": dt.astimezone(tz).strftime("%H:%M") if dt else None,
                "text": e.get("text", ""),
                "category": e.get("category", "navigation"),
                "author": e.get("author"),
                "origin": entry_origin,
                "position": pos_out,
                "position_display": pos_display,
            }
        )
    return {"date": date, "count": len(entries), "entries": entries}


async def list_drills(
    client: LogbookClient,
    drill_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    fallback_tz: str = FALLBACK_TZ,
    now: datetime | None = None,
) -> dict:
    """Drill entries in a date window (default: the last 180 days).

    Walks the plugin's UTC day index — window bounds are UTC day-file dates,
    matching how entries are stored. An entry counts as a drill when its
    category is "drill" or its text opens with a [drill:…] tag; tagged fields
    are parsed, untagged drill-category entries are listed with None fields
    (they can't contribute to latest_by_type).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if until is None:
        until = now.date().isoformat()
    else:
        validate_date(until)
    if since is None:
        since = (date_cls.fromisoformat(until) - timedelta(days=180)).isoformat()
    else:
        validate_date(since)
    if drill_type is not None:
        validate_drill_type(drill_type)

    # Validate since/until range before attempting to fetch
    since_date = date_cls.fromisoformat(since)
    until_date = date_cls.fromisoformat(until)
    if since_date > until_date:
        raise ValueError(f"since ({since!r}) must not be after until ({until!r})")

    try:
        days = [d for d in await client.get_dates() if since <= d <= until]
        rows: list[dict] = []
        for day in sorted(days):
            for e in await client.get_entries(day):
                parsed = parse_drill_tag(e.get("text", ""))
                if e.get("category") != "drill" and parsed is None:
                    continue
                if not e.get("datetime"):
                    continue  # undateable — useless for cadence; skip
                if drill_type is not None and (
                    parsed is None or parsed["drill_type"] != drill_type
                ):
                    continue
                pos_out, pos_display = _position_fields(e)
                rows.append(
                    {
                        "id": e["datetime"],
                        "date": e["datetime"][:10],
                        "time_display": _time_display(
                            e["datetime"], pos_out, fallback_tz
                        ),
                        "drill_type": parsed["drill_type"] if parsed else None,
                        "outcome": parsed["outcome"] if parsed else None,
                        "duration_minutes": (
                            parsed["duration_minutes"] if parsed else None
                        ),
                        "participants": parsed["participants"] if parsed else None,
                        "notes": (
                            parsed["notes"] if parsed else e.get("text") or None
                        ),
                        "position": pos_out,
                        "position_display": pos_display,
                    }
                )
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise RuntimeError(
            f"Logbook unavailable: cannot reach SignalK at {client.base_url}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        auth = _auth_error(exc, client.base_url)
        if auth:
            raise auth from exc
        raise RuntimeError(
            f"Logbook read failed (HTTP {exc.response.status_code})"
        ) from exc
    except ValueError as exc:                  # malformed 200 body (JSONDecodeError)
        raise RuntimeError(
            f"Logbook read returned malformed data from {client.base_url}"
        ) from exc

    rows.sort(key=lambda r: r["id"])
    latest_by_type: dict[str, str] = {}
    for r in rows:
        if r["drill_type"]:
            latest_by_type[r["drill_type"]] = r["date"]
    return {
        "since": since,
        "until": until,
        "count": len(rows),
        "drills": rows,
        "latest_by_type": latest_by_type,
    }
