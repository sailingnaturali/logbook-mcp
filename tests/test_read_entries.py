from datetime import datetime, timezone

import httpx
import pytest
import respx

from logbook_mcp.client import LogbookClient
from logbook_mcp.tools import read_entries, derive_origin

BASE = "http://test-sk:3000"
API = f"{BASE}/plugins/signalk-logbook"
POSITION_URL = f"{BASE}/signalk/v1/api/vessels/self/navigation/position"

# 2026-06-06T02:30Z is still 2026-06-05 19:30 in America/Vancouver
NOW = datetime(2026, 6, 6, 2, 30, 0, tzinfo=timezone.utc)

ENTRIES = [
    {
        "datetime": "2026-06-05T14:00:00.000Z",
        "position": {"latitude": 48.70, "longitude": -123.20, "source": "GPS"},
        "text": "Departed Bedwell Harbour",
        "author": "auto",
        "category": "navigation",
    },
    {
        "datetime": "2026-06-05T18:32:00.000Z",
        "position": {"latitude": 48.42, "longitude": -123.27, "source": "GPS"},
        "text": "Beautiful sunset off Discovery Island",
        "author": "naturali",
        "category": "navigation",
    },
]


@pytest.fixture
async def client():
    c = LogbookClient(BASE, token="test-token")
    yield c
    await c.aclose()


def _no_fix():
    """No GPS fix -> the canonical tz falls back to fallback_tz."""
    respx.get(POSITION_URL).respond(404)


@respx.mock
async def test_read_entries_explicit_date(client):
    _no_fix()
    # A PDT local day spans two UTC day-files; the evening file is empty here.
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=ENTRIES)
    respx.get(f"{API}/logs/2026-06-06").respond(404)

    result = await read_entries(client, date="2026-06-05")

    assert result["date"] == "2026-06-05"
    assert result["count"] == 2
    first, second = result["entries"]
    assert first["entry_display"] == "Entry 1"
    assert first["time_display"] == "07:00"        # 14:00Z -> 07:00 PDT
    assert second["entry_display"] == "Entry 2"
    assert second["id"] == "2026-06-05T18:32:00.000Z"
    assert second["category"] == "navigation"
    assert second["author"] == "naturali"
    assert second["position_display"] == "48.4 North, 123.3 West"


@respx.mock
async def test_local_day_spans_two_utc_files(client):
    # The R2 case: a vessel-local (PDT) day [00:00, 24:00) is UTC
    # [07:00 same-day, 07:00 next-day) — two UTC-keyed day-files.
    _no_fix()
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[
        {"datetime": "2026-06-05T03:00:00.000Z", "text": "previous local day"},   # 06-04 20:00 PDT
        {"datetime": "2026-06-05T08:00:00.000Z", "text": "early morning local"},  # 06-05 01:00 PDT
    ])
    respx.get(f"{API}/logs/2026-06-06").respond(200, json=[
        {"datetime": "2026-06-06T05:00:00.000Z", "text": "late evening local"},   # 06-05 22:00 PDT
        {"datetime": "2026-06-06T08:00:00.000Z", "text": "next local day"},       # 06-06 01:00 PDT
    ])

    result = await read_entries(client, date="2026-06-05")

    assert result["count"] == 2
    texts = [e["text"] for e in result["entries"]]
    assert texts == ["early morning local", "late evening local"]
    assert [e["time_display"] for e in result["entries"]] == ["01:00", "22:00"]


@respx.mock
async def test_read_entries_defaults_to_vessel_local_today(client):
    # UTC date is already 06-06, but the vessel (PDT, from the live fix)
    # is still on 06-05 — the default must be the vessel-local date.
    respx.get(POSITION_URL).respond(
        200, json={"value": {"latitude": 48.76, "longitude": -123.05}}
    )
    route = respx.get(f"{API}/logs/2026-06-05").respond(200, json=ENTRIES)
    respx.get(f"{API}/logs/2026-06-06").respond(200, json=[])

    result = await read_entries(client, now=NOW)

    assert route.called
    assert result["date"] == "2026-06-05"
    assert result["count"] == 2


