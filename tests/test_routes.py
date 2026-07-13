import json
from datetime import datetime, timedelta
from urllib.parse import unquote

import httpx
from sqlmodel import Session, select

from app.backup_service import backup_service
from app.models import Feeding, FeedingStart, NotificationLog
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


def test_create_feeding_snack(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.post(
        "/feedings",
        data={
            "timestamp": "2026-07-09T12:00",
            "po_amount": "10",
            "ng_amount": "5",
            "is_snack": "on",
        },
    )
    assert r.status_code == 200

    with Session(test_engine) as session:
        feeding = session.get(Feeding, 1)
    assert feeding.is_snack is True
    assert feeding.target_per_feed is None


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
    assert "Timestamp,PO,NG,Total,Target,Is Snack,Notes" in r.text
    assert "30,10,40,70,false" in r.text


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


def test_update_feeding_to_snack(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})

    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime(2026, 7, 9, 12, 0),
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
            "po_amount": "10",
            "ng_amount": "5",
            "is_snack": "on",
        },
    )
    assert r.status_code == 200

    with Session(test_engine) as session:
        feeding = session.get(Feeding, feeding_id)
    assert feeding.is_snack is True
    assert feeding.target_per_feed is None


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
    assert "target-status-green" in r.text
    assert 'style="width: 90%"' in r.text


def test_summary_cards_show_trend_when_history_present(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})

    now = datetime.now().replace(second=0, microsecond=0)
    current_period_start = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if now.hour < 6:
        current_period_start -= timedelta(days=1)

    with Session(test_engine) as session:
        # Current feeding
        session.add(
            Feeding(
                timestamp=current_period_start + timedelta(hours=2),
                po_amount=100,
                ng_amount=0,
            )
        )
        # Three past days with 50 ml at same time of day
        for day_offset in range(1, 4):
            past_time = (
                current_period_start - timedelta(days=day_offset) + timedelta(hours=1)
            )
            session.add(
                Feeding(
                    timestamp=past_time,
                    po_amount=50,
                    ng_amount=0,
                )
            )
        session.commit()

    r = client.get("/summary-cards")
    assert r.status_code == 200
    assert "Trend" in r.text
    assert "vs 7-day avg" in r.text
    assert "On pace for" in r.text


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
    assert "Next feed window" in response.text
    assert "started " in response.text
    assert " ago" in response.text
    assert "feed-countdown-green" in response.text
    assert f"{format_time(window_start)}-{format_time(window_end)}" in response.text


def test_index_includes_mobile_feeding_cards(client):
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
    assert 'class="feeding-cards"' in response.text
    assert 'class="feeding-card"' in response.text
    assert 'class="feeding-card-face"' in response.text
    assert 'class="feeding-card-toggle"' in response.text
    assert 'class="feeding-card-details"' in response.text


