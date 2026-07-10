from datetime import datetime
from io import StringIO

from sqlmodel import Session

from app.csv_import import import_feedings_from_text
from app.csv_io import FeedingCsvWriter
from app.models import Feeding


def _make_csv_text(rows):
    output = StringIO()
    writer = FeedingCsvWriter()
    return writer.write_feedings(rows, output)


def test_import_feedings_from_text(test_engine):
    csv_text = _make_csv_text([
        Feeding(timestamp=datetime(2026, 7, 3, 6, 0), po_amount=30, ng_amount=10),
    ])
    with Session(test_engine) as session:
        result = import_feedings_from_text(session, csv_text, skip_existing=False)
    assert result["imported"] == 1
    assert result["skipped"] is False


def test_import_feedings_skips_when_existing(test_engine):
    csv_text = _make_csv_text([
        Feeding(timestamp=datetime(2026, 7, 3, 6, 0), po_amount=30, ng_amount=10),
    ])
    with Session(test_engine) as session:
        import_feedings_from_text(session, csv_text, skip_existing=False)
        result = import_feedings_from_text(session, csv_text, skip_existing=True)
    assert result["imported"] == 0
    assert result["skipped"] is True


def test_import_feedings_from_text_preserves_notes(test_engine):
    csv_text = _make_csv_text([
        Feeding(timestamp=datetime(2026, 7, 3, 6, 0), po_amount=30, ng_amount=10, notes="after nap"),
    ])
    with Session(test_engine) as session:
        result = import_feedings_from_text(session, csv_text, skip_existing=False)
        feeding = session.get(Feeding, 1)
    assert result["imported"] == 1
    assert feeding.notes == "after nap"
