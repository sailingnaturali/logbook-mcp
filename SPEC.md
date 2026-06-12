# logbook-mcp — Specification

This document is the design contract for the `logbook-mcp` MCP server. It
covers the shipped Phase 0 surface and the planned Phase 0.5 surface. The
README is the marketing/quickstart view; this file is the source of truth for
tool shapes, behavior contracts, and acceptance criteria.

## Goals

1. Capture a sailor's day on the water with as little friction as possible —
   ideally one MCP call at a time, from a voice or chat client.
2. Produce a defensible audit trail that maps cleanly onto USCG and Transport
   Canada sea-service documentation requirements.
3. The log lives on the boat: `signalk-logbook` owns storage (per-day YAML on
   the SignalK server). `logbook-mcp` itself is stateless — it is a thin HTTP
   client with no local database.

## Non-goals (for now)

- Multi-user / cloud sync.
- Vessel-tracking, AIS feeds, or real-time chart overlay.
- Offline queueing for `mark_moment`.
- Entry edit or delete tools — humans curate via the SignalK admin UI.

## Conventions

- **Timestamps**: ISO 8601 UTC with `Z` suffix (e.g. `2026-05-21T20:37:00.123456Z`).
- **Coordinates**: Decimal degrees. Latitude `[-90, 90]`, longitude `[-180, 180]`.
  Display formatting is `"{abs:.1f} {North|South}, {abs:.1f} {East|West}"`,
  with zero values rendered without a direction (`"0.0, 0.0"`).
- **IDs**: `id` is the entry's datetime key (a string, e.g.
  `"2026-06-05T18:32:00Z"`). `entry_display` is `"Entry {n}"` where `n` is
  the entry's 1-based ordinal within its day.
- **Errors**: Returned as MCP tool errors (`isError: true`). Input validation
  is delegated to MCP's `inputSchema` validator (jsonschema); domain errors
  raise from the tool function.

## Phase 0 — shipped (0.2.0)

### Tool: `mark_moment`

Record a moment in the ship's log via signalk-logbook. Position, speed, wind,
and barometer are captured automatically from the vessel's sensors. Pass
`position` only to override the GPS fix.

