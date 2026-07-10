"""amend_entry_author: the spoken-correction path for voice attribution."""

import json

import pytest
import respx

from logbook_mcp.client import LogbookClient
from logbook_mcp.tools import amend_entry_author

BASE = "http://test-sk:3000"
API = f"{BASE}/plugins/signalk-logbook"

ENTRY = {
    "datetime": "2026-07-10T01:00:00.000Z",
    "text": "Dictated line",
    "author": "Bryan",
    "category": "navigation",
}


@pytest.fixture
async def client():
    c = LogbookClient(BASE, token="test-token")
    yield c
    await c.aclose()


@respx.mock
async def test_amend_reattributes_entry(client):
    respx.get(f"{API}/logs/2026-07-10").respond(200, json=[ENTRY])
    put = respx.put(url__regex=r".*/logs/2026-07-10/.*").respond(200)

    result = await amend_entry_author(
        client, entry_id="2026-07-10T01:00:00.000Z", author="Sarah"
    )

    body = json.loads(put.calls[0].request.content)
    assert body["author"] == "Sarah"
    assert body["text"] == "Dictated line"
    assert result == {
        "id": "2026-07-10T01:00:00.000Z",
        "author": "Sarah",
        "confirmation": "Corrected. Entry now logged as Sarah.",
    }


@respx.mock
async def test_amend_missing_entry_raises(client):
    respx.get(f"{API}/logs/2026-07-10").respond(200, json=[])

    with pytest.raises(RuntimeError, match="No log entry"):
        await amend_entry_author(
            client, entry_id="2026-07-10T01:00:00.000Z", author="Sarah"
        )


async def test_amend_rejects_malformed_id(client):
    with pytest.raises(ValueError):
        await amend_entry_author(client, entry_id="garbage", author="Sarah")
