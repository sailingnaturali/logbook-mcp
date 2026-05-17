"""Logbook MCP server."""

from __future__ import annotations

import asyncio
import json
import os

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from logbook_mcp.db import LogbookDB
from logbook_mcp.tools import mark_moment


def build_server() -> Server:
    server = Server("logbook-mcp")
    db_path = os.environ.get(
        "LOGBOOK_DB_PATH", os.path.expanduser("~/.naturali/logbook.db")
    )
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db = LogbookDB(db_path)
    db.init_schema()

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="mark_moment",
                description="Record a marked moment in the logbook with optional position.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "position": {
                            "type": "object",
                            "properties": {
                                "longitude": {"type": "number"},
                                "latitude": {"type": "number"},
                            },
                            "required": ["longitude", "latitude"],
                        },
                    },
                    "required": ["text"],
                },
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, args: dict) -> list[types.TextContent]:
        if name == "mark_moment":
            result = mark_moment(db, text=args["text"], position=args.get("position"))
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


def main() -> None:
    server = build_server()

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(_run())


if __name__ == "__main__":
    main()
