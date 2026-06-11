# Security policy

## Supported versions

The most recent published release on PyPI is supported. Older versions are not.

## Reporting

Email security issues to: `bryan.clark+logbook-mcp-security@gmail.com` (a routing alias for the maintainer in `pyproject.toml`). We respond within 7 days.

Do not file public issues for security bugs.

## Scanning

Every PR runs cisco-ai-defense/mcp-scanner. See `.github/workflows/security.yml`.

## Transport

The SignalK admin token is sent over plain HTTP on the boat LAN (the Pi's
SignalK server does not serve TLS). The token is never logged. Treat the LAN
as the trust boundary; do not point `LOGBOOK_SK_URL` across an untrusted
network — use the Tailscale address instead.
