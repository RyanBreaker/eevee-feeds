from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session

from app.models import Feeding
from app.repository import get_or_create_config
from app.target_amount import (
    FeedTarget,
    compute_feed_target,
    effective_target_for_feeding,
)


@pytest.fixture
def session(test_engine):
    with Session(test_engine) as session:
        yield session


def test_compute_feed_target_fallback_with_no_previous_feeding(session):
    config = get_or_create_config(session)
    config.start_volume = 520
    config.increment = 0
    session.add(config)

    result = compute_feed_target(
        session, config, datetime(2026, 7, 3, 8, 0)
    )

    assert isinstance(result, FeedTarget)
    assert result.target_volume == 520
    assert result.per_feed == 65
    assert result.interval_minutes is None
    assert result.actual_interval_minutes is None


def test_compute_feed_target_uses_previous_feeding_interval(session):
    config = get_or_create_config(session)
    config.start_volume = 520
    config.increment = 0
    session.add(config)

    previous = Feeding(
        timestamp=datetime(2026, 7, 3, 5, 0), po_amount=30, ng_amount=10
    )
    session.add(previous)
    session.commit()

    result = compute_feed_target(
        session, config, datetime(2026, 7, 3, 8, 0)
    )

    assert result.target_volume == 520
    assert result.per_feed == 65
    assert result.interval_minutes == 180
    assert result.actual_interval_minutes == 180


def test_compute_feed_target_rounds_up(session):
    config = get_or_create_config(session)
    config.start_volume = 550
    config.increment = 0
    session.add(config)

    previous = Feeding(
        timestamp=datetime(2026, 7, 3, 5, 0), po_amount=30, ng_amount=10
    )
    session.add(previous)
    session.commit()

    result = compute_feed_target(
        session, config, datetime(2026, 7, 3, 8, 0)
    )

    assert result.per_feed == 69
    assert result.actual_interval_minutes == 180


def test_compute_feed_target_excludes_given_feeding_id(session):
    config = get_or_create_config(session)
    config.start_volume = 560
    config.increment = 0
    session.add(config)

    earlier = Feeding(
        timestamp=datetime(2026, 7, 9, 6, 0), po_amount=30, ng_amount=10
    )
    current = Feeding(
        timestamp=datetime(2026, 7, 9, 9, 0), po_amount=30, ng_amount=10
    )
    session.add_all([earlier, current])
    session.commit()

    result = compute_feed_target(
        session,
        config,
        datetime(2026, 7, 9, 12, 0),
        exclude_feeding_id=current.id,
    )

    # 6-hour actual interval, capped to 4 hours -> 560 * 4 / 24 = 93
    assert result.per_feed == 93
    assert result.actual_interval_minutes == 360
    assert result.interval_minutes == 240


def test_compute_feed_target_skips_snacks(session):
    config = get_or_create_config(session)
    config.start_volume = 520
    config.increment = 0
    session.add(config)

    real_feeding = Feeding(
        timestamp=datetime(2026, 7, 3, 5, 0), po_amount=30, ng_amount=10
    )
    snack = Feeding(
        timestamp=datetime(2026, 7, 3, 7, 0),
        po_amount=10,
        ng_amount=5,
        is_snack=True,
    )
    session.add_all([real_feeding, snack])
    session.commit()

    result = compute_feed_target(session, config, datetime(2026, 7, 3, 9, 0))

    # Interval should be from real_feeding at 5:00, not snack at 7:00 -> 4 h
    assert result.per_feed == 87
    assert result.actual_interval_minutes == 240
    assert result.interval_minutes == 240


def test_compute_feed_target_clamps_to_floor(session):
    config = get_or_create_config(session)
    config.start_volume = 560
    config.increment = 0
    session.add(config)

    previous = Feeding(
        timestamp=datetime(2026, 7, 9, 5, 30), po_amount=30, ng_amount=10
    )
    session.add(previous)
    session.commit()

    result = compute_feed_target(
        session, config, datetime(2026, 7, 9, 6, 30)
    )

    assert result.per_feed == 47
    assert result.actual_interval_minutes == 60
    assert result.interval_minutes == 120


def test_compute_feed_target_respects_period_target_volume(session):
    config = get_or_create_config(session)
    config.start_date = date(2026, 7, 3)
    config.start_volume = 520
    config.increment = 40
    config.increment_day = "Wednesday"
    session.add(config)

    result = compute_feed_target(
        session, config, datetime(2026, 7, 9, 8, 0)
    )

    assert result.target_volume == 560


def test_effective_target_for_feeding_prefers_stored_value(session):
    config = get_or_create_config(session)
    feeding = Feeding(
        timestamp=datetime(2026, 7, 10, 9, 0),
        po_amount=40,
        ng_amount=10,
        target_per_feed=99,
    )
    session.add(feeding)
    session.commit()

    assert effective_target_for_feeding(session, config, feeding) == 99


def test_effective_target_for_feeding_infers_when_not_stored(session):
    config = get_or_create_config(session)
    config.start_volume = 520
    config.increment = 0
    session.add(config)

    feeding = Feeding(
        timestamp=datetime(2026, 7, 10, 9, 0), po_amount=40, ng_amount=10
    )
    session.add(feeding)
    session.commit()

    assert effective_target_for_feeding(session, config, feeding) == 65


def test_effective_target_for_snack_is_none(session):
    config = get_or_create_config(session)
    config.start_volume = 520
    config.increment = 0
    session.add(config)

    feeding = Feeding(
        timestamp=datetime(2026, 7, 10, 9, 0),
        po_amount=40,
        ng_amount=10,
        is_snack=True,
    )
    session.add(feeding)
    session.commit()

    assert effective_target_for_feeding(session, config, feeding) is None
