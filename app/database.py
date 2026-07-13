import os

from sqlalchemy import inspect, text
from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./feedings.db")

# Use psycopg 3 (PostgreSQL driver) if a plain postgresql:// URL is supplied.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


def _add_is_snack_column_if_missing() -> None:
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("feeding")}
    if "is_snack" in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE feeding ADD COLUMN is_snack BOOLEAN NOT NULL DEFAULT FALSE")
        )


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    _add_is_snack_column_if_missing()


def get_session():
    with Session(engine) as session:
        yield session


def session_factory() -> Session:
    return Session(engine)
