from datetime import datetime, date
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import SQLModel, Field


class Feeding(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime
    po_amount: int = Field(ge=0)
    ng_amount: int = Field(ge=0)
    is_snack: bool = Field(default=False)
    target_per_feed: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FeedingStart(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TargetConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    start_date: date
    start_volume: int
    increment: int
    increment_day: str = "Wednesday"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class NotificationLog(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("feeding_id", "threshold_hours"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    feeding_id: int = Field(index=True)
    threshold_hours: int = Field(index=True)
    sent_at: datetime = Field(default_factory=datetime.utcnow)


class BackupLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    period_start: datetime = Field(index=True)
    run_timestamp: datetime
    object_key: str
    success: bool
