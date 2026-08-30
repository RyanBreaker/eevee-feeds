from datetime import datetime, time, timedelta
from typing import Optional

from sqlmodel import Session

from app.models import Feeding, TargetConfig
from app.period import (
    format_feeding_countdown,
    get_period_label,
    get_period_start,
    get_target_volume,
    linear_trend,
    linear_trend_fitted_at,
    linear_trend_slope_at,
)
from app.repository import (
    get_feeding_number,
    get_feedings_for_period,
    get_feedings_with_gaps,
    get_last_feeding,
)
from app.target_amount import effective_target_for_feeding


def attach_effective_targets(
    session: Session,
    config: TargetConfig,
    feedings_with_gaps: list[tuple[Feeding, Optional[timedelta]]],
) -> list[tuple[Feeding, Optional[timedelta]]]:
    """Set ``feeding.effective_target`` on each feeding for template use."""
    for feeding, _ in feedings_with_gaps:
        # Bypass Pydantic so we can attach a transient computed value.
        object.__setattr__(
            feeding,
            "effective_target",
            effective_target_for_feeding(session, config, feeding),
        )
    return feedings_with_gaps


def attach_feeding_numbers(
    feedings_with_gaps: list[tuple[Feeding, Optional[timedelta]]],
) -> list[tuple[Feeding, Optional[timedelta]]]:
    """Set ``feeding.number`` to the 1-based position within the Period."""
    for number, (feeding, _) in enumerate(feedings_with_gaps, start=1):
        # Bypass Pydantic so we can attach a transient computed value.
        object.__setattr__(feeding, "number", number)
    return feedings_with_gaps


def attach_feeding_number(
    session: Session, config: TargetConfig, feeding: Feeding
) -> Feeding:
    """Set ``feeding.number`` to the 1-based position within its Period."""
    # Bypass Pydantic so we can attach a transient computed value.
    object.__setattr__(
        feeding,
        "number",
        get_feeding_number(session, feeding, config.period_start_time),
    )
    return feeding


def _get_average_total_at_time(
    session: Session, reference_time: datetime, start_time: time, days: int = 7
) -> Optional[float]:
    """Return the average total intake at the same time of day over the last N days."""
    current_period_start = get_period_start(reference_time, start_time)
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


def _trend_status_class(variance: int) -> str:
    return "trend-status-green" if variance >= 0 else "trend-status-red"


def _get_previous_period_total_at_time(
    session: Session, reference_time: datetime, start_time: time
) -> Optional[int]:
    """Return the previous Period's total intake at the same elapsed time.

    Returns None when the previous Period has no Feedings at all.
    """
    current_period_start = get_period_start(reference_time, start_time)
    previous_period_start = current_period_start - timedelta(days=1)
    feedings = get_feedings_for_period(session, previous_period_start)
    if not feedings:
        return None
    cutoff = previous_period_start + (reference_time - current_period_start)
    return sum(
        f.po_amount + f.ng_amount for f in feedings if f.timestamp <= cutoff
    )


def _get_intake_trend(session: Session, config: TargetConfig) -> Optional[int]:
    """Return the Intake trend slope (mL/day) over the last 14 completed Periods.

    Empty Periods still count as day positions so the slope is per day.
    Returns None when fewer than 3 of those Periods have Feedings.
    """
    current_period = get_current_period_start(config.period_start_time)
    days = []
    totals = []
    for day_offset in range(14, 0, -1):
        start = current_period - timedelta(days=day_offset)
        feedings = get_feedings_for_period(session, start)
        if feedings:
            days.append(14 - day_offset)
            totals.append(sum(f.po_amount + f.ng_amount for f in feedings))
    if len(totals) < 3:
        return None
    return round(linear_trend_slope_at(days, totals))


def get_current_period_start(start_time: time) -> datetime:
    return get_period_start(datetime.now(), start_time)


def get_period_summary(session: Session, config: TargetConfig, period_start: datetime) -> dict:
    feedings_with_gaps = attach_feeding_numbers(
        attach_effective_targets(
            session, config, get_feedings_with_gaps(session, period_start)
        )
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

    gaps = [
        gap for feeding, gap in feedings_with_gaps if gap and not feeding.is_snack
    ]
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
    trend_variance_yesterday = None
    trend_status_class_yesterday = ""
    intake_trend = None
    is_current = period_start == get_current_period_start(config.period_start_time)
    if is_current:
        now = datetime.now()
        last_feeding = get_last_feeding(session, skip_snacks=True)
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

        avg_total_at_time = _get_average_total_at_time(
            session, now, config.period_start_time
        )
        if avg_total_at_time is not None:
            trend_variance = round(total - avg_total_at_time)
            trend_status_class = _trend_status_class(trend_variance)
        yesterday_total_at_time = _get_previous_period_total_at_time(
            session, now, config.period_start_time
        )
        if yesterday_total_at_time is not None:
            trend_variance_yesterday = round(total - yesterday_total_at_time)
            trend_status_class_yesterday = _trend_status_class(
                trend_variance_yesterday
            )
        elapsed_hours = (now - period_start).total_seconds() / 3600
        if elapsed_hours >= 1 and total > 0:
            trend_pace = round(total / elapsed_hours * 24)
        intake_trend = _get_intake_trend(session, config)

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
        "trend_variance_yesterday": trend_variance_yesterday,
        "trend_status_class_yesterday": trend_status_class_yesterday,
        "intake_trend": intake_trend,
        "is_current": is_current,
    }


def get_chart_data(session: Session, config: TargetConfig, end_period: datetime) -> list[dict]:
    oral_only = config.tracking_mode == "oral_only"
    current_period = get_current_period_start(config.period_start_time)
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
        period_feedings = [f for f, _ in summary["feedings"]]
        period = {
            "label": get_period_label(start, config.period_start_time),
            "total": summary["total"] if has_feedings else None,
            "target": summary["target"],
            "regular_count": (
                sum(1 for f in period_feedings if not f.is_snack)
                if has_feedings
                else None
            ),
            "snack_count": (
                sum(1 for f in period_feedings if f.is_snack)
                if has_feedings
                else None
            ),
        }
        if not oral_only:
            period["po_pct"] = summary["po_pct"] if has_feedings else None
        periods.append(period)

    x_values = [i for i, has in enumerate(has_data) if has]
    if oral_only:
        trend_key = "intake_trend_line"
        y_values = [periods[i]["total"] for i in x_values]
        # Fit over true day positions so the line matches the mL/day slope.
        trend_values = linear_trend_fitted_at(x_values, y_values)
    else:
        trend_key = "po_trend"
        y_values = [periods[i]["po_pct"] for i in x_values]
        trend_values = linear_trend(y_values)
    trend_iter = iter(trend_values)
    for i, has in enumerate(has_data):
        if has:
            periods[i][trend_key] = round(next(trend_iter), 1)
        else:
            periods[i][trend_key] = None

    return periods
