# Drill logging — design

2026-06-12. Approved approach: logbook-mcp grows a generic drill surface;
drill taxonomy/cadence smarts stay in the agent layer (`naturali-agents`).

## Problem

Safety drills — real crew drills (MOB recovery, fire), radio/DSC test calls,
and synthetic alert-chain tests (a test MOB fired through SignalK → Poseidon)
— happen but leave no record. Commercial practice (SOLAS III/19, SOLAS V/26,
46 CFR) logs every drill and runs them on a cadence. We want drill entries in
the ship's log, machine-findable, with overdue drills surfaced in the daily
briefing and on-ask.

## Constraints

- Backend is `@meri-imperiumi/signalk-logbook`: entries are YAML day files;
  POST accepts `text`, `category`, `position`, `observations`. Its schema's
  category enum (`navigation`, `engine`, `radio`, `maintenance`) has no
  `drill`, **but the POST handler copies `category` unvalidated** — writing
  `drill` works today; an upstream PR makes it official.
- Poseidon's alarm lane is tool-free by design — automatic logging cannot live
  there. The drill runner owns logging (user decision).
- logbook-mcp is published and generic: it must not hardcode vessel- or
  crew-specific drill types or cadences (workspace principle: smarts live in
  the crew-context layer).
- A pleasure vessel has no legal drill obligations; cadences are *adopted*
  commercial practice, tunable in config.

## Entry format (the wire)

Structure rides in the entry text as a leading bracket tag; prose follows:

```
[drill:mob outcome=pass duration=14m crew=Bryan,K] Lifesling recovery under power, two passes, contact in 4 min.
```

- Every drill entry gets `category: "drill"` (including radio checks —
  `drill_type=radio` carries the distinction; one filter finds everything).
- Tag fields: `outcome` (required), `duration` (optional, minutes, `<n>m`),
  `crew` (optional, comma-separated). Tag fields split on whitespace, so
  values cannot contain spaces: `log_drill` normalizes internal whitespace in
  participant names to hyphens (`Bryan Clark` → `Bryan-Clark`) and rejects
  names containing commas. `drill_type` is the token after the colon:
  lowercase `[a-z0-9-]{1,32}`.
- Composing and parsing live only in logbook-mcp, round-trip tested.

## logbook-mcp changes (v0.4.0)

New tools:

- **`log_drill`** — `drill_type` (string, pattern above; not validated against
  any type list), `outcome` (`pass`|`partial`|`fail`), optional
  `duration_minutes` (number), `participants` (array of strings), `notes`
  (string), `position` (lat/lon override). Composes tag + prose, POSTs with
  `category: "drill"`, re-fetches and returns the written entry (same contract
  as `mark_moment`).
- **`list_drills`** — optional `drill_type`, `since`, `until` (YYYY-MM-DD;
  default window: last 180 days). Walks `GET /logs` (day index) filtered to
  the range, fetches each day, returns entries whose category is `drill` or
  whose text carries a `[drill:…]` tag, with parsed fields, plus a
  `latest_by_type` summary (`drill_type` → date of most recent drill).

Existing surface:

- `mark_moment` gains optional `category` (enum: the four upstream values +
  `drill`) — resolves the open SPEC question; default stays `navigation`.
- `LogbookClient.post_entry` grows a `category` parameter.

## Agent layer (naturali-agents)

- **`drills.yaml`** — the vessel's drill taxonomy. Per type: `label`,
  `cadence_days`, `underway_only` (bool), `basis` (one-line reg reference),
  `spoken` (voice-friendly description). Initial table:

  | type | cadence | underway_only | basis |
  |------|---------|---------------|-------|
  | mob | 30 d | yes | SOLAS III/19 practice norm |
  | fire | 30 d | no | SOLAS III/19.3.2 monthly crew fire drill |
  | abandon-ship | 30 d | no | SOLAS III/19.3.2; ditch-bag + liferaft walk-through |
  | steering-failure | 90 d | yes | SOLAS V/26 emergency steering |
  | flooding | 90 d | no | 46 CFR damage-control practice |
  | radio | 30 d | no | ITU/coast-guard radio-check practice |
  | alert-chain | 30 d | no | ours: scripted MOB-through-the-stack test |

- **`drill_status` helper** — joins `list_drills.latest_by_type` against
  `drills.yaml` → list of `{type, last_done, due_in_days}`; negative =
  overdue; never-done types report overdue.
- **Briefing** — an "overdue drills" line, emitted only when something is due.
- **Crew channel** — prompt/skill addition: conducting a drill by voice logs
  it (`log_drill`); "when did we last do a fire drill?" answers from
  `list_drills`. Spoken output never reads tag syntax aloud (voice
  conventions).
- **`scripts/drill_alert_chain.py`** — automates the synthetic test: POST
  `/signalk/v2/api/notifications/mob`, wait for Poseidon's `alert` timing
  record in `voice-timing.jsonl`, DELETE the notification (bare-id route),
  then `log_drill` (`alert-chain`, narration latency in notes). No record
  within timeout → `outcome=fail` + non-zero exit.

## Upstream (non-blocking)

PR to `@meri-imperiumi/signalk-logbook`: add `drill` to the schema category
enum and the UI category select. Until merged, `drill`-category entries write
fine; only UI categorization is cosmetic. No internal plans in the PR text.

## Testing (TDD)

- Tag composer/parser round-trip, including no-optional-fields, prose with
  brackets, malformed tags (parse → None, entry still listed if category is
  `drill`).
- `post_entry` sends `category`.
- `list_drills` date-walk with mocked REST: range filtering, mixed
  categories, `latest_by_type` correctness.
- `drill_status` cadence math: due, overdue, never-done.
- Alert-chain script: unit-test the timing-record wait/parse against a fixture
  jsonl; the live path stays a manual/opt-in smoke test.

## Out of scope

- Auto-detecting drills from alarm raise→clear patterns.
- Compliance reporting/exports (sea-time export remains the separate 1.0 goal).
- vessel-knowledge-mcp involvement.

## Build order

1. logbook-mcp: client category → tag module → `log_drill` → `list_drills` →
   `mark_moment` category → release 0.4.0.
2. naturali-agents: `drills.yaml` + `drill_status` → briefing line → crew
   channel prompt → `drill_alert_chain.py`.
3. Upstream enum PR.
