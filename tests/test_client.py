import json

import httpx
import pytest
import respx

from logbook_mcp.client import LogbookClient

BASE = "http://test-sk:3000"
API = f"{BASE}/plugins/signalk-logbook"

ENTRY = {
    "datetime": "2026-06-05T18:32:00.000Z",
    "position": {"latitude": 48.42, "longitude": -123.27, "source": "GPS"},
    "text": "Beautiful sunset off Discovery Island",
    "author": "naturali",
    "category": "navigation",
}


@pytest.fixture
async def client():
    c = LogbookClient(BASE, token="test-token")
    yield c
    await c.aclose()


@respx.mock
async def test_get_entries_returns_day_list(client):
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[ENTRY])
    entries = await client.get_entries("2026-06-05")
    assert entries == [ENTRY]


@respx.mock
async def test_get_entries_sends_bearer_token(client):
    route = respx.get(f"{API}/logs/2026-06-05").respond(200, json=[])
    await client.get_entries("2026-06-05")
    assert route.calls[0].request.headers["authorization"] == "Bearer test-token"


@respx.mock
async def test_requests_carry_auth_cookie(client):
    # The logbook plugin derives the entry author from this cookie.
    route = respx.get(f"{API}/logs/2026-06-05").respond(200, json=[])
    await client.get_entries("2026-06-05")
    cookie = route.calls[0].request.headers.get("cookie", "")
    assert "JAUTHENTICATION=test-token" in cookie


@respx.mock
async def test_get_entries_404_means_empty_day(client):
    respx.get(f"{API}/logs/2026-06-05").respond(404)
    assert await client.get_entries("2026-06-05") == []


async def test_get_entries_rejects_malformed_date(client):
    with pytest.raises(ValueError, match="invalid date"):
        await client.get_entries("../../etc/passwd")


@respx.mock
async def test_post_entry_sends_text_json(client):
    route = respx.post(f"{API}/logs").respond(201)
    await client.post_entry("Sunset off Discovery Island")
    assert json.loads(route.calls[0].request.content) == {
        "text": "Sunset off Discovery Island",
        "ago": 0,
    }


@respx.mock
async def test_put_entry_urlencodes_datetime_key(client):
    route = respx.put(
        f"{API}/logs/2026-06-05/2026-06-05T18%3A32%3A00.000Z"
    ).respond(200)
    await client.put_entry("2026-06-05", "2026-06-05T18:32:00.000Z", ENTRY)
    assert route.called
    assert json.loads(route.calls[0].request.content) == ENTRY


@respx.mock
async def test_get_position_returns_fix(client):
    respx.get(f"{BASE}/signalk/v1/api/vessels/self/navigation/position").respond(
        200, json={"value": {"latitude": 48.76, "longitude": -123.05}}
    )
    pos = await client.get_position()
    assert pos == {"latitude": 48.76, "longitude": -123.05}


@respx.mock
async def test_get_position_none_on_404(client):
    respx.get(f"{BASE}/signalk/v1/api/vessels/self/navigation/position").respond(404)
    assert await client.get_position() is None


@respx.mock
async def test_get_position_none_on_connect_error(client):
    respx.get(f"{BASE}/signalk/v1/api/vessels/self/navigation/position").mock(
        side_effect=httpx.ConnectError("boom")
    )
    assert await client.get_position() is None


async def test_put_entry_rejects_malformed_date(client):
    with pytest.raises(ValueError, match="invalid date"):
        await client.put_entry("junk", "2026-06-05T18:32:00.000Z", ENTRY)


@respx.mock
async def test_post_entry_sends_category_when_given(client):
    route = respx.post(f"{API}/logs").respond(201)
    await client.post_entry("MOB drill", category="drill")
    assert json.loads(route.calls[0].request.content) == {
        "text": "MOB drill",
        "ago": 0,
        "category": "drill",
    }


@respx.mock
async def test_post_entry_omits_category_by_default(client):
    # The plugin defaults to "navigation" server-side; don't send the field.
    route = respx.post(f"{API}/logs").respond(201)
    await client.post_entry("Sunset off Discovery Island")
    assert "category" not in json.loads(route.calls[0].request.content)


@respx.mock
async def test_get_dates_returns_day_index(client):
    respx.get(f"{API}/logs").respond(
        200, json=["2026-06-01", "2026-06-05", "2026-06-12"]
    )
    assert await client.get_dates() == ["2026-06-01", "2026-06-05", "2026-06-12"]


@respx.mock
async def test_get_dates_404_means_no_logs(client):
    respx.get(f"{API}/logs").respond(404)
    assert await client.get_dates() == []
