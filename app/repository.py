from datetime import date, datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.models import Feeding, FeedingStart, TargetConfig
from app.period import get_period_start, get_target_feed_amount, get_target_volume


def get_default_target_config() -> TargetConfig:
    return TargetConfig(
        start_date=date(2026, 7, 3),
        start_volume=520,
        increment=40,
        increment_day="Wednesday",
    )


def get_or_create_config(session: Session) -> TargetConfig:
    config = session.exec(select(TargetConfig)).first()
    if not config:
        config = get_default_target_config()
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


def get_feeding_by_id(session: Session, feeding_id: int) -> Optional[Feeding]:
    return session.get(Feeding, feeding_id)


def get_last_feeding(session: Session) -> Optional[Feeding]:
    return session.exec(
        select(Feeding).order_by(Feeding.timestamp.desc()).limit(1)
    ).first()


def has_feedings(session: Session) -> bool:
    return session.exec(select(Feeding)).first() is not None


def get_all_feedings(session: Session) -> list[Feeding]:
    return list(session.exec(select(Feeding).order_by(Feeding.timestamp)).all())


def get_feedings_for_period(session: Session, period_start: datetime) -> list[Feeding]:
    next_period_start = period_start + timedelta(days=1)
    statement = (
        select(Feeding)
        .where(Feeding.timestamp >= period_start, Feeding.timestamp < next_period_start)
        .order_by(Feeding.timestamp)
    )
    return list(session.exec(statement).all())


def get_previous_feeding(
    session: Session,
    timestamp: datetime,
    exclude_feeding_id: Optional[int] = None,
) -> Optional[Feeding]:
    """Return the most recent Feeding strictly before ``timestamp``.

    If ``exclude_feeding_id`` is provided, that Feeding is omitted from the
    search so that editing a Feeding does not use the feeding itself as the
    reference point.
    """
    statement = select(Feeding).where(Feeding.timestamp < timestamp)
    if exclude_feeding_id is not None:
        statement = statement.where(Feeding.id != exclude_feeding_id)
    return session.exec(
        statement.order_by(Feeding.timestamp.desc()).limit(1)
    ).first()


def get_inferred_target_per_feed(
    session: Session, config: TargetConfig, feeding: Feeding
) -> int:
    """Compute the suggested per-feed amount for ``feeding`` dynamically.

    Used as a fallback when a Feeding was created before ``target_per_feed``
    was stored (legacy/imported data).
    """
    period_start = get_period_start(feeding.timestamp)
    target = get_target_volume(config, period_start.date())
    previous_feeding = get_previous_feeding(
        session, feeding.timestamp, exclude_feeding_id=feeding.id
    )
    previous_timestamp = previous_feeding.timestamp if previous_feeding else None
    return get_target_feed_amount(target, feeding.timestamp, previous_timestamp)


def get_effective_target_per_feed(
    session: Session, config: TargetConfig, feeding: Feeding
) -> int:
    """Return the stored target if available, otherwise infer it."""
    if feeding.target_per_feed is not None:
        return feeding.target_per_feed
    return get_inferred_target_per_feed(session, config, feeding)


def attach_effective_targets(
    session: Session,
    config: TargetConfig,
    feedings_with_gaps: list[tuple[Feeding, Optional[timedelta]]],
) -> list[tuple[Feeding, Optional[timedelta]]]:
    """Set ``feeding.effective_target`` on each feeding for template use."""
    for feeding, _ in feedings_with_gaps:
        # Bypass Pydantic so we can attach a transient computed value.
        object.__setattr__(
            feeding,
            "effective_target",
            get_effective_target_per_feed(session, config, feeding),
        )
    return feedings_with_gaps


def get_feedings_with_gaps(
    session: Session, period_start: datetime
) -> list[tuple[Feeding, Optional[timedelta]]]:
    previous_feeding = get_previous_feeding(session, period_start)

    feedings = get_feedings_for_period(session, period_start)
    result = []
    last_time = previous_feeding.timestamp if previous_feeding else None

    for feeding in feedings:
        gap = feeding.timestamp - last_time if last_time else None
        result.append((feeding, gap))
        last_time = feeding.timestamp

    return result


def get_feeding_gap(session: Session, feeding: Feeding) -> Optional[timedelta]:
    period_start = get_period_start(feeding.timestamp)
    previous_feeding = session.exec(
        select(Feeding)
        .where(Feeding.timestamp < feeding.timestamp, Feeding.timestamp >= period_start)
        .order_by(Feeding.timestamp.desc())
        .limit(1)
    ).first()

    if not previous_feeding:
        previous_feeding = get_previous_feeding(session, period_start)

    if previous_feeding:
        return feeding.timestamp - previous_feeding.timestamp
    return None


def get_feeding_start(session: Session) -> Optional[FeedingStart]:
    return session.exec(select(FeedingStart)).first()


def create_feeding_start(session: Session, timestamp: datetime) -> FeedingStart:
    feeding_start = FeedingStart(timestamp=timestamp)
    session.add(feeding_start)
    session.commit()
    session.refresh(feeding_start)
    return feeding_start


def delete_feeding_start(session: Session, feeding_start: FeedingStart) -> None:
    session.delete(feeding_start)
    session.commit()


def update_feeding_start_timestamp(
    session: Session, feeding_start: FeedingStart, timestamp: datetime
) -> FeedingStart:
    feeding_start.timestamp = timestamp
    feeding_start.updated_at = datetime.utcnow()
    session.add(feeding_start)
    session.commit()
    session.refresh(feeding_start)
    return feeding_start
