from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session

from app.models import TargetConfig
from app.period import (
    format_feeding_countdown,
    get_period_label,
    get_period_start,
    get_target_volume,
    linear_trend,
)
from app.repository import (
    attach_effective_targets,
    get_feedings_for_period,
    get_feedings_with_gaps,
    get_last_feeding,
)


def _get_average_total_at_time(
    session: Session, reference_time: datetime, days: int = 7
) -> Optional[float]:
    """Return the average total intake at the same time of day over the last N days."""
    current_period_start = get_period_start(reference_time)
    time_into_period = reference_time - current_period_start
    totals = []
    days_with_feedings = 0
    for day_offset in range(1, days + 1):
        past_period_start = current_period_start - timedelta(days=day_offset)
        past_cutoff = past_period_start + time_into_period
        feedings = get_feedings_for_period(session, past_period_start)
        feedings_up_to_time = [f for f in feedings if f.timestamp <= past_cutoff]
        if feedings_up_to_time:
            days_with_feedings += 1
        total = sum(f.po_amount + f.ng_amount for f in feedings_up_to_time)
        totals.append(total)
    if days_with_feedings < 3:
        return None
    return sum(totals) / len(totals)


def get_current_period_start() -> datetime:
    return get_period_start(datetime.now())


def get_period_summary(session: Session, config: TargetConfig, period_start: datetime) -> dict:
    feedings_with_gaps = attach_effective_targets(
        session, config, get_feedings_with_gaps(session, period_start)
    )
    feedings = [f for f, _ in feedings_with_gaps]
    po = sum(f.po_amount for f in feedings)
    ng = sum(f.ng_amount for f in feedings)
    total = po + ng
    target = get_target_volume(config, period_start.date())
    po_pct = (po / total * 100) if total > 0 else 0
    remaining = target - total

    target_variance = total - target

    if target > 0:
        target_ratio = total / target
    else:
        target_ratio = 0
    target_progress_pct = int(min(target_ratio * 100, 100))
    if target_ratio >= 0.9:
        target_status_class = "target-status-green"
    elif target_ratio >= 0.75:
        target_status_class = "target-status-yellow"
    else:
        target_status_class = "target-status-red"

    gaps = [gap for _, gap in feedings_with_gaps if gap]
    avg_gap = None
    if gaps:
        avg_seconds = sum(gap.total_seconds() for gap in gaps) / len(gaps)
        avg_gap = timedelta(seconds=avg_seconds)

    time_since_last = None
    next_feeding_window = None
    next_feeding_countdown_text = None
    next_feeding_countdown_class = ""
    next_feeding_window_start_ts = None
    next_feeding_window_end_ts = None
    trend_variance = None
    trend_status_class = ""
    trend_pace = None
    if period_start == get_current_period_start():
        now = datetime.now()
        last_feeding = get_last_feeding(session)
        if last_feeding:
            time_since_last = now - last_feeding.timestamp
            next_feeding_window = (
                last_feeding.timestamp + timedelta(hours=2),
                last_feeding.timestamp + timedelta(hours=4),
            )
            next_feeding_countdown_text, next_feeding_countdown_class = (
                format_feeding_countdown(
                    next_feeding_window[0], next_feeding_window[1]
                )
            )
            next_feeding_window_start_ts = int(
                next_feeding_window[0].timestamp()
            )
            next_feeding_window_end_ts = int(next_feeding_window[1].timestamp())

        avg_total_at_time = _get_average_total_at_time(session, now)
        if avg_total_at_time is not None:
            trend_variance = round(total - avg_total_at_time)
            trend_status_class = (
                "trend-status-green" if trend_variance >= 0 else "trend-status-red"
            )
        elapsed_hours = (now - period_start).total_seconds() / 3600
        if elapsed_hours >= 1 and total > 0:
            trend_pace = round(total / elapsed_hours * 24)

    return {
        "po": po,
        "ng": ng,
        "total": total,
        "target": target,
        "po_pct": round(po_pct, 1),
        "remaining": remaining,
        "target_variance": target_variance,
        "target_progress_pct": target_progress_pct,
        "target_status_class": target_status_class,
        "feedings": feedings_with_gaps,
        "avg_gap": avg_gap,
        "time_since_last": time_since_last,
        "next_feeding_window": next_feeding_window,
        "next_feeding_countdown_text": next_feeding_countdown_text,
        "next_feeding_countdown_class": next_feeding_countdown_class,
        "next_feeding_window_start_ts": next_feeding_window_start_ts,
        "next_feeding_window_end_ts": next_feeding_window_end_ts,
        "trend_variance": trend_variance,
        "trend_status_class": trend_status_class,
        "trend_pace": trend_pace,
    }


def get_chart_data(session: Session, config: TargetConfig, end_period: datetime) -> list[dict]:
    current_period = get_current_period_start()
    if end_period >= current_period:
        chart_end = current_period - timedelta(days=1)
    else:
        chart_end = end_period

    periods = []
    has_data = []
    for i in range(13, -1, -1):
        start = chart_end - timedelta(days=i)
        summary = get_period_summary(session, config, start)
        has_feedings = summary["total"] > 0
        has_data.append(has_feedings)
        periods.append(
            {
                "label": get_period_label(start),
                "total": summary["total"] if has_feedings else None,
                "target": summary["target"],
                "po_pct": summary["po_pct"] if has_feedings else None,
            }
        )

    x_values = [i for i, has in enumerate(has_data) if has]
    y_values = [periods[i]["po_pct"] for i in x_values]
    trend_values = linear_trend(y_values)
    trend_iter = iter(trend_values)
    for i, has in enumerate(has_data):
        if has:
            periods[i]["po_trend"] = round(next(trend_iter), 1)
        else:
            periods[i]["po_trend"] = None

    return periods
