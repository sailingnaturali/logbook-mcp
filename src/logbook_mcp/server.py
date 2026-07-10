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
from logbook_mcp.tools import (
    DEFAULT_AGENT_AUTHORS,
    FALLBACK_TZ,
    amend_entry_author,
    list_drills,
    log_drill,
    mark_moment,
    read_entries,
)


def _parse_authors(raw: str) -> frozenset[str]:
    return frozenset(a.strip() for a in raw.split(",") if a.strip())


def _env_config() -> tuple[str, str | None, str, float, frozenset[str], frozenset[str]]:
    url = os.environ.get("LOGBOOK_SK_URL", "http://naturalaspi.local:3000")
    token = os.environ.get("LOGBOOK_SK_TOKEN")
    tz = os.environ.get("LOGBOOK_TZ", FALLBACK_TZ)
    timeout = float(os.environ.get("LOGBOOK_TIMEOUT", "5.0"))
    agent_authors = _parse_authors(
        os.environ.get("LOGBOOK_AGENT_AUTHORS", "hermes,poseidon")
    )
    auto_authors = _parse_authors(os.environ.get("LOGBOOK_AUTO_AUTHORS", ""))
    return url, token, tz, timeout, agent_authors, auto_authors


def build_server(
    client: LogbookClient,
    fallback_tz: str = FALLBACK_TZ,
    agent_authors: frozenset[str] = DEFAULT_AGENT_AUTHORS,
    auto_authors: frozenset[str] = frozenset(),
) -> Server:
    server = Server("logbook-mcp")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="mark_moment",
                description=(
                    "Record a moment in the ship's log. Position, speed, wind, "
                    "and barometer are captured automatically from the vessel's "
                    "sensors; pass position only to override the GPS fix. "
                    "Pass author (who dictated/asked) for attribution — the "
                    "confirmation then ends 'Logged as {author}.' Pass origin "
                    "'manual' when a person composed the words verbatim (voice "
                    "dictation); default 'agent' when the agent composed them."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "text": {"type": "string", "minLength": 1},
                        "category": {
                            "type": "string",
                            "enum": [
                                "navigation",
                                "engine",
                                "radio",
                                "maintenance",
                                "drill",
                            ],
                        },
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
                        "author": {"type": "string", "minLength": 1},
                        "origin": {"type": "string", "enum": ["manual", "agent"]},
                    },
                    "required": ["text"],
                },
            ),
            types.Tool(
                name="read_entries",
                description=(
                    "Read the ship's log entries for a day "
                    "(default: today, vessel-local). "
                    "Each entry includes origin: manual (a person composed it), "
                    "agent, or auto (unattended vessel machinery). Filter with origin."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "date": {
                            "type": "string",
                            "pattern": r"^\d{4}-\d{2}-\d{2}$",
                        },
                        "origin": {
                            "type": "string",
                            "enum": ["manual", "auto", "agent"],
                        },
                    },
                },
            ),
            types.Tool(
                name="log_drill",
                description=(
                    "Record a safety drill in the ship's log (MOB, fire, "
                    "abandon-ship, steering-failure, flooding, radio, "
                    "alert-chain, …). Position and conditions are captured "
                    "automatically; pass position only to override the GPS fix."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "drill_type": {
                            "type": "string",
                            "pattern": "^[a-z0-9-]{1,32}$",
                        },
                        "outcome": {
                            "type": "string",
                            "enum": ["pass", "partial", "fail"],
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1440,
                        },
                        "participants": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 1,
                        },
                        "notes": {"type": "string"},
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
                    "required": ["drill_type", "outcome"],
                },
            ),
            types.Tool(
                name="list_drills",
                description=(
                    "List safety drills from the ship's log (default: last "
                    "180 days), with a latest_by_type summary for cadence "
                    "checks."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "drill_type": {
                            "type": "string",
                            "pattern": "^[a-z0-9-]{1,32}$",
                        },
                        "since": {
                            "type": "string",
                            "pattern": r"^\d{4}-\d{2}-\d{2}$",
                        },
                        "until": {
                            "type": "string",
                            "pattern": r"^\d{4}-\d{2}-\d{2}$",
                        },
                    },
                },
            ),
            types.Tool(
                name="amend_entry_author",
                description=(
                    "Correct who a log entry is attributed to (e.g. a voice entry "
                    "assumed the wrong speaker). Use the entry id from mark_moment "
                    "or read_entries. The confirmation is ready to speak."
                ),
                inputSchema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "entry_id": {"type": "string", "minLength": 10},
                        "author": {"type": "string", "minLength": 1},
                    },
                    "required": ["entry_id", "author"],
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
                category=args.get("category"),
                author=args.get("author"),
                origin=args.get("origin", "agent"),
            )
        elif name == "read_entries":
            result = await read_entries(
                client, date=args.get("date"), fallback_tz=fallback_tz,
                origin=args.get("origin"),
                agent_authors=agent_authors, auto_authors=auto_authors,
            )
        elif name == "log_drill":
            result = await log_drill(
                client,
                drill_type=args["drill_type"],
                outcome=args["outcome"],
                duration_minutes=args.get("duration_minutes"),
                participants=args.get("participants"),
                notes=args.get("notes"),
                position=args.get("position"),
                fallback_tz=fallback_tz,
            )
        elif name == "list_drills":
            result = await list_drills(
                client,
                drill_type=args.get("drill_type"),
                since=args.get("since"),
                until=args.get("until"),
                fallback_tz=fallback_tz,
            )
        elif name == "amend_entry_author":
            result = await amend_entry_author(
                client, entry_id=args["entry_id"], author=args["author"]
            )
        else:
            raise ValueError(f"Unknown tool: {name}")
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


def main() -> None:
    url, token, tz, timeout, agent_authors, auto_authors = _env_config()
    client = LogbookClient(url, token=token, timeout=timeout)
    server = build_server(client, fallback_tz=tz, agent_authors=agent_authors, auto_authors=auto_authors)

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
