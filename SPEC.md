# logbook-mcp — Specification

This document is the design contract for the `logbook-mcp` MCP server. It
covers the shipped Phase 0 surface and the planned Phase 0.5 surface. The
README is the marketing/quickstart view; this file is the source of truth for
tool shapes, DB schema, and acceptance criteria.

## Goals

1. Capture a sailor's day on the water with as little friction as possible —
   ideally one MCP call at a time, from a voice or chat client.
2. Produce a defensible audit trail that maps cleanly onto USCG and Transport
   Canada sea-service documentation requirements.
3. Stay local-first: a single SQLite file under `LOGBOOK_DB_PATH` (default
   `~/.naturali/logbook.db`).

## Non-goals (for now)

- Multi-user / cloud sync.
- Vessel-tracking, AIS feeds, or real-time chart overlay.
- Anything that requires a network call from the server process.

## Conventions

- **Timestamps**: ISO 8601 UTC with `Z` suffix (e.g. `2026-05-21T20:37:00.123456Z`).
- **Coordinates**: Decimal degrees. Latitude `[-90, 90]`, longitude `[-180, 180]`.
  Storage uses SQLite `REAL`. Display formatting is `"{abs:.4f} {N|S}, {abs:.4f} {E|W}"`,
  with zero values rendered without a direction (`"0.0000, 0.0000"`).
- **IDs**: Every persisted row exposes both a raw integer `id` (for
  programmatic reference) and a `*_display` string (for human/LLM surfaces).
- **Errors**: Returned as MCP tool errors (`isError: true`). Input validation
  is delegated to MCP's `inputSchema` validator (jsonschema); domain errors
  raise from the tool function.

## Phase 0 — shipped

### Tool: `mark_moment`

Record a free-form marked moment, optionally with a position.

**Input**

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

**Output** (JSON text content)

```json
{
  "id": 42,
  "entry_display": "Entry 42",
  "text": "Beautiful sunset off Discovery Island",
  "timestamp": "2026-05-21T20:37:00.123456Z",
  "position": { "longitude": -123.27, "latitude": 48.42 },
  "position_display": "48.4200 North, 123.2700 West"
}
```

`position` and `position_display` are `null` when no position was supplied.

**Acceptance criteria**

- Row appears in `marked_moments` with all four fields populated (or NULLs
  for missing coordinates).
- Response includes both `id` and `entry_display`; `entry_display` is exactly
  `"Entry {id}"`.
- Out-of-range coordinates and empty `text` are rejected by the MCP validator
  before the handler runs.

### Schema: `marked_moments`

```sql
CREATE TABLE IF NOT EXISTS marked_moments (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    text      TEXT    NOT NULL,
    timestamp TEXT    NOT NULL,
    longitude REAL,
    latitude  REAL
);
```

## Phase 0.5 — planned

Goal: enough surface for an LLM agent to record a full sea-day end-to-end and
draft a human-reviewable summary that maps onto USCG sea-service form fields.

### Tool: `record_sea_day`

Capture a single sea-day record. Days are the atomic unit USCG/TC count.

**Input** (sketch — to be refined)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["date", "vessel", "role"],
  "properties": {
    "date":       { "type": "string", "format": "date" },
    "vessel":     { "type": "string", "minLength": 1 },
    "role":       { "type": "string", "enum": ["master", "mate", "crew", "deckhand"] },
    "start":      { "type": "string", "format": "date-time" },
    "end":        { "type": "string", "format": "date-time" },
    "hours":      { "type": "number", "minimum": 0, "maximum": 24 },
    "conditions": { "type": "string" },
    "departed":   { "type": "string" },
    "arrived":    { "type": "string" },
    "notes":      { "type": "string" }
  }
}
```

**Open questions** (to resolve before implementing)

- USCG counts a "day" as 4+ hours underway. TC has its own rules. Should the
  schema enforce the 4-hour minimum, or warn?
- How are tied-up / dockside days represented? Separate tool, or a flag?
- Vessel: free-text vs. lookup against a `vessels` table.

### Tool: `draft_summary`

Given a `sea_day` id, draft a narrative summary suitable for a logbook entry,
combining the day's structured fields with any `mark_moment` entries whose
timestamp falls inside `[start, end]`.

**Input**: `{ "day_id": int }`
**Output**: `{ "summary": str, "moment_ids": int[] }`

Idempotent: re-running overwrites the stored summary.

### Tool: `export_uscg_form`

Render a USCG sea-service form (CG-719S or successor) from `sea_days` in a
date range.

**Input** (sketch)

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "start_date": { "type": "string", "format": "date" },
    "end_date":   { "type": "string", "format": "date" },
    "vessel":     { "type": "string" },
    "format":     { "type": "string", "enum": ["pdf", "csv", "json"], "default": "csv" }
  }
}
```

**Output**: a path on disk (or base64 blob) plus a row-count summary.

### Tool: `export_tc_form`

Same as `export_uscg_form` but emits Transport Canada's sea-service form
layout (TBD which form).

### Schema additions: `sea_days`, `summaries`

```sql
CREATE TABLE IF NOT EXISTS sea_days (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    NOT NULL,           -- YYYY-MM-DD
    vessel     TEXT    NOT NULL,
    role       TEXT    NOT NULL,
    start_ts   TEXT,                       -- ISO 8601 Z
    end_ts     TEXT,
    hours      REAL,
    conditions TEXT,
    departed   TEXT,
    arrived    TEXT,
    notes      TEXT,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS summaries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id     INTEGER NOT NULL REFERENCES sea_days(id) ON DELETE CASCADE,
    summary    TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    UNIQUE (day_id)
);
```

A future migration may add a `day_id` foreign key on `marked_moments` once the
"which moments belong to which day" question is settled — for now the link is
computed at summary-draft time via timestamp range.

## Versioning policy

- `0.1.x` — Phase 0 only.
- `0.2.0` — first Phase 0.5 tool lands (`record_sea_day`).
- `1.0.0` — full Phase 0.5 surface stable; `export_*` tools have passed at
  least one real sea-service submission.

Schema migrations: every change to a table ships with an idempotent `ALTER
TABLE` or `CREATE TABLE` in `LogbookDB.init_schema()`. Rows are never
backfilled destructively without an explicit migration tool.

## Open design questions

- Should `mark_moment` allow attaching a `day_id` at creation time, or always
  resolve via timestamp?
- Do we want a `redact_moment(id)` tool, or is deletion enough?
- Should the server expose resources (e.g. `logbook://days/2026-05-21`) in
  addition to tools, so clients can browse without a tool call?
