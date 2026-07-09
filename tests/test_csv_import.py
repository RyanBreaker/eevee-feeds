import csv
from datetime import datetime
from io import StringIO

from sqlmodel import Session

from app.csv_import import import_feedings_from_text, parse_timestamp


def _make_csv(rows):
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "PO", "NG"])
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def test_parse_timestamp():
    ts = parse_timestamp("Thu, Jul 3, 2026 6:00 AM")
    assert ts == datetime(2026, 7, 3, 6, 0)


def test_parse_timestamp_with_nonbreaking_space():
    ts = parse_timestamp("Thu, Jul 3, 2026\u202f6:00 AM")
    assert ts == datetime(2026, 7, 3, 6, 0)


def test_import_feedings_from_text(test_engine):
    csv_text = _make_csv([["Thu, Jul 3, 2026 6:00 AM", 30, 10]])
    with Session(test_engine) as session:
        result = import_feedings_from_text(session, csv_text, skip_existing=False)
    assert result["imported"] == 1
    assert result["skipped"] is False


def test_import_feedings_skips_when_existing(test_engine):
    csv_text = _make_csv([["Thu, Jul 3, 2026 6:00 AM", 30, 10]])
    with Session(test_engine) as session:
        import_feedings_from_text(session, csv_text, skip_existing=False)
        result = import_feedings_from_text(session, csv_text, skip_existing=True)
    assert result["imported"] == 0
    assert result["skipped"] is True
