import json
from datetime import datetime, timedelta
from urllib.parse import unquote

import httpx
from sqlmodel import Session

from app.backup_service import backup_service
from app.models import Feeding, NotificationLog
from app.notification_service import notification_service
from app.period import format_time
from app.repository import get_or_create_config
from app.summary import get_chart_data


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


def test_create_feeding(client, test_engine):
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

    with Session(test_engine) as session:
        feeding = session.get(Feeding, 1)
    assert feeding.target_per_feed == 70


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
    assert "Timestamp,PO,NG,Total,Target,Notes" in r.text
    assert "30,10,40,70" in r.text


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

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def mock_async_client(*args, **kwargs):
        return mock_client

    monkeypatch.setattr(httpx, "AsyncClient", mock_async_client)
    monkeypatch.setattr(notification_service, "topic", "test-topic")

    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.post("/settings/test-notify", follow_redirects=False)
    assert r.status_code == 303
    assert "sent successfully" in unquote(r.headers["location"])

    data = json.loads(captured[0]["content"])
    assert data["title"] == "🍼 5h 0m since last feed"
    assert data["priority"] == 4
    assert data["topic"] == "test-topic"


def test_settings_page_with_notification_log(client, test_engine, monkeypatch):
    monkeypatch.setattr(notification_service, "topic", "test-topic")
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
    assert "70 ml" in r.text
    assert "+0 ml" in r.text
    assert "after edit" in r.text
    assert "inline-form" not in r.text
    assert r.headers.get("HX-Trigger") == "feeding-updated"

    with Session(test_engine) as session:
        feeding = session.get(Feeding, feeding_id)
    assert feeding.target_per_feed == 70


def test_feeding_row_shows_variance_when_over_target(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})

    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime(2026, 7, 9, 12, 0),
            po_amount=80,
            ng_amount=10,
            target_per_feed=70,
        )
        session.add(feeding)
        session.commit()
        feeding_id = feeding.id

    r = client.get(f"/feedings/{feeding_id}")
    assert r.status_code == 200
    assert "90 ml" in r.text
    assert "70 ml" in r.text
    assert "+20 ml" in r.text
    assert "feed-variance over" in r.text


def test_feeding_row_infers_target_when_not_stored(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})

    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime(2026, 7, 9, 12, 0),
            po_amount=30,
            ng_amount=10,
            target_per_feed=None,
        )
        session.add(feeding)
        session.commit()
        feeding_id = feeding.id

    r = client.get(f"/feedings/{feeding_id}")
    assert r.status_code == 200
    assert "40 ml" in r.text
    assert "70 ml" in r.text
    assert "-30 ml" in r.text
    assert "feed-variance under" in r.text


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


def test_summary_cards_show_vs_target_when_targets_present(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})

    with Session(test_engine) as session:
        config = get_or_create_config(session)
        config.start_volume = 100
        config.increment = 0
        session.add(config)
        feeding = Feeding(
            timestamp=datetime.now() - timedelta(hours=3),
            po_amount=80,
            ng_amount=10,
            target_per_feed=70,
        )
        session.add(feeding)
        session.commit()

    r = client.get("/summary-cards")
    assert r.status_code == 200
    assert "Total / Target" in r.text
    assert "90 / 100 ml" in r.text
    assert "-10 ml" in r.text
    assert 'class="progress-bar"' in r.text
    assert 'target-status-green' in r.text
    assert 'style="width: 90%"' in r.text


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
    assert "Next feed" in response.text
    assert "started " in response.text
    assert " ago" in response.text
    assert "feed-countdown-green" in response.text
    assert f"{format_time(window_start)}-{format_time(window_end)}" in response.text


