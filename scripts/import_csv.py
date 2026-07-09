import csv
from datetime import datetime

from sqlmodel import Session, select

from app.database import create_db_and_tables, engine
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


def main() -> None:
    create_db_and_tables()

    with Session(engine) as session:
        seed_config(session)

        existing_count = session.exec(select(Feeding)).first()
        if existing_count is not None:
            print("Feedings already exist in the database. Skipping import.")
            return

        with open("feedings.csv", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                timestamp = parse_timestamp(row["Timestamp"])
                po = int(row["PO"])
                ng = int(row["NG"])
                feeding = Feeding(timestamp=timestamp, po_amount=po, ng_amount=ng)
                session.add(feeding)

        session.commit()
        print("Import complete.")


if __name__ == "__main__":
    main()