@respx.mock
async def test_read_entries_default_date_falls_back_to_tz_env(client):
    _no_fix()
    route = respx.get(f"{API}/logs/2026-06-05").respond(200, json=[])
    respx.get(f"{API}/logs/2026-06-06").respond(200, json=[])

    result = await read_entries(client, now=NOW, fallback_tz="America/Vancouver")

    assert route.called
    assert result["count"] == 0


@respx.mock
async def test_read_entries_empty_day(client):
    _no_fix()
    respx.get(f"{API}/logs/2026-06-05").respond(404)
    respx.get(f"{API}/logs/2026-06-06").respond(404)
    result = await read_entries(client, date="2026-06-05")
    assert result == {"date": "2026-06-05", "count": 0, "entries": []}


@respx.mock
async def test_read_entries_tolerates_entry_missing_datetime(client):
    # A malformed entry (no datetime) must not crash the whole day read.
    _no_fix()
    malformed = {"text": "corrupt entry", "category": "navigation"}
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[malformed])
    respx.get(f"{API}/logs/2026-06-06").respond(404)

    result = await read_entries(client, date="2026-06-05")

    assert result["count"] == 1
    entry = result["entries"][0]
    assert entry["id"] == ""
    assert entry["time_display"] is None
    assert entry["text"] == "corrupt entry"


@respx.mock
async def test_read_entries_malformed_body_raises_clear_error(client):
    # A 200 with a non-JSON body must surface as the read error, not a raw
    # JSONDecodeError escaping the handler.
    _no_fix()
    respx.get(f"{API}/logs/2026-06-05").respond(200, content=b"<html>oops</html>")
    with pytest.raises(RuntimeError, match="Logbook read"):
        await read_entries(client, date="2026-06-05")


@respx.mock
async def test_read_entries_unreachable_raises_clear_error(client):
    _no_fix()
    respx.get(f"{API}/logs/2026-06-05").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(RuntimeError, match="Logbook unavailable"):
        await read_entries(client, date="2026-06-05")


AUTO_E = {
    "datetime": "2026-07-09T23:07:19.758Z",
    "text": "Warn: Inside 400m Approach Distance Prohibition (navigation.restrictedArea.x)",
    "author": "",
    "category": "navigation",
}
AGENT_E = {
    "datetime": "2026-07-09T23:30:00.000Z",
    "text": "[drill:mob] pass",
    "author": "hermes",
    "category": "drill",
}
HUMAN_E = {
    "datetime": "2026-07-09T23:45:00.000Z",
    "text": "Sunset over Boundary Pass",
    "author": "Bryan Clark",
    "category": "navigation",
}
EXPLICIT_E = {
    "datetime": "2026-07-09T23:50:00.000Z",
    "text": "Dictated note",
    "author": "poseidon",
    "origin": "manual",
    "category": "navigation",
}


@respx.mock
async def test_read_entries_derives_origin(client):
    respx.get(f"{BASE}/signalk/v1/api/vessels/self/navigation/position").respond(404)
    respx.get(f"{API}/logs/2026-07-09").respond(
        200, json=[AUTO_E, AGENT_E, HUMAN_E, EXPLICIT_E]
    )
    respx.get(f"{API}/logs/2026-07-10").respond(404)

    result = await read_entries(client, date="2026-07-09", fallback_tz="UTC")

    origins = [e["origin"] for e in result["entries"]]
    assert origins == ["auto", "agent", "manual", "manual"]


@respx.mock
async def test_read_entries_origin_filter(client):
    respx.get(f"{BASE}/signalk/v1/api/vessels/self/navigation/position").respond(404)
    respx.get(f"{API}/logs/2026-07-09").respond(
        200, json=[AUTO_E, AGENT_E, HUMAN_E, EXPLICIT_E]
    )
    respx.get(f"{API}/logs/2026-07-10").respond(404)

    result = await read_entries(
        client, date="2026-07-09", fallback_tz="UTC", origin="manual"
    )

    assert result["count"] == 2
    assert [e["text"] for e in result["entries"]] == [
        "Sunset over Boundary Pass",
        "Dictated note",
    ]


async def test_read_entries_rejects_bad_origin_filter(client):
    with pytest.raises(ValueError):
        await read_entries(client, date="2026-07-09", origin="human")