def test_mobile_feeding_cards_render_feeding_data(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    feeding_time = datetime.now().replace(second=0, microsecond=0)
    client.post(
        "/feedings",
        data={
            "timestamp": feeding_time.strftime("%Y-%m-%dT%H:%M"),
            "po_amount": "30",
            "ng_amount": "10",
            "notes": "via tube",
        },
    )

    response = client.get("/")
    assert response.status_code == 200
    assert 'class="badge badge-po"' in response.text
    assert "PO 30ml" in response.text
    assert "NG 10ml" in response.text
    assert "Total 40ml" in response.text
    assert "via tube" in response.text
    assert 'class="feeding-card-actions"' in response.text


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


def test_complete_feeding_form_includes_interval_note_placeholder(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post("/feedings/start", data={"timestamp": "2026-07-09T12:00"})
    r = client.get("/")
    assert r.status_code == 200
    assert '<span class="feed-interval-note"></span>' in r.text


def test_start_feed_target_requires_auth(client):
    r = client.get(
        "/feedings/start-target?timestamp=2026-07-09T12:00", follow_redirects=False
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_start_feed_target_without_previous_feeding(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.get("/feedings/start-target?timestamp=2026-07-03T08:00")
    assert r.status_code == 200
    assert "65 ml" in r.text
    assert "no previous feed" in r.text


def test_start_feed_target_with_previous_feeding(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime(2026, 7, 9, 9, 0),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    r = client.get("/feedings/start-target?timestamp=2026-07-09T12:00")
    assert r.status_code == 200
    assert "70 ml" in r.text
    assert "3h 0m after last feed" in r.text


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


def test_start_feeding_creates_feeding_start(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    timestamp = "2026-07-09T12:00"
    r = client.post("/feedings/start", data={"timestamp": timestamp})
    assert r.status_code == 200
    assert 'id="complete-feeding-form"' in r.text

    with Session(test_engine) as session:
        feeding_start = session.exec(select(FeedingStart)).first()
    assert feeding_start is not None
    assert feeding_start.timestamp.strftime("%Y-%m-%dT%H:%M") == timestamp


def test_complete_feeding_creates_feeding_and_deletes_start(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post("/feedings/start", data={"timestamp": "2026-07-09T12:00"})

    r = client.post(
        "/feedings/complete",
        data={
            "timestamp": "2026-07-09T12:00",
            "po_amount": "30",
            "ng_amount": "10",
            "notes": "done",
        },
    )
    assert r.status_code == 200
    assert 'id="feeding-list-container"' in r.text
    assert 'id="feeding-list"' in r.text
    assert r.headers.get("HX-Trigger") == "feeding-completed"

    with Session(test_engine) as session:
        feeding = session.exec(select(Feeding)).first()
        feeding_start = session.exec(select(FeedingStart)).first()
    assert feeding is not None
    assert feeding.po_amount == 30
    assert feeding.ng_amount == 10
    assert feeding.notes == "done"
    assert feeding.target_per_feed == 70
    assert feeding_start is None


def test_complete_feeding_snack(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post("/feedings/start", data={"timestamp": "2026-07-09T12:00"})

    r = client.post(
        "/feedings/complete",
        data={
            "timestamp": "2026-07-09T12:00",
            "po_amount": "10",
            "ng_amount": "5",
            "is_snack": "on",
        },
    )
    assert r.status_code == 200

    with Session(test_engine) as session:
        feeding = session.exec(select(Feeding)).first()
    assert feeding.is_snack is True
    assert feeding.target_per_feed is None


def test_cancel_feeding_start_deletes_it(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post("/feedings/start", data={"timestamp": "2026-07-09T12:00"})

    r = client.delete("/feedings/start")
    assert r.status_code == 200
    assert 'id="start-feed-form"' in r.text

    with Session(test_engine) as session:
        feeding_start = session.exec(select(FeedingStart)).first()
    assert feeding_start is None


def test_delete_feeding_returns_list_container_without_deleted_row(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    # Create two feedings for the same period
    client.post(
        "/feedings",
        data={"timestamp": "2026-07-09T10:00", "po_amount": "20", "ng_amount": "10"},
    )
    r = client.post(
        "/feedings",
        data={"timestamp": "2026-07-09T14:00", "po_amount": "30", "ng_amount": "10"},
    )
    feeding_id_to_delete = None
    with Session(test_engine) as session:
        feedings = list(session.exec(select(Feeding).order_by(Feeding.timestamp)))
        assert len(feedings) == 2
        feeding_id_to_delete = feedings[0].id

    r = client.delete(f"/feedings/{feeding_id_to_delete}")
    assert r.status_code == 200
    assert 'id="feeding-list-container"' in r.text
    assert f'id="feeding-{feeding_id_to_delete}"' not in r.text
    assert "2:00 PM" in r.text

    with Session(test_engine) as session:
        remaining = list(session.exec(select(Feeding)))
    assert len(remaining) == 1
    assert remaining[0].id != feeding_id_to_delete


def test_cannot_start_feeding_when_one_in_progress(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post("/feedings/start", data={"timestamp": "2026-07-09T12:00"})

    r = client.post("/feedings/start", data={"timestamp": "2026-07-09T13:00"})
    assert r.status_code == 409


def test_update_feeding_start_timestamp(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post("/feedings/start", data={"timestamp": "2026-07-09T12:00"})

    r = client.put("/feedings/start", data={"timestamp": "2026-07-09T11:30"})
    assert r.status_code == 200
    assert 'id="complete-feeding-form"' in r.text
    assert "2026-07-09T11:30" in r.text

    with Session(test_engine) as session:
        feeding_start = session.exec(select(FeedingStart)).first()
    assert feeding_start.timestamp.strftime("%Y-%m-%dT%H:%M") == "2026-07-09T11:30"


def test_index_shows_start_control_when_no_feeding_start(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="start-feed-form"' in r.text
    assert 'id="complete-feeding-form"' not in r.text


def test_start_feed_form_includes_target_preview_wiring(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.get("/")
    assert r.status_code == 200
    assert 'hx-get="/feedings/start-target"' in r.text
    assert 'hx-trigger="load, change"' in r.text
    assert 'id="start-feed-target-preview"' in r.text


def test_index_shows_complete_form_when_feeding_start_exists(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post("/feedings/start", data={"timestamp": "2026-07-09T12:00"})

    r = client.get("/")
    assert r.status_code == 200
    assert 'id="complete-feeding-form"' in r.text
    assert 'id="start-feed-form"' not in r.text


def test_non_today_page_shows_in_progress_notice(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post("/feedings/start", data={"timestamp": "2026-07-09T12:00"})

    r = client.get("/?period=2026-07-08")
    assert r.status_code == 200
    assert "A feed is in progress" in r.text
    assert 'id="complete-feeding-form"' not in r.text
    assert 'id="start-feed-form"' not in r.text


def test_settings_page_shows_in_progress_notice(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post("/feedings/start", data={"timestamp": "2026-07-09T12:00"})

    r = client.get("/settings")
    assert r.status_code == 200
    assert "A feed is in progress" in r.text


def test_start_feeding_accepts_future_timestamp(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    future = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
    r = client.post("/feedings/start", data={"timestamp": future})
    assert r.status_code == 200
    assert 'id="complete-feeding-form"' in r.text


def test_complete_feeding_rejects_future_timestamp(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    client.post("/feedings/start", data={"timestamp": "2026-07-09T12:00"})

    future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    r = client.post(
        "/feedings/complete",
        data={
            "timestamp": future,
            "po_amount": "30",
            "ng_amount": "10",
        },
    )
    assert r.status_code == 400


def test_complete_feeding_without_start_returns_404(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    r = client.post(
        "/feedings/complete",
        data={
            "timestamp": "2026-07-09T12:00",
            "po_amount": "30",
            "ng_amount": "10",
        },
    )
    assert r.status_code == 404


def test_create_feeding_rejects_future_timestamp(client):
    client.post("/login", data={"username": "admin", "password": "secret"})
    future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    r = client.post(
        "/feedings",
        data={
            "timestamp": future,
            "po_amount": "30",
            "ng_amount": "10",
        },
    )
    assert r.status_code == 400


def test_update_feeding_rejects_future_timestamp(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime(2026, 7, 9, 12, 0), po_amount=30, ng_amount=10
        )
        session.add(feeding)
        session.commit()
        feeding_id = feeding.id

    future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    r = client.put(
        f"/feedings/{feeding_id}",
        data={
            "timestamp": future,
            "po_amount": "30",
            "ng_amount": "10",
        },
    )
    assert r.status_code == 400


def test_edit_feeding_form_returns_card_for_mobile_target(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime(2026, 7, 9, 12, 0),
            po_amount=30,
            ng_amount=10,
            notes="initial",
        )
        session.add(feeding)
        session.commit()
        feeding_id = feeding.id

    r = client.get(
        f"/feedings/{feeding_id}/edit",
        headers={"HX-Target": f"feeding-card-{feeding_id}"},
    )
    assert r.status_code == 200
    assert f'<div class="feeding-card editing" id="feeding-card-{feeding_id}">' in r.text
    assert "feeding-card-edit-fields" in r.text
    assert "2026-07-09T12:00" in r.text


def test_edit_feeding_form_returns_table_row_for_table_target(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime(2026, 7, 9, 12, 0),
            po_amount=30,
            ng_amount=10,
            notes="initial",
        )
        session.add(feeding)
        session.commit()
        feeding_id = feeding.id

    r = client.get(
        f"/feedings/{feeding_id}/edit",
        headers={"HX-Target": f"feeding-{feeding_id}"},
    )
    assert r.status_code == 200
    assert f'<tr id="feeding-{feeding_id}" class="editing">' in r.text
    assert "inline-form" in r.text


def test_feeding_row_returns_card_for_mobile_target(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime(2026, 7, 9, 12, 0),
            po_amount=30,
            ng_amount=10,
            target_per_feed=70,
        )
        session.add(feeding)
        session.commit()
        feeding_id = feeding.id

    r = client.get(
        f"/feedings/{feeding_id}",
        headers={"HX-Target": f"feeding-card-{feeding_id}"},
    )
    assert r.status_code == 200
    assert f'<div class="feeding-card" id="feeding-card-{feeding_id}">' in r.text
    assert "PO 30ml" in r.text
    assert "NG 10ml" in r.text
    assert "Total 40ml" in r.text


def test_update_feeding_renders_card_for_mobile_target(client, test_engine):
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
        headers={"HX-Target": f"feeding-card-{feeding_id}"},
    )
    assert r.status_code == 200
    assert f'<div class="feeding-card" id="feeding-card-{feeding_id}">' in r.text
    assert "PO 45ml" in r.text
    assert "NG 25ml" in r.text
    assert "Total 70ml" in r.text
    assert "after edit" in r.text
    assert r.headers.get("HX-Trigger") == "feeding-updated"


def test_mobile_feeding_card_edit_button_targets_card_id(client, test_engine):
    client.post("/login", data={"username": "admin", "password": "secret"})
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=datetime.now() - timedelta(hours=3),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()
        feeding_id = feeding.id

    r = client.get("/")
    assert r.status_code == 200
    assert f'id="feeding-card-{feeding_id}"' in r.text
    assert f'hx-target="#feeding-card-{feeding_id}"' in r.text
    assert f'hx-get="/feedings/{feeding_id}/edit"' in r.text
