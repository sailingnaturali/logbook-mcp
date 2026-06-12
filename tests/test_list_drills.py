from datetime import datetime, timezone

import pytest
import respx

from logbook_mcp.client import LogbookClient
from logbook_mcp.tools import list_drills

BASE = "http://test-sk:3000"
API = f"{BASE}/plugins/signalk-logbook"

NOW = datetime(2026, 6, 12, 20, 30, 0, tzinfo=timezone.utc)

MOB_MAY = {
    "datetime": "2026-05-10T18:00:00.000Z",
    "text": "[drill:mob outcome=partial duration=20m] Slow first pass.",
    "category": "drill",
    "author": "naturali",
}
NAV_MAY = {
    "datetime": "2026-05-10T19:00:00.000Z",
    "text": "Anchored in Bedwell Harbour",
    "category": "navigation",
    "author": "naturali",
}
MOB_JUNE = {
    "datetime": "2026-06-12T20:14:00.000Z",
    "text": "[drill:mob outcome=pass duration=14m crew=Bryan,K] Clean recovery.",
    "category": "drill",
    "author": "naturali",
    "position": {"latitude": 48.76, "longitude": -123.05, "source": "GPS"},
}
FIRE_JUNE_UNTAGGED = {
    # category=drill but freehand text (e.g. typed in the plugin UI):
    # still listed, fields None.
    "datetime": "2026-06-01T17:00:00.000Z",
    "text": "Fire drill at the dock, extinguisher walk-through",
    "category": "drill",
    "author": "naturali",
}


@pytest.fixture
async def client():
    c = LogbookClient(BASE, token="test-token")
    yield c
    await c.aclose()


def _mock_days():
    respx.get(f"{API}/logs").respond(
        200, json=["2025-09-01", "2026-05-10", "2026-06-01", "2026-06-12"]
    )
    respx.get(f"{API}/logs/2026-05-10").respond(200, json=[MOB_MAY, NAV_MAY])
    respx.get(f"{API}/logs/2026-06-01").respond(200, json=[FIRE_JUNE_UNTAGGED])
    respx.get(f"{API}/logs/2026-06-12").respond(200, json=[MOB_JUNE])


@respx.mock
async def test_list_drills_default_window_and_latest_by_type(client):
    _mock_days()
    result = await list_drills(client, now=NOW)

    # 2025-09-01 is outside the 180-day default window — never fetched.
    assert result["since"] == "2025-12-14"
    assert result["until"] == "2026-06-12"
    assert result["count"] == 3
    assert [d["id"] for d in result["drills"]] == [
        "2026-05-10T18:00:00.000Z",
        "2026-06-01T17:00:00.000Z",
        "2026-06-12T20:14:00.000Z",
    ]

    june_mob = result["drills"][2]
    assert june_mob["drill_type"] == "mob"
    assert june_mob["outcome"] == "pass"
    assert june_mob["duration_minutes"] == 14
    assert june_mob["participants"] == ["Bryan", "K"]
    assert june_mob["notes"] == "Clean recovery."
    assert june_mob["position"] == {"longitude": -123.05, "latitude": 48.76}

    untagged = result["drills"][1]
    assert untagged["drill_type"] is None
    assert untagged["notes"] == "Fire drill at the dock, extinguisher walk-through"

    # latest per type; untagged entries can't contribute a type
    assert result["latest_by_type"] == {"mob": "2026-06-12"}


@respx.mock
async def test_list_drills_filters_by_type_and_range(client):
    _mock_days()
    result = await list_drills(
        client, drill_type="mob", since="2026-05-01", until="2026-05-31", now=NOW
    )
    assert result["count"] == 1
    assert result["drills"][0]["id"] == "2026-05-10T18:00:00.000Z"
    assert result["latest_by_type"] == {"mob": "2026-05-10"}


async def test_list_drills_rejects_bad_inputs(client):
    with pytest.raises(ValueError, match="drill_type"):
        await list_drills(client, drill_type="MOB!", now=NOW)
    with pytest.raises(ValueError, match="invalid date"):
        await list_drills(client, since="last month", now=NOW)


@respx.mock
async def test_list_drills_unreachable_surfaces_runtime_error(client):
    import httpx
    respx.get(f"{API}/logs").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(RuntimeError, match="Logbook unavailable"):
        await list_drills(client, now=NOW)


@respx.mock
async def test_list_drills_malformed_body_surfaces_runtime_error(client):
    respx.get(f"{API}/logs").respond(200, content=b"not json")
    with pytest.raises(RuntimeError, match="malformed data"):
        await list_drills(client, now=NOW)


@respx.mock
async def test_list_drills_rejects_inverted_range(client):
    with pytest.raises(ValueError, match="since"):
        await list_drills(client, since="2026-07-01", until="2026-06-01", now=NOW)


@respx.mock
async def test_list_drills_auth_error_mentions_token(client):
    respx.get(f"{API}/logs").respond(401)
    with pytest.raises(RuntimeError, match="LOGBOOK_SK_TOKEN"):
        await list_drills(client, now=NOW)