**Input schema** (from `src/logbook_mcp/server.py`)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["text"],
  "properties": {
    "text": { "type": "string", "minLength": 1 },
    "category": {
      "type": "string",
      "enum": ["navigation", "engine", "radio", "maintenance", "drill"]
    },
    "position": {
      "type": "object",
      "additionalProperties": false,
      "required": ["longitude", "latitude"],
      "properties": {
        "longitude": { "type": "number", "minimum": -180, "maximum": 180 },
        "latitude":  { "type": "number", "minimum": -90,  "maximum": 90  }
      }
    }
  }
}
```

`category` is optional. When omitted, the signalk-logbook plugin defaults to
`"navigation"`. Valid values: `navigation`, `engine`, `radio`, `maintenance`,
`drill`.

**Response** (JSON text content)

```json
{
  "id": "2026-06-05T18:32:00Z",
  "entry_display": "Entry 3",
  "confirmation": "Logged. Entry 3. 11:32. 48.4 North, 123.3 West.",
  "text": "Beautiful sunset off Discovery Island",
  "timestamp": "2026-06-05T18:32:00Z",
  "time_display": "11:32",
  "position": { "longitude": -123.27, "latitude": 48.42 },
  "position_display": "48.4 North, 123.3 West"
}
```

- `id` — the entry's datetime key (string); its REST identity in signalk-logbook.
- `entry_display` — `"Entry {n}"` where `n` is the 1-based ordinal within the day.
- `confirmation` — ready-to-speak confirmation sentence; voice agents must relay
  it verbatim rather than assembling their own from the individual fields.
- `time_display` — vessel-local wall-clock time (`HH:MM`), derived from the
  entry's own position via `timezonefinder` + `zoneinfo`; falls back to
  `LOGBOOK_TZ` when the entry has no position.
- `position` and `position_display` are `null` when no fix is available.

**POST → re-fetch dance**

`POST /logs` returns a bare `201` with no body. The tool re-fetches the day's
entries (`GET /logs/{today}`) and identifies the just-created entry as the
newest-by-datetime. If the UTC clock rolled past midnight between POST and
re-fetch, the entry may be in the previous day's file — the tool checks that
day before giving up.

The client always sends `ago: 0` in the POST body — the plugin calls
`buffer.get(req.body.ago)` whenever its state buffer is non-empty, and omitting
the field causes an HTTP 500 once the buffer has been populated (verified live).

The access token is sent both as an `Authorization: Bearer` header (required by
signalk-server's admin gate) **and** as a `JAUTHENTICATION` cookie (required by
the plugin, which calls `parseJwt(req.cookies.JAUTHENTICATION).id` to derive the
entry author). Both must be present for writes to succeed.

**Position override**

When `position` is explicitly supplied, after the POST → re-fetch the tool
issues a `PUT` to patch the entry with `source: "manual"`, overriding the
snapshotted GPS fix.

**Error-honesty rules** (verbatim from the design spec)

- Pi unreachable / timeout before POST completes: tool error stating the
  moment was **NOT recorded** — no silent failure.
- 401/403 at any point: error message names `LOGBOOK_SK_TOKEN` so it is
  immediately actionable. The token must belong to an **admin** user —
  signalk-server gates all `/plugins/*` routes behind admin auth
  (`tokensecurity.ts adminAuthenticationMiddleware`); device tokens and
  read/write user tokens receive 401.
- Post-write confirmation failures (re-fetch or PUT errors): error states the
  entry **was recorded but could not be confirmed**; advise the user to check
  via `read_entries`.
- Non-2xx on any call: surfaced as a tool error with the HTTP status and URL.

**Acceptance criteria**

- Entry appears in signalk-logbook for the correct day.
- Response includes `id` (datetime string), `entry_display` (`"Entry {n}"`),
  `time_display` (vessel-local HH:MM), `timestamp`, `position`, and
  `position_display`.
- Out-of-range coordinates and empty `text` are rejected by the MCP validator
  before the handler runs.
- When `position` is supplied, a PUT is issued and the response reflects the
  overridden coordinates with `source: "manual"`.

---

### Tool: `read_entries`

Read a day's log entries. Defaults to today in vessel-local time (current GPS
fix → `timezonefinder`; falls back to `LOGBOOK_TZ`).

**Input schema** (from `src/logbook_mcp/server.py`)

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "date": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
    }
  }
}
```

**Response**

```json
{
  "date": "2026-06-05",
  "count": 3,
  "entries": [
    {
      "id": "2026-06-05T14:00:00Z",
      "entry_display": "Entry 1",
      "time_display": "07:00",
      "text": "Departed Tsawwassen",
      "category": "navigation",
      "author": null,
      "position": { "longitude": -123.13, "latitude": 49.01 },
      "position_display": "49.0 North, 123.1 West"
    }
  ]
}
```

Each entry includes `id`, `entry_display`, `time_display` (vessel-local HH:MM),
`text`, `category`, `author`, `position`, and `position_display`. Entries are
sorted ascending by datetime. `position` and `position_display` are `null` when
no fix is recorded for that entry.

---

### Tool: `log_drill`

Record a safety drill in the ship's log. Position and conditions are captured
automatically from the vessel's sensors; pass `position` only to override the
GPS fix. Extends `mark_moment` with drill-specific fields: composes a
`[drill:type …]` tag as the entry text and sets `category: "drill"`.

**Input schema** (from `src/logbook_mcp/server.py`)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["drill_type", "outcome"],
  "properties": {
    "drill_type": { "type": "string", "pattern": "^[a-z0-9-]{1,32}$" },
    "outcome":    { "type": "string", "enum": ["pass", "partial", "fail"] },
    "duration_minutes": { "type": "integer", "minimum": 1, "maximum": 1440 },
    "participants": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 },
      "minItems": 1
    },
    "notes": { "type": "string" },
    "position": {
      "type": "object",
      "additionalProperties": false,
      "required": ["longitude", "latitude"],
      "properties": {
        "longitude": { "type": "number", "minimum": -180, "maximum": 180 },
        "latitude":  { "type": "number", "minimum": -90,  "maximum": 90  }
      }
    }
  }
}
```

**Tag format** (written to entry text by `src/logbook_mcp/drills.py`)

```
[drill:<drill_type> outcome=<outcome> duration=<n>m crew=<p1>,<p2>] notes…
```

- `drill_type`: lowercase `[a-z0-9-]`, 1–32 characters (e.g. `mob`, `fire`,
  `abandon-ship`). Invalid values are rejected before any write.
- `outcome`: one of `pass`, `partial`, `fail`.
- `duration`: written as `<n>m` (e.g. `duration=14m`); omitted when not
  supplied. `n` must be a whole number ≥ 1.
- `crew`: participant names joined by commas. Internal whitespace in a name is
  normalized to hyphens (e.g. `"K Smith"` → `K-Smith`). Names containing
  commas or brackets are rejected.
- Notes are written as prose after the closing `]`, separated by a space.
  They are omitted from the tag when absent.

**Response**

```json
{
  "id": "2026-06-12T18:00:00Z",
  "entry_display": "Entry 4",
  "confirmation": "Logged mob drill, pass. Entry 4. 11:00.",
  "text": "[drill:mob outcome=pass duration=14m crew=Bryan,K]",
  "timestamp": "2026-06-12T18:00:00Z",
  "time_display": "11:00",
  "position": { "longitude": -123.27, "latitude": 48.42 },
  "position_display": "48.4 North, 123.3 West",
  "drill_type": "mob",
  "outcome": "pass",
  "duration_minutes": 14,
  "participants": ["Bryan", "K"],
  "notes": null
}
```

- All `mark_moment` fields are present.
- `confirmation` names the drill type (hyphens replaced with spaces) and
  outcome: `"Logged <type> drill, <outcome>. <entry_display>. <time_display>."`.
- `drill_type`, `outcome`, `duration_minutes`, `participants`, and `notes` are
  the normalized values parsed back from the composed tag (the round-trip-tested
  source of truth).

---

### Tool: `list_drills`

List safety drills from the ship's log. Window bounds are UTC calendar-day
boundaries (matching how signalk-logbook stores day files).

**Input schema** (from `src/logbook_mcp/server.py`)

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "drill_type": { "type": "string", "pattern": "^[a-z0-9-]{1,32}$" },
    "since":      { "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$" },
    "until":      { "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$" }
  }
}
```

All parameters are optional.

- Default window: 180 UTC days ending today (`until` defaults to today UTC,
  `since` defaults to `until − 180 days`).
- `since` after `until` is rejected with a `ValueError` before any fetch.
- `drill_type` filters to a single drill type; invalid values are rejected.

**Response**

```json
{
  "since": "2025-12-14",
  "until": "2026-06-12",
  "count": 2,
  "drills": [
    {
      "id": "2026-05-01T17:00:00Z",
      "date": "2026-05-01",
      "time_display": "10:00",
      "drill_type": "mob",
      "outcome": "pass",
      "duration_minutes": 12,
      "participants": ["Bryan", "K"],
      "notes": null,
      "position": { "longitude": -123.27, "latitude": 48.42 },
      "position_display": "48.4 North, 123.3 West"
    }
  ],
  "latest_by_type": {
    "mob": "2026-05-01"
  }
}
```

- `drills` is sorted ascending by `id` (UTC datetime string).
- `latest_by_type`: maps each drill type to the date (`YYYY-MM-DD`) of its
  most recent entry. Useful for cadence checks (e.g. "last MOB drill was 42
  days ago"). Only entries with a parsed `[drill:…]` tag contribute; entries
  that carry `category: "drill"` but no tag are listed in `drills` with all
  drill fields as `None` and do **not** appear in `latest_by_type`.

---

## Phase 0.5 — planned

Goal: enough surface for an LLM agent to produce a human-reviewable sea-time
summary that maps onto USCG sea-service form fields.

### Sea-time layer

`record_sea_day` and its parallel SQLite store are **not built**. Instead,
`export_uscg_form` / `export_tc_form` will *derive* sea days by scanning
signalk-logbook entries (trip start/end markers and hourly underway entries
from `signalk-autostate` are exactly the evidence a sea-service form needs).
Role and vessel are supplied at export time. One source of truth: the
signalk-logbook YAML on the Pi.

`draft_summary` likewise reads entries by date range (via `read_entries`)
rather than joining database tables.

This approach is the only genuinely novel layer we maintain; the export logic
references the same design spec:
[docs/superpowers/specs/2026-06-05-adopt-signalk-logbook-design.md](docs/superpowers/specs/2026-06-05-adopt-signalk-logbook-design.md).

### Tool: `export_uscg_form` (sketch)

Derive USCG CG-719S sea-service data from signalk-logbook entries in a date
range.

**Input** (to be refined)

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "start_date": { "type": "string", "format": "date" },
    "end_date":   { "type": "string", "format": "date" },
    "vessel":     { "type": "string" },
    "role":       { "type": "string", "enum": ["master", "mate", "crew", "deckhand"] },
    "format":     { "type": "string", "enum": ["pdf", "csv", "json"], "default": "csv" }
  }
}
```

**Output**: a path on disk (or base64 blob) plus a row-count summary.

### Tool: `export_tc_form` (sketch)

Same as `export_uscg_form` but emits Transport Canada's sea-service form
layout (form TBD).

### Tool: `draft_summary` (sketch)

Given a date range, draft a narrative summary combining entries for human
review. Reads entries via `read_entries` rather than joining database tables.

**Input** (sketch): `{ "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD" }`
**Output**: `{ "summary": str, "entry_count": int }`

---

## Versioning policy

- `0.1.x` — SQLite Phase 0 (historical; `mark_moment` only, no REST backend).
- `0.2.0` — REST backend over signalk-logbook; `mark_moment` and `read_entries`
  shipped; `LOGBOOK_DB_PATH` retired.
- `0.3.0` — vessel-local day windows; `LogbookClient.get_entries` date param.
- `0.4.0` — drill surface: `log_drill`, `list_drills`; `mark_moment` `category`
  param; `LogbookClient.post_entry` category + `get_dates`.
- `1.0.0` — sea-time export surface (`export_uscg_form` / `export_tc_form`)
  stable after at least one real sea-service submission.

## Open design questions

- Do we want a `redact_moment(id)` tool, or is curation always via the
  SignalK admin UI?
- Should the server expose MCP resources (e.g. `logbook://days/2026-05-21`)
  so clients can browse without a tool call?
