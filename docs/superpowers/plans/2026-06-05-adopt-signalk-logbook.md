# logbook-mcp over signalk-logbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace logbook-mcp's SQLite store with a stateless HTTP client over the `signalk-logbook` plugin's REST API on the Pi, preserving the `mark_moment` contract and adding `read_entries`.

**Architecture:** `signalk-logbook` (installed on the Pi's SignalK server) owns the ship's log as per-day YAML and auto-enriches entries with vessel state. logbook-mcp becomes a thin async client: `client.py` wraps the REST API, `tools.py` implements `mark_moment`/`read_entries`, `server.py` wires env config. `db.py` and all SQLite code are deleted.

**Tech Stack:** Python 3.11+, `mcp`, `httpx` (async client), `timezonefinder`+`zoneinfo` (vessel-local `time_display`), `pytest`+`respx` (HTTP mocking — same idiom as sibling repo `signalk-mcp`).

**Spec:** `docs/superpowers/specs/2026-06-05-adopt-signalk-logbook-design.md` (approved). Read it first.

**Key API facts (verified against `meri-imperiumi/signalk-logbook` source):**
- Routes mount at `{SK_URL}/plugins/signalk-logbook/…`
- `GET /logs` → `["2026-06-05", …]`; `GET /logs/{date}` → array of entries; `POST /logs {text}` → bare `201`, **no body**; `PUT /logs/{date}/{datetime}` → `200`; `DELETE` → `204`
- Entries look like: `{"datetime": "2026-06-05T18:32:00.000Z", "position": {"latitude": 48.42, "longitude": -123.27, "source": "GPS"}, "speed": {"sog": 5.8}, "heading": 190, "wind": {"speed": 12.7, "direction": 89.5}, "barometer": 1013.25, "text": "...", "author": "...", "category": "navigation"}`
- Writes require a SignalK access token. Send `Authorization: Bearer {token}`; if the Pi's signalk-server rejects Bearer with 401, retry the scheme `JWT {token}` (older signalk-server accepts only `JWT`) — Task 9 verifies which.

**Working directory:** `/Users/clarkbw/src/sailingnaturali/logbook-mcp` unless stated otherwise.

**Commit policy:** this machine is `studio.local` → commit and push without asking (workspace CLAUDE.md).

---

### Task 1: Dependencies and version bump

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml**

Change `version` and `dependencies`, and add `respx` to the dev group:

```toml
[project]
name = "logbook-mcp"
version = "0.2.0"
description = "MCP server over signalk-logbook: marked moments, day reads, and (future) USCG/TC sea-time export"
readme = "README.md"
authors = [
    { name = "Bryan Clark", email = "clarkbw@gmail.com" }
]
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.27.1,<2",
    "httpx>=0.28.1",
    "timezonefinder>=8.2.4",
]

[project.scripts]
logbook-mcp = "logbook_mcp.server:main"

[build-system]
requires = ["uv_build>=0.11.14,<0.12.0"]
build-backend = "uv_build"

[dependency-groups]
dev = [
    "pytest>=9.0.3",
    "pytest-asyncio>=1.3.0",
    "respx>=0.22.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Sync and verify**

Run: `uv sync`
Expected: resolves and installs httpx, timezonefinder, respx without errors.

Run: `uv run python -c "import httpx, respx, timezonefinder; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add httpx/timezonefinder/respx, bump to 0.2.0"
```

---

### Task 2: LogbookClient

**Files:**
- Create: `src/logbook_mcp/client.py`
- Test: `tests/test_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_client.py`:

```python
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
    import json
    assert json.loads(route.calls[0].request.content) == {
        "text": "Sunset off Discovery Island"
    }


@respx.mock
async def test_put_entry_urlencodes_datetime_key(client):
    route = respx.put(
        f"{API}/logs/2026-06-05/2026-06-05T18%3A32%3A00.000Z"
    ).respond(200)
    await client.put_entry("2026-06-05", "2026-06-05T18:32:00.000Z", ENTRY)
    assert route.called


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'logbook_mcp.client'`

- [ ] **Step 3: Implement LogbookClient**

Create `src/logbook_mcp/client.py`:

```python
"""Thin async wrapper around the signalk-logbook plugin's REST API."""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_date(date: str) -> None:
    """Reject anything that isn't YYYY-MM-DD before interpolating into a URL."""
    if not _DATE_RE.match(date):
        raise ValueError(f"invalid date: {date!r}")


class LogbookClient:
    """Async client for signalk-logbook on a SignalK server.

    ``base_url`` is the SignalK server root (e.g. http://naturalaspi.local:3000);
    plugin routes live under /plugins/signalk-logbook. Writes require a SignalK
    access token, sent as ``Authorization: Bearer {token}``.
    """

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.AsyncClient(timeout=5.0, headers=headers)

    @property
    def _api(self) -> str:
        return f"{self.base_url}/plugins/signalk-logbook"

    async def get_entries(self, date: str) -> list[dict]:
        """Entries for a YYYY-MM-DD day. A 404 means no log that day -> []."""
        validate_date(date)
        resp = await self._http.get(f"{self._api}/logs/{date}")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json()

    async def post_entry(self, text: str) -> None:
        """Create an entry; the plugin enriches it server-side from live SignalK.

        POST returns a bare 201 with no body — callers re-fetch the day to see
        the created entry.
        """
        resp = await self._http.post(f"{self._api}/logs", json={"text": text})
        resp.raise_for_status()

    async def put_entry(self, date: str, datetime_key: str, entry: dict) -> None:
        """Replace an entry identified by its datetime key."""
        validate_date(date)
        url = f"{self._api}/logs/{date}/{quote(datetime_key, safe='')}"
        resp = await self._http.put(url, json=entry)
        resp.raise_for_status()

    async def get_position(self) -> dict | None:
        """Current GPS fix from SignalK, or None if unavailable.

        Absence (404, no fix, unreachable) is a normal result here, not an
        error — callers fall back to LOGBOOK_TZ.
        """
        url = f"{self.base_url}/signalk/v1/api/vessels/self/navigation/position"
        try:
            resp = await self._http.get(url)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        value = resp.json().get("value") or {}
        if value.get("latitude") is None or value.get("longitude") is None:
            return None
        return {"latitude": value["latitude"], "longitude": value["longitude"]}

    async def aclose(self) -> None:
        await self._http.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/logbook_mcp/client.py tests/test_client.py
git commit -m "feat: LogbookClient — async wrapper over signalk-logbook REST API"
```

---

### Task 3: Formatting helpers (position, local time)

**Files:**
- Rewrite: `src/logbook_mcp/tools.py` (helpers only in this task; tools come in Tasks 4–5)
- Test: `tests/test_helpers.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_helpers.py`:

```python
from logbook_mcp.tools import _format_position, _time_display


def test_format_position_north_west():
    assert _format_position(48.42, -123.27) == "48.4 North, 123.3 West"


def test_format_position_south_east():
    assert _format_position(-55.98, 67.27) == "56.0 South, 67.3 East"


def test_format_position_zero_renders_without_direction():
    assert _format_position(0, 0) == "0.0, 0.0"


def test_format_position_none_is_none():
    assert _format_position(None, None) is None


def test_time_display_localizes_from_entry_position():
    # 18:32Z on 2026-06-05 in America/Vancouver (PDT, UTC-7) is 11:32
    out = _time_display(
        "2026-06-05T18:32:00.000Z",
        {"latitude": 48.42, "longitude": -123.27},
        fallback_tz="UTC",
    )
    assert out == "11:32"


def test_time_display_falls_back_to_configured_tz_without_position():
    out = _time_display("2026-06-05T18:32:00.000Z", None, fallback_tz="America/Vancouver")
    assert out == "11:32"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_helpers.py -v`
Expected: FAIL — `ImportError: cannot import name '_time_display'`

- [ ] **Step 3: Rewrite tools.py with helpers**

Replace the entire contents of `src/logbook_mcp/tools.py` (the old SQLite-backed
`mark_moment` goes away; the new one lands in Task 4):

```python
"""MCP tool implementations for logbook-mcp.

Async functions over a LogbookClient; contracts in SPEC.md.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx

from logbook_mcp.client import LogbookClient

if TYPE_CHECKING:
    from timezonefinder import TimezoneFinder

_tf: "TimezoneFinder | None" = None


def _get_timezone_finder() -> "TimezoneFinder":
    """Lazy-init TimezoneFinder — it loads ~50MB of shapefile data."""
    global _tf
    if _tf is None:
        from timezonefinder import TimezoneFinder
        _tf = TimezoneFinder()
    return _tf


def _format_position(lat: float | None, lon: float | None) -> str | None:
    if lat is None or lon is None:
        return None
    lat_part = f"{abs(lat):.1f}" if lat == 0 else f"{abs(lat):.1f} {'North' if lat > 0 else 'South'}"
    lon_part = f"{abs(lon):.1f}" if lon == 0 else f"{abs(lon):.1f} {'East' if lon > 0 else 'West'}"
    return f"{lat_part}, {lon_part}"


def _entry_timezone(position: dict | None, fallback_tz: str) -> zoneinfo.ZoneInfo:
    """Timezone at the entry's own position, else the configured fallback."""
    if position:
        tz_name = _get_timezone_finder().timezone_at(
            lat=position["latitude"], lng=position["longitude"]
        )
        if tz_name:
            return zoneinfo.ZoneInfo(tz_name)
    return zoneinfo.ZoneInfo(fallback_tz)


def _time_display(datetime_iso: str, position: dict | None, fallback_tz: str) -> str:
    """Vessel-local HH:MM for an entry timestamp (same display as signalk-mcp)."""
    dt = datetime.fromisoformat(datetime_iso.replace("Z", "+00:00"))
    return dt.astimezone(_entry_timezone(position, fallback_tz)).strftime("%H:%M")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_helpers.py -v`
Expected: 6 passed. (Note: `tests/test_mark_moment.py` and others now fail to
import — that's expected mid-rewrite; they are replaced in Tasks 4 and 6.)

- [ ] **Step 5: Commit**

```bash
git add src/logbook_mcp/tools.py tests/test_helpers.py
git commit -m "feat: position/local-time helpers for REST-backed tools"
```

---

### Task 4: mark_moment over the REST API

**Files:**
- Modify: `src/logbook_mcp/tools.py` (append)
- Rewrite: `tests/test_mark_moment.py`

- [ ] **Step 1: Write failing tests**

Replace the entire contents of `tests/test_mark_moment.py`:

```python
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
        "text": "Beautiful sunset off Discovery Island"
    }
    assert result["id"] == "2026-06-05T18:32:00.000Z"
    assert result["entry_display"] == "Entry 2"  # 2nd entry of the day
    assert result["text"] == "Beautiful sunset off Discovery Island"
    assert result["timestamp"] == "2026-06-05T18:32:00.000Z"
    assert result["time_display"] == "11:32"  # PDT from the entry's own fix
    assert result["position"] == {"longitude": -123.27, "latitude": 48.42}
    assert result["position_display"] == "48.4 North, 123.3 West"


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
    assert result["position_display"] == "48.4 North, 123.3 West"


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mark_moment.py -v`
Expected: FAIL — `ImportError: cannot import name 'mark_moment'`

- [ ] **Step 3: Implement mark_moment**

Append to `src/logbook_mcp/tools.py`:

```python
def _auth_error(exc: httpx.HTTPStatusError, base_url: str) -> RuntimeError | None:
    if exc.response.status_code in (401, 403):
        return RuntimeError(
            f"Logbook auth failed (HTTP {exc.response.status_code}) at {base_url}: "
            "check LOGBOOK_SK_TOKEN"
        )
    return None


