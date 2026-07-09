import csv
from datetime import datetime
from io import StringIO, TextIOWrapper
from typing import Optional, TextIO

from sqlmodel import Session, select

from app.models import Feeding, TargetConfig


def parse_timestamp(raw: str) -> datetime:
    # Normalize non-breaking spaces that may appear in exported dates.
    cleaned = raw.replace("\u202f", " ").replace("\xa0", " ")
    return datetime.strptime(cleaned, "%a, %b %d, %Y %I:%M %p")


def seed_config(session: Session) -> None:
    existing = session.exec(select(TargetConfig)).first()
    if existing:
        return

    config = TargetConfig(
        start_date=datetime(2026, 7, 3).date(),
        start_volume=520,
        increment=40,
        increment_day="Wednesday",
    )
    session.add(config)


def import_feedings_from_csv(session: Session, file: TextIO, skip_existing: bool = True) -> dict:
    """Import feedings from a CSV file. Returns a summary dict."""
    seed_config(session)

    if skip_existing:
        existing = session.exec(select(Feeding)).first()
        if existing is not None:
            return {"imported": 0, "skipped": True}

    reader = csv.DictReader(file)
    count = 0
    for row in reader:
        timestamp = parse_timestamp(row["Timestamp"])
        po = int(row["PO"])
        ng = int(row["NG"])
        feeding = Feeding(timestamp=timestamp, po_amount=po, ng_amount=ng)
        session.add(feeding)
        count += 1

    session.commit()
    return {"imported": count, "skipped": False}


def import_feedings_from_text(session: Session, text: str, skip_existing: bool = True) -> dict:
    return import_feedings_from_csv(session, StringIO(text), skip_existing=skip_existing)
