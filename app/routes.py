import csv
import os
import secrets
from datetime import date, datetime, time, timedelta
from io import StringIO
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.auth import require_auth, verify_credentials
from app.csv_import import import_feedings_from_text
from app.database import get_session
from app.models import Feeding, NotificationLog, TargetConfig
from app.notifier import DEFAULT_SERVER, DEFAULT_THRESHOLDS, notifier
from app.period import format_duration, get_period_label, get_period_start, get_target_volume

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["format_duration"] = format_duration


def get_or_create_config(session: Session) -> TargetConfig:
    config = session.exec(select(TargetConfig)).first()
    if not config:
        config = TargetConfig(
            start_date=date(2026, 7, 3),
            start_volume=520,
            increment=40,
            increment_day="Wednesday",
        )
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


def get_current_period_start() -> datetime:
    return get_period_start(datetime.now())


def get_feedings_for_period(session: Session, period_start: datetime) -> list[Feeding]:
    next_period_start = period_start + timedelta(days=1)
    statement = (
        select(Feeding)
        .where(Feeding.timestamp >= period_start, Feeding.timestamp < next_period_start)
        .order_by(Feeding.timestamp)
    )
    return list(session.exec(statement).all())


def get_feedings_with_gaps(session: Session, period_start: datetime) -> list[tuple[Feeding, Optional[timedelta]]]:
    previous_feeding = session.exec(
        select(Feeding)
        .where(Feeding.timestamp < period_start)
        .order_by(Feeding.timestamp.desc())
        .limit(1)
    ).first()

    feedings = get_feedings_for_period(session, period_start)
    result = []
    last_time = previous_feeding.timestamp if previous_feeding else None

    for feeding in feedings:
        gap = feeding.timestamp - last_time if last_time else None
        result.append((feeding, gap))
        last_time = feeding.timestamp

    return result


def get_feeding_gap(session: Session, feeding: Feeding) -> Optional[timedelta]:
    period_start = get_period_start(feeding.timestamp)
    previous_feeding = session.exec(
        select(Feeding)
        .where(Feeding.timestamp < feeding.timestamp, Feeding.timestamp >= period_start)
        .order_by(Feeding.timestamp.desc())
        .limit(1)
    ).first()

    if not previous_feeding:
        previous_feeding = session.exec(
            select(Feeding)
            .where(Feeding.timestamp < period_start)
            .order_by(Feeding.timestamp.desc())
            .limit(1)
        ).first()

    if previous_feeding:
        return feeding.timestamp - previous_feeding.timestamp
    return None


def get_period_summary(session: Session, config: TargetConfig, period_start: datetime) -> dict:
    feedings_with_gaps = get_feedings_with_gaps(session, period_start)
    feedings = [f for f, _ in feedings_with_gaps]
    po = sum(f.po_amount for f in feedings)
    ng = sum(f.ng_amount for f in feedings)
    total = po + ng
    target = get_target_volume(config, period_start.date())
    po_pct = (po / total * 100) if total > 0 else 0
    remaining = target - total

    gaps = [gap for _, gap in feedings_with_gaps if gap]
    avg_gap = None
    if gaps:
        avg_seconds = sum(gap.total_seconds() for gap in gaps) / len(gaps)
        avg_gap = timedelta(seconds=avg_seconds)

    time_since_last = None
    if period_start == get_current_period_start():
        last_feeding = session.exec(
            select(Feeding).order_by(Feeding.timestamp.desc()).limit(1)
        ).first()
        if last_feeding:
            time_since_last = datetime.now() - last_feeding.timestamp

    return {
        "po": po,
        "ng": ng,
        "total": total,
        "target": target,
        "po_pct": round(po_pct, 1),
        "remaining": remaining,
        "feedings": feedings_with_gaps,
        "avg_gap": avg_gap,
        "time_since_last": time_since_last,
    }


def get_chart_data(session: Session, config: TargetConfig, end_period: datetime) -> list[dict]:
    current_period = get_current_period_start()
    if end_period >= current_period:
        chart_end = current_period - timedelta(days=1)
    else:
        chart_end = end_period

    periods = []
    for i in range(13, -1, -1):
        start = chart_end - timedelta(days=i)
        summary = get_period_summary(session, config, start)
        periods.append(
            {
                "label": get_period_label(start),
                "total": summary["total"],
                "target": summary["target"],
                "po_pct": summary["po_pct"],
            }
        )
    return periods


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: Optional[str] = None):
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": error}
    )


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if verify_credentials(username, password):
        request.session["user"] = username
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid username or password"},
        status_code=401,
    )