async def _newest_entry(
    client: LogbookClient, now: datetime
) -> tuple[dict, int]:
    """The just-created entry and its 1-based ordinal within its day.

    POST /logs returns no body, so we re-fetch the day. If the clock rolled
    past UTC midnight between write and re-fetch, the entry is in the
    previous day's file — check there before giving up.
    """
    for day in (now.date(), now.date() - timedelta(days=1)):
        entries = await client.get_entries(day.isoformat())
        if entries:
            entries.sort(key=lambda e: e["datetime"])
            return entries[-1], len(entries)
    raise RuntimeError(
        "Logbook entry was recorded but could not be confirmed: "
        "no entries found on re-fetch"
    )


async def mark_moment(
    client: LogbookClient,
    text: str,
    position: dict | None = None,
    fallback_tz: str = "America/Vancouver",
    now: datetime | None = None,
) -> dict:
    """Record a moment in the ship's log via signalk-logbook.

    The plugin snapshots position/heading/speed/wind/barometer server-side.
    An explicit ``position`` overrides the snapshotted fix via a follow-up PUT.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    try:
        await client.post_entry(text)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise RuntimeError(
            f"Logbook unavailable: cannot reach SignalK at {client.base_url} "
            "— moment NOT recorded"
        ) from exc
    except httpx.HTTPStatusError as exc:
        auth = _auth_error(exc, client.base_url)
        if auth:
            raise auth from exc
        raise RuntimeError(
            f"Logbook write failed (HTTP {exc.response.status_code}) "
            "— moment NOT recorded"
        ) from exc

    # Past this point the moment IS recorded; errors must say so honestly.
    try:
        entry, ordinal = await _newest_entry(client, now)

        if position is not None:
            entry = {
                **entry,
                "position": {
                    "longitude": position["longitude"],
                    "latitude": position["latitude"],
                    "source": "manual",
                },
            }
            day = entry["datetime"][:10]
            await client.put_entry(day, entry["datetime"], entry)
    except RuntimeError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(
            "Logbook entry was recorded but could not be confirmed "
            f"({exc.__class__.__name__}); check the log via read_entries"
        ) from exc

    pos = entry.get("position") or None
    pos_out = (
        {"longitude": pos["longitude"], "latitude": pos["latitude"]}
        if pos and pos.get("latitude") is not None
        else None
    )
    return {
        "id": entry["datetime"],
        "entry_display": f"Entry {ordinal}",
        "text": entry.get("text", text),
        "timestamp": entry["datetime"],
        "time_display": _time_display(entry["datetime"], pos_out, fallback_tz),
        "position": pos_out,
        "position_display": _format_position(
            pos_out["latitude"] if pos_out else None,
            pos_out["longitude"] if pos_out else None,
        ),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mark_moment.py tests/test_helpers.py tests/test_client.py -v`
Expected: all pass (7 + 6 + 9)

- [ ] **Step 5: Commit**

```bash
git add src/logbook_mcp/tools.py tests/test_mark_moment.py
git commit -m "feat: mark_moment over signalk-logbook REST with honest error states"
```

---

### Task 5: read_entries

**Files:**
- Modify: `src/logbook_mcp/tools.py` (append)
- Create: `tests/test_read_entries.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_read_entries.py`:

```python
from datetime import datetime, timezone

import httpx
import pytest
import respx

from logbook_mcp.client import LogbookClient
from logbook_mcp.tools import read_entries

BASE = "http://test-sk:3000"
API = f"{BASE}/plugins/signalk-logbook"
POSITION_URL = f"{BASE}/signalk/v1/api/vessels/self/navigation/position"

# 2026-06-06T02:30Z is still 2026-06-05 19:30 in America/Vancouver
NOW = datetime(2026, 6, 6, 2, 30, 0, tzinfo=timezone.utc)

ENTRIES = [
    {
        "datetime": "2026-06-05T14:00:00.000Z",
        "position": {"latitude": 48.70, "longitude": -123.20, "source": "GPS"},
        "text": "Departed Bedwell Harbour",
        "author": "auto",
        "category": "navigation",
    },
    {
        "datetime": "2026-06-05T18:32:00.000Z",
        "position": {"latitude": 48.42, "longitude": -123.27, "source": "GPS"},
        "text": "Beautiful sunset off Discovery Island",
        "author": "naturali",
        "category": "navigation",
    },
]


@pytest.fixture
async def client():
    c = LogbookClient(BASE, token="test-token")
    yield c
    await c.aclose()


@respx.mock
async def test_read_entries_explicit_date(client):
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=ENTRIES)

    result = await read_entries(client, date="2026-06-05")

    assert result["date"] == "2026-06-05"
    assert result["count"] == 2
    first, second = result["entries"]
    assert first["entry_display"] == "Entry 1"
    assert first["time_display"] == "07:00"
    assert second["entry_display"] == "Entry 2"
    assert second["id"] == "2026-06-05T18:32:00.000Z"
    assert second["category"] == "navigation"
    assert second["author"] == "naturali"
    assert second["position_display"] == "48.4 North, 123.3 West"


@respx.mock
async def test_read_entries_defaults_to_vessel_local_today(client):
    # UTC date is already 06-06, but the vessel (PDT, from the live fix)
    # is still on 06-05 — the default must be the vessel-local date.
    respx.get(POSITION_URL).respond(
        200, json={"value": {"latitude": 48.76, "longitude": -123.05}}
    )
    route = respx.get(f"{API}/logs/2026-06-05").respond(200, json=ENTRIES)

    result = await read_entries(client, now=NOW)

    assert route.called
    assert result["date"] == "2026-06-05"


@respx.mock
async def test_read_entries_default_date_falls_back_to_tz_env(client):
    respx.get(POSITION_URL).respond(404)  # no fix
    route = respx.get(f"{API}/logs/2026-06-05").respond(200, json=[])

    result = await read_entries(client, now=NOW, fallback_tz="America/Vancouver")

    assert route.called
    assert result["count"] == 0


@respx.mock
async def test_read_entries_empty_day(client):
    respx.get(f"{API}/logs/2026-06-05").respond(404)
    result = await read_entries(client, date="2026-06-05")
    assert result == {"date": "2026-06-05", "count": 0, "entries": []}


@respx.mock
async def test_read_entries_unreachable_raises_clear_error(client):
    respx.get(f"{API}/logs/2026-06-05").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(RuntimeError, match="Logbook unavailable"):
        await read_entries(client, date="2026-06-05")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_read_entries.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_entries'`

- [ ] **Step 3: Implement read_entries**

Append to `src/logbook_mcp/tools.py`:

```python
async def read_entries(
    client: LogbookClient,
    date: str | None = None,
    fallback_tz: str = "America/Vancouver",
    now: datetime | None = None,
) -> dict:
    """Read a day's log entries (default: today in vessel-local time).

    The default date resolves via the current GPS fix → timezone; if there is
    no fix, ``fallback_tz`` decides what "today" means.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if date is None:
        fix = await client.get_position()
        tz = _entry_timezone(fix, fallback_tz)
        date = now.astimezone(tz).date().isoformat()

    try:
        raw = await client.get_entries(date)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise RuntimeError(
            f"Logbook unavailable: cannot reach SignalK at {client.base_url}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        auth = _auth_error(exc, client.base_url)
        if auth:
            raise auth from exc
        raise RuntimeError(
            f"Logbook read failed (HTTP {exc.response.status_code})"
        ) from exc

    raw.sort(key=lambda e: e["datetime"])
    entries = []
    for n, e in enumerate(raw, start=1):
        pos = e.get("position") or None
        pos_out = (
            {"longitude": pos["longitude"], "latitude": pos["latitude"]}
            if pos and pos.get("latitude") is not None
            else None
        )
        entries.append(
            {
                "id": e["datetime"],
                "entry_display": f"Entry {n}",
                "time_display": _time_display(e["datetime"], pos_out, fallback_tz),
                "text": e.get("text", ""),
                "category": e.get("category", "navigation"),
                "author": e.get("author"),
                "position": pos_out,
                "position_display": _format_position(
                    pos_out["latitude"] if pos_out else None,
                    pos_out["longitude"] if pos_out else None,
                ),
            }
        )
    return {"date": date, "count": len(entries), "entries": entries}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_read_entries.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/logbook_mcp/tools.py tests/test_read_entries.py
git commit -m "feat: read_entries — day reads with vessel-local default date"
```

---

### Task 6: Rewire server.py, delete db.py

**Files:**
- Rewrite: `src/logbook_mcp/server.py`
- Delete: `src/logbook_mcp/db.py`
- Rewrite: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

The existing tests use `create_connected_server_and_client_session` from
`mcp.shared.memory` for real in-memory MCP round trips — keep that pattern.
Replace the entire contents of `tests/test_server.py`:

```python
import json

import pytest
import respx
from mcp.shared.memory import create_connected_server_and_client_session

from logbook_mcp.client import LogbookClient
from logbook_mcp.server import build_server

BASE = "http://test-sk:3000"
API = f"{BASE}/plugins/signalk-logbook"

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


async def test_list_tools_exposes_both_tools(lb_client):
    server = build_server(lb_client)
    assert server.name == "logbook-mcp"
    async with create_connected_server_and_client_session(server) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools.tools} == {"mark_moment", "read_entries"}


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
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[CREATED])
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
    import httpx
    respx.post(f"{API}/logs").mock(side_effect=httpx.ConnectError("boom"))
    server = build_server(lb_client)
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("mark_moment", {"text": "x"})
        assert result.isError
        assert "NOT recorded" in result.content[0].text
