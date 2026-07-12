from datetime import datetime, timedelta

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
    get_feedings_with_gaps,
    get_last_feeding,
)


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
    if period_start == get_current_period_start():
        last_feeding = get_last_feeding(session)
        if last_feeding:
            time_since_last = datetime.now() - last_feeding.timestamp
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

    for i, period in enumerate(periods):
        window_totals = [
            p["total"] for p in periods[max(0, i - 6) : i + 1] if p["total"] is not None
        ]
        if window_totals:
            period["rolling_avg"] = round(sum(window_totals) / len(window_totals))
        else:
            period["rolling_avg"] = None

    return periods
