import json

import httpx
import pytest
import respx
from mcp.shared.memory import create_connected_server_and_client_session

from logbook_mcp.client import LogbookClient
from logbook_mcp.server import build_server

BASE = "http://test-sk:3000"
API = f"{BASE}/plugins/signalk-logbook"
POSITION_URL = f"{BASE}/signalk/v1/api/vessels/self/navigation/position"

CREATED = {
    "datetime": "2026-06-05T18:32:00.000Z",
    "position": {"latitude": 48.42, "longitude": -123.27, "source": "GPS"},
    "text": "Sunset",
    "author": "naturali",
    "category": "navigation",
}


@pytest.fixture
async def lb_client():
    c = LogbookClient(BASE, token="t")
    yield c
    await c.aclose()


async def test_list_tools_exposes_all_tools(lb_client):
    server = build_server(lb_client)
    assert server.name == "logbook-mcp"
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools.tools} == {
            "mark_moment", "read_entries", "log_drill", "list_drills",
        }
        mark = next(t for t in tools.tools if t.name == "mark_moment")
        assert mark.inputSchema["properties"]["category"]["enum"] == [
            "navigation", "engine", "radio", "maintenance", "drill",
        ]


@respx.mock
async def test_mark_moment_round_trip_through_server(lb_client):
    """A real MCP client→server round trip returns the expected JSON payload."""
    respx.post(f"{API}/logs").respond(201)
    respx.get(url__regex=rf"{API}/logs/\d{{4}}-\d{{2}}-\d{{2}}$").respond(
        200, json=[CREATED]
    )
    server = build_server(lb_client)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("mark_moment", {"text": "Sunset"})
        assert len(result.content) == 1
        payload = json.loads(result.content[0].text)
        assert payload["entry_display"] == "Entry 1"
        assert payload["id"] == "2026-06-05T18:32:00.000Z"
        assert payload["position_display"] == "48.4 North, 123.3 West"


@respx.mock
async def test_read_entries_round_trip_through_server(lb_client):
    respx.get(POSITION_URL).respond(404)
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[CREATED])
    respx.get(f"{API}/logs/2026-06-06").respond(404)
    server = build_server(lb_client)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("read_entries", {"date": "2026-06-05"})
        payload = json.loads(result.content[0].text)
        assert payload["date"] == "2026-06-05"
        assert payload["count"] == 1
        assert payload["entries"][0]["text"] == "Sunset"


async def test_mark_moment_rejects_out_of_range_latitude(lb_client):
    """MCP's inputSchema validator rejects out-of-range coordinates."""
    server = build_server(lb_client)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "mark_moment",
            {"text": "bad coords", "position": {"latitude": 200, "longitude": 0}},
        )
        assert result.isError


async def test_mark_moment_rejects_empty_text(lb_client):
    """minLength=1 on text rejects empty strings."""
    server = build_server(lb_client)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("mark_moment", {"text": ""})
        assert result.isError


async def test_read_entries_rejects_malformed_date(lb_client):
    """The date pattern rejects URL junk before it reaches the client."""
    server = build_server(lb_client)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("read_entries", {"date": "not-a-date"})
        assert result.isError


@respx.mock
async def test_unreachable_pi_surfaces_as_tool_error(lb_client):
    respx.post(f"{API}/logs").mock(side_effect=httpx.ConnectError("boom"))
    server = build_server(lb_client)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("mark_moment", {"text": "x"})
        assert result.isError
        assert "NOT recorded" in result.content[0].text


@respx.mock
async def test_read_entries_unreachable_surfaces_as_tool_error(lb_client):
    respx.get(POSITION_URL).respond(404)
    respx.get(url__regex=rf"{API}/logs/\d{{4}}-\d{{2}}-\d{{2}}$").mock(
        side_effect=httpx.ConnectError("boom")
    )
    server = build_server(lb_client)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("read_entries", {"date": "2026-06-05"})
        assert result.isError
        assert "SignalK" in result.content[0].text


DRILL_CREATED = {
    "datetime": "2026-06-12T20:29:50.000Z",
    "text": "[drill:mob outcome=pass] Clean recovery.",
    "author": "naturali",
    "category": "drill",
}


@respx.mock
async def test_log_drill_round_trip_through_server(lb_client):
    respx.post(f"{API}/logs").respond(201)
    respx.get(url__regex=rf"{API}/logs/\d{{4}}-\d{{2}}-\d{{2}}$").respond(
        200, json=[DRILL_CREATED]
    )
    server = build_server(lb_client)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "log_drill",
            {"drill_type": "mob", "outcome": "pass", "notes": "Clean recovery."},
        )
        payload = json.loads(result.content[0].text)
        assert payload["drill_type"] == "mob"
        assert payload["outcome"] == "pass"
        assert payload["confirmation"].startswith("Logged mob drill, pass.")


@respx.mock
async def test_list_drills_round_trip_through_server(lb_client):
    respx.get(f"{API}/logs").respond(200, json=["2026-06-12"])
    respx.get(f"{API}/logs/2026-06-12").respond(200, json=[DRILL_CREATED])
    server = build_server(lb_client)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "list_drills", {"since": "2026-06-01", "until": "2026-06-30"}
        )
        payload = json.loads(result.content[0].text)
        assert payload["count"] == 1
        assert payload["latest_by_type"] == {"mob": "2026-06-12"}
