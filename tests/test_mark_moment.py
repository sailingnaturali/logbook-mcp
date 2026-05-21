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
    """mark_moment stores the text and returns an id + timestamp."""
    result = mark_moment(db, text="Beautiful sunset off Discovery Island")

    assert "timestamp" in result
    assert "id" not in result
    assert result["text"] == "Beautiful sunset off Discovery Island"
    assert result["entry_display"].startswith("Entry ")

    entry_id = int(result["entry_display"].split()[-1])
    rows = db.query(
        "SELECT id, text FROM marked_moments WHERE id = ?", (entry_id,)
    )
    assert len(rows) == 1
    assert rows[0]["text"] == "Beautiful sunset off Discovery Island"


def test_mark_moment_accepts_optional_position(db):
    """mark_moment records a {longitude, latitude} if provided."""
    result = mark_moment(
        db,
        text="Discovery Island sunset",
        position={"longitude": -123.27, "latitude": 48.42},
    )
    entry_id = int(result["entry_display"].split()[-1])
    rows = db.query(
        "SELECT longitude, latitude FROM marked_moments WHERE id = ?", (entry_id,)
    )
    assert rows[0]["longitude"] == -123.27
    assert rows[0]["latitude"] == 48.42
    assert result["position_display"] == "48.4200 North, 123.2700 West"
    assert "position" not in result


def test_mark_moment_without_position_stores_nulls(db):
    """mark_moment with no position stores NULL for longitude/latitude."""
    result = mark_moment(db, text="No position provided")
    rows = db.query(
        "SELECT longitude, latitude FROM marked_moments WHERE id = ?",
        (int(result["entry_display"].split()[-1]),),
    )
    assert rows[0]["longitude"] is None
    assert rows[0]["latitude"] is None
    assert result["position_display"] is None
