import json
from datetime import datetime, timezone

import pytest
import respx

from logbook_mcp.client import LogbookClient
from logbook_mcp.tools import log_drill

BASE = "http://test-sk:3000"
API = f"{BASE}/plugins/signalk-logbook"

NOW = datetime(2026, 6, 12, 20, 30, 0, tzinfo=timezone.utc)

DRILL_ENTRY = {
    "datetime": "2026-06-12T20:29:50.000Z",
    "position": {"latitude": 48.76, "longitude": -123.05, "source": "GPS"},
    "text": "[drill:mob outcome=pass duration=14m crew=Bryan,K] Lifesling recovery.",
    "author": "naturali",
    "category": "drill",
}


@pytest.fixture
async def client():
    c = LogbookClient(BASE, token="test-token")
    yield c
    await c.aclose()


@respx.mock
async def test_log_drill_writes_tagged_drill_entry(client):
    post = respx.post(f"{API}/logs").respond(201)
    respx.get(f"{API}/logs/2026-06-12").respond(200, json=[DRILL_ENTRY])

    result = await log_drill(
        client,
        drill_type="mob",
        outcome="pass",
        duration_minutes=14,
        participants=["Bryan", "K"],
        notes="Lifesling recovery.",
        now=NOW,
    )

    body = json.loads(post.calls[0].request.content)
    assert body["category"] == "drill"
    assert body["text"] == (
        "[drill:mob outcome=pass duration=14m crew=Bryan,K] Lifesling recovery."
    )
    assert body["origin"] == "agent"
    # mark_moment's write/confirm contract is inherited
    assert result["id"] == "2026-06-12T20:29:50.000Z"
    assert result["drill_type"] == "mob"
    assert result["outcome"] == "pass"
    assert result["duration_minutes"] == 14
    assert result["participants"] == ["Bryan", "K"]
    assert result["notes"] == "Lifesling recovery."
    # voice confirmation never reads tag syntax aloud
    assert "[" not in result["confirmation"]
    assert result["confirmation"].startswith("Logged mob drill, pass.")


@respx.mock
async def test_log_drill_rejects_invalid_input_without_writing(client):
    post = respx.post(f"{API}/logs").respond(201)
    with pytest.raises(ValueError, match="outcome"):
        await log_drill(client, drill_type="mob", outcome="heroic", now=NOW)
    assert not post.called


@respx.mock
async def test_log_drill_propagates_unconfirmed_write_error(client):
    # POST succeeds but the re-fetch fails: mark_moment's "recorded but could
    # not be confirmed" honesty must survive the log_drill wrapper.
    respx.post(f"{API}/logs").respond(201)
    respx.get(f"{API}/logs/2026-06-12").respond(200, json=[])
    respx.get(f"{API}/logs/2026-06-11").respond(200, json=[])
    with pytest.raises(RuntimeError, match="could not be confirmed"):
        await log_drill(client, drill_type="mob", outcome="pass", now=NOW)
