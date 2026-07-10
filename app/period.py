from datetime import datetime, time, timedelta, date
from typing import Sequence


def get_period_start(timestamp: datetime) -> datetime:
    """Return the 6AM start of the feeding period that contains the timestamp."""
    dt = timestamp.date()
    if timestamp.time() < time(6, 0):
        dt -= timedelta(days=1)
    return datetime.combine(dt, time(6, 0))


def get_period_label(timestamp: datetime) -> str:
    return get_period_start(timestamp).strftime("%b %-d")


_DAY_MAP = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def count_increment_days(start_date: date, current_date: date, day_name: str) -> int:
    target_weekday = _DAY_MAP[day_name]
    count = 0
    d = start_date + timedelta(days=1)
    while d <= current_date:
        if d.weekday() == target_weekday:
            count += 1
        d += timedelta(days=1)
    return count


def get_target_volume(config, current_date: date) -> int:
    if current_date <= config.start_date:
        return config.start_volume
    increments = count_increment_days(config.start_date, current_date, config.increment_day)
    return config.start_volume + increments * config.increment


def format_time(dt: datetime) -> str:
    hour = dt.hour
    am_pm = "AM" if hour < 12 else "PM"
    hour_12 = hour % 12
    if hour_12 == 0:
        hour_12 = 12
    return f"{hour_12}:{dt.strftime('%M')}{am_pm}"


def linear_trend(values: Sequence[float]) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(values)
    sum_xy = sum(xi * yi for xi, yi in zip(x, values))
    sum_x2 = sum(xi * xi for xi in x)
    denominator = n * sum_x2 - sum_x * sum_x
    if denominator == 0:
        return [sum_y / n] * n
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / n
    return [slope * xi + intercept for xi in x]


def format_duration(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
