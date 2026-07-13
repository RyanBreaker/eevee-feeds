from datetime import date, datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.models import Feeding, FeedingStart, TargetConfig
from app.period import get_period_start


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


def get_last_feeding(session: Session, skip_snacks: bool = False) -> Optional[Feeding]:
    statement = select(Feeding)
    if skip_snacks:
        statement = statement.where(Feeding.is_snack == False)
    return session.exec(
        statement.order_by(Feeding.timestamp.desc()).limit(1)
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
    skip_snacks: bool = False,
) -> Optional[Feeding]:
    """Return the most recent Feeding strictly before ``timestamp``.

    If ``exclude_feeding_id`` is provided, that Feeding is omitted from the
    search so that editing a Feeding does not use the feeding itself as the
    reference point.

    If ``skip_snacks`` is True, Snack feedings are excluded so the result can
    be used as the schedule-relevant previous Feeding.
    """
    statement = select(Feeding).where(Feeding.timestamp < timestamp)
    if exclude_feeding_id is not None:
        statement = statement.where(Feeding.id != exclude_feeding_id)
    if skip_snacks:
        statement = statement.where(Feeding.is_snack == False)
    return session.exec(
        statement.order_by(Feeding.timestamp.desc()).limit(1)
    ).first()


def get_feedings_with_gaps(
    session: Session, period_start: datetime
) -> list[tuple[Feeding, Optional[timedelta]]]:
    previous_feeding = get_previous_feeding(session, period_start, skip_snacks=True)

    feedings = get_feedings_for_period(session, period_start)
    result = []
    last_time = previous_feeding.timestamp if previous_feeding else None

    for feeding in feedings:
        gap = feeding.timestamp - last_time if last_time else None
        result.append((feeding, gap))
        if not feeding.is_snack:
            last_time = feeding.timestamp

    return result


def get_feeding_gap(session: Session, feeding: Feeding) -> Optional[timedelta]:
    period_start = get_period_start(feeding.timestamp)
    previous_feeding = session.exec(
        select(Feeding)
        .where(
            Feeding.timestamp < feeding.timestamp,
            Feeding.timestamp >= period_start,
            Feeding.is_snack == False,
        )
        .order_by(Feeding.timestamp.desc())
        .limit(1)
    ).first()

    if not previous_feeding:
        previous_feeding = get_previous_feeding(session, period_start, skip_snacks=True)

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
