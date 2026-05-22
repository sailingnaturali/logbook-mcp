"""Logbook MCP server."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from logbook_mcp.db import LogbookDB
from logbook_mcp.tools import mark_moment


def _default_db() -> LogbookDB:
    db_path = os.environ.get(
        "LOGBOOK_DB_PATH", os.path.expanduser("~/.naturali/logbook.db")
    )
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    db = LogbookDB(db_path)
    db.init_schema()
    return db


def build_server(db: LogbookDB | None = None) -> Server:
    server = Server("logbook-mcp")
    if db is None:
        db = _default_db()

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="mark_moment",
                description="Record a marked moment in the logbook with optional position.",
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
        ]

    @server.call_tool()
    async def _call_tool(name: str, args: dict[str, Any]) -> list[types.TextContent]:
        if name == "mark_moment":
            result = mark_moment(db, text=args["text"], position=args.get("position"))
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


def main() -> None:
    db = _default_db()
    server = build_server(db=db)

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    try:
        asyncio.run(_run())
    finally:
        db.close()


if __name__ == "__main__":
    main()
