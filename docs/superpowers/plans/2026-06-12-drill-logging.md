# Drill Logging (logbook-mcp) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** logbook-mcp v0.4.0 — `log_drill` and `list_drills` tools plus a `category` parameter on `mark_moment`, so safety drills land in the ship's log as structured, machine-findable entries.

**Architecture:** Drill structure rides in the entry text as a leading bracket tag (`[drill:mob outcome=pass duration=14m crew=Bryan,K] prose…`) with `category: "drill"` on the entry. Composing/parsing lives in a new `drills.py` module; `log_drill` delegates to `mark_moment` for all write/confirm plumbing; `list_drills` walks the plugin's day index. The agent-side cadence layer (naturali-agents) and the upstream enum PR are separate follow-on plans.

**Tech Stack:** Python 3.12, mcp SDK, httpx, respx for HTTP-mocked tests, pytest(-asyncio), uv.

**Spec:** `docs/superpowers/specs/2026-06-12-drill-logging-design.md`

**Conventions:** Run everything from the repo root `/Users/clarkbw/src/sailingnaturali/logbook-mcp`. Test command is `uv run pytest <file>::<test> -v`. Commit after every green test, terse conventional-commit messages.

---

### Task 1: `post_entry` accepts a category

**Files:**
- Modify: `src/logbook_mcp/client.py` (the `post_entry` method, ~line 54)
- Test: `tests/test_client.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_client.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -k category -v`
Expected: FAIL — `TypeError: post_entry() got an unexpected keyword argument 'category'`

- [ ] **Step 3: Implement** — in `src/logbook_mcp/client.py`, change `post_entry`:

```python
    async def post_entry(self, text: str, category: str | None = None) -> None:
        """Create an entry; the plugin enriches it server-side from live SignalK.

        ``ago: 0`` is always included — the plugin calls ``buffer.get(req.body.ago)``
        whenever its state buffer is non-empty, and omitting the field causes an
        HTTP 500 once the buffer has been populated.

        ``category`` is sent only when given; the plugin defaults to
        "navigation". The plugin copies it unvalidated, so values outside its
        schema enum (e.g. "drill") write fine — validation is our job.

        POST returns a bare 201 with no body — callers re-fetch the day to see
        the created entry.
        """
        body: dict = {"text": text, "ago": 0}
        if category is not None:
            body["category"] = category
        resp = await self._http.post(f"{self._api}/logs", json=body)
        resp.raise_for_status()
```

