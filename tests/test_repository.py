from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session

from app.models import Feeding
from app.repository import (
    get_all_feedings,
    get_default_target_config,
    get_feeding_by_id,
    get_feeding_gap,
    get_feedings_for_period,
    get_feedings_with_gaps,
    get_last_feeding,
    get_or_create_config,
    get_previous_feeding,
)


@pytest.fixture
def session(test_engine):
    with Session(test_engine) as session:
        yield session


def test_get_default_target_config():
    config = get_default_target_config()
    assert config.start_date == date(2026, 7, 3)
    assert config.start_volume == 520
    assert config.increment == 40
    assert config.increment_day == "Wednesday"


def test_get_or_create_config_creates_defaults(session):
    config = get_or_create_config(session)
    assert config.start_volume == 520
    assert config.increment == 40
    assert config.increment_day == "Wednesday"


def test_get_or_create_config_returns_existing(session):
    first = get_or_create_config(session)
    second = get_or_create_config(session)
    assert first.id == second.id


def test_get_feeding_by_id(session):
    feeding = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0),
        po_amount=10,
        ng_amount=20,
    )
    session.add(feeding)
    session.commit()
    session.refresh(feeding)
    assert feeding.id is not None

    found = get_feeding_by_id(session, feeding.id)
    assert found is not None
    assert found.id == feeding.id


def test_get_feeding_by_id_missing(session):
    found = get_feeding_by_id(session, 999)
    assert found is None


def test_get_last_feeding(session):
    feeding1 = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0), po_amount=10, ng_amount=20
    )
    feeding2 = Feeding(
        timestamp=datetime(2026, 7, 10, 10, 0), po_amount=15, ng_amount=25
    )
    session.add(feeding1)
    session.add(feeding2)
    session.commit()

    last = get_last_feeding(session)
    assert last is not None
    assert last.timestamp == datetime(2026, 7, 10, 10, 0)


def test_get_last_feeding_empty(session):
    assert get_last_feeding(session) is None


def test_get_all_feedings_orders_by_timestamp(session):
    feeding1 = Feeding(
        timestamp=datetime(2026, 7, 10, 10, 0), po_amount=10, ng_amount=20
    )
    feeding2 = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0), po_amount=15, ng_amount=25
    )
    session.add(feeding1)
    session.add(feeding2)
    session.commit()

    feedings = get_all_feedings(session)
    assert len(feedings) == 2
    assert feedings[0].timestamp == datetime(2026, 7, 10, 8, 0)


def test_get_feedings_for_period(session):
    period_start = datetime(2026, 7, 10, 6, 0)
    in_period = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0), po_amount=10, ng_amount=20
    )
    before_period = Feeding(
        timestamp=datetime(2026, 7, 10, 5, 0), po_amount=15, ng_amount=25
    )
    after_period = Feeding(
        timestamp=datetime(2026, 7, 11, 7, 0), po_amount=20, ng_amount=30
    )
    session.add_all([in_period, before_period, after_period])
    session.commit()

    feedings = get_feedings_for_period(session, period_start)
    assert len(feedings) == 1
    assert feedings[0].timestamp == datetime(2026, 7, 10, 8, 0)


def test_get_feedings_with_gaps(session):
    previous = Feeding(
        timestamp=datetime(2026, 7, 10, 5, 0), po_amount=10, ng_amount=20
    )
    current1 = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0), po_amount=15, ng_amount=25
    )
    current2 = Feeding(
        timestamp=datetime(2026, 7, 10, 10, 0), po_amount=20, ng_amount=30
    )
    session.add_all([previous, current1, current2])
    session.commit()

    period_start = datetime(2026, 7, 10, 6, 0)
    feedings_with_gaps = get_feedings_with_gaps(session, period_start)
    assert len(feedings_with_gaps) == 2

    first_feeding, first_gap = feedings_with_gaps[0]
    assert first_feeding.timestamp == datetime(2026, 7, 10, 8, 0)
    assert first_gap == timedelta(hours=3)

    second_feeding, second_gap = feedings_with_gaps[1]
    assert second_feeding.timestamp == datetime(2026, 7, 10, 10, 0)
    assert second_gap == timedelta(hours=2)


def test_get_feeding_gap_within_period(session):
    feeding1 = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0), po_amount=10, ng_amount=20
    )
    feeding2 = Feeding(
        timestamp=datetime(2026, 7, 10, 10, 0), po_amount=15, ng_amount=25
    )
    session.add(feeding1)
    session.add(feeding2)
    session.commit()

    gap = get_feeding_gap(session, feeding2)
    assert gap == timedelta(hours=2)


def test_get_feeding_gap_no_previous_feeding(session):
    feeding = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0), po_amount=10, ng_amount=20
    )
    session.add(feeding)
    session.commit()

    assert get_feeding_gap(session, feeding) is None


def test_get_feedings_with_gaps_no_previous_feeding(session):
    current = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0), po_amount=10, ng_amount=20
    )
    session.add(current)
    session.commit()

    period_start = datetime(2026, 7, 10, 6, 0)
    feedings_with_gaps = get_feedings_with_gaps(session, period_start)
    assert len(feedings_with_gaps) == 1
    feeding, gap = feedings_with_gaps[0]
    assert feeding.timestamp == datetime(2026, 7, 10, 8, 0)
    assert gap is None


def test_get_feeding_gap_across_periods(session):
    feeding1 = Feeding(
        timestamp=datetime(2026, 7, 9, 10, 0), po_amount=10, ng_amount=20
    )
    feeding2 = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0), po_amount=15, ng_amount=25
    )
    session.add(feeding1)
    session.add(feeding2)
    session.commit()

    gap = get_feeding_gap(session, feeding2)
    assert gap == timedelta(hours=22)


def test_get_previous_feeding_returns_most_recent_before_timestamp(session):
    feeding1 = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0), po_amount=10, ng_amount=20
    )
    feeding2 = Feeding(
        timestamp=datetime(2026, 7, 10, 10, 0), po_amount=15, ng_amount=25
    )
    session.add_all([feeding1, feeding2])
    session.commit()

    previous = get_previous_feeding(session, datetime(2026, 7, 10, 12, 0))
    assert previous is not None
    assert previous.timestamp == datetime(2026, 7, 10, 10, 0)


def test_get_previous_feeding_excludes_given_feeding_id(session):
    feeding1 = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0), po_amount=10, ng_amount=20
    )
    feeding2 = Feeding(
        timestamp=datetime(2026, 7, 10, 10, 0), po_amount=15, ng_amount=25
    )
    session.add_all([feeding1, feeding2])
    session.commit()

    previous = get_previous_feeding(
        session, datetime(2026, 7, 10, 12, 0), exclude_feeding_id=feeding2.id
    )
    assert previous is not None
    assert previous.timestamp == datetime(2026, 7, 10, 8, 0)


def test_get_previous_feeding_returns_none_when_no_match(session):
    feeding = Feeding(
        timestamp=datetime(2026, 7, 10, 10, 0), po_amount=10, ng_amount=20
    )
    session.add(feeding)
    session.commit()

    assert get_previous_feeding(session, datetime(2026, 7, 10, 8, 0)) is None
