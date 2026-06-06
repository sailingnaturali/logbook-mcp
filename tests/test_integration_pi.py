"""Integration smoke test against the real Pi.

Skipped unless LOGBOOK_INTEGRATION=1. Requires LOGBOOK_SK_TOKEN with write
access on the Pi's SignalK. NOTE: Phase 0 vessel data is fully mocked —
position will be the fixed Boundary Pass fix; that is expected.
"""

import os
from datetime import datetime, timezone

import pytest

from logbook_mcp.client import LogbookClient
from logbook_mcp.tools import mark_moment, read_entries

pytestmark = pytest.mark.skipif(
    not os.environ.get("LOGBOOK_INTEGRATION"),
    reason="set LOGBOOK_INTEGRATION=1 (and LOGBOOK_SK_TOKEN) to run against the Pi",
)

SK_URL = os.environ.get("LOGBOOK_SK_URL", "http://naturalaspi.local:3000")


@pytest.fixture
async def client():
    c = LogbookClient(SK_URL, token=os.environ.get("LOGBOOK_SK_TOKEN"))
    yield c
    await c.aclose()


async def test_mark_and_read_back(client):
    marker = f"integration-test {datetime.now(timezone.utc).isoformat()}"
    result = await mark_moment(client, text=marker)

    assert result["entry_display"].startswith("Entry ")
    assert result["timestamp"].endswith("Z")
    # Mock vessel publishes a fix, so enrichment should have captured it:
    assert result["position"] is not None
    assert result["time_display"]  # non-empty HH:MM

    day = result["timestamp"][:10]
    read = await read_entries(client, date=day)
    assert any(e["text"] == marker for e in read["entries"])
