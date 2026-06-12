"""Drill entry tag: compose and parse.

Drill structure rides in the entry text as a leading bracket tag —
``[drill:mob outcome=pass duration=14m crew=Bryan,K] prose…`` — because the
signalk-logbook plugin only persists text/category/position. This module is
the single place that knows the tag syntax; spec in
docs/superpowers/specs/2026-06-12-drill-logging-design.md.
"""

from __future__ import annotations

import re

VALID_OUTCOMES = ("pass", "partial", "fail")

_DRILL_TYPE_RE = re.compile(r"^[a-z0-9-]{1,32}$")


def _normalize_participant(name: str) -> str:
    """Tag fields split on whitespace and crew splits on commas, so names
    may contain neither: internal whitespace becomes hyphens, commas are an
    error."""
    name = name.strip()
    if not name:
        raise ValueError("participant name is empty")
    if "," in name:
        raise ValueError(f"participant name may not contain a comma: {name!r}")
    return re.sub(r"\s+", "-", name)


def compose_drill_text(
    drill_type: str,
    outcome: str,
    duration_minutes: int | None = None,
    participants: list[str] | None = None,
    notes: str | None = None,
) -> str:
    """Build the drill entry text: bracket tag, then optional prose."""
    if not _DRILL_TYPE_RE.match(drill_type or ""):
        raise ValueError(
            f"invalid drill_type {drill_type!r}: want lowercase [a-z0-9-], 1-32 chars"
        )
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"invalid outcome {outcome!r}: want one of {VALID_OUTCOMES}")
    fields = [f"outcome={outcome}"]
    if duration_minutes is not None:
        if int(duration_minutes) < 1:
            raise ValueError(f"invalid duration_minutes {duration_minutes!r}: want >= 1")
        fields.append(f"duration={int(duration_minutes)}m")
    if participants:
        fields.append("crew=" + ",".join(_normalize_participant(p) for p in participants))
    tag = f"[drill:{drill_type} {' '.join(fields)}]"
    if notes and notes.strip():
        return f"{tag} {notes.strip()}"
    return tag


def is_valid_drill_type(drill_type: str) -> bool:
    """Shared by list_drills' filter validation."""
    return bool(_DRILL_TYPE_RE.match(drill_type or ""))
