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


def validate_drill_type(drill_type: str | None) -> None:
    """Raise ValueError unless drill_type is lowercase [a-z0-9-], 1-32 chars."""
    if not _DRILL_TYPE_RE.match(drill_type or ""):
        raise ValueError(
            f"invalid drill_type {drill_type!r}: want lowercase [a-z0-9-], 1-32 chars"
        )


def _normalize_participant(name: str) -> str:
    """Tag fields split on whitespace and crew splits on commas, so names
    may contain neither: internal whitespace becomes hyphens, commas and
    brackets are an error."""
    name = name.strip()
    if not name:
        raise ValueError("participant name is empty")
    if "," in name:
        raise ValueError(f"participant name may not contain a comma: {name!r}")
    if "[" in name or "]" in name:
        raise ValueError(f"participant name may not contain brackets: {name!r}")
    return re.sub(r"\s+", "-", name)


def compose_drill_text(
    drill_type: str,
    outcome: str,
    duration_minutes: int | None = None,
    participants: list[str] | None = None,
    notes: str | None = None,
) -> str:
    """Build the drill entry text: bracket tag, then optional prose."""
    validate_drill_type(drill_type)
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"invalid outcome {outcome!r}: want one of {VALID_OUTCOMES}")
    fields = [f"outcome={outcome}"]
    if duration_minutes is not None:
        if duration_minutes != int(duration_minutes) or int(duration_minutes) < 1:
            raise ValueError(
                f"invalid duration_minutes {duration_minutes!r}: want a whole number >= 1"
            )
        fields.append(f"duration={int(duration_minutes)}m")
    if participants:
        fields.append("crew=" + ",".join(_normalize_participant(p) for p in participants))
    tag = f"[drill:{drill_type} {' '.join(fields)}]"
    if notes and notes.strip():
        return f"{tag} {notes.strip()}"
    return tag


_TAG_RE = re.compile(
    r"^\[drill:([a-z0-9-]{1,32})((?:\s+[a-z]+=[^\s\]]+)*)\]\s*(.*)$",
    re.DOTALL,
)

_DURATION_RE = re.compile(r"^[1-9]\d*m$")


def parse_drill_tag(text: str) -> dict | None:
    """Parse a drill tag at the start of entry text.

    Returns ``{drill_type, outcome, duration_minutes, participants, notes}``
    or None when the text doesn't open with a well-formed tag. Unknown
    ``key=value`` fields are ignored; recognized fields with malformed values
    degrade to None rather than failing the whole tag.
    """
    m = _TAG_RE.match(text or "")
    if not m:
        return None
    drill_type, raw_fields, notes = m.group(1), m.group(2), m.group(3)
    parsed: dict = {
        "drill_type": drill_type,
        "outcome": None,
        "duration_minutes": None,
        "participants": None,
        "notes": notes.strip() or None,
    }
    for field in raw_fields.split():
        key, _, value = field.partition("=")
        if key == "outcome" and value in VALID_OUTCOMES:
            parsed["outcome"] = value
        elif key == "duration" and _DURATION_RE.match(value):
            parsed["duration_minutes"] = int(value[:-1])
        elif key == "crew" and value:
            parsed["participants"] = value.split(",")
    return parsed
