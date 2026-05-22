import json
import os
import tempfile

import pytest
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.fixture
def tmp_db_path(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setenv("LOGBOOK_DB_PATH", path)
    yield path
    if os.path.exists(path):
        os.unlink(path)


def test_build_server_registers_mark_moment(tmp_db_path):
    """build_server returns a Server with mark_moment in its tool list."""
    from logbook_mcp.server import build_server

    server = build_server()
    assert server.name == "logbook-mcp"

    # The @server.list_tools() decorator stores a request handler; invoking it
    # via the in-memory client (below) is the supported way to read it.


async def test_mark_moment_round_trip_through_server(tmp_db_path):
    """A real MCP client→server round trip returns the expected JSON payload."""
    from logbook_mcp.server import build_server

    server = build_server()
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        assert any(t.name == "mark_moment" for t in tools.tools)

        result = await client.call_tool("mark_moment", {"text": "round-trip test"})
        assert len(result.content) == 1
        payload = json.loads(result.content[0].text)
        assert payload["text"] == "round-trip test"
        assert isinstance(payload["id"], int)
        assert payload["entry_display"] == f"Entry {payload['id']}"
        assert payload["timestamp"].endswith("Z")
        assert payload["position"] is None


async def test_mark_moment_rejects_out_of_range_latitude(tmp_db_path):
    """MCP's inputSchema validator rejects out-of-range coordinates."""
    from logbook_mcp.server import build_server

    server = build_server()
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "mark_moment",
            {"text": "bad coords", "position": {"latitude": 200, "longitude": 0}},
        )
        assert result.isError


async def test_mark_moment_rejects_empty_text(tmp_db_path):
    """minLength=1 on text rejects empty strings."""
    from logbook_mcp.server import build_server

    server = build_server()
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("mark_moment", {"text": ""})
        assert result.isError


async def test_mark_moment_rejects_unknown_arg(tmp_db_path):
    """additionalProperties=false rejects unknown arguments."""
    from logbook_mcp.server import build_server

    server = build_server()
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool(
            "mark_moment", {"text": "hi", "vessel": "Naturali"}
        )
        assert result.isError


def test_build_server_handles_bare_filename_db_path(monkeypatch, tmp_path):
    """LOGBOOK_DB_PATH with no directory component shouldn't crash."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOGBOOK_DB_PATH", "logbook.db")

    from logbook_mcp.server import build_server

    build_server()
    assert (tmp_path / "logbook.db").exists()
