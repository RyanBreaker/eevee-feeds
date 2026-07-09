import json
from datetime import datetime, timedelta
from urllib.parse import unquote

import httpx
from sqlmodel import Session

from app.models import Feeding, NotificationLog
from app.notifier import notifier


def test_login_page(client):
    r = client.get("/login")
    assert r.status_code == 200


def test_login_required_redirect(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_login_and_home(client):
    r = client.post(
        "/login",
        data={"username": "admin", "password": "secret"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    r = client.get("/")
    assert r.status_code == 200


def test_login_invalid(client):
    r = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    assert "Invalid" in r.text


def test_create_feeding(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.post(
        "/feedings",
        data={
            "timestamp": "2026-07-09T12:00",
            "po_amount": "30",
            "ng_amount": "10",
        },
    )
    assert r.status_code == 200


def test_export_csv(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post(
        "/feedings",
        data={
            "timestamp": "2026-07-09T12:00",
            "po_amount": "30",
            "ng_amount": "10",
        },
    )
    r = client.get("/export")
    assert r.status_code == 200
    assert "Timestamp,PO,NG,Total,Notes" in r.text
    assert "30,10,40" in r.text


def test_simple_test_notification(client, monkeypatch, test_engine):
    captured = []

    def handler(request: httpx.Request):
        captured.append({"content": request.content})
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

    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.post("/settings/test-notify", follow_redirects=False)
    assert r.status_code == 303
    assert "sent successfully" in unquote(r.headers["location"])

    data = json.loads(captured[0]["content"])
    assert data["title"] == "🍼 5h 0m since last feed"
    assert data["priority"] == 4
    assert data["topic"] == "test-topic"


def test_settings_page_with_notification_log(client, test_engine, monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "test-topic")
    client.post("/login", data={"username": "admin", "password": "secret"})

    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime.now() - timedelta(hours=5),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

        log = NotificationLog(feeding_id=feeding.id, threshold_hours=2)
        session.add(log)
        session.commit()

    response = client.get("/settings")
    assert response.status_code == 200
    assert "test-topic" in response.text
