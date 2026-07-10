import json
from datetime import datetime, timedelta

from app.period import format_time
from urllib.parse import unquote

import httpx
from sqlmodel import Session

from app.models import Feeding, NotificationLog
from app.notifier import notifier
from app.routes import get_chart_data, get_or_create_config


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


def test_update_feeding_renders_table_row(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})

    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime.now() - timedelta(hours=3),
            po_amount=30,
            ng_amount=10,
            notes="initial",
        )
        session.add(feeding)
        session.commit()
        feeding_id = feeding.id

    r = client.put(
        f"/feedings/{feeding_id}",
        data={
            "timestamp": "2026-07-09T12:00",
            "po_amount": "45",
            "ng_amount": "25",
            "notes": "after edit",
        },
    )
    assert r.status_code == 200
    assert f'<tr id="feeding-{feeding_id}">' in r.text
    assert "45 ml" in r.text
    assert "25 ml" in r.text
    assert "after edit" in r.text
    assert "inline-form" not in r.text
    assert r.headers.get("HX-Trigger") == "feeding-updated"


def test_summary_cards_route(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})

    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime.now() - timedelta(hours=3),
            po_amount=30,
            ng_amount=10,
            notes="initial",
        )
        session.add(feeding)
        session.commit()

    r = client.get("/summary-cards")
    assert r.status_code == 200
    assert 'id="summary-cards"' in r.text
    assert "30 /" in r.text
    assert "10 ml" in r.text


def test_next_feeding_window_on_today_page(client):
    client.post("/login", data={"username": "admin", "password": "secret"})

    feeding_time = datetime.now().replace(second=0, microsecond=0) - timedelta(hours=3)
    client.post(
        "/feedings",
        data={
            "timestamp": feeding_time.strftime("%Y-%m-%dT%H:%M"),
            "po_amount": "30",
            "ng_amount": "10",
        },
    )

    window_start = feeding_time + timedelta(hours=2)
    window_end = feeding_time + timedelta(hours=4)

    response = client.get("/")
    assert response.status_code == 200
    assert "Next feeding window" in response.text
    assert f"{format_time(window_start)}-{format_time(window_end)}" in response.text


def test_index_includes_po_trend(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post(
        "/feedings",
        data={
            "timestamp": "2026-07-09T12:00",
            "po_amount": "30",
            "ng_amount": "10",
        },
    )

    response = client.get("/")
    assert response.status_code == 200
    assert '"po_trend"' in response.text
    assert "PO % Trend" in response.text


def test_chart_data_excludes_empty_periods(test_engine):
    with Session(test_engine) as session:
        config = get_or_create_config(session)
        feeding = Feeding(
            timestamp=datetime(2026, 7, 5, 12, 0),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

        chart_data = get_chart_data(session, config, datetime(2026, 7, 5, 6, 0))

    data_day = next(d for d in chart_data if d["label"] == "Jul 5")
    empty_day = next(d for d in chart_data if d["label"] == "Jul 4")

    assert data_day["total"] == 40
    assert data_day["po_pct"] is not None
    assert data_day["po_trend"] is not None
    assert empty_day["total"] is None
    assert empty_day["po_pct"] is None
    assert empty_day["po_trend"] is None
    assert empty_day["target"] is not None
