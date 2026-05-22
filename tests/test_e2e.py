"""End-to-end tests: drive logbook-mcp as a subprocess over MCP stdio."""

import json
import os
import subprocess
import sys

import pytest


@pytest.fixture
def server(tmp_path):
    """Start logbook-mcp as a real subprocess and return a call_tool helper."""
    db = tmp_path / "e2e.db"
    env = os.environ.copy()
    env["LOGBOOK_DB_PATH"] = str(db)

    proc = subprocess.Popen(
        [sys.executable, "-m", "logbook_mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    def send(msg):
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        proc.stdin.flush()

    def recv():
        return json.loads(proc.stdout.readline())

    send({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "e2e", "version": "0"},
    }})
    recv()
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    _id = [1]

    def call_tool(name, arguments):
        cid = _id[0]
        _id[0] += 1
        send({"jsonrpc": "2.0", "id": cid, "method": "tools/call",
              "params": {"name": name, "arguments": arguments}})
        resp = recv()
        text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
        return json.loads(text)

    yield call_tool

    proc.stdin.close()
    proc.wait(timeout=5)


def test_mark_moment_with_position_returns_display_fields(server):
    result = server("mark_moment", {
        "text": "Passed Active Pass, wind 15kt NW",
        "position": {"latitude": 48.8731, "longitude": -123.2837},
    })
    assert result["id"] == 1
    assert result["entry_display"] == "Entry 1"
    assert result["text"] == "Passed Active Pass, wind 15kt NW"
    assert result["timestamp"].endswith("Z")
    assert result["position"] == {"latitude": 48.8731, "longitude": -123.2837}
    assert result["position_display"] == "48.9 North, 123.3 West"


def test_mark_moment_without_position_returns_null_display(server):
    result = server("mark_moment", {"text": "Anchored in Montague Harbour"})
    assert result["entry_display"] == "Entry 1"
    assert result["position_display"] is None


def test_entry_display_increments_across_calls(server):
    first = server("mark_moment", {"text": "Raised anchor"})
    second = server("mark_moment", {"text": "Passed through Porlier Pass"})
    assert first["entry_display"] == "Entry 1"
    assert second["entry_display"] == "Entry 2"


def test_southern_hemisphere_position_display(server):
    result = server("mark_moment", {
        "text": "Arrived Grenada",
        "position": {"latitude": -12.0573, "longitude": -61.7517},
    })
    assert result["position_display"] == "12.1 South, 61.8 West"
