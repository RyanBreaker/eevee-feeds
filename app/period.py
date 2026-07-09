from datetime import datetime, time, timedelta, date


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
