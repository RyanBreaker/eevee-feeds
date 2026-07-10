from datetime import date, datetime, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.models import Feeding, TargetConfig
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


def get_last_feeding(session: Session) -> Optional[Feeding]:
    return session.exec(
        select(Feeding).order_by(Feeding.timestamp.desc()).limit(1)
    ).first()


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


def _get_most_recent_feeding_before(
    session: Session, timestamp: datetime
) -> Optional[Feeding]:
    return session.exec(
        select(Feeding)
        .where(Feeding.timestamp < timestamp)
        .order_by(Feeding.timestamp.desc())
        .limit(1)
    ).first()


def get_feedings_with_gaps(
    session: Session, period_start: datetime
) -> list[tuple[Feeding, Optional[timedelta]]]:
    previous_feeding = _get_most_recent_feeding_before(session, period_start)

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
        previous_feeding = _get_most_recent_feeding_before(session, period_start)

    if previous_feeding:
        return feeding.timestamp - previous_feeding.timestamp
    return None
