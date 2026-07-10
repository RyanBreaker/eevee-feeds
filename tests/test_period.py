from datetime import date, datetime, timedelta

from app.models import TargetConfig
from app.period import format_duration, format_time, get_period_label, get_period_start, get_target_volume, linear_trend


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


def test_format_time_am():
    assert format_time(datetime(2026, 7, 9, 5, 35)) == "5:35AM"


def test_format_time_pm():
    assert format_time(datetime(2026, 7, 9, 15, 35)) == "3:35PM"


def test_format_time_noon():
    assert format_time(datetime(2026, 7, 9, 12, 0)) == "12:00PM"


def test_format_time_midnight():
    assert format_time(datetime(2026, 7, 9, 0, 0)) == "12:00AM"


def test_format_time_padded_minutes():
    assert format_time(datetime(2026, 7, 9, 15, 5)) == "3:05PM"


def test_linear_trend_increasing():
    values = [0, 1, 2, 3, 4]
    trend = linear_trend(values)
    assert trend[0] == 0
    assert trend[-1] == 4


def test_linear_trend_flat():
    values = [5, 5, 5, 5]
    assert linear_trend(values) == [5, 5, 5, 5]


def test_linear_trend_empty():
    assert linear_trend([]) == []
