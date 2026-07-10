"""derive_origin: explicit field wins; else author conventions decide."""

from logbook_mcp.tools import DEFAULT_AGENT_AUTHORS, derive_origin


def test_explicit_origin_field_wins_over_author():
    assert derive_origin({"origin": "manual", "author": "poseidon"}) == "manual"
    assert derive_origin({"origin": "auto", "author": "Bryan"}) == "auto"
    assert derive_origin({"origin": "agent", "author": ""}) == "agent"


def test_unknown_explicit_origin_falls_back_to_heuristic():
    # A future upstream enum value must not leak through as-is.
    assert derive_origin({"origin": "import", "author": ""}) == "auto"


def test_empty_or_missing_author_is_auto():
    assert derive_origin({"author": ""}) == "auto"
    assert derive_origin({}) == "auto"


def test_agent_principal_is_agent():
    assert derive_origin({"author": "hermes"}) == "agent"
    assert derive_origin({"author": "poseidon"}) == "agent"
    assert "hermes" in DEFAULT_AGENT_AUTHORS and "poseidon" in DEFAULT_AGENT_AUTHORS


def test_auto_principal_is_auto():
    assert derive_origin({"author": "dsc-logger"}, auto_authors=frozenset({"dsc-logger"})) == "auto"


def test_anything_else_is_manual():
    assert derive_origin({"author": "Bryan Clark"}) == "manual"
    assert derive_origin({"author": "bryan"}) == "manual"
