# Changelog

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

## v0.1.0 — 2026-05-20

### Added

- MCP server entry point (stdio transport)
- `LogbookDB` — SQLite wrapper with schema init
- Tools: `mark_moment` (text + optional position)
- GitHub Actions: pytest + mcp-scanner security scan
- MIT license
