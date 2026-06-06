# logbook-mcp over signalk-logbook — Design

**Date:** 2026-06-05
**Status:** Approved design, pending implementation plan
**Decision:** Build-on-top — logbook-mcp becomes a thin, stateless MCP over
`meri-imperiumi/signalk-logbook`'s REST API. SQLite store is retired.

## Background and decision

Prime directive: use/improve existing tools before building our own. We audited
logbook-mcp against the SignalK logbook ecosystem:

| Project | Verdict | Why |
|---|---|---|
| `meri-imperiumi/signalk-logbook` | **Adopt as backend** | Runs on the SignalK server (the Pi). Per-day YAML entries, REST API with OpenAPI, admin UI, semi-automatic entries (hourly underway, trip start/end via `signalk-autostate`). `POST /logs` auto-enriches entries server-side with position, heading, SOG/STW, wind, barometer, log, engine hours. |
| `Saillogger/signalk-saillogger` | Rejected | Data lives in their cloud — wrong shape for local-first agent read/write. |
| `xbgmsharp/signalk-postgsail` | Rejected | A whole Postgres+PostgREST+Grafana tier to operate; aimed at trip dashboards, not agent narrative entries. |
| Keep ours (status quo) | Rejected | We would rebuild — worse — what exists: no UI, no auto-entries, no enrichment, and the log dies with the Mac instead of living on the boat. |

What survives as **our** unique ground: the sea-time accounting / USCG & TC
sea-service form export layer (nothing in the ecosystem does it), and the
agent-facing MCP surface itself.

Maintenance-risk note: signalk-logbook is 16★, single maintainer (Henri
Bergius, core SignalK community), last pushed 2025-09. Acceptable: the YAML
files are trivially parseable forever even if the plugin dies, and the REST
surface is small enough to vendor.

## Architecture

- **Pi (`naturalaspi`)**: install `signalk-logbook` on the SignalK server.
  Entries live as per-day YAML under SignalK's plugin data dir.
  **Pre-flight: verify the docker volume persists `plugin-config-data`**
  before trusting it with real entries. The ship's log lives on the boat:
  browsable in the SignalK admin UI, independent of the Mac.
- **Mac Studio**: `logbook-mcp` (same repo, same PyPI package) drops SQLite
  entirely and becomes a **stateless HTTP client**. `db.py` is deleted; a
  small `client.py` wraps
  `http://naturalaspi.local:3000/plugins/signalk-logbook/logs…`.
- **Config (env)**:
  - `LOGBOOK_SK_URL` — default `http://naturalaspi.local:3000`
  - `LOGBOOK_SK_TOKEN` — SignalK access token (writes require auth); one-time
    admin grant on the Pi, stored in `~/.hermes/.env` alongside other creds
  - `LOGBOOK_TZ` — fallback timezone for `time_display` when an entry has no
    position (default `America/Vancouver`)
  - `LOGBOOK_DB_PATH` is retired.

**Deliberately deferred:** `signalk-autostate` (trip start/end detection).
The Phase 0 mock vessel sails 6 kts forever, so autostate + hourly
auto-entries would spam the log with fake entries hourly, around the clock.
Install it when real sensors come online; nothing in our code depends on it
until the sea-time phase.

## Tool surface

### `mark_moment(text, position?)` — input schema unchanged

Flow:
1. `POST /logs {text}` — the plugin snapshots position, heading, SOG/STW,
   wind, barometer from live SignalK. (This fixes the long-standing
   naturali-agents SPEC.md drift: position now really does come from the
   vessel fix.)
2. `POST` returns a bare `201` with no body (verified in `plugin/index.js`),
   so: `GET /logs/{today}` and take the newest entry to build the response.
3. If `position` was explicitly passed, follow up with `PUT` to override the
   snapshotted fix (explicit beats automatic). The prompt drops `position`
   from the call signature; the param remains only for explicit overrides
   ("log this at the harbour entrance").

Response (field names preserved, plus one new field):

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

- `id` changes int → string: the entry's datetime key (its REST identity).
- `entry_display` is `"Entry {n}"` where `n` is the entry's 1-based ordinal
  within its day (we already fetch the day's entries to find the new one, so
  the ordinal is free). Keeps the old `"Entry {n}"` spoken shape, and avoids
  speaking a UTC-derived time next to the local `time_display` (SOUL.md
  forbids spoken UTC).
