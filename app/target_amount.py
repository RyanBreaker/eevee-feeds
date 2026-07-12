from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session

from app.models import Feeding, TargetConfig
from app.period import (
    get_period_start,
    get_target_feed_amount,
    get_target_feed_interval,
    get_target_volume,
)
from app.repository import get_previous_feeding


@dataclass
class FeedTarget:
    target_volume: int
    per_feed: int
    interval_minutes: Optional[int]
    actual_interval_minutes: Optional[int]


def compute_feed_target(
    session: Session,
    config: TargetConfig,
    timestamp: datetime,
    exclude_feeding_id: Optional[int] = None,
) -> FeedTarget:
    period_start = get_period_start(timestamp)
    target_volume = get_target_volume(config, period_start.date())
    previous_feeding = get_previous_feeding(
        session, timestamp, exclude_feeding_id=exclude_feeding_id
    )
    previous_timestamp = previous_feeding.timestamp if previous_feeding else None
    per_feed = get_target_feed_amount(target_volume, timestamp, previous_timestamp)

    interval = get_target_feed_interval(timestamp, previous_timestamp)
    if interval is not None:
        interval_minutes = int(interval.total_seconds() // 60)
        assert previous_timestamp is not None
        actual_interval = timestamp - previous_timestamp
        actual_interval_minutes = int(actual_interval.total_seconds() // 60)
    else:
        interval_minutes = None
        actual_interval_minutes = None

    return FeedTarget(
        target_volume=target_volume,
        per_feed=per_feed,
        interval_minutes=interval_minutes,
        actual_interval_minutes=actual_interval_minutes,
    )


def effective_target_for_feeding(
    session: Session, config: TargetConfig, feeding: Feeding
) -> int:
    if feeding.target_per_feed is not None:
        return feeding.target_per_feed
    return compute_feed_target(
        session, config, feeding.timestamp, exclude_feeding_id=feeding.id
    ).per_feed
