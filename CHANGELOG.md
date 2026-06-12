# Changelog

## 0.4.0 — 2026-06-12

- `log_drill` / `list_drills`: safety drills as structured log entries
  (`[drill:type …]` tag + `category: "drill"`), with a `latest_by_type`
  summary for cadence checks.
- `mark_moment` accepts an optional `category`.
- `LogbookClient`: `post_entry` category, `get_dates` day index.

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
- `mark_moment` response includes a ready-to-speak `confirmation` string for voice agents.

## v0.1.0 — 2026-05-20

### Added

- MCP server entry point (stdio transport)
- `LogbookDB` — SQLite wrapper with schema init
- Tools: `mark_moment` (text + optional position)
- GitHub Actions: pytest + mcp-scanner security scan
- MIT license
