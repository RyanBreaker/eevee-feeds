from datetime import datetime, date
from typing import Optional
from sqlmodel import SQLModel, Field


class Feeding(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime
    po_amount: int = Field(ge=0)
    ng_amount: int = Field(ge=0)
    notes: Optional[str] = None
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
