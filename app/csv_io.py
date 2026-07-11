import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import List, Optional, TextIO

from app.models import Feeding

SCHEMA = ["Timestamp", "PO", "NG", "Total", "Notes"]
_TIMESTAMP_FORMAT = "%a, %b %d, %Y %I:%M %p"


def _normalize_timestamp(raw: str) -> str:
    return raw.replace("\u202f", " ").replace("\xa0", " ")


def _parse_timestamp(raw: str) -> datetime:
    return datetime.strptime(_normalize_timestamp(raw), _TIMESTAMP_FORMAT)


def _format_timestamp(dt: datetime) -> str:
    return dt.strftime(_TIMESTAMP_FORMAT)


@dataclass
class FeedingCsvRow:
    timestamp: datetime
    po_amount: int
    ng_amount: int
    notes: Optional[str] = None


class FeedingCsvReader:
    def read_rows(self, source: str | TextIO) -> List[FeedingCsvRow]:
        if isinstance(source, str):
            source = StringIO(source)
        reader = csv.DictReader(source)
        rows: List[FeedingCsvRow] = []
        for row in reader:
            po_amount = int(row["PO"])
            ng_amount = int(row["NG"])
            total_raw = row.get("Total")
            if total_raw:
                expected_total = po_amount + ng_amount
                if int(total_raw) != expected_total:
                    raise ValueError(
                        f"CSV Total mismatch: {total_raw} != {expected_total} "
                        f"for {row['Timestamp']}"
                    )
            rows.append(
                FeedingCsvRow(
                    timestamp=_parse_timestamp(row["Timestamp"]),
                    po_amount=po_amount,
                    ng_amount=ng_amount,
                    notes=row.get("Notes") or None,
                )
            )
        return rows

    def read_feedings(self, source: str | TextIO) -> List[Feeding]:
        return [
            Feeding(
                timestamp=row.timestamp,
                po_amount=row.po_amount,
                ng_amount=row.ng_amount,
                notes=row.notes,
            )
            for row in self.read_rows(source)
        ]


class FeedingCsvWriter:
    def write_rows(self, rows: List[FeedingCsvRow], output: Optional[TextIO] = None) -> str:
        if output is None:
            output = StringIO()
        writer = csv.DictWriter(output, fieldnames=SCHEMA)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Timestamp": _format_timestamp(row.timestamp),
                    "PO": row.po_amount,
                    "NG": row.ng_amount,
                    "Total": row.po_amount + row.ng_amount,
                    "Notes": row.notes or "",
                }
            )
        if isinstance(output, StringIO):
            return output.getvalue()
        return ""

    def write_feedings(self, feedings: List[Feeding], output: Optional[TextIO] = None) -> str:
        rows = [
            FeedingCsvRow(
                timestamp=f.timestamp,
                po_amount=f.po_amount,
                ng_amount=f.ng_amount,
                notes=f.notes,
            )
            for f in feedings
        ]
        return self.write_rows(rows, output)
