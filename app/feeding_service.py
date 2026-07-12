from datetime import datetime
from typing import Optional

from sqlmodel import Session

from app.models import Feeding, FeedingStart, TargetConfig
from app.target_amount import compute_feed_target


def _require_timestamp_not_future(timestamp: datetime) -> None:
    if timestamp > datetime.now():
        raise ValueError("Timestamp cannot be in the future")


def create_feeding(
    session: Session,
    config: TargetConfig,
    timestamp: datetime,
    po_amount: int,
    ng_amount: int,
    notes: Optional[str],
) -> Feeding:
    _require_timestamp_not_future(timestamp)
    target_per_feed = compute_feed_target(session, config, timestamp).per_feed
    feeding = Feeding(
        timestamp=timestamp,
        po_amount=po_amount,
        ng_amount=ng_amount,
        target_per_feed=target_per_feed,
        notes=notes,
    )
    session.add(feeding)
    session.commit()
    session.refresh(feeding)
    return feeding


def update_feeding(
    session: Session,
    config: TargetConfig,
    feeding: Feeding,
    timestamp: datetime,
    po_amount: int,
    ng_amount: int,
    notes: Optional[str],
) -> Feeding:
    _require_timestamp_not_future(timestamp)
    target_per_feed = compute_feed_target(
        session, config, timestamp, exclude_feeding_id=feeding.id
    ).per_feed

    feeding.timestamp = timestamp
    feeding.po_amount = po_amount
    feeding.ng_amount = ng_amount
    feeding.target_per_feed = target_per_feed
    feeding.notes = notes
    feeding.updated_at = datetime.utcnow()
    session.add(feeding)
    session.commit()
    session.refresh(feeding)
    return feeding


def complete_feeding(
    session: Session,
    config: TargetConfig,
    feeding_start: FeedingStart,
    timestamp: datetime,
    po_amount: int,
    ng_amount: int,
    notes: Optional[str],
) -> Feeding:
    _require_timestamp_not_future(timestamp)
    target_per_feed = compute_feed_target(session, config, timestamp).per_feed
    feeding = Feeding(
        timestamp=timestamp,
        po_amount=po_amount,
        ng_amount=ng_amount,
        target_per_feed=target_per_feed,
        notes=notes,
    )
    session.add(feeding)
    session.delete(feeding_start)
    session.commit()
    session.refresh(feeding)
    return feeding


def delete_feeding(session: Session, feeding: Feeding) -> None:
    session.delete(feeding)
    session.commit()
