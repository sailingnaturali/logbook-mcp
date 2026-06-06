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

**Response** (JSON text content)

```json
{
  "id": "2026-06-05T18:32:00Z",
  "entry_display": "Entry 3",
  "text": "Beautiful sunset off Discovery Island",
  "timestamp": "2026-06-05T18:32:00Z",
  "time_display": "11:32",
  "position": { "longitude": -123.27, "latitude": 48.42 },
  "position_display": "48.4 North, 123.3 West"
}
```

- `id` — the entry's datetime key (string); its REST identity in signalk-logbook.
- `entry_display` — `"Entry {n}"` where `n` is the 1-based ordinal within the day.
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

**Position override**

When `position` is explicitly supplied, after the POST → re-fetch the tool
issues a `PUT` to patch the entry with `source: "manual"`, overriding the
snapshotted GPS fix.

**Error-honesty rules** (verbatim from the design spec)

- Pi unreachable / timeout before POST completes: tool error stating the
  moment was **NOT recorded** — no silent failure.
- 401/403 at any point: error message names `LOGBOOK_SK_TOKEN` so it is
  immediately actionable.
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
- `1.0.0` — sea-time export surface (`export_uscg_form` / `export_tc_form`)
  stable after at least one real sea-service submission.

## Open design questions

- Should `mark_moment` accept a `category` parameter, or always default to
  `"navigation"`?
- Do we want a `redact_moment(id)` tool, or is curation always via the
  SignalK admin UI?
- Should the server expose MCP resources (e.g. `logbook://days/2026-05-21`)
  so clients can browse without a tool call?
