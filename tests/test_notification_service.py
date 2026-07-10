import json
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, select

from app.models import Feeding, NotificationLog
from app.notification_service import DEFAULT_THRESHOLDS, NotificationService


def make_service(session_factory, **overrides):
    kwargs = {
        "session_factory": session_factory,
        "topic": "test-topic",
        "server": "https://ntfy.sh",
        "thresholds": "2,3,4",
        "app_url": None,
    }
    kwargs.update(overrides)
    return NotificationService(**kwargs)


def test_parse_thresholds_default():
    service = make_service(lambda: None)
    assert service.parse_thresholds(None) == DEFAULT_THRESHOLDS


def test_parse_thresholds_custom():
    service = make_service(lambda: None)
    assert service.parse_thresholds("4, 2, 2") == [2, 4]


def test_parse_thresholds_invalid():
    service = make_service(lambda: None)
    assert service.parse_thresholds("not-a-number") == [2, 3, 4]


def test_body_for_feeding():
    service = make_service(lambda: None)
    feeding = Feeding(
        timestamp=datetime(2026, 7, 9, 12, 0),
        po_amount=30,
        ng_amount=10,
    )
    body = service.body_for_feeding(feeding)
    assert "PO 30 ml" in body
    assert "NG 10 ml" in body
    assert "12:00 PM" in body


def test_priority():
    service = make_service(lambda: None)
    assert service.priority([]) == 3
    assert service.priority([2]) == 3
    assert service.priority([2, 3]) == 3
    assert service.priority([2, 3, 4]) == 4


def test_build_payload():
    service = make_service(lambda: None, app_url=None)
    payload = service.build_payload("Title", "Body", 3)
    assert payload == {
        "topic": "test-topic",
        "title": "Title",
        "message": "Body",
        "priority": 3,
        "tags": ["🍼"],
    }


def test_build_payload_with_app_url():
    service = make_service(lambda: None, app_url="https://example.com")
    payload = service.build_payload("Title", "Body", 4)
    assert payload["click"] == "https://example.com"


@pytest.mark.asyncio
async def test_send_test_payload(monkeypatch, test_engine):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"url": str(request.url), "content": request.content})
        return httpx.Response(200, text="ok")

    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime.now() - timedelta(hours=5),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    def session_factory():
        return Session(test_engine)

    service = make_service(session_factory)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        ok = await service.send_test(session, client)

    assert ok is True

    data = json.loads(captured[0]["content"])
    assert data["topic"] == "test-topic"
    assert data["title"] == "🍼 5h 0m since last feed"
    assert data["priority"] == 4
    assert captured[0]["url"] == "https://ntfy.sh/"


@pytest.mark.asyncio
async def test_send_test_payload_under_threshold(test_engine):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"content": request.content})
        return httpx.Response(200, text="ok")

    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime.now() - timedelta(minutes=30),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    def session_factory():
        return Session(test_engine)

    service = make_service(session_factory)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        ok = await service.send_test(session, client)

    assert ok is True

    data = json.loads(captured[0]["content"])
    assert data["title"] == "🍼 30m since last feed"
    assert data["priority"] == 3


@pytest.mark.asyncio
async def test_run_check_sends_notification_when_threshold_crossed(test_engine):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"content": request.content})
        return httpx.Response(200, text="ok")

    now = datetime(2026, 7, 10, 12, 0)
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=now - timedelta(hours=5),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()
        feeding_id = feeding.id

    def session_factory():
        return Session(test_engine)

    service = make_service(session_factory)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        await service.run_check(session, client, now=now)

    assert len(captured) == 3
    data = json.loads(captured[2]["content"])
    assert data["title"] == "🍼 4h 0m since last feed"
    assert data["priority"] == 4

    with Session(test_engine) as session:
        logs = session.exec(
            select(NotificationLog).where(NotificationLog.feeding_id == feeding_id)
        ).all()
        assert len(logs) == 3
        assert {log.threshold_hours for log in logs} == {2, 3, 4}


@pytest.mark.asyncio
async def test_run_check_skips_already_sent(test_engine):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"content": request.content})
        return httpx.Response(200, text="ok")

    now = datetime(2026, 7, 10, 12, 0)
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=now - timedelta(hours=5),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()
        feeding_id = feeding.id
        session.add(NotificationLog(feeding_id=feeding_id, threshold_hours=4))
        session.commit()

    def session_factory():
        return Session(test_engine)

    service = make_service(session_factory)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        await service.run_check(session, client, now=now)

    assert len(captured) == 2

    with Session(test_engine) as session:
        logs = session.exec(
            select(NotificationLog).where(NotificationLog.feeding_id == feeding_id)
        ).all()
        assert len(logs) == 3
        assert {log.threshold_hours for log in logs} == {2, 3, 4}

    captured = []

    def handler(request: httpx.Request):
        captured.append({"content": request.content})
        return httpx.Response(200, text="ok")

    now = datetime(2026, 7, 10, 12, 0)
    app_start_time = now - timedelta(minutes=30)
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=now - timedelta(hours=5),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    def session_factory():
        return Session(test_engine)

    service = make_service(session_factory)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        await service.run_check(session, client, now=now, app_start_time=app_start_time)

    assert len(captured) == 0


@pytest.mark.asyncio
async def test_run_check_sends_multiple_thresholds(test_engine):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"content": request.content})
        return httpx.Response(200, text="ok")

    now = datetime(2026, 7, 10, 12, 0)
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=now - timedelta(hours=5),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()
        feeding_id = feeding.id

    def session_factory():
        return Session(test_engine)

    service = make_service(session_factory)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        await service.run_check(session, client, now=now)

    assert len(captured) == 3

    with Session(test_engine) as session:
        logs = session.exec(
            select(NotificationLog).where(NotificationLog.feeding_id == feeding_id)
        ).all()
        assert len(logs) == 3


def test_get_status_enabled(test_engine, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")

    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime.now() - timedelta(hours=5),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    def session_factory():
        return Session(test_engine)

    service = make_service(session_factory)
    with Session(test_engine) as session:
        status = service.get_status(session)

    assert status["enabled"] is True
    assert status["topic"] == "test-topic"
    assert status["thresholds"] == [2, 3, 4]


def test_get_status_disabled(test_engine):
    def session_factory():
        return Session(test_engine)

    service = make_service(session_factory, topic=None)
    with Session(test_engine) as session:
        status = service.get_status(session)

    assert status["enabled"] is False
    assert status["topic"] is None
