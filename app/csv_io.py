import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import List, Optional, TextIO

from app.models import Feeding

SCHEMA = ["Timestamp", "PO", "NG", "Total", "Target", "Is Snack", "Notes"]
_TIMESTAMP_FORMAT = "%a, %b %d, %Y %I:%M %p"


def _normalize_timestamp(raw: str) -> str:
    return raw.replace("\u202f", " ").replace("\xa0", " ")


def _parse_timestamp(raw: str) -> datetime:
    return datetime.strptime(_normalize_timestamp(raw), _TIMESTAMP_FORMAT)


def _format_timestamp(dt: datetime) -> str:
    return dt.strftime(_TIMESTAMP_FORMAT)


def _parse_bool(raw: Optional[str]) -> bool:
    return raw is not None and raw.strip().lower() in {"true", "1", "yes"}


@dataclass
class FeedingCsvRow:
    timestamp: datetime
    po_amount: int
    ng_amount: int
    notes: Optional[str] = None
    target_per_feed: Optional[int] = None
    is_snack: bool = False


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
            target_raw = row.get("Target")
            target_per_feed = int(target_raw) if target_raw else None
            is_snack = _parse_bool(row.get("Is Snack"))
            if is_snack:
                target_per_feed = None
            rows.append(
                FeedingCsvRow(
                    timestamp=_parse_timestamp(row["Timestamp"]),
                    po_amount=po_amount,
                    ng_amount=ng_amount,
                    notes=row.get("Notes") or None,
                    target_per_feed=target_per_feed,
                    is_snack=is_snack,
                )
            )
        return rows

    def read_feedings(self, source: str | TextIO) -> List[Feeding]:
        return [
            Feeding(
                timestamp=row.timestamp,
                po_amount=row.po_amount,
                ng_amount=row.ng_amount,
                target_per_feed=row.target_per_feed,
                is_snack=row.is_snack,
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
                    "Target": row.target_per_feed if row.target_per_feed is not None else "",
                    "Is Snack": "true" if row.is_snack else "false",
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
                target_per_feed=f.target_per_feed,
                is_snack=f.is_snack,
            )
            for f in feedings
        ]
        return self.write_rows(rows, output)