(Keep the existing docstring sentences; only the `category` paragraph and the body construction change.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v`
Expected: all PASS (including the pre-existing `test_post_entry_sends_text_json`).

- [ ] **Step 5: Commit**

```bash
git add tests/test_client.py src/logbook_mcp/client.py
git commit -m "feat: post_entry accepts optional category"
```

---

### Task 2: `get_dates` — the plugin's day index

**Files:**
- Modify: `src/logbook_mcp/client.py` (new method after `get_entries`)
- Test: `tests/test_client.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_client.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -k get_dates -v`
Expected: FAIL — `AttributeError: 'LogbookClient' object has no attribute 'get_dates'`

- [ ] **Step 3: Implement** — in `src/logbook_mcp/client.py`, add after `get_entries`:

```python
    async def get_dates(self) -> list[str]:
        """All YYYY-MM-DD days that have a log file. 404 -> no logs yet -> []."""
        resp = await self._http.get(f"{self._api}/logs")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_client.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_client.py src/logbook_mcp/client.py
git commit -m "feat: get_dates exposes the plugin day index"
```

---

### Task 3: drill tag composer (`drills.py`)

**Files:**
- Create: `src/logbook_mcp/drills.py`
- Create: `tests/test_drills.py`

- [ ] **Step 1: Write the failing tests** — create `tests/test_drills.py`:

```python
import pytest

from logbook_mcp.drills import compose_drill_text


def test_compose_full_tag():
    text = compose_drill_text(
        "mob", "pass",
        duration_minutes=14,
        participants=["Bryan", "K"],
        notes="Lifesling recovery under power, contact in 4 min.",
    )
    assert text == (
        "[drill:mob outcome=pass duration=14m crew=Bryan,K] "
        "Lifesling recovery under power, contact in 4 min."
    )


def test_compose_minimal_tag_no_optionals():
    assert compose_drill_text("fire", "partial") == "[drill:fire outcome=partial]"


def test_compose_normalizes_participant_whitespace_to_hyphens():
    text = compose_drill_text("mob", "pass", participants=["Bryan Clark", " K  Lee "])
    assert text == "[drill:mob outcome=pass crew=Bryan-Clark,K-Lee]"


def test_compose_rejects_comma_in_participant():
    with pytest.raises(ValueError, match="comma"):
        compose_drill_text("mob", "pass", participants=["Clark, Bryan"])


def test_compose_rejects_bad_drill_type():
    for bad in ("MOB", "man overboard", "", "x" * 33, "mob!"):
        with pytest.raises(ValueError, match="drill_type"):
            compose_drill_text(bad, "pass")


def test_compose_rejects_bad_outcome():
    with pytest.raises(ValueError, match="outcome"):
        compose_drill_text("mob", "aced-it")


def test_compose_rejects_nonpositive_duration():
    with pytest.raises(ValueError, match="duration"):
        compose_drill_text("mob", "pass", duration_minutes=0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_drills.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'logbook_mcp.drills'`

- [ ] **Step 3: Implement** — create `src/logbook_mcp/drills.py`:

```python
"""Drill entry tag: compose and parse.

Drill structure rides in the entry text as a leading bracket tag —
``[drill:mob outcome=pass duration=14m crew=Bryan,K] prose…`` — because the
signalk-logbook plugin only persists text/category/position. This module is
the single place that knows the tag syntax; spec in
docs/superpowers/specs/2026-06-12-drill-logging-design.md.
"""

from __future__ import annotations

import re

VALID_OUTCOMES = ("pass", "partial", "fail")

_DRILL_TYPE_RE = re.compile(r"^[a-z0-9-]{1,32}$")


def _normalize_participant(name: str) -> str:
    """Tag fields split on whitespace and crew splits on commas, so names
    may contain neither: internal whitespace becomes hyphens, commas are an
    error."""
    name = name.strip()
    if not name:
        raise ValueError("participant name is empty")
    if "," in name:
        raise ValueError(f"participant name may not contain a comma: {name!r}")
    return re.sub(r"\s+", "-", name)


def compose_drill_text(
    drill_type: str,
    outcome: str,
    duration_minutes: int | None = None,
    participants: list[str] | None = None,
    notes: str | None = None,
) -> str:
    """Build the drill entry text: bracket tag, then optional prose."""
    if not _DRILL_TYPE_RE.match(drill_type or ""):
        raise ValueError(
            f"invalid drill_type {drill_type!r}: want lowercase [a-z0-9-], 1-32 chars"
        )
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"invalid outcome {outcome!r}: want one of {VALID_OUTCOMES}")
    fields = [f"outcome={outcome}"]
    if duration_minutes is not None:
        if int(duration_minutes) < 1:
            raise ValueError(f"invalid duration_minutes {duration_minutes!r}: want >= 1")
        fields.append(f"duration={int(duration_minutes)}m")
    if participants:
        fields.append("crew=" + ",".join(_normalize_participant(p) for p in participants))
    tag = f"[drill:{drill_type} {' '.join(fields)}]"
    if notes and notes.strip():
        return f"{tag} {notes.strip()}"
    return tag


def is_valid_drill_type(drill_type: str) -> bool:
    """Shared by list_drills' filter validation."""
    return bool(_DRILL_TYPE_RE.match(drill_type or ""))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_drills.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_drills.py src/logbook_mcp/drills.py
git commit -m "feat: drill tag composer"
```

---

### Task 4: drill tag parser

**Files:**
- Modify: `src/logbook_mcp/drills.py`
- Test: `tests/test_drills.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_drills.py`:

```python
from logbook_mcp.drills import parse_drill_tag


def test_parse_full_tag():
    parsed = parse_drill_tag(
        "[drill:mob outcome=pass duration=14m crew=Bryan,K] "
        "Lifesling recovery under power."
    )
    assert parsed == {
        "drill_type": "mob",
        "outcome": "pass",
        "duration_minutes": 14,
        "participants": ["Bryan", "K"],
        "notes": "Lifesling recovery under power.",
    }


def test_parse_minimal_tag():
    assert parse_drill_tag("[drill:fire outcome=partial]") == {
        "drill_type": "fire",
        "outcome": "partial",
        "duration_minutes": None,
        "participants": None,
        "notes": None,
    }


def test_compose_parse_round_trip():
    text = compose_drill_text(
        "steering-failure", "fail",
        duration_minutes=25,
        participants=["Bryan Clark"],
        notes="Emergency tiller jammed; needs rework [see maintenance log].",
    )
    parsed = parse_drill_tag(text)
    assert parsed == {
        "drill_type": "steering-failure",
        "outcome": "fail",
        "duration_minutes": 25,
        "participants": ["Bryan-Clark"],
        "notes": "Emergency tiller jammed; needs rework [see maintenance log].",
    }


def test_parse_ignores_unknown_fields():
    # Forward compatibility: a future writer may add fields we don't know.
    parsed = parse_drill_tag("[drill:mob outcome=pass wind=15kn] notes")
    assert parsed["outcome"] == "pass"
    assert parsed["notes"] == "notes"


def test_parse_non_drill_text_returns_none():
    for text in (
        "Beautiful sunset off Discovery Island",
        "",
        "[drill:] missing type",
        "[drill:MOB outcome=pass] uppercase type",
        "prose before [drill:mob outcome=pass] tag not at start",
    ):
        assert parse_drill_tag(text) is None


def test_parse_tolerates_malformed_field_values():
    # Bad field values degrade to None for that field; the tag still parses.
    parsed = parse_drill_tag("[drill:mob outcome=heroic duration=fast]")
    assert parsed["drill_type"] == "mob"
    assert parsed["outcome"] is None
    assert parsed["duration_minutes"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_drills.py -k parse -v`
Expected: FAIL — `ImportError: cannot import name 'parse_drill_tag'`

- [ ] **Step 3: Implement** — append to `src/logbook_mcp/drills.py`:

```python
_TAG_RE = re.compile(
    r"^\[drill:([a-z0-9-]{1,32})((?:\s+[a-z]+=[^\s\]]+)*)\]\s*(.*)$",
    re.DOTALL,
)

_DURATION_RE = re.compile(r"^\d+m$")


def parse_drill_tag(text: str) -> dict | None:
    """Parse a drill tag at the start of entry text.

    Returns ``{drill_type, outcome, duration_minutes, participants, notes}``
    or None when the text doesn't open with a well-formed tag. Unknown
    ``key=value`` fields are ignored; recognized fields with malformed values
    degrade to None rather than failing the whole tag.
    """
    m = _TAG_RE.match(text or "")
    if not m:
        return None
    drill_type, raw_fields, notes = m.group(1), m.group(2), m.group(3)
    parsed: dict = {
        "drill_type": drill_type,
        "outcome": None,
        "duration_minutes": None,
        "participants": None,
        "notes": notes.strip() or None,
    }
    for field in raw_fields.split():
        key, _, value = field.partition("=")
        if key == "outcome" and value in VALID_OUTCOMES:
            parsed["outcome"] = value
        elif key == "duration" and _DURATION_RE.match(value):
            parsed["duration_minutes"] = int(value[:-1])
        elif key == "crew" and value:
            parsed["participants"] = value.split(",")
    return parsed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_drills.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_drills.py src/logbook_mcp/drills.py
git commit -m "feat: drill tag parser"
```

---

### Task 5: `mark_moment` passes category through

**Files:**
- Modify: `src/logbook_mcp/tools.py` (`mark_moment`, ~line 107)
- Test: `tests/test_mark_moment.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_mark_moment.py`:

```python
@respx.mock
async def test_mark_moment_sends_category(client):
    post = respx.post(f"{API}/logs").respond(201)
    respx.get(f"{API}/logs/2026-06-05").respond(200, json=[CREATED])

    await mark_moment(client, text="Checked in with VTS", category="radio", now=NOW)

    assert json.loads(post.calls[0].request.content)["category"] == "radio"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mark_moment.py::test_mark_moment_sends_category -v`
Expected: FAIL — `TypeError: mark_moment() got an unexpected keyword argument 'category'`

- [ ] **Step 3: Implement** — in `src/logbook_mcp/tools.py`, change the `mark_moment` signature and the `post_entry` call:

```python
async def mark_moment(
    client: LogbookClient,
    text: str,
    position: dict | None = None,
    fallback_tz: str = FALLBACK_TZ,
    now: datetime | None = None,
    category: str | None = None,
) -> dict:
```

and inside, the write becomes:

```python
        await client.post_entry(text, category=category)
```

(Everything else in the function is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mark_moment.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_mark_moment.py src/logbook_mcp/tools.py
git commit -m "feat: mark_moment accepts optional category"
```

---

### Task 6: `log_drill` tool

**Files:**
- Modify: `src/logbook_mcp/tools.py` (new function after `mark_moment`)
- Create: `tests/test_log_drill.py`

- [ ] **Step 1: Write the failing tests** — create `tests/test_log_drill.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_log_drill.py -v`
Expected: FAIL — `ImportError: cannot import name 'log_drill'`

- [ ] **Step 3: Implement** — in `src/logbook_mcp/tools.py`: add to the imports near the top

```python
from logbook_mcp.drills import compose_drill_text, parse_drill_tag
```

then add after `mark_moment`:

```python
async def log_drill(
    client: LogbookClient,
    drill_type: str,
    outcome: str,
    duration_minutes: int | None = None,
    participants: list[str] | None = None,
    notes: str | None = None,
    position: dict | None = None,
    fallback_tz: str = FALLBACK_TZ,
    now: datetime | None = None,
) -> dict:
    """Record a safety drill in the ship's log.

    Validation and the tag format live in drills.py; the write/confirm
    plumbing is mark_moment's. Raises ValueError before any write when the
    drill fields are invalid.
    """
    text = compose_drill_text(
        drill_type, outcome,
        duration_minutes=duration_minutes,
        participants=participants,
        notes=notes,
    )
    result = await mark_moment(
        client, text=text, position=position,
        fallback_tz=fallback_tz, now=now, category="drill",
    )
    # Echo normalized fields from the composed text (the round-trip-tested
    # source of truth), not the raw inputs.
    parsed = parse_drill_tag(text) or {}
    spoken_type = drill_type.replace("-", " ")
    confirmation = (
        f"Logged {spoken_type} drill, {outcome}. "
        f"{result['entry_display']}. {result['time_display']}."
    )
    return {
        **result,
        "confirmation": confirmation,
        "drill_type": drill_type,
        "outcome": outcome,
        "duration_minutes": parsed.get("duration_minutes"),
        "participants": parsed.get("participants"),
        "notes": parsed.get("notes"),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_log_drill.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_log_drill.py src/logbook_mcp/tools.py
git commit -m "feat: log_drill tool"
```

---

### Task 7: `list_drills` tool

**Files:**
- Modify: `src/logbook_mcp/tools.py` (new function after `read_entries`)
- Create: `tests/test_list_drills.py`

- [ ] **Step 1: Write the failing tests** — create `tests/test_list_drills.py`:

```python
from datetime import datetime, timezone

import pytest
import respx

from logbook_mcp.client import LogbookClient
from logbook_mcp.tools import list_drills

BASE = "http://test-sk:3000"
API = f"{BASE}/plugins/signalk-logbook"

NOW = datetime(2026, 6, 12, 20, 30, 0, tzinfo=timezone.utc)

MOB_MAY = {
    "datetime": "2026-05-10T18:00:00.000Z",
    "text": "[drill:mob outcome=partial duration=20m] Slow first pass.",
    "category": "drill",
    "author": "naturali",
}
NAV_MAY = {
    "datetime": "2026-05-10T19:00:00.000Z",
    "text": "Anchored in Bedwell Harbour",
    "category": "navigation",
    "author": "naturali",
}
MOB_JUNE = {
    "datetime": "2026-06-12T20:14:00.000Z",
    "text": "[drill:mob outcome=pass duration=14m crew=Bryan,K] Clean recovery.",
    "category": "drill",
    "author": "naturali",
    "position": {"latitude": 48.76, "longitude": -123.05, "source": "GPS"},
}
FIRE_JUNE_UNTAGGED = {
    # category=drill but freehand text (e.g. typed in the plugin UI):
    # still listed, fields None.
    "datetime": "2026-06-01T17:00:00.000Z",
    "text": "Fire drill at the dock, extinguisher walk-through",
    "category": "drill",
    "author": "naturali",
}


@pytest.fixture
async def client():
    c = LogbookClient(BASE, token="test-token")
    yield c
    await c.aclose()


def _mock_days():
    respx.get(f"{API}/logs").respond(
        200, json=["2025-09-01", "2026-05-10", "2026-06-01", "2026-06-12"]
    )
    respx.get(f"{API}/logs/2026-05-10").respond(200, json=[MOB_MAY, NAV_MAY])
    respx.get(f"{API}/logs/2026-06-01").respond(200, json=[FIRE_JUNE_UNTAGGED])
    respx.get(f"{API}/logs/2026-06-12").respond(200, json=[MOB_JUNE])


@respx.mock
async def test_list_drills_default_window_and_latest_by_type(client):
    _mock_days()
    result = await list_drills(client, now=NOW)

    # 2025-09-01 is outside the 180-day default window — never fetched.
    assert result["since"] == "2025-12-14"
    assert result["until"] == "2026-06-12"
    assert result["count"] == 3
    assert [d["id"] for d in result["drills"]] == [
        "2026-05-10T18:00:00.000Z",
        "2026-06-01T17:00:00.000Z",
        "2026-06-12T20:14:00.000Z",
    ]

    june_mob = result["drills"][2]
    assert june_mob["drill_type"] == "mob"
    assert june_mob["outcome"] == "pass"
    assert june_mob["duration_minutes"] == 14
    assert june_mob["participants"] == ["Bryan", "K"]
    assert june_mob["notes"] == "Clean recovery."
    assert june_mob["position"] == {"longitude": -123.05, "latitude": 48.76}

    untagged = result["drills"][1]
    assert untagged["drill_type"] is None
    assert untagged["notes"] == "Fire drill at the dock, extinguisher walk-through"

    # latest per type; untagged entries can't contribute a type
    assert result["latest_by_type"] == {"mob": "2026-06-12"}


@respx.mock
async def test_list_drills_filters_by_type_and_range(client):
    _mock_days()
    result = await list_drills(
        client, drill_type="mob", since="2026-05-01", until="2026-05-31", now=NOW
    )
    assert result["count"] == 1
    assert result["drills"][0]["id"] == "2026-05-10T18:00:00.000Z"
    assert result["latest_by_type"] == {"mob": "2026-05-10"}


async def test_list_drills_rejects_bad_inputs(client):
    with pytest.raises(ValueError, match="drill_type"):
        await list_drills(client, drill_type="MOB!", now=NOW)
    with pytest.raises(ValueError, match="invalid date"):
        await list_drills(client, since="last month", now=NOW)


@respx.mock
async def test_list_drills_unreachable_surfaces_runtime_error(client):
    import httpx
    respx.get(f"{API}/logs").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(RuntimeError, match="Logbook unavailable"):
        await list_drills(client, now=NOW)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_list_drills.py -v`
Expected: FAIL — `ImportError: cannot import name 'list_drills'`

- [ ] **Step 3: Implement** — in `src/logbook_mcp/tools.py`: extend the drills import (added in Task 6) to

```python
from logbook_mcp.drills import compose_drill_text, is_valid_drill_type, parse_drill_tag
```

Then add after `read_entries`:

```python
async def list_drills(
    client: LogbookClient,
    drill_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    fallback_tz: str = FALLBACK_TZ,
    now: datetime | None = None,
) -> dict:
    """Drill entries in a date window (default: the last 180 days).

    Walks the plugin's UTC day index — window bounds are UTC day-file dates,
    matching how entries are stored. An entry counts as a drill when its
    category is "drill" or its text opens with a [drill:…] tag; tagged fields
    are parsed, untagged drill-category entries are listed with None fields
    (they can't contribute to latest_by_type).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if until is None:
        until = now.date().isoformat()
    else:
        validate_date(until)
    if since is None:
        since = (date_cls.fromisoformat(until) - timedelta(days=180)).isoformat()
    else:
        validate_date(since)
    if drill_type is not None and not is_valid_drill_type(drill_type):
        raise ValueError(
            f"invalid drill_type {drill_type!r}: want lowercase [a-z0-9-], 1-32 chars"
        )

    try:
        days = [d for d in await client.get_dates() if since <= d <= until]
        rows: list[dict] = []
        for day in sorted(days):
            for e in await client.get_entries(day):
                parsed = parse_drill_tag(e.get("text", ""))
                if e.get("category") != "drill" and parsed is None:
                    continue
                if not e.get("datetime"):
                    continue  # undateable — useless for cadence; skip
                if drill_type is not None and (
                    parsed is None or parsed["drill_type"] != drill_type
                ):
                    continue
                pos = e.get("position") or None
                # A partial fix (only one of lat/lon present) counts as no fix.
                pos_out = (
                    {"longitude": pos["longitude"], "latitude": pos["latitude"]}
                    if pos and pos.get("latitude") is not None
                    else None
                )
                rows.append(
                    {
                        "id": e["datetime"],
                        "date": e["datetime"][:10],
                        "time_display": _time_display(
                            e["datetime"], pos_out, fallback_tz
                        ),
                        "drill_type": parsed["drill_type"] if parsed else None,
                        "outcome": parsed["outcome"] if parsed else None,
                        "duration_minutes": (
                            parsed["duration_minutes"] if parsed else None
                        ),
                        "participants": parsed["participants"] if parsed else None,
                        "notes": (
                            parsed["notes"] if parsed else e.get("text") or None
                        ),
                        "position": pos_out,
                        "position_display": _format_position(
                            pos_out["latitude"] if pos_out else None,
                            pos_out["longitude"] if pos_out else None,
                        ),
                    }
                )
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

    rows.sort(key=lambda r: r["id"])
    latest_by_type: dict[str, str] = {}
    for r in rows:
        if r["drill_type"]:
            latest_by_type[r["drill_type"]] = r["date"]
    return {
        "since": since,
        "until": until,
        "count": len(rows),
        "drills": rows,
        "latest_by_type": latest_by_type,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_list_drills.py tests/test_drills.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_list_drills.py src/logbook_mcp/tools.py src/logbook_mcp/drills.py
git commit -m "feat: list_drills tool with latest_by_type summary"
```

---

### Task 8: register the tools on the MCP server

**Files:**
- Modify: `src/logbook_mcp/server.py` (`_list_tools` and `_call_tool` in `build_server`)
- Test: `tests/test_server.py`

- [ ] **Step 1: Update the existing tool-set test and add round trips** — `tests/test_server.py` uses `create_connected_server_and_client_session` from `mcp.shared.memory` and an `lb_client` fixture; the existing `test_list_tools_exposes_both_tools` asserts the tool-name set **with equality**, so it must grow the new names. Change it to:

```python
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
```

Then append (the drill day is mocked and the window passed explicitly — `list_drills`' default window uses the wall clock, and tests must not depend on when they run):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server.py -v`
Expected: FAIL — `test_list_tools_exposes_all_tools` on the tool-name set mismatch; the round trips with `Unknown tool: log_drill`

- [ ] **Step 3: Implement** — in `src/logbook_mcp/server.py`:

Add the import:

```python
from logbook_mcp.tools import FALLBACK_TZ, list_drills, log_drill, mark_moment, read_entries
```

In `_list_tools`, add to `mark_moment`'s `inputSchema["properties"]`:

```python
                        "category": {
                            "type": "string",
                            "enum": [
                                "navigation",
                                "engine",
                                "radio",
                                "maintenance",
                                "drill",
                            ],
                        },
```

and append two tools to the returned list (reuse the exact `position` sub-schema already present on `mark_moment`):

```python
            types.Tool(
                name="log_drill",
                description=(
                    "Record a safety drill in the ship's log (MOB, fire, "
                    "abandon-ship, steering-failure, flooding, radio, "
                    "alert-chain, …). Position and conditions are captured "
                    "automatically; pass position only to override the GPS fix."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "drill_type": {
                            "type": "string",
                            "pattern": "^[a-z0-9-]{1,32}$",
                        },
                        "outcome": {
                            "type": "string",
                            "enum": ["pass", "partial", "fail"],
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1440,
                        },
                        "participants": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 1,
                        },
                        "notes": {"type": "string"},
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
                    "required": ["drill_type", "outcome"],
                },
            ),
            types.Tool(
                name="list_drills",
                description=(
                    "List safety drills from the ship's log (default: last "
                    "180 days), with a latest_by_type summary for cadence "
                    "checks."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "drill_type": {
                            "type": "string",
                            "pattern": "^[a-z0-9-]{1,32}$",
                        },
                        "since": {
                            "type": "string",
                            "pattern": r"^\d{4}-\d{2}-\d{2}$",
                        },
                        "until": {
                            "type": "string",
                            "pattern": r"^\d{4}-\d{2}-\d{2}$",
                        },
                    },
                },
            ),
```

In `_call_tool`, pass the new arg through `mark_moment` and add the two branches before the final `else`:

```python
        if name == "mark_moment":
            result = await mark_moment(
                client,
                text=args["text"],
                position=args.get("position"),
                fallback_tz=fallback_tz,
                category=args.get("category"),
            )
        elif name == "log_drill":
            result = await log_drill(
                client,
                drill_type=args["drill_type"],
                outcome=args["outcome"],
                duration_minutes=args.get("duration_minutes"),
                participants=args.get("participants"),
                notes=args.get("notes"),
                position=args.get("position"),
                fallback_tz=fallback_tz,
            )
        elif name == "list_drills":
            result = await list_drills(
                client,
                drill_type=args.get("drill_type"),
                since=args.get("since"),
                until=args.get("until"),
                fallback_tz=fallback_tz,
            )
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q --ignore=tests/test_integration_pi.py`
Expected: all PASS (the Pi integration file is the opt-in live smoke test; skip per its own convention if it self-skips, ignore otherwise)

- [ ] **Step 5: Commit**

```bash
git add tests/test_server.py src/logbook_mcp/server.py
git commit -m "feat: register log_drill + list_drills; expose mark_moment category"
```

---

### Task 9: docs and version bump

**Files:**
- Modify: `pyproject.toml` (version), `CHANGELOG.md`, `SPEC.md`, `README.md`

- [ ] **Step 1: Bump version** — in `pyproject.toml`: `version = "0.4.0"`.

- [ ] **Step 2: CHANGELOG** — prepend an entry following the file's existing format:

```markdown
## 0.4.0 — 2026-06-12

- `log_drill` / `list_drills`: safety drills as structured log entries
  (`[drill:type …]` tag + `category: "drill"`), with a `latest_by_type`
  summary for cadence checks.
- `mark_moment` accepts an optional `category`.
- `LogbookClient`: `post_entry` category, `get_dates` day index.
```

- [ ] **Step 3: SPEC.md** — document the two new tools' input/output contracts and the tag format (mirror the level of detail of the existing `mark_moment`/`read_entries` sections; lift the format definition from `docs/superpowers/specs/2026-06-12-drill-logging-design.md`). Remove the open-question bullet "Should `mark_moment` accept a `category` parameter…" — it's resolved. Update the versions list with `0.4.0`.

- [ ] **Step 4: README.md** — add the two tools to the tool table/list with one-line descriptions, matching existing entries' tone. Keep any "why" prose ≤ a couple of lines.

- [ ] **Step 5: Full suite, then commit**

Run: `uv run pytest -q --ignore=tests/test_integration_pi.py`
Expected: all PASS

```bash
git add pyproject.toml CHANGELOG.md SPEC.md README.md
git commit -m "docs: drill logging surface; bump to v0.4.0"
git push
```

---

## Follow-on (separate plans, not this one)

1. **naturali-agents**: `drills.yaml` + `drill_status` cadence helper, briefing
   line, crew-channel prompt, `scripts/drill_alert_chain.py` (spec §"Agent
   layer").
2. **Upstream**: PR adding `drill` to `@meri-imperiumi/signalk-logbook`'s
   category enum + UI select (casual tone, no internal plans; Bryan reviews
   before posting).
