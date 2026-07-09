from datetime import date, datetime, timedelta

from app.models import TargetConfig
from app.period import format_duration, get_period_label, get_period_start, get_target_volume


def test_format_duration_minutes_only():
    assert format_duration(timedelta(minutes=5)) == "5m"


def test_format_duration_hours_and_minutes():
    assert format_duration(timedelta(hours=1, minutes=30)) == "1h 30m"


def test_format_duration_zero():
    assert format_duration(timedelta(hours=0)) == "0m"


def test_get_period_start_before_6am():
    dt = datetime(2026, 7, 9, 5, 0)
    assert get_period_start(dt) == datetime(2026, 7, 8, 6, 0)


def test_get_period_start_at_6am():
    dt = datetime(2026, 7, 9, 6, 0)
    assert get_period_start(dt) == datetime(2026, 7, 9, 6, 0)


def test_get_period_start_after_6am():
    dt = datetime(2026, 7, 9, 7, 0)
    assert get_period_start(dt) == datetime(2026, 7, 9, 6, 0)


def test_get_period_label():
    dt = datetime(2026, 7, 9, 7, 0)
    assert get_period_label(dt) == "Jul 9"


def test_get_target_volume():
    config = TargetConfig(
        start_date=date(2026, 7, 3),
        start_volume=520,
        increment=40,
        increment_day="Wednesday",
    )
    assert get_target_volume(config, date(2026, 7, 3)) == 520
    assert get_target_volume(config, date(2026, 7, 9)) == 560
    assert get_target_volume(config, date(2026, 7, 16)) == 600
