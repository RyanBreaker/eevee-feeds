from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine, text

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