@router.get("/logout")
def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    period: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    config = get_or_create_config(session)
    current_period = get_current_period_start()

    if period:
        try:
            selected_date = datetime.strptime(period, "%Y-%m-%d").date()
            selected_period = datetime.combine(selected_date, time(6, 0))
        except ValueError:
            selected_period = current_period
    else:
        selected_period = current_period

    if selected_period > current_period:
        selected_period = current_period

    is_current = selected_period.date() == current_period.date()
    summary = get_period_summary(session, config, selected_period)
    chart_data = get_chart_data(session, config, selected_period)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "summary": summary,
            "feedings": summary["feedings"],
            "chart_data": chart_data,
            "selected_period": selected_period,
            "selected_period_label": selected_period.strftime("%b %-d"),
            "previous_period": (selected_period - timedelta(days=1)).date().isoformat(),
            "next_period": (selected_period + timedelta(days=1)).date().isoformat(),
            "is_current": is_current,
        },
    )


@router.post("/feedings", response_class=HTMLResponse)
def create_feeding(
    request: Request,
    timestamp: datetime = Form(...),
    po_amount: int = Form(...),
    ng_amount: int = Form(...),
    notes: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    if timestamp > datetime.now():
        raise HTTPException(status_code=400, detail="Timestamp cannot be in the future")

    feeding = Feeding(
        timestamp=timestamp,
        po_amount=po_amount,
        ng_amount=ng_amount,
        notes=notes,
    )
    session.add(feeding)
    session.commit()

    config = get_or_create_config(session)
    feeding_period = get_period_start(feeding.timestamp)
    summary = get_period_summary(session, config, feeding_period)
    return templates.TemplateResponse(
        "partials/feeding_list.html",
        {
            "request": request,
            "feedings": summary["feedings"],
            "summary": summary,
        },
    )


@router.get("/feedings/{feeding_id}", response_class=HTMLResponse)
def feeding_row(
    request: Request,
    feeding_id: int,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    feeding = session.get(Feeding, feeding_id)
    if not feeding:
        raise HTTPException(status_code=404, detail="Feeding not found")
    gap = get_feeding_gap(session, feeding)
    return templates.TemplateResponse(
        "partials/feeding_row.html",
        {"request": request, "feeding": feeding, "gap": gap},
    )


@router.get("/feedings/{feeding_id}/edit", response_class=HTMLResponse)
def edit_feeding_form(
    request: Request,
    feeding_id: int,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    feeding = session.get(Feeding, feeding_id)
    if not feeding:
        raise HTTPException(status_code=404, detail="Feeding not found")
    return templates.TemplateResponse(
        "partials/feeding_edit_row.html",
        {"request": request, "feeding": feeding},
    )


@router.put("/feedings/{feeding_id}", response_class=HTMLResponse)
def update_feeding(
    request: Request,
    feeding_id: int,
    timestamp: datetime = Form(...),
    po_amount: int = Form(...),
    ng_amount: int = Form(...),
    notes: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    if timestamp > datetime.now():
        raise HTTPException(status_code=400, detail="Timestamp cannot be in the future")

    feeding = session.get(Feeding, feeding_id)
    if not feeding:
        raise HTTPException(status_code=404, detail="Feeding not found")

    feeding.timestamp = timestamp
    feeding.po_amount = po_amount
    feeding.ng_amount = ng_amount
    feeding.notes = notes
    feeding.updated_at = datetime.utcnow()
    session.add(feeding)
    session.commit()

    config = get_or_create_config(session)
    feeding_period = get_period_start(feeding.timestamp)
    summary = get_period_summary(session, config, feeding_period)
    gap = get_feeding_gap(session, feeding)
    return templates.TemplateResponse(
        "partials/feeding_row_oob.html",
        {
            "request": request,
            "feeding": feeding,
            "gap": gap,
            "summary": summary,
        },
    )


@router.delete("/feedings/{feeding_id}", response_class=HTMLResponse)
def delete_feeding(
    request: Request,
    feeding_id: int,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    feeding = session.get(Feeding, feeding_id)
    if not feeding:
        raise HTTPException(status_code=404, detail="Feeding not found")
    feeding_period = get_period_start(feeding.timestamp)
    session.delete(feeding)
    session.commit()

    config = get_or_create_config(session)
    summary = get_period_summary(session, config, feeding_period)
    return templates.TemplateResponse(
        "partials/feeding_list.html",
        {
            "request": request,
            "feedings": summary["feedings"],
            "summary": summary,
        },
    )

def get_notification_status(session: Session) -> dict:
    topic = os.getenv("NTFY_TOPIC")
    server = (os.getenv("NTFY_SERVER") or DEFAULT_SERVER).rstrip("/")
    raw_thresholds = os.getenv("NTFY_THRESHOLDS")
    thresholds = (
        notifier._parse_thresholds(raw_thresholds)
        if raw_thresholds
        else DEFAULT_THRESHOLDS
    )
    last_feeding = session.exec(
        select(Feeding).order_by(Feeding.timestamp.desc()).limit(1)
    ).first()

    next_notification = None
    if topic and last_feeding:
        sent_thresholds = {
            row[0]
            for row in session.exec(
                select(NotificationLog.threshold_hours).where(
                    NotificationLog.feeding_id == last_feeding.id
                )
            ).all()
        }
        now = datetime.now()
        for threshold in thresholds:
            if threshold in sent_thresholds:
                continue
            threshold_time = last_feeding.timestamp + timedelta(hours=threshold)
            if threshold_time > now:
                next_notification = threshold_time
                break

    return {
        "enabled": bool(topic),
        "topic": topic,
        "server": server,
        "thresholds": thresholds,
        "next_notification": next_notification,
    }


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    message: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    config = get_or_create_config(session)
    notification = get_notification_status(session)
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "config": config, "message": message, "notification": notification},
    )


@router.post("/settings/test-notify")
async def test_notify(
    request: Request,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    if not notifier.topic:
        message = "Notifications are not configured: NTFY_TOPIC is not set."
        return RedirectResponse(
            url=f"/settings?message={quote(message)}", status_code=303
        )
    ok = await notifier.send_test()
    if ok:
        message = "Test notification sent successfully."
    else:
        message = "Failed to send test notification. Check the server logs."
    return RedirectResponse(url=f"/settings?message={quote(message)}", status_code=303)


@router.post("/settings/test-notify-current")
async def test_notify_current(
    request: Request,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    if not notifier.topic:
        message = "Notifications are not configured: NTFY_TOPIC is not set."
        return RedirectResponse(
            url=f"/settings?message={quote(message)}", status_code=303
        )

    last_feeding = session.exec(
        select(Feeding).order_by(Feeding.timestamp.desc()).limit(1)
    ).first()
    if not last_feeding:
        message = "No feedings have been logged yet, so there is no gap to report."
        return RedirectResponse(
            url=f"/settings?message={quote(message)}", status_code=303
        )

    ok = await notifier.send_test_current_gap()
    if ok:
        message = "Current-gap test notification sent successfully."
    else:
        message = "Failed to send current-gap test notification. Check the server logs."
    return RedirectResponse(url=f"/settings?message={quote(message)}", status_code=303)


@router.post("/settings")
def update_settings(
    request: Request,
    start_date: date = Form(...),
    start_volume: int = Form(...),
    increment: int = Form(...),
    increment_day: str = Form(...),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    config = get_or_create_config(session)
    config.start_date = start_date
    config.start_volume = start_volume
    config.increment = increment
    config.increment_day = increment_day
    config.updated_at = datetime.utcnow()
    session.add(config)
    session.commit()
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/import")
def import_csv_upload(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    try:
        content = file.file.read().decode("utf-8")
        result = import_feedings_from_text(session, content, skip_existing=True)
    except Exception as exc:
        message = f"Import failed: {exc}"
        return RedirectResponse(
            url=f"/settings?message={quote(message)}",
            status_code=303,
        )

    if result["skipped"]:
        message = "Feedings already exist. No new rows imported."
    else:
        message = f"Imported {result['imported']} feedings."

    return RedirectResponse(
        url=f"/settings?message={quote(message)}",
        status_code=303,
    )


@router.get("/export")
def export_csv(
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    feedings = list(session.exec(select(Feeding).order_by(Feeding.timestamp)).all())
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "PO", "NG", "Total", "Notes"])
    for f in feedings:
        writer.writerow(
            [
                f.timestamp.strftime("%a, %b %d, %Y %I:%M %p"),
                f.po_amount,
                f.ng_amount,
                f.po_amount + f.ng_amount,
                f.notes or "",
            ]
        )
    content = output.getvalue()
    output.close()
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=feedings.csv"},
    )
