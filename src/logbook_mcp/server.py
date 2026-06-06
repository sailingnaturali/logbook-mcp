"""Logbook MCP server — thin surface over signalk-logbook on the Pi."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from logbook_mcp.client import LogbookClient
from logbook_mcp.tools import mark_moment, read_entries


def _env_config() -> tuple[str, str | None, str]:
    url = os.environ.get("LOGBOOK_SK_URL", "http://naturalaspi.local:3000")
    token = os.environ.get("LOGBOOK_SK_TOKEN")
    tz = os.environ.get("LOGBOOK_TZ", "America/Vancouver")
    return url, token, tz


def build_server(client: LogbookClient, fallback_tz: str = "America/Vancouver") -> Server:
    server = Server("logbook-mcp")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="mark_moment",
                description=(
                    "Record a moment in the ship's log. Position, speed, wind, "
                    "and barometer are captured automatically from the vessel's "
                    "sensors; pass position only to override the GPS fix."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "text": {"type": "string", "minLength": 1},
                        "position": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "longitude": {
                                    "type": "number",
                                    "minimum": -180,
                                    "maximum": 180,
                                },
                                "latitude": {
                                    "type": "number",
                                    "minimum": -90,
                                    "maximum": 90,
                                },
                            },
                            "required": ["longitude", "latitude"],
                        },
                    },
                    "required": ["text"],
                },
            ),
            types.Tool(
                name="read_entries",
                description=(
                    "Read the ship's log entries for a day "
                    "(default: today, vessel-local)."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "date": {
                            "type": "string",
                            "pattern": r"^\d{4}-\d{2}-\d{2}$",
                        },
                    },
                },
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, args: dict[str, Any]) -> list[types.TextContent]:
        if name == "mark_moment":
            result = await mark_moment(
                client,
                text=args["text"],
                position=args.get("position"),
                fallback_tz=fallback_tz,
            )
        elif name == "read_entries":
            result = await read_entries(
                client, date=args.get("date"), fallback_tz=fallback_tz
            )
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


def main() -> None:
    url, token, tz = _env_config()
    client = LogbookClient(url, token=token)
    server = build_server(client, fallback_tz=tz)

    async def _run() -> None:
        try:
            async with stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )
        finally:
            await client.aclose()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
