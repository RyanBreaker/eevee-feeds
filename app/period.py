import math
from datetime import datetime, time, timedelta, date
from typing import Optional, Sequence


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


def get_per_feed_target(target_volume: int, feeds_per_day: int = 8) -> int:
    return math.ceil(target_volume / feeds_per_day)


def get_target_feed_interval(
    selected_timestamp: datetime,
    previous_timestamp: Optional[datetime] = None,
) -> Optional[timedelta]:
    """Return the clamped/rounded interval used for TargetFeedAmount.

    The elapsed interval is rounded to the nearest 30 minutes (ties round up)
    and clamped to a [2, 4] hour range. When there is no previous Feeding,
    return None.
    """
    if previous_timestamp is None:
        return None

    interval_hours = (selected_timestamp - previous_timestamp).total_seconds() / 3600
    rounded_hours = math.floor(interval_hours * 2 + 0.5) / 2
    clamped_hours = max(2.0, min(4.0, rounded_hours))
    return timedelta(hours=clamped_hours)


def get_target_feed_amount(
    target_volume: int,
    selected_timestamp: datetime,
    previous_timestamp: Optional[datetime] = None,
) -> int:
    """Return the interval-aware recommended volume for a single Feeding.

    The elapsed interval is rounded to the nearest 30 minutes (ties round up),
    clamped to a [2, 4] hour range, and then prorated against the 24-hour
    target volume. When there is no previous Feeding, fall back to the static
    per-feed target (target_volume / 8, rounded up).
    """
    interval = get_target_feed_interval(selected_timestamp, previous_timestamp)
    if interval is None:
        return get_per_feed_target(target_volume)

    hours = interval.total_seconds() / 3600
    return round(target_volume * hours / 24)


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


def format_feeding_countdown(
    window_start: datetime,
    window_end: datetime,
    now: Optional[datetime] = None,
) -> tuple[str, str]:
    """Return display text and CSS class for the next-feed countdown.

    Phases:
      - before window starts: "in 42m", neutral
      - during window:       "started 10m ago", green
      - after window ends:   "overdue by 12m", red
    """
    if now is None:
        now = datetime.now()
    if now < window_start:
        return f"in {format_duration(window_start - now)}", ""
    if now <= window_end:
        return f"started {format_duration(now - window_start)} ago", "feed-countdown-green"
    return f"overdue by {format_duration(now - window_end)}", "feed-countdown-red"
