import asyncio
import json
import logging
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import Session

from app.models import Feeding
from app.notifier import FeedingNotifier, notifier


def test_notifier_exposes_service_config():
    notifier.service.topic = "test-topic"
    notifier.service.server = "https://example.com"
    notifier.service.app_url = "https://app.example.com"
    notifier.service.thresholds = [1, 2]

    assert notifier.service.topic == "test-topic"
    assert notifier.service.server == "https://example.com"
    assert notifier.service.app_url == "https://app.example.com"
    assert notifier.service.thresholds == [1, 2]


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

    monkeypatch.setattr(notifier.service, "topic", "test-topic")
    monkeypatch.setattr(
        notifier,
        "client",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    ok = await notifier.send_test()
    assert ok is True

    data = json.loads(captured[0]["content"])
    assert data["topic"] == "test-topic"
    assert data["title"] == "🍼 5h 0m since last feed"
    assert data["priority"] == 4
    assert captured[0]["url"] == "https://ntfy.sh/"


@pytest.mark.asyncio
async def test_send_test_payload_under_threshold(monkeypatch, test_engine):
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

    monkeypatch.setattr(notifier.service, "topic", "test-topic")
    monkeypatch.setattr(
        notifier,
        "client",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    ok = await notifier.send_test()
    assert ok is True

    data = json.loads(captured[0]["content"])
    assert data["title"] == "🍼 30m since last feed"
    assert data["priority"] == 3


@pytest.mark.asyncio
async def test_notifier_start_stop_with_topic(monkeypatch):
    monkeypatch.setattr(notifier.service, "topic", "test-topic")
    monkeypatch.setattr(notifier, "client", None)
    monkeypatch.setattr(notifier, "task", None)
    monkeypatch.setattr(notifier, "app_start_time", None)

    notifier.start()
    assert notifier.task is not None
    assert notifier.client is not None

    await notifier.stop()
    assert notifier.task is None or notifier.task.done()


@pytest.mark.asyncio
async def test_notifier_start_no_topic(monkeypatch):
    monkeypatch.setattr(notifier.service, "topic", None)
    monkeypatch.setattr(notifier, "client", None)
    monkeypatch.setattr(notifier, "task", None)
    monkeypatch.setattr(notifier, "app_start_time", None)

    notifier.start()
    assert notifier.task is None
    assert notifier.client is None


@pytest.mark.asyncio
async def test_loop_logs_and_survives_check_failure(monkeypatch, caplog):
    checked = asyncio.Event()

    async def failing_run_check(*args, **kwargs):
        checked.set()
        raise RuntimeError("db blew up")

    monkeypatch.setattr(notifier.service, "run_check", failing_run_check)

    with caplog.at_level(logging.ERROR, logger="uvicorn"):
        task = asyncio.create_task(notifier._loop())
        await asyncio.wait_for(checked.wait(), timeout=1)
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert "Notifier check failed" in caplog.text
    assert "RuntimeError: db blew up" in caplog.text