```

Note: `test_build_server_handles_bare_filename_db_path` from the old file is
deleted with the SQLite store — there is no DB path anymore.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL — `build_server` does not accept `client=`

- [ ] **Step 3: Rewrite server.py**

Replace the entire contents of `src/logbook_mcp/server.py`:

```python
"""Logbook MCP server — thin surface over signalk-logbook on the Pi."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from logbook_mcp.client import LogbookClient
from logbook_mcp.tools import mark_moment, read_entries


def _env_config() -> tuple[str, str | None, str]:
    url = os.environ.get("LOGBOOK_SK_URL", "http://naturalaspi.local:3000")
    token = os.environ.get("LOGBOOK_SK_TOKEN")
    tz = os.environ.get("LOGBOOK_TZ", "America/Vancouver")
    return url, token, tz


def build_server(client: LogbookClient, fallback_tz: str = "America/Vancouver") -> Server:
    server = Server("logbook-mcp")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="mark_moment",
                description=(
                    "Record a moment in the ship's log. Position, speed, wind, "
                    "and barometer are captured automatically from the vessel's "
                    "sensors; pass position only to override the GPS fix."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "text": {"type": "string", "minLength": 1},
                        "position": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "longitude": {
                                    "type": "number",
                                    "minimum": -180,
                                    "maximum": 180,
                                },
                                "latitude": {
                                    "type": "number",
                                    "minimum": -90,
                                    "maximum": 90,
                                },
                            },
                            "required": ["longitude", "latitude"],
                        },
                    },
                    "required": ["text"],
                },
            ),
            types.Tool(
                name="read_entries",
                description=(
                    "Read the ship's log entries for a day "
                    "(default: today, vessel-local)."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "date": {
                            "type": "string",
                            "pattern": r"^\d{4}-\d{2}-\d{2}$",
                        },
                    },
                },
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, args: dict[str, Any]) -> list[types.TextContent]:
        if name == "mark_moment":
            result = await mark_moment(
                client,
                text=args["text"],
                position=args.get("position"),
                fallback_tz=fallback_tz,
            )
        elif name == "read_entries":
            result = await read_entries(
                client, date=args.get("date"), fallback_tz=fallback_tz
            )
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


def main() -> None:
    url, token, tz = _env_config()
    client = LogbookClient(url, token=token)
    server = build_server(client, fallback_tz=tz)

    async def _run() -> None:
        try:
            async with stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )
        finally:
            await client.aclose()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Delete db.py and stale pycache**

```bash
git rm src/logbook_mcp/db.py
rm -rf src/logbook_mcp/__pycache__ tests/__pycache__
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: everything passes **except** `tests/test_e2e.py` (still imports
`LogbookDB`; replaced in Task 7). If only test_e2e fails, proceed.

- [ ] **Step 6: Commit**

```bash
git add -A src/logbook_mcp tests/test_server.py
git commit -m "feat: rewire server to LogbookClient env config; drop SQLite store"
```

---

### Task 7: Replace e2e test with env-gated Pi integration test

**Files:**
- Rewrite: `tests/test_e2e.py` → delete, create `tests/test_integration_pi.py`

- [ ] **Step 1: Replace the file**

```bash
git rm tests/test_e2e.py
```

Create `tests/test_integration_pi.py`:

```python
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
```

- [ ] **Step 2: Verify gating works (offline)**

Run: `uv run pytest tests/test_integration_pi.py -v`
Expected: 1 skipped (no LOGBOOK_INTEGRATION set). Then run the full suite:

Run: `uv run pytest -v`
Expected: all pass, 1 skipped.

- [ ] **Step 3: Commit**

```bash
git add -A tests
git commit -m "test: env-gated Pi integration test replaces SQLite e2e"
```

---

### Task 8: Rewrite README.md, SPEC.md, CHANGELOG.md

**Files:**
- Modify: `README.md`, `SPEC.md`, `CHANGELOG.md`

- [ ] **Step 1: Rewrite README.md**

Keep it the marketing/quickstart view. New content must state: logbook-mcp is
a thin MCP over `meri-imperiumi/signalk-logbook`; the ship's log lives on the
SignalK server as per-day YAML; tools are `mark_moment` and `read_entries`;
configuration is:

```bash
export LOGBOOK_SK_URL=http://naturalaspi.local:3000   # SignalK server root
export LOGBOOK_SK_TOKEN=...                            # SignalK access token (write)
export LOGBOOK_TZ=America/Vancouver                    # fallback timezone
logbook-mcp
```

Note the backend requirement: "Requires signalk-logbook installed and enabled
on the SignalK server." Keep the roadmap section: sea-time derivation +
USCG/TC exports now derive from signalk-logbook entries (link the spec).
Remove all SQLite/`LOGBOOK_DB_PATH` references.

- [ ] **Step 2: Rewrite SPEC.md**

SPEC.md remains the source of truth for tool shapes. Replace the Phase 0
section with the REST-backed contracts (copy the exact response shapes from
the design spec `docs/superpowers/specs/2026-06-05-adopt-signalk-logbook-design.md`
— `mark_moment` response with string `id`, ordinal `entry_display`, new
`time_display`; `read_entries` response with `date`/`count`/`entries`).
Replace the Phase 0.5 `sea_days`/`summaries` SQL schema section with the
derive-from-entries approach (the design spec's "Sea-time layer" section is
the text to adapt). Keep the error conventions, drop the SQLite conventions.
Update the versioning policy: `0.2.0` = REST backend over signalk-logbook.

- [ ] **Step 3: Add CHANGELOG entry**

Prepend to `CHANGELOG.md`:

```markdown
## 0.2.0 — 2026-06-05

**Breaking: SQLite store replaced by signalk-logbook.** logbook-mcp is now a
stateless MCP over the signalk-logbook plugin's REST API on the SignalK
server. The ship's log lives on the boat as per-day YAML.

- `mark_moment`: entries are auto-enriched server-side (position, speed,
  wind, barometer); `position` param now only overrides the GPS fix.
  Response: `id` is now the entry's datetime key (string), `entry_display`
  is the entry's ordinal within its day, and new `time_display` carries
  vessel-local HH:MM.
- New tool: `read_entries(date?)` — read a day's log (default today,
  vessel-local).
- Config: `LOGBOOK_SK_URL` / `LOGBOOK_SK_TOKEN` / `LOGBOOK_TZ` replace
  `LOGBOOK_DB_PATH`.
- Roadmap change: sea-time (USCG/TC) exports will derive from
  signalk-logbook entries; the planned `sea_days` store is dropped.
```

- [ ] **Step 4: Commit**

```bash
git add README.md SPEC.md CHANGELOG.md
git commit -m "docs: rewrite README/SPEC/CHANGELOG for signalk-logbook backend"
git push
```

---

### Task 9: Pi ops — install signalk-logbook, provision token

**This task touches the Pi and has manual checkpoints. Do not skip the volume
check — entries written into an unpersisted container layer are lost on
recreate.**

**Files:**
- Modify: `~/src/sailingnaturali/infrastructure/pi5-signalk/` (notes/docs — follow that repo's existing doc conventions)

- [ ] **Step 1: Confirm SignalK is up and volume-backed**

```bash
ssh naturalaspi docker ps --format '{{.Names}} {{.Status}}'
ssh naturalaspi docker inspect signalk --format '{{json .Mounts}}'
```

Expected: `signalk` container Up; Mounts include a bind/volume covering the
SignalK config dir (the path that contains `plugin-config-data`, typically
`/home/node/.signalk`). **If `plugin-config-data` is not under a persisted
mount, stop and fix the compose file first** (add the volume in
`infrastructure/pi5-signalk/` and recreate the container).

- [ ] **Step 2: Install the plugin**

Preferred: SignalK Admin UI → Appstore → search "signalk-logbook" → install →
restart server. CLI alternative (adjust the .signalk path to the mount found
in Step 1):

```bash
ssh naturalaspi 'docker exec signalk sh -c "cd /home/node/.signalk && npm install signalk-logbook"'
ssh naturalaspi docker restart signalk
```

Verify: `curl -s http://naturalaspi.local:3000/plugins/signalk-logbook/logs`
Expected: `[]` (or a JSON array), possibly 401 if reads require auth — either
proves the routes are mounted. A 404 means the plugin isn't enabled yet:
enable it in Admin UI → Server → Plugin Config → Logbook.

- [ ] **Step 3 (MANUAL — Bryan): provision a write token**

In the SignalK Admin UI on `naturalaspi.local:3000`: Security → create an
access token (or approve a device access request) with **read/write**
permission for the agent. Add it to `~/.hermes/.env`:

```
LOGBOOK_SK_TOKEN=<token>
```

- [ ] **Step 4: Verify auth scheme**

```bash
TOKEN=$(grep LOGBOOK_SK_TOKEN ~/.hermes/.env | cut -d= -f2)
curl -s -o /dev/null -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"token smoke test"}' \
  http://naturalaspi.local:3000/plugins/signalk-logbook/logs
```

Expected: `201`. If `401`, retry with `-H "Authorization: JWT $TOKEN"`; if JWT
works, change the header construction in `src/logbook_mcp/client.py`
(`Bearer` → `JWT`), update `tests/test_client.py::test_get_entries_sends_bearer_token`
to match, re-run the suite, and commit.

- [ ] **Step 5: Document in infrastructure repo and commit there**

Record in `infrastructure/pi5-signalk/` notes: plugin installed, volume
verified, token provisioning steps, auth scheme that worked. Commit + push
(infrastructure repo, this machine's policy allows it).

---

### Task 10: Run the integration test against the Pi

- [ ] **Step 1: Run it**

```bash
cd ~/src/sailingnaturali/logbook-mcp
LOGBOOK_INTEGRATION=1 \
LOGBOOK_SK_TOKEN=$(grep LOGBOOK_SK_TOKEN ~/.hermes/.env | cut -d= -f2) \
uv run pytest tests/test_integration_pi.py -v
```

Expected: 1 passed. The entry's position will be the mocked Boundary Pass fix
(~48.76N) — that is correct for Phase 0.

- [ ] **Step 2: Eyeball the SignalK UI (MANUAL — optional but recommended)**

Open `http://naturalaspi.local:3000` → Logbook webapp. The
`integration-test …` entry should be visible with position/conditions filled.

---

### Task 11: Update naturali-agents (prompt + SPEC)

**Files:**
- Modify: `~/src/sailingnaturali/naturali-agents/prompts/navigator.md:20`
- Modify: `~/src/sailingnaturali/naturali-agents/SPEC.md:15` and the "Tool surface — logbook-mcp" section (around line 119)

- [ ] **Step 1: Replace navigator.md line 20**

Old:

```
- `mcp_logbook_mark_moment(text, position)` — record a moment in the logbook; when confirming, respond ONLY with: "Logged. [entry_display]. [display from get_local_time]. [position_display]." — use these fields verbatim, no other formatting
```

New (two lines):

```
- `mcp_logbook_mark_moment(text)` — record a moment in the ship's log; position, wind, and conditions are captured automatically from the vessel's sensors. When confirming, respond ONLY with: "Logged. [entry_display]. [time_display]. [position_display]." — use these fields verbatim, no other formatting
- `mcp_logbook_read_entries(date?)` — read the day's log entries (default today); for "what did we log today?" — quote entry text with each entry's time_display, never UTC
```

- [ ] **Step 2: Update naturali-agents SPEC.md**

Line 15 diagram: change `logbook-mcp ──▶ sqlite` to
`logbook-mcp ──▶ signalk-logbook (Pi)`.

Replace the "Tool surface — logbook-mcp" bullet (line ~123) with:

```
- `mcp_logbook_mark_moment(text: str, position?: {latitude, longitude})` — append an entry via signalk-logbook on the Pi; the plugin snapshots position/speed/wind/barometer from live SignalK. Returns `{ id, entry_display, timestamp, time_display, position, position_display }`. `time_display` is vessel-local; stored timestamps are UTC. `position` only overrides the GPS fix.
- `mcp_logbook_read_entries(date?: YYYY-MM-DD)` — a day's entries (default today, vessel-local). Returns `{ date, count, entries[] }`.
```

- [ ] **Step 3: Commit + push naturali-agents**

```bash
cd ~/src/sailingnaturali/naturali-agents
git add prompts/navigator.md SPEC.md
git commit -m "feat: logbook tools now backed by signalk-logbook; self-contained mark_moment confirmation"
git push
```

---

### Task 12: Hermes config swap + archive old SQLite

**Files:**
- Modify: `~/.hermes/config.yaml` (machine-local, NOT in git) — the `logbook:` block around line 641

- [ ] **Step 1: Edit the logbook MCP server env block**

In `~/.hermes/config.yaml`, in the `logbook:` server block: remove
`LOGBOOK_DB_PATH` and add:

```yaml
      LOGBOOK_SK_URL: http://naturalaspi.local:3000
      LOGBOOK_SK_TOKEN: ${LOGBOOK_SK_TOKEN}   # if hermes interpolates from .env; otherwise paste, matching how other secrets in this file are handled
      LOGBOOK_TZ: America/Vancouver
```

**Match the existing secret-handling convention in the file** — look at how
the weather/stormglass keys are passed before choosing interpolation vs
literal.

- [ ] **Step 2: Archive the SQLite file**

```bash
mv ~/.naturali/logbook.db ~/.naturali/logbook.db.pre-signalk-archive
```

- [ ] **Step 3 (MANUAL — Bryan): restart Hermes and voice-test**

Restart the Hermes agent, then say: "log this moment: testing the new
logbook". Expected spoken reply, exactly the contract shape:
"Logged. Entry N. HH:MM. 48.8 North, 123.1 West." Then: "what did we log
today?" should quote the entry back.

---

### Task 13: Final verification sweep

- [ ] **Step 1: Full local suite**

```bash
cd ~/src/sailingnaturali/logbook-mcp && uv run pytest -v
```

Expected: all pass, integration test skipped (or run it gated again).

- [ ] **Step 2: Check nothing references the dead store**

```bash
grep -rn "LOGBOOK_DB_PATH\|LogbookDB\|sqlite" --include="*.py" --include="*.md" \
  ~/src/sailingnaturali/logbook-mcp ~/src/sailingnaturali/naturali-agents | grep -v archive | grep -v plans/ | grep -v specs/
```

Expected: no hits outside historical docs (plans/specs/CHANGELOG).

- [ ] **Step 3: Push everything**

```bash
cd ~/src/sailingnaturali/logbook-mcp && git push
```

PyPI release of 0.2.0 is **out of scope** — Hermes runs logbook-mcp from the
local checkout (see `~/.hermes/config.yaml` args). Flag to Bryan that a
`uv publish` is available when he wants the public package updated.
