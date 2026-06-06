# logbook-mcp

A thin MCP over [meri-imperiumi/signalk-logbook](https://github.com/meri-imperiumi/signalk-logbook) — the ship's log lives on the SignalK server as per-day YAML.

Part of the [Naturali](https://sailingnaturali.com) open-source boat agent stack.

**Requires signalk-logbook installed and enabled on the SignalK server.**

## Tools

- `mark_moment(text, position?)` — record a moment in the ship's log; position, speed, wind, and barometer are auto-enriched server-side from the vessel's sensors; `position` only needed to override the GPS fix.
- `read_entries(date?)` — read a day's log entries (default: today, vessel-local).

## Installation

```bash
uv tool install logbook-mcp
```

## Configuration

```bash
export LOGBOOK_SK_URL=http://naturalaspi.local:3000   # SignalK server root
export LOGBOOK_SK_TOKEN=...                            # SignalK access token (write)
export LOGBOOK_TZ=America/Vancouver                    # fallback timezone
logbook-mcp
```

Replace `naturalaspi.local` with your SignalK server's hostname. Create the
access token in the SignalK admin UI (Security → Access Requests / Tokens)
for an **admin** user — without it, writes fail with an error naming
`LOGBOOK_SK_TOKEN`. The token must belong to an **admin** user — signalk-server
gates all `/plugins/*` routes behind admin auth (`adminAuthenticationMiddleware`
in `tokensecurity.ts`); device tokens and read/write user tokens receive 401.

## Roadmap

Sea-time derivation and USCG/TC sea-service form exports are planned for Phase 0.5. Rather than maintaining a parallel store, `export_uscg_form` / `export_tc_form` will derive sea days by scanning signalk-logbook entries, and `draft_summary` will read entries by date range. See [docs/superpowers/specs/2026-06-05-adopt-signalk-logbook-design.md](docs/superpowers/specs/2026-06-05-adopt-signalk-logbook-design.md) for the design.

See [SPEC.md](SPEC.md) for the full tool contract.

## License

MIT. See LICENSE.

## Security

If you find a security issue, see [SECURITY.md](SECURITY.md).
