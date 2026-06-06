from datetime import datetime, timezone

import httpx
import pytest
import respx

from logbook_mcp.client import LogbookClient
from logbook_mcp.tools import read_entries

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


@respx.mock
async def test_read_entries_explicit_date(client):
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=ENTRIES)

    result = await read_entries(client, date="2026-06-05")

    assert result["date"] == "2026-06-05"
    assert result["count"] == 2
    first, second = result["entries"]
    assert first["entry_display"] == "Entry 1"
    # 14:00Z → 07:00 PDT: timezonefinder resolves (48.70, -123.20) to
    # America/Vancouver — real geographic data, not an arbitrary constant.
    assert first["time_display"] == "07:00"
    assert second["entry_display"] == "Entry 2"
    assert second["id"] == "2026-06-05T18:32:00.000Z"
    assert second["category"] == "navigation"
    assert second["author"] == "naturali"
    assert second["position_display"] == "48.4 North, 123.3 West"


@respx.mock
async def test_read_entries_defaults_to_vessel_local_today(client):
    # UTC date is already 06-06, but the vessel (PDT, from the live fix)
    # is still on 06-05 — the default must be the vessel-local date.
    respx.get(POSITION_URL).respond(
        200, json={"value": {"latitude": 48.76, "longitude": -123.05}}
    )
    route = respx.get(f"{API}/logs/2026-06-05").respond(200, json=ENTRIES)

    result = await read_entries(client, now=NOW)

    assert route.called
    assert result["date"] == "2026-06-05"


@respx.mock
async def test_read_entries_default_date_falls_back_to_tz_env(client):
    respx.get(POSITION_URL).respond(404)  # no fix
    route = respx.get(f"{API}/logs/2026-06-05").respond(200, json=[])

    result = await read_entries(client, now=NOW, fallback_tz="America/Vancouver")

    assert route.called
    assert result["count"] == 0


@respx.mock
async def test_read_entries_empty_day(client):
    respx.get(f"{API}/logs/2026-06-05").respond(404)
    result = await read_entries(client, date="2026-06-05")
    assert result == {"date": "2026-06-05", "count": 0, "entries": []}


@respx.mock
async def test_read_entries_tolerates_entry_missing_datetime(client):
    # A malformed entry (no datetime) must not crash the whole day read.
    malformed = {"text": "corrupt entry", "category": "navigation"}
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[malformed])

    result = await read_entries(client, date="2026-06-05")

    assert result["count"] == 1
    entry = result["entries"][0]
    assert entry["id"] == ""
    assert entry["time_display"] is None
    assert entry["text"] == "corrupt entry"


@respx.mock
async def test_read_entries_unreachable_raises_clear_error(client):
    respx.get(f"{API}/logs/2026-06-05").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(RuntimeError, match="Logbook unavailable"):
        await read_entries(client, date="2026-06-05")
