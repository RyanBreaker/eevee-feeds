from datetime import datetime, timedelta

import pytest
from sqlmodel import Session

from app.feeding_service import (
    complete_feeding,
    create_feeding,
    delete_feeding,
    update_feeding,
)
from app.models import Feeding, FeedingStart
from app.repository import get_feeding_by_id, get_feeding_start
from app.repository import get_or_create_config


@pytest.fixture
def session(test_engine):
    with Session(test_engine) as session:
        yield session


def test_create_feeding_stores_feeding(session):
    config = get_or_create_config(session)

    feeding = create_feeding(
        session,
        config,
        timestamp=datetime(2026, 7, 10, 9, 0),
        po_amount=40,
        ng_amount=10,
        notes="hello",
    )

    assert feeding.id is not None
    assert feeding.timestamp == datetime(2026, 7, 10, 9, 0)
    assert feeding.po_amount == 40
    assert feeding.ng_amount == 10
    assert feeding.notes == "hello"
    assert feeding.target_per_feed is not None


def test_create_feeding_rejects_future_timestamp(session):
    config = get_or_create_config(session)
    future = datetime.now() + timedelta(days=1)

    with pytest.raises(ValueError, match="Timestamp cannot be in the future"):
        create_feeding(session, config, future, 40, 10, None)


def test_update_feeding_updates_fields(session):
    config = get_or_create_config(session)
    feeding = create_feeding(
        session,
        config,
        timestamp=datetime(2026, 7, 10, 9, 0),
        po_amount=40,
        ng_amount=10,
        notes="old",
    )
    original_updated_at = feeding.updated_at

    updated = update_feeding(
        session,
        config,
        feeding,
        timestamp=datetime(2026, 7, 10, 10, 0),
        po_amount=50,
        ng_amount=5,
        notes="new",
    )

    assert updated.timestamp == datetime(2026, 7, 10, 10, 0)
    assert updated.po_amount == 50
    assert updated.ng_amount == 5
    assert updated.notes == "new"
    assert updated.updated_at > original_updated_at


def test_update_feeding_rejects_future_timestamp(session):
    config = get_or_create_config(session)
    feeding = create_feeding(
        session,
        config,
        timestamp=datetime(2026, 7, 10, 9, 0),
        po_amount=40,
        ng_amount=10,
        notes=None,
    )
    future = datetime.now() + timedelta(days=1)

    with pytest.raises(ValueError, match="Timestamp cannot be in the future"):
        update_feeding(session, config, feeding, future, 50, 5, None)


def test_complete_feeding_creates_feeding_and_removes_start(session):
    config = get_or_create_config(session)
    feeding_start = FeedingStart(timestamp=datetime(2026, 7, 10, 8, 0))
    session.add(feeding_start)
    session.commit()

    feeding = complete_feeding(
        session,
        config,
        feeding_start,
        timestamp=datetime(2026, 7, 10, 9, 0),
        po_amount=40,
        ng_amount=10,
        notes=None,
    )

    assert feeding.id is not None
    assert get_feeding_start(session) is None


def test_complete_feeding_rejects_future_timestamp(session):
    config = get_or_create_config(session)
    feeding_start = FeedingStart(timestamp=datetime(2026, 7, 10, 8, 0))
    session.add(feeding_start)
    session.commit()
    future = datetime.now() + timedelta(days=1)

    with pytest.raises(ValueError, match="Timestamp cannot be in the future"):
        complete_feeding(session, config, feeding_start, future, 40, 10, None)


def test_delete_feeding_removes_feeding(session):
    config = get_or_create_config(session)
    feeding = create_feeding(
        session,
        config,
        timestamp=datetime(2026, 7, 10, 9, 0),
        po_amount=40,
        ng_amount=10,
        notes=None,
    )
    feeding_id = feeding.id

    delete_feeding(session, feeding)

    assert get_feeding_by_id(session, feeding_id) is None
