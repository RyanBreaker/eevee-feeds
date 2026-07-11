import csv
from datetime import datetime
from io import StringIO

import pytest

from app.csv_io import FeedingCsvReader, FeedingCsvWriter, SCHEMA
from app.models import Feeding


def _make_csv_text(rows):
    output = StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(SCHEMA)
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def test_schema_has_expected_columns():
    assert SCHEMA == ["Timestamp", "PO", "NG", "Total", "Notes"]


def test_reader_parses_basic_row():
    text = _make_csv_text([["Thu, Jul 3, 2026 6:00 AM", 30, 10, 40, "first"]])
    reader = FeedingCsvReader()
    rows = reader.read_rows(text)

    assert len(rows) == 1
    assert rows[0].timestamp == datetime(2026, 7, 3, 6, 0)
    assert rows[0].po_amount == 30
    assert rows[0].ng_amount == 10
    assert rows[0].notes == "first"


def test_reader_parses_nonbreaking_space():
    text = _make_csv_text([["Thu, Jul 3, 2026\u202f6:00 AM", 30, 10, 40, ""]])
    reader = FeedingCsvReader()
    rows = reader.read_rows(text)

    assert rows[0].timestamp == datetime(2026, 7, 3, 6, 0)


def test_reader_returns_feedings():
    text = _make_csv_text([["Thu, Jul 3, 2026 6:00 AM", 30, 10, 40, ""]])
    reader = FeedingCsvReader()
    feedings = reader.read_feedings(text)

    assert len(feedings) == 1
    assert isinstance(feedings[0], Feeding)
    assert feedings[0].timestamp == datetime(2026, 7, 3, 6, 0)
    assert feedings[0].po_amount == 30
    assert feedings[0].ng_amount == 10


def test_reader_rejects_mismatched_total():
    text = _make_csv_text([["Thu, Jul 3, 2026 6:00 AM", 30, 10, 99, ""]])
    reader = FeedingCsvReader()
    with pytest.raises(ValueError):
        reader.read_rows(text)


def test_writer_outputs_header_and_rows():
    writer = FeedingCsvWriter()
    content = writer.write_feedings([
        Feeding(timestamp=datetime(2026, 7, 3, 6, 0), po_amount=30, ng_amount=10, notes="hello"),
    ])

    reader = csv.reader(StringIO(content))
    rows = list(reader)
    assert rows[0] == ["Timestamp", "PO", "NG", "Total", "Notes"]
    assert rows[1] == ["Fri, Jul 03, 2026 06:00 AM", "30", "10", "40", "hello"]


def test_writer_computes_total():
    writer = FeedingCsvWriter()
    content = writer.write_feedings([
        Feeding(timestamp=datetime(2026, 7, 3, 6, 0), po_amount=25, ng_amount=15),
    ])

    reader = csv.reader(StringIO(content))
    rows = list(reader)
    assert rows[1][3] == "40"


def test_round_trip_preserves_feedings():
    original = [
        Feeding(timestamp=datetime(2026, 7, 3, 6, 0), po_amount=30, ng_amount=10, notes="first"),
        Feeding(timestamp=datetime(2026, 7, 3, 9, 0), po_amount=45, ng_amount=5, notes="second"),
    ]

    writer = FeedingCsvWriter()
    content = writer.write_feedings(original)

    csv_reader = FeedingCsvReader()
    imported = csv_reader.read_feedings(content)

    assert len(imported) == 2
    for orig, imp in zip(original, imported):
        assert orig.timestamp == imp.timestamp
        assert orig.po_amount == imp.po_amount
        assert orig.ng_amount == imp.ng_amount
        assert orig.notes == imp.notes
