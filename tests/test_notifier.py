import json
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import Session

from app.models import Feeding
from app.notifier import FeedingNotifier, notifier


def test_parse_thresholds_default():
    n = FeedingNotifier()
    assert n._parse_thresholds(None) == [2, 3, 4]


def test_parse_thresholds_custom():
    n = FeedingNotifier()
    assert n._parse_thresholds("4, 2, 2") == [2, 4]


def test_parse_thresholds_invalid():
    n = FeedingNotifier()
    assert n._parse_thresholds("not-a-number") == [2, 3, 4]


@pytest.mark.asyncio
async def test_send_test_payload(monkeypatch):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"url": str(request.url), "content": request.content})
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(notifier, "topic", "test-topic")
    monkeypatch.setattr(
        notifier,
        "client",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    ok = await notifier.send_test()
    assert ok is True

    data = json.loads(captured[0]["content"])
    assert data["topic"] == "test-topic"
    assert data["title"] == "Test notification"
    assert data["priority"] == 3
    assert captured[0]["url"] == "https://ntfy.sh/"


@pytest.mark.asyncio
async def test_send_test_current_gap_payload(monkeypatch, test_engine):
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

    monkeypatch.setattr(notifier, "topic", "test-topic")
    monkeypatch.setattr(
        notifier,
        "client",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    ok = await notifier.send_test_current_gap()
    assert ok is True

    data = json.loads(captured[0]["content"])
    assert data["topic"] == "test-topic"
    assert data["title"] == "5h 0m since last feed"
    assert data["priority"] == 4
    assert "🍼" in data["tags"]


@pytest.mark.asyncio
async def test_send_test_current_gap_payload_under_threshold(monkeypatch, test_engine):
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

    monkeypatch.setattr(notifier, "topic", "test-topic")
    monkeypatch.setattr(
        notifier,
        "client",
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    ok = await notifier.send_test_current_gap()
    assert ok is True

    data = json.loads(captured[0]["content"])
    assert data["title"] == "30m since last feed"
    assert data["priority"] == 3
