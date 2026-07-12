from datetime import datetime, timedelta

import pytest
from sqlmodel import Session

from app.models import Feeding
from app.repository import get_or_create_config
from app.summary import (
    _get_average_total_at_time,
    attach_effective_targets,
    get_chart_data,
    get_current_period_start,
    get_period_summary,
)


@pytest.fixture
def session(test_engine):
    with Session(test_engine) as session:
        yield session


def test_get_current_period_start_is_period_start_of_now():
    now = datetime.now()
    period_start = get_current_period_start()
    # period_start should be 6 AM today or yesterday depending on time of day
    assert period_start.hour == 6
    assert period_start.minute == 0
    assert period_start.second == 0


def test_get_period_summary(session):
    config = get_or_create_config(session)
    feeding = Feeding(
        timestamp=datetime(2026, 7, 3, 8, 0), po_amount=30, ng_amount=10
    )
    session.add(feeding)
    session.commit()

    period_start = datetime(2026, 7, 3, 6, 0)
    summary = get_period_summary(session, config, period_start)

    assert summary["po"] == 30
    assert summary["ng"] == 10
    assert summary["total"] == 40
    assert summary["po_pct"] == 75.0
    assert summary["remaining"] == 520 - 40
    assert len(summary["feedings"]) == 1
    assert summary["avg_gap"] is None


def test_get_period_summary_includes_target_variance(session):
    config = get_or_create_config(session)
    config.start_volume = 100
    config.increment = 0
    session.add(config)
    feeding = Feeding(
        timestamp=datetime(2026, 7, 3, 8, 0),
        po_amount=80,
        ng_amount=10,
        target_per_feed=70,
    )
    session.add(feeding)
    session.commit()

    period_start = datetime(2026, 7, 3, 6, 0)
    summary = get_period_summary(session, config, period_start)

    assert summary["total"] == 90
    assert summary["target_variance"] == -10


def test_get_period_summary_infers_target_for_legacy_feeding(session):
    config = get_or_create_config(session)
    config.start_volume = 100
    config.increment = 0
    session.add(config)
    feeding = Feeding(
        timestamp=datetime(2026, 7, 3, 8, 0), po_amount=30, ng_amount=10
    )
    session.add(feeding)
    session.commit()

    period_start = datetime(2026, 7, 3, 6, 0)
    summary = get_period_summary(session, config, period_start)

    assert summary["target_variance"] == 40 - 100


def test_get_period_summary_target_progress_and_status(session):
    config = get_or_create_config(session)
    config.start_volume = 100
    config.increment = 0
    session.add(config)

    cases = [
        # (po, ng, expected_pct, expected_class)
        (95, 0, 95, "target-status-green"),
        (80, 0, 80, "target-status-yellow"),
        (70, 0, 70, "target-status-red"),
        (150, 0, 100, "target-status-green"),
    ]

    for po, ng, expected_pct, expected_class in cases:
        feeding = Feeding(
            timestamp=datetime(2026, 7, 3, 8, 0), po_amount=po, ng_amount=ng
        )
        session.add(feeding)
        session.commit()

        period_start = datetime(2026, 7, 3, 6, 0)
        summary = get_period_summary(session, config, period_start)

        assert summary["target_progress_pct"] == expected_pct, (po, ng)
        assert summary["target_status_class"] == expected_class, (po, ng)

        session.delete(feeding)
        session.commit()


def test_get_period_summary_target_progress_zero_when_empty(session):
    config = get_or_create_config(session)
    config.start_volume = 100
    config.increment = 0
    session.add(config)
    session.commit()

    period_start = datetime(2026, 7, 3, 6, 0)
    summary = get_period_summary(session, config, period_start)

    assert summary["target_progress_pct"] == 0
    assert summary["target_status_class"] == "target-status-red"


def test_get_period_summary_for_past_period_has_no_next_window(session):
    config = get_or_create_config(session)
    feeding = Feeding(
        timestamp=datetime(2026, 7, 3, 8, 0), po_amount=30, ng_amount=10
    )
    session.add(feeding)
    session.commit()

    period_start = datetime(2026, 7, 3, 6, 0)
    summary = get_period_summary(session, config, period_start)

    assert summary["time_since_last"] is None
    assert summary["next_feeding_window"] is None


def test_get_period_summary_for_current_period_includes_next_window(session):
    config = get_or_create_config(session)
    feeding_time = datetime.now() - timedelta(hours=3)
    feeding = Feeding(timestamp=feeding_time, po_amount=30, ng_amount=10)
    session.add(feeding)
    session.commit()

    current_period = get_current_period_start()
    summary = get_period_summary(session, config, current_period)

    assert summary["time_since_last"] is not None
    assert summary["next_feeding_window"] is not None
    start, end = summary["next_feeding_window"]
    assert start == feeding_time + timedelta(hours=2)
    assert end == feeding_time + timedelta(hours=4)
    assert summary["next_feeding_countdown_text"].startswith("started ")
    assert summary["next_feeding_countdown_text"].endswith(" ago")
    assert summary["next_feeding_countdown_class"] == "feed-countdown-green"
    assert isinstance(summary["next_feeding_window_start_ts"], int)
    assert isinstance(summary["next_feeding_window_end_ts"], int)
    assert summary["next_feeding_window_start_ts"] < summary["next_feeding_window_end_ts"]


def test_get_period_summary_with_multiple_feedings_computes_avg_gap(session):
    config = get_or_create_config(session)
    feeding1 = Feeding(
        timestamp=datetime(2026, 7, 10, 8, 0), po_amount=10, ng_amount=10
    )
    feeding2 = Feeding(
        timestamp=datetime(2026, 7, 10, 10, 0), po_amount=20, ng_amount=20
    )
    session.add_all([feeding1, feeding2])
    session.commit()

    period_start = datetime(2026, 7, 10, 6, 0)
    summary = get_period_summary(session, config, period_start)

    assert summary["avg_gap"] == timedelta(hours=2)


