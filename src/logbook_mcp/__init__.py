"""logbook-mcp: MCP server for sea-day capture and marked moments."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("logbook-mcp")
except PackageNotFoundError:
    __version__ = "0.0.0+local"
