import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from logbook_mcp.client import LogbookClient
from logbook_mcp.tools import mark_moment

BASE = "http://test-sk:3000"
API = f"{BASE}/plugins/signalk-logbook"

NOW = datetime(2026, 6, 5, 18, 32, 5, tzinfo=timezone.utc)

EARLIER = {
    "datetime": "2026-06-05T14:00:00.000Z",
    "position": {"latitude": 48.70, "longitude": -123.20, "source": "GPS"},
    "text": "Departed Bedwell Harbour",
    "author": "naturali",
    "category": "navigation",
}
CREATED = {
    "datetime": "2026-06-05T18:32:00.000Z",
    "position": {"latitude": 48.42, "longitude": -123.27, "source": "GPS"},
    "speed": {"sog": 5.8},
    "barometer": 1013.25,
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
async def test_mark_moment_posts_text_and_returns_contract(client):
    post = respx.post(f"{API}/logs").respond(201)
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[EARLIER, CREATED])

    result = await mark_moment(
        client, text="Beautiful sunset off Discovery Island", now=NOW
    )

    assert json.loads(post.calls[0].request.content) == {
        "text": "Beautiful sunset off Discovery Island",
        "ago": 0,
    }
    assert result["id"] == "2026-06-05T18:32:00.000Z"
    assert result["entry_display"] == "Entry 2"  # 2nd entry of the day
    assert result["text"] == "Beautiful sunset off Discovery Island"
    assert result["timestamp"] == "2026-06-05T18:32:00.000Z"
    assert result["time_display"] == "11:32"  # PDT from the entry's own fix
    assert result["position"] == {"longitude": -123.27, "latitude": 48.42}
    assert result["position_display"] == "48.4 North, 123.3 West"
    assert result["confirmation"] == "Logged. Entry 2. 11:32. 48.4 North, 123.3 West."


@respx.mock
async def test_mark_moment_entry_without_position(client):
    no_fix = {**CREATED, "position": None}
    del no_fix["speed"]
    respx.post(f"{API}/logs").respond(201)
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[no_fix])

    result = await mark_moment(client, text="x", now=NOW, fallback_tz="America/Vancouver")

    assert result["position"] is None
    assert result["position_display"] is None
    assert result["time_display"] == "11:32"  # falls back to LOGBOOK_TZ
    assert result["confirmation"] == "Logged. Entry 1. 11:32."


@respx.mock
async def test_mark_moment_explicit_position_overrides_via_put(client):
    respx.post(f"{API}/logs").respond(201)
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[CREATED])
    put = respx.put(
        f"{API}/logs/2026-06-05/2026-06-05T18%3A32%3A00.000Z"
    ).respond(200)

    result = await mark_moment(
        client,
        text="Beautiful sunset off Discovery Island",
        position={"longitude": -123.30, "latitude": 48.45},
        now=NOW,
    )

    body = json.loads(put.calls[0].request.content)
    assert body["position"] == {
        "longitude": -123.30, "latitude": 48.45, "source": "manual"
    }
    assert result["position"] == {"longitude": -123.30, "latitude": 48.45}
    assert result["position_display"] == "48.5 North, 123.3 West"


@respx.mock
async def test_mark_moment_finds_entry_on_previous_utc_day(client):
    # Entry written at 23:59:59Z; by the time we re-fetch, UTC has rolled over.
    late = {**CREATED, "datetime": "2026-06-05T23:59:59.000Z"}
    after_midnight = datetime(2026, 6, 6, 0, 0, 1, tzinfo=timezone.utc)
    respx.post(f"{API}/logs").respond(201)
    respx.get(f"{API}/logs/2026-06-06").respond(404)
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[EARLIER, late])

    result = await mark_moment(client, text="x", now=after_midnight)
    assert result["id"] == "2026-06-05T23:59:59.000Z"


@respx.mock
async def test_mark_moment_unreachable_says_not_recorded(client):
    respx.post(f"{API}/logs").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(RuntimeError, match="NOT recorded"):
        await mark_moment(client, text="x", now=NOW)


@respx.mock
async def test_mark_moment_auth_failure_names_token_env_var(client):
    respx.post(f"{API}/logs").respond(401)
    with pytest.raises(RuntimeError, match="LOGBOOK_SK_TOKEN"):
        await mark_moment(client, text="x", now=NOW)


@respx.mock
async def test_mark_moment_post_ok_but_confirm_failed_is_honest(client):
    # POST landed; the confirmation GET failed. The moment WAS recorded —
    # the error must not claim otherwise.
    respx.post(f"{API}/logs").respond(201)
    respx.get(f"{API}/logs/2026-06-05").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(RuntimeError, match="recorded but could not be confirmed"):
        await mark_moment(client, text="x", now=NOW)


@respx.mock
async def test_mark_moment_datetime_less_newest_entry_is_honest(client):
    # The re-fetched day's newest entry lacks "datetime" (malformed store).
    # That must surface as the post-write honesty error, not a raw KeyError.
    respx.post(f"{API}/logs").respond(201)
    respx.get(f"{API}/logs/2026-06-05").respond(
        200, json=[{"text": "no datetime here", "category": "navigation"}]
    )
    with pytest.raises(RuntimeError, match="recorded but could not be confirmed"):
        await mark_moment(client, text="x", now=NOW)


@respx.mock
async def test_mark_moment_put_failure_after_post_is_honest(client):
    # POST and re-fetch succeeded; the position-override PUT failed.
    # The moment WAS recorded — the error must not claim otherwise.
    respx.post(f"{API}/logs").respond(201)
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[CREATED])
    respx.put(
        f"{API}/logs/2026-06-05/2026-06-05T18%3A32%3A00.000Z"
    ).respond(500)
    with pytest.raises(RuntimeError, match="recorded but could not be confirmed"):
        await mark_moment(
            client,
            text="x",
            position={"longitude": -123.30, "latitude": 48.45},
            now=NOW,
        )


@respx.mock
async def test_mark_moment_sends_category(client):
    post = respx.post(f"{API}/logs").respond(201)
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[CREATED])

    await mark_moment(client, text="Checked in with VTS", category="radio", now=NOW)

    assert json.loads(post.calls[0].request.content)["category"] == "radio"
