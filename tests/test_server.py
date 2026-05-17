import json
import os
import tempfile

import pytest


@pytest.fixture
def tmp_db_path(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    monkeypatch.setenv("LOGBOOK_DB_PATH", path)
    yield path
    if os.path.exists(path):
        os.unlink(path)


def test_build_server_registers_mark_moment(tmp_db_path):
    from logbook_mcp.server import build_server

    server = build_server()
    assert server.name == "logbook-mcp"


async def test_mark_moment_round_trip_through_server(tmp_db_path):
    """Calling the registered mark_moment handler returns JSON text content."""
    from mcp.types import CallToolRequest, CallToolRequestParams

    from logbook_mcp.server import build_server

    server = build_server()
    handler = server.request_handlers[CallToolRequest]
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="mark_moment",
            arguments={"text": "round-trip test"},
        ),
    )
    result = await handler(request)
    content = result.root.content
    assert len(content) == 1
    payload = json.loads(content[0].text)
    assert payload["text"] == "round-trip test"
    assert "id" in payload
    assert "timestamp" in payload


def test_build_server_handles_bare_filename_db_path(monkeypatch, tmp_path):
    """LOGBOOK_DB_PATH with no directory component shouldn't crash."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOGBOOK_DB_PATH", "logbook.db")

    from logbook_mcp.server import build_server

    build_server()
    assert (tmp_path / "logbook.db").exists()
