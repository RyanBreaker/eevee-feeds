from sqlalchemy import Column, Date, DateTime, Integer, MetaData, String, Table, create_engine, text

import app.database as database_module
from app.database import create_db_and_tables


def test_create_db_and_tables_adds_missing_is_snack_column():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    # Create a pre-migration feeding table without is_snack.
    Table(
        "feeding",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("timestamp", DateTime, nullable=False),
        Column("po_amount", Integer, nullable=False),
        Column("ng_amount", Integer, nullable=False),
        Column("target_per_feed", Integer),
        Column("notes", String),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
    )
    metadata.create_all(engine)

    # Confirm the legacy schema does not have is_snack.
    with engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(feeding)")
            )
        }
    assert "is_snack" not in columns

    # Run the app startup routine against this engine.
    original_engine = database_module.engine
    database_module.engine = engine
    try:
        create_db_and_tables()
    finally:
        database_module.engine = original_engine

    with engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(feeding)")
            )
        }
    assert "is_snack" in columns


def test_create_db_and_tables_adds_missing_period_start_time_column():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()

    # Create a pre-migration targetconfig table without period_start_time,
    # with one existing config row.
    Table(
        "targetconfig",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("start_date", Date, nullable=False),
        Column("start_volume", Integer, nullable=False),
        Column("increment", Integer, nullable=False),
        Column("increment_day", String, nullable=False),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO targetconfig "
                "(start_date, start_volume, increment, increment_day, created_at, updated_at) "
                "VALUES ('2026-07-03', 520, 40, 'Wednesday', '2026-07-03 00:00:00', '2026-07-03 00:00:00')"
            )
        )

    # Run the app startup routine against this engine.
    original_engine = database_module.engine
    database_module.engine = engine
    try:
        create_db_and_tables()
    finally:
        database_module.engine = original_engine

    with engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(targetconfig)")
            )
        }
        row = conn.execute(
            text("SELECT period_start_time FROM targetconfig")
        ).first()
    assert "period_start_time" in columns
    # Existing rows get the 6:00 AM default, preserving current behavior.
    assert row[0] == "06:00:00"