def test_index_shows_po_percentage_per_feeding(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    feeding_time = datetime.now().replace(second=0, microsecond=0)
    client.post(
        "/feedings",
        data={
            "timestamp": feeding_time.strftime("%Y-%m-%dT%H:%M"),
            "po_amount": "30",
            "ng_amount": "10",
        },
    )

    response = client.get("/")
    assert response.status_code == 200
    assert "<th>PO %</th>" in response.text
    assert "75.0%" in response.text


def test_index_shows_placeholder_for_zero_volume_feeding(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    feeding_time = datetime.now().replace(second=0, microsecond=0)
    client.post(
        "/feedings",
        data={
            "timestamp": feeding_time.strftime("%Y-%m-%dT%H:%M"),
            "po_amount": "0",
            "ng_amount": "0",
        },
    )

    response = client.get("/")
    assert response.status_code == 200
    assert "<th>PO %</th>" in response.text
    assert "75.0%" not in response.text
    assert "—" in response.text


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


def test_feed_target_requires_auth(client):
    r = client.get("/api/feed-target?date=2026-07-09", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_feed_target_returns_target_and_per_feed(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime(2026, 7, 3, 5, 0),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    r = client.get("/api/feed-target?timestamp=2026-07-03T08:00")
    assert r.status_code == 200
    data = r.json()
    assert data["target"] == 520
    # 3-hour interval -> 520 * 3 / 24 = 65
    assert data["per_feed"] == 65
    assert data["actual_interval_minutes"] == 180
    assert data["interval_minutes"] == 180


def test_feed_target_rounds_up(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        config = get_or_create_config(session)
        config.start_volume = 550
        session.add(config)
        feeding = Feeding(
            timestamp=datetime(2026, 7, 3, 5, 0),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    r = client.get("/api/feed-target?timestamp=2026-07-03T08:00")
    assert r.status_code == 200
    data = r.json()
    assert data["target"] == 550
    # 3-hour interval -> 550 * 3 / 24 = 68.75 -> 69
    assert data["per_feed"] == 69
    assert data["actual_interval_minutes"] == 180
    assert data["interval_minutes"] == 180


def test_feed_target_falls_back_to_static_per_feed(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.get("/api/feed-target?timestamp=2026-07-03T08:00")
    assert r.status_code == 200
    data = r.json()
    assert data["target"] == 520
    # No prior feeding -> ceil(520 / 8) = 65
    assert data["per_feed"] == 65
    assert data["actual_interval_minutes"] is None
    assert data["interval_minutes"] is None


def test_feed_target_with_previous_feeding(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime(2026, 7, 9, 9, 0),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    r = client.get("/api/feed-target?timestamp=2026-07-09T12:00")
    assert r.status_code == 200
    data = r.json()
    assert data["target"] == 560
    # 3-hour interval -> 560 * 3 / 24 = 70
    assert data["per_feed"] == 70
    assert data["actual_interval_minutes"] == 180
    assert data["interval_minutes"] == 180


def test_feed_target_editing_excludes_current_feeding(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        earlier = Feeding(
            timestamp=datetime(2026, 7, 9, 6, 0),
            po_amount=30,
            ng_amount=10,
        )
        current = Feeding(
            timestamp=datetime(2026, 7, 9, 9, 0),
            po_amount=30,
            ng_amount=10,
        )
        session.add(earlier)
        session.add(current)
        session.commit()
        current_id = current.id

    r = client.get(
        f"/api/feed-target?timestamp=2026-07-09T12:00&feeding_id={current_id}"
    )
    assert r.status_code == 200
    data = r.json()
    # Excluding the current feeding, the previous feeding is at 6:00.
    # The 6-hour interval is capped to 4 hours -> 560 * 4 / 24 = 93.
    assert data["per_feed"] == 93
    assert data["actual_interval_minutes"] == 360
    assert data["interval_minutes"] == 240


def test_feed_target_backdated_timestamp(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        earlier = Feeding(
            timestamp=datetime(2026, 7, 9, 9, 0),
            po_amount=30,
            ng_amount=10,
        )
        later = Feeding(
            timestamp=datetime(2026, 7, 9, 15, 0),
            po_amount=30,
            ng_amount=10,
        )
        session.add(earlier)
        session.add(later)
        session.commit()

    r = client.get("/api/feed-target?timestamp=2026-07-09T12:00")
    assert r.status_code == 200
    data = r.json()
    # The previous feeding strictly before 12:00 is at 9:00,
    # so the interval is 3 hours -> 560 * 3 / 24 = 70.
    assert data["per_feed"] == 70
    assert data["actual_interval_minutes"] == 180
    assert data["interval_minutes"] == 180


def test_feed_target_period_boundary(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        # Feeding just before the 6:00 AM boundary of the next period.
        feeding = Feeding(
            timestamp=datetime(2026, 7, 9, 5, 30),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    r = client.get("/api/feed-target?timestamp=2026-07-09T06:30")
    assert r.status_code == 200
    data = r.json()
    # Previous feeding is in the previous period but still counts.
    # Interval is 1 hour, clamped to the 2-hour floor -> 560 * 2 / 24 = 47.
    assert data["per_feed"] == 47
    assert data["actual_interval_minutes"] == 60
    assert data["interval_minutes"] == 120


def test_add_feeding_form_includes_interval_note_placeholder(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.get("/")
    assert r.status_code == 200
    assert '<span class="feed-interval-note"></span>' in r.text


def test_settings_page_shows_backup_disabled(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.get("/settings")
    assert r.status_code == 200
    assert "Backups are disabled" in r.text


def test_settings_page_shows_backup_enabled(client, monkeypatch):
    def mock_status(session):
        return {
            "enabled": True,
            "bucket_name": "test-bucket",
            "last_run": None,
            "last_result": None,
            "last_object_key": None,
            "last_error": None,
        }

    monkeypatch.setattr(backup_service, "get_status", mock_status)
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.get("/settings")
    assert r.status_code == 200
    assert "Backups are enabled" in r.text
    assert "test-bucket" in r.text
    assert "Back up now" in r.text


def test_manual_backup_requires_auth(client):
    r = client.post("/settings/backup", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_manual_backup_success(client, monkeypatch):
    monkeypatch.setattr(backup_service, "_enabled", True)

    async def mock_run_backup(session, now=None):
        return True

    monkeypatch.setattr(backup_service, "run_backup", mock_run_backup)

    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.post("/settings/backup", follow_redirects=False)
    assert r.status_code == 303
    assert "completed successfully" in unquote(r.headers["location"])


def test_manual_backup_failure(client, monkeypatch):
    monkeypatch.setattr(backup_service, "_enabled", True)

    async def mock_run_backup(session, now=None):
        return False

    monkeypatch.setattr(backup_service, "run_backup", mock_run_backup)

    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.post("/settings/backup", follow_redirects=False)
    assert r.status_code == 303
    assert "Backup failed" in unquote(r.headers["location"])


def test_manual_backup_disabled(client, monkeypatch):
    async def mock_run_backup(session, now=None):
        return False

    monkeypatch.setattr(backup_service, "run_backup", mock_run_backup)

    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.post("/settings/backup", follow_redirects=False)
    assert r.status_code == 303
    assert "Backup is not configured" in unquote(r.headers["location"])
