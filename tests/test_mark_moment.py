import os
import tempfile

import pytest

from logbook_mcp.db import LogbookDB
from logbook_mcp.tools import mark_moment


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = LogbookDB(path)
    db.init_schema()
    yield db
    db.close()
    os.unlink(path)


def test_mark_moment_persists_text_and_timestamp(db):
    """mark_moment stores the text and returns id + entry_display + timestamp."""
    result = mark_moment(db, text="Beautiful sunset off Discovery Island")

    assert isinstance(result["id"], int)
    assert result["entry_display"] == f"Entry {result['id']}"
    assert result["text"] == "Beautiful sunset off Discovery Island"
    assert result["timestamp"].endswith("Z")

    rows = db.query(
        "SELECT id, text FROM marked_moments WHERE id = ?", (result["id"],)
    )
    assert len(rows) == 1
    assert rows[0]["text"] == "Beautiful sunset off Discovery Island"


def test_mark_moment_accepts_optional_position(db):
    """mark_moment records a {longitude, latitude} if provided and round-trips it."""
    result = mark_moment(
        db,
        text="Discovery Island sunset",
        position={"longitude": -123.27, "latitude": 48.42},
    )
    rows = db.query(
        "SELECT longitude, latitude FROM marked_moments WHERE id = ?", (result["id"],)
    )
    assert rows[0]["longitude"] == -123.27
    assert rows[0]["latitude"] == 48.42
    assert result["position"] == {"longitude": -123.27, "latitude": 48.42}
    assert result["position_display"] == "48.4200 North, 123.2700 West"


def test_mark_moment_without_position_stores_nulls(db):
    """mark_moment with no position stores NULL for longitude/latitude."""
    result = mark_moment(db, text="No position provided")
    rows = db.query(
        "SELECT longitude, latitude FROM marked_moments WHERE id = ?", (result["id"],)
    )
    assert rows[0]["longitude"] is None
    assert rows[0]["latitude"] is None
    assert result["position"] is None
    assert result["position_display"] is None


def test_mark_moment_zero_coordinates_render_without_direction(db):
    """0 latitude/longitude render as bare magnitudes (neither N/S nor E/W)."""
    result = mark_moment(
        db,
        text="Null Island",
        position={"longitude": 0, "latitude": 0},
    )
    assert result["position_display"] == "0.0000, 0.0000"


def test_mark_moment_southern_western_hemisphere(db):
    """Negative lat/lon render as South/West."""
    result = mark_moment(
        db,
        text="Cape Horn",
        position={"longitude": -67.27, "latitude": -55.98},
    )
    assert result["position_display"] == "55.9800 South, 67.2700 West"
