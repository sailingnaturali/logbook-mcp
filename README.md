# logbook-mcp

An MCP server for sea-day capture, marked moments, and license sea-time form export.

Part of the [Naturali](https://sailingnaturali.com) open-source boat agent stack.

## Phase 0 status

Minimal: `mark_moment(text, position?)` — optional `{longitude, latitude}` payload. SQLite-backed.

See [SPEC.md](SPEC.md) for the design contract and the Phase 0.5 plan.

## Phase 0.5+ roadmap

- `record_sea_day(start, end, role, vessel, conditions)`
- `export_uscg_form()`, `export_tc_form()`
- `draft_summary(day_id)`

## Installation

```bash
uv tool install logbook-mcp
```

## Configuration

```bash
export LOGBOOK_DB_PATH=~/.naturali/logbook.db
logbook-mcp
```

## License

MIT. See LICENSE.

## Security

If you find a security issue, see SECURITY.md.
