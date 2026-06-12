import pytest

from logbook_mcp.drills import compose_drill_text


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
