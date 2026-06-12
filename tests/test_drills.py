import pytest

from logbook_mcp.drills import compose_drill_text, parse_drill_tag


def test_compose_full_tag():
    text = compose_drill_text(
        "mob", "pass",
        duration_minutes=14,
        participants=["Bryan", "K"],
        notes="Lifesling recovery under power, contact in 4 min.",
    )
    assert text == (
        "[drill:mob outcome=pass duration=14m crew=Bryan,K] "
        "Lifesling recovery under power, contact in 4 min."
    )


def test_compose_minimal_tag_no_optionals():
    assert compose_drill_text("fire", "partial") == "[drill:fire outcome=partial]"


def test_compose_normalizes_participant_whitespace_to_hyphens():
    text = compose_drill_text("mob", "pass", participants=["Bryan Clark", " K  Lee "])
    assert text == "[drill:mob outcome=pass crew=Bryan-Clark,K-Lee]"


def test_compose_rejects_comma_in_participant():
    with pytest.raises(ValueError, match="comma"):
        compose_drill_text("mob", "pass", participants=["Clark, Bryan"])


def test_compose_rejects_brackets_in_participant():
    for bad in ("Bryan]Name", "Bryan[Name"):
        with pytest.raises(ValueError, match="bracket"):
            compose_drill_text("mob", "pass", participants=[bad])


def test_compose_rejects_bad_drill_type():
    for bad in ("MOB", "man overboard", "", "x" * 33, "mob!"):
        with pytest.raises(ValueError, match="drill_type"):
            compose_drill_text(bad, "pass")


def test_compose_rejects_bad_outcome():
    with pytest.raises(ValueError, match="outcome"):
        compose_drill_text("mob", "aced-it")


def test_compose_rejects_nonpositive_duration():
    with pytest.raises(ValueError, match="duration"):
        compose_drill_text("mob", "pass", duration_minutes=0)


def test_compose_rejects_fractional_duration():
    with pytest.raises(ValueError, match="duration"):
        compose_drill_text("mob", "pass", duration_minutes=14.7)


def test_parse_full_tag():
    parsed = parse_drill_tag(
        "[drill:mob outcome=pass duration=14m crew=Bryan,K] "
        "Lifesling recovery under power."
    )
    assert parsed == {
        "drill_type": "mob",
        "outcome": "pass",
        "duration_minutes": 14,
        "participants": ["Bryan", "K"],
        "notes": "Lifesling recovery under power.",
    }


def test_parse_minimal_tag():
    assert parse_drill_tag("[drill:fire outcome=partial]") == {
        "drill_type": "fire",
        "outcome": "partial",
        "duration_minutes": None,
        "participants": None,
        "notes": None,
    }


def test_compose_parse_round_trip():
    text = compose_drill_text(
        "steering-failure", "fail",
        duration_minutes=25,
        participants=["Bryan Clark"],
        notes="Emergency tiller jammed; needs rework [see maintenance log].",
    )
    parsed = parse_drill_tag(text)
    assert parsed == {
        "drill_type": "steering-failure",
        "outcome": "fail",
        "duration_minutes": 25,
        "participants": ["Bryan-Clark"],
        "notes": "Emergency tiller jammed; needs rework [see maintenance log].",
    }


def test_parse_ignores_unknown_fields():
    # Forward compatibility: a future writer may add fields we don't know.
    parsed = parse_drill_tag("[drill:mob outcome=pass wind=15kn] notes")
    assert parsed["outcome"] == "pass"
    assert parsed["notes"] == "notes"


def test_parse_non_drill_text_returns_none():
    for text in (
        "Beautiful sunset off Discovery Island",
        "",
        "[drill:] missing type",
        "[drill:MOB outcome=pass] uppercase type",
        "prose before [drill:mob outcome=pass] tag not at start",
    ):
        assert parse_drill_tag(text) is None


def test_parse_tolerates_malformed_field_values():
    # Bad field values degrade to None for that field; the tag still parses.
    parsed = parse_drill_tag("[drill:mob outcome=heroic duration=fast]")
    assert parsed["drill_type"] == "mob"
    assert parsed["outcome"] is None
    assert parsed["duration_minutes"] is None


def test_parse_rejects_zero_or_padded_duration():
    for text in ("[drill:mob outcome=pass duration=0m]",
                 "[drill:mob outcome=pass duration=007m]"):
        assert parse_drill_tag(text)["duration_minutes"] is None
