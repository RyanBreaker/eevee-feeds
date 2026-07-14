import json
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, select

from app.models import Feeding, FeedingStart, NotificationLog
from app.notification_service import DEFAULT_THRESHOLDS, NotificationService


def make_service(**overrides):
    kwargs = {
        "topic": "test-topic",
        "server": "https://ntfy.sh",
        "thresholds": "2,3,4",
        "app_url": None,
    }
    kwargs.update(overrides)
    return NotificationService(**kwargs)


def test_parse_thresholds_default():
    service = make_service()
    assert service.parse_thresholds(None) == DEFAULT_THRESHOLDS


def test_parse_thresholds_custom():
    service = make_service()
    assert service.parse_thresholds("4, 2, 2") == [2, 4]


def test_parse_thresholds_invalid():
    service = make_service()
    assert service.parse_thresholds("not-a-number") == [2, 3, 4]


def test_body_for_feeding():
    service = make_service()
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
    service = make_service()
    assert service.priority([]) == 3
    assert service.priority([2]) == 3
    assert service.priority([2, 3]) == 3
    assert service.priority([2, 3, 4]) == 4


def test_build_payload():
    service = make_service(app_url=None)
    payload = service.build_payload("Title", "Body", 3)
    assert payload == {
        "topic": "test-topic",
        "title": "Title",
        "message": "Body",
        "priority": 3,
        "tags": ["🍼"],
    }


def test_build_payload_with_app_url():
    service = make_service(app_url="https://example.com")
    payload = service.build_payload("Title", "Body", 4)
    assert payload["click"] == "https://example.com"


@pytest.mark.asyncio
async def test_send_test_payload(test_engine):
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

    service = make_service()
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

    service = make_service()
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

    service = make_service()
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

    service = make_service()
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


@pytest.mark.asyncio
async def test_run_check_skips_before_app_start_time(test_engine):
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

    service = make_service()
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

    service = make_service()
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

    service = make_service()
    with Session(test_engine) as session:
        status = service.get_status(session)

    assert status["enabled"] is True
    assert status["topic"] == "test-topic"
    assert status["thresholds"] == [2, 3, 4]


def test_get_status_disabled(test_engine):
    service = make_service(topic=None)
    with Session(test_engine) as session:
        status = service.get_status(session)

    assert status["enabled"] is False
    assert status["topic"] is None


@pytest.mark.asyncio
async def test_run_check_ignores_snacks(test_engine):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"content": request.content})
        return httpx.Response(200, text="ok")

    now = datetime(2026, 7, 10, 12, 0)
    with Session(test_engine) as session:
        real_feeding = Feeding(
            timestamp=now - timedelta(hours=5),
            po_amount=30,
            ng_amount=10,
        )
        snack = Feeding(
            timestamp=now - timedelta(hours=1),
            po_amount=10,
            ng_amount=0,
            is_snack=True,
        )
        session.add_all([real_feeding, snack])
        session.commit()
        real_feeding_id = real_feeding.id

    service = make_service()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        await service.run_check(session, client, now=now)

    assert len(captured) == 3
    data = json.loads(captured[2]["content"])
    assert data["title"] == "🍼 4h 0m since last feed"

    with Session(test_engine) as session:
        logs = session.exec(
            select(NotificationLog).where(NotificationLog.feeding_id == real_feeding_id)
        ).all()
        assert len(logs) == 3


@pytest.mark.asyncio
async def test_run_check_sends_start_reminders(test_engine):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"content": request.content})
        return httpx.Response(200, text="ok")

    now = datetime(2026, 7, 10, 12, 0)
    start_time = now - timedelta(minutes=50)
    with Session(test_engine) as session:
        feeding_start = FeedingStart(timestamp=start_time)
        session.add(feeding_start)
        session.commit()

    service = make_service()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        await service.run_check(session, client, now=now)

    assert len(captured) == 3
    titles = [json.loads(item["content"])["title"] for item in captured]
    assert titles == [
        "🍼 15m since feed started",
        "🍼 30m since feed started",
        "🍼 45m since feed started",
    ]


