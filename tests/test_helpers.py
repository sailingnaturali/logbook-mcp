from logbook_mcp.tools import _format_position, _time_display


def test_format_position_north_west():
    assert _format_position(48.42, -123.27) == "48.4 North, 123.3 West"


def test_format_position_south_east():
    assert _format_position(-55.98, 67.27) == "56.0 South, 67.3 East"


def test_format_position_zero_renders_without_direction():
    assert _format_position(0, 0) == "0.0, 0.0"


def test_format_position_none_is_none():
    assert _format_position(None, None) is None


def test_time_display_localizes_from_entry_position():
    # 18:32Z on 2026-06-05 in America/Vancouver (PDT, UTC-7) is 11:32
    out = _time_display(
        "2026-06-05T18:32:00.000Z",
        {"latitude": 48.42, "longitude": -123.27},
        fallback_tz="UTC",
    )
    assert out == "11:32"


def test_time_display_falls_back_to_configured_tz_without_position():
    out = _time_display("2026-06-05T18:32:00.000Z", None, fallback_tz="America/Vancouver")
    assert out == "11:32"
