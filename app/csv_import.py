from io import StringIO
from typing import TextIO

from sqlmodel import Session, select

from app.csv_io import FeedingCsvReader
from app.models import Feeding
from app.repository import get_or_create_config


def import_feedings_from_csv(
    session: Session, file: TextIO, skip_existing: bool = True
) -> dict:
    """Import feedings from a CSV file. Returns a summary dict."""
    get_or_create_config(session)

    if skip_existing:
        existing = session.exec(select(Feeding)).first()
        if existing is not None:
            return {"imported": 0, "skipped": True}

    reader = FeedingCsvReader()
    feedings = reader.read_feedings(file)
    count = 0
    for feeding in feedings:
        session.add(feeding)
        count += 1

    session.commit()
    return {"imported": count, "skipped": False}


def import_feedings_from_text(session: Session, text: str, skip_existing: bool = True) -> dict:
    return import_feedings_from_csv(session, StringIO(text), skip_existing=skip_existing)