- `time_display` is **new**: vessel-local wall-clock time, localized from the
  entry's own position via `timezonefinder` + `zoneinfo` (same approach and
  display format as signalk-mcp's `get_local_time`, e.g. `"11:32"`). Falls
  back to `LOGBOOK_TZ` when the entry has no position.
- `position_display` format unchanged.

### `read_entries(date?)` — new

`GET /logs/{date}`; `date` defaults to today in vessel-local time (current
fix → `timezonefinder`, falling back to `LOGBOOK_TZ`). Returns the
day's entries with friendly position/time formatting so agents and the
briefing can quote the log. Includes entry `category`, `author`, and `text`.

No edit/delete tools — humans curate via the SignalK admin UI; agents only
append and read.

## Hermes prompt changes (`naturali-agents/prompts/navigator.md`)

Line 20 becomes (self-contained confirmation, one tool call instead of two —
the `get_local_time` chain is dropped because `time_display` comes back from
the logbook itself):

```
- `mcp_logbook_mark_moment(text)` — record a moment in the ship's log;
  position, wind, and conditions are captured automatically from the vessel's
  sensors. When confirming, respond ONLY with:
  "Logged. [entry_display]. [time_display]. [position_display]."
  — use these fields verbatim, no other formatting
```

New line for reads:

```
- `mcp_logbook_read_entries(date?)` — read the day's log entries (default
  today); for "what did we log today?" — quote entry text with local times,
  never UTC
```

Spoken result is unchanged from today:
"Logged. Entry 3. 11:32. 48.4 North, 123.3 West."

## Sea-time layer (roadmap — not built now)

`record_sea_day`'s parallel store is **deleted from the spec**. Future
`export_uscg_form` / `export_tc_form` *derive* sea days by scanning
signalk-logbook entries (trip start/end markers and hourly underway entries
are exactly the evidence a sea-service form needs), with role/vessel supplied
at export time. One source of truth; the export logic is the only genuinely
novel code we maintain. `draft_summary` likewise reads entries by date range
rather than joining SQLite tables.

## Error handling

- Pi unreachable / timeout (5 s): MCP tool error stating plainly the moment
  was **NOT recorded** — no silent failure, no offline queue (explicit YAGNI
  decision; revisit only if real-world dropouts hurt).
- 401/403: error message names `LOGBOOK_SK_TOKEN` so it is immediately
  actionable.
- Non-2xx on any call: surfaced as a tool error with status and URL.

## Migration

None. Phase 0 SQLite entries are mock-era test data; archive
`~/.naturali/logbook.db` as-is. (If real entries are discovered, a one-off
YAML import script can be added to the plan.)

## Testing

- Unit tests with mocked HTTP: happy path, position override (POST→GET→PUT),
  the POST-then-fetch dance, unreachable-Pi error, auth error, `time_display`
  localization and `LOGBOOK_TZ` fallback. Replaces the SQLite tests.
- Env-gated integration smoke test against the real Pi.
- End-to-end verify before flipping Hermes config: voice → Navigator →
  `mark_moment` → entry visible in the SignalK admin UI.

## Cross-repo touchpoints

| Repo | Change |
|---|---|
| `logbook-mcp` | `db.py` → `client.py`; new tool `read_entries`; README/SPEC rewritten; version → 0.2.0 |
| `infrastructure` | Pi: install `signalk-logbook`, document token provisioning, verify docker volume persistence |
| `naturali-agents` | `prompts/navigator.md` line 20 + new read line; `SPEC.md` tool-surface section corrected |
| `~/.hermes/config.yaml` | env swap: `LOGBOOK_DB_PATH` → `LOGBOOK_SK_URL`/`LOGBOOK_SK_TOKEN`/`LOGBOOK_TZ` (machine-local, not in git) |

## Open items deliberately out of scope

- `signalk-autostate` install (when real sensors arrive)
- Sea-time derivation + USCG/TC exports (next phase; this design only commits
  to deriving from signalk-logbook entries rather than a parallel store)
- Offline queueing for `mark_moment`
- Entry edit/delete tools