def test_get_average_total_at_time_computes_average(session):
    # Reference: 2026-07-10 12:00, period start 06:00
    reference_time = datetime(2026, 7, 10, 12, 0)
    # Three days with feedings before 12:00
    for day, po in [(7, 30), (8, 40), (9, 50)]:
        session.add(
            Feeding(
                timestamp=datetime(2026, 7, day, 10, 0),
                po_amount=po,
                ng_amount=0,
            )
        )
    # Day 6 has a feeding after the cutoff (should be excluded)
    session.add(
        Feeding(
            timestamp=datetime(2026, 7, 6, 14, 0),
            po_amount=100,
            ng_amount=0,
        )
    )
    session.commit()

    avg = _get_average_total_at_time(session, reference_time)
    # 7 days: Jul 3-9. Jul 7,8,9 = 30,40,50; Jul 3,4,5 = 0; Jul 6 = 0 (after cutoff)
    assert avg == (30 + 40 + 50) / 7


def test_get_average_total_at_time_returns_none_with_too_few_days(session):
    reference_time = datetime(2026, 7, 10, 12, 0)
    for day in [8, 9]:
        session.add(
            Feeding(
                timestamp=datetime(2026, 7, day, 10, 0),
                po_amount=30,
                ng_amount=0,
            )
        )
    session.commit()

    avg = _get_average_total_at_time(session, reference_time)
    assert avg is None


def test_get_period_summary_includes_trend_for_current_period(session, monkeypatch):
    config = get_or_create_config(session)
    current_period_start = get_current_period_start()
    now = current_period_start + timedelta(hours=2)

    class FakeDatetime:
        @classmethod
        def now(cls):
            return now

        @classmethod
        def utcnow(cls):
            return now

    import app.summary

    monkeypatch.setattr(app.summary, "datetime", FakeDatetime)

    # Current feeding 30 min ago: total 100
    session.add(
        Feeding(
            timestamp=now - timedelta(minutes=30),
            po_amount=100,
            ng_amount=0,
        )
    )
    # Three past days with 50 ml before the same time of day
    for day_offset in range(1, 4):
        past_time = current_period_start - timedelta(days=day_offset) + timedelta(hours=1)
        session.add(
            Feeding(
                timestamp=past_time,
                po_amount=50,
                ng_amount=0,
            )
        )
    session.commit()

    summary = get_period_summary(session, config, current_period_start)

    # Three past days at 50 ml plus four empty days in the 7-day window
    expected_avg = (50 * 3) / 7
    assert summary["trend_variance"] == round(100 - expected_avg)
    assert summary["trend_status_class"] == "trend-status-green"
    # Pace = 100 ml over 2h * 24h = 1200 ml
    assert summary["trend_pace"] == 1200


def test_get_period_summary_no_trend_pace_under_one_hour(session, monkeypatch):
    config = get_or_create_config(session)
    current_period_start = get_current_period_start()
    now = current_period_start + timedelta(minutes=30)

    class FakeDatetime:
        @classmethod
        def now(cls):
            return now

        @classmethod
        def utcnow(cls):
            return now

    import app.summary

    monkeypatch.setattr(app.summary, "datetime", FakeDatetime)

    session.add(
        Feeding(
            timestamp=now - timedelta(minutes=10),
            po_amount=100,
            ng_amount=0,
        )
    )
    for day_offset in range(1, 4):
        past_time = current_period_start - timedelta(days=day_offset) + timedelta(minutes=10)
        session.add(
            Feeding(
                timestamp=past_time,
                po_amount=50,
                ng_amount=0,
            )
        )
    session.commit()

    summary = get_period_summary(session, config, current_period_start)

    assert summary["trend_variance"] is not None
    assert summary["trend_pace"] is None


def test_get_chart_data_excludes_empty_periods(session):
    config = get_or_create_config(session)
    feeding = Feeding(
        timestamp=datetime(2026, 7, 5, 12, 0), po_amount=30, ng_amount=10
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


def test_get_chart_data_future_end_period_clamps_to_yesterday(session):
    config = get_or_create_config(session)
    feeding = Feeding(
        timestamp=datetime(2026, 7, 5, 12, 0), po_amount=30, ng_amount=10
    )
    session.add(feeding)
    session.commit()

    far_future = datetime(2027, 1, 1, 6, 0)
    chart_data = get_chart_data(session, config, far_future)

    assert len(chart_data) == 14
    assert all(d["target"] is not None for d in chart_data)


def test_get_chart_data_computes_trend_line(session):
    config = get_or_create_config(session)
    for i in range(5):
        feeding = Feeding(
            timestamp=datetime(2026, 7, 1 + i, 12, 0),
            po_amount=20 + i * 5,
            ng_amount=20,
        )
        session.add(feeding)
    session.commit()

    chart_data = get_chart_data(session, config, datetime(2026, 7, 5, 6, 0))
    data_days = [d for d in chart_data if d["total"] is not None]
    assert len(data_days) == 5
    assert all(d["po_trend"] is not None for d in data_days)


def test_attach_effective_targets_sets_transient_attribute(session):
    config = get_or_create_config(session)
    feeding = Feeding(
        timestamp=datetime(2026, 7, 10, 9, 0), po_amount=40, ng_amount=10
    )
    session.add(feeding)
    session.commit()

    result = attach_effective_targets(session, config, [(feeding, None)])
    assert result[0][0].effective_target == 70