@pytest.mark.asyncio
async def test_run_check_start_reminders_are_unbounded(test_engine):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"content": request.content})
        return httpx.Response(200, text="ok")

    now = datetime(2026, 7, 10, 12, 0)
    start_time = now - timedelta(minutes=80)
    with Session(test_engine) as session:
        feeding_start = FeedingStart(timestamp=start_time)
        session.add(feeding_start)
        session.commit()

    service = make_service()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        await service.run_check(session, client, now=now)

    assert len(captured) == 5
    titles = [json.loads(item["content"])["title"] for item in captured]
    assert titles[-1] == "🍼 1h 15m since feed started"


@pytest.mark.asyncio
async def test_run_check_suppresses_normal_notifications_when_feeding_start_exists(
    test_engine,
):
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
        feeding_start = FeedingStart(timestamp=now - timedelta(minutes=20))
        session.add_all([feeding, feeding_start])
        session.commit()

    service = make_service()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        await service.run_check(session, client, now=now)

    assert len(captured) == 1
    data = json.loads(captured[0]["content"])
    assert data["title"] == "🍼 15m since feed started"


@pytest.mark.asyncio
async def test_run_check_skips_start_reminders_before_app_start_time(test_engine):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"content": request.content})
        return httpx.Response(200, text="ok")

    now = datetime(2026, 7, 10, 12, 0)
    app_start_time = now - timedelta(minutes=20)
    start_time = now - timedelta(minutes=50)
    with Session(test_engine) as session:
        feeding_start = FeedingStart(timestamp=start_time)
        session.add(feeding_start)
        session.commit()

    service = make_service()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        await service.run_check(
            session, client, now=now, app_start_time=app_start_time
        )

    assert len(captured) == 2
    titles = [json.loads(item["content"])["title"] for item in captured]
    assert titles == [
        "🍼 30m since feed started",
        "🍼 45m since feed started",
    ]


@pytest.mark.asyncio
async def test_run_check_start_reminders_skip_already_sent(test_engine):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"content": request.content})
        return httpx.Response(200, text="ok")

    now = datetime(2026, 7, 10, 12, 0)
    start_time = now - timedelta(minutes=50)
    with Session(test_engine) as session:
        feeding_start = FeedingStart(timestamp=start_time)
        session.add(feeding_start)
        session.commit()
        feeding_start_id = feeding_start.id
        from app.models import FeedingStartReminderLog

        session.add(
            FeedingStartReminderLog(
                feeding_start_id=feeding_start_id, threshold_minutes=15
            )
        )
        session.commit()

    service = make_service()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with Session(test_engine) as session:
        await service.run_check(session, client, now=now)

    assert len(captured) == 2
    titles = [json.loads(item["content"])["title"] for item in captured]
    assert titles == [
        "🍼 30m since feed started",
        "🍼 45m since feed started",
    ]


def test_get_status_with_feeding_start(test_engine):
    now = datetime(2026, 7, 10, 12, 0)
    start_time = now - timedelta(minutes=10)
    with Session(test_engine) as session:
        feeding_start = FeedingStart(timestamp=start_time)
        session.add(feeding_start)
        session.commit()

    service = make_service()
    with Session(test_engine) as session:
        status = service.get_status(session)

    assert status["next_notification"] == start_time + timedelta(minutes=15)


def test_get_status_with_feeding_start_skips_sent_threshold(test_engine):
    now = datetime(2026, 7, 10, 12, 0)
    start_time = now - timedelta(minutes=20)
    with Session(test_engine) as session:
        feeding_start = FeedingStart(timestamp=start_time)
        session.add(feeding_start)
        session.commit()
        feeding_start_id = feeding_start.id
        from app.models import FeedingStartReminderLog

        session.add(
            FeedingStartReminderLog(
                feeding_start_id=feeding_start_id, threshold_minutes=15
            )
        )
        session.commit()

    service = make_service()
    with Session(test_engine) as session:
        status = service.get_status(session)

    assert status["next_notification"] == start_time + timedelta(minutes=30)
