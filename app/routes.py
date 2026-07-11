from datetime import date, datetime, time, timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.backup_service import backup_service
from app.auth import require_auth, verify_credentials
from app.csv_import import import_feedings_from_text
from app.csv_io import FeedingCsvWriter
from app.database import get_session
from app.models import Feeding, TargetConfig
from app.notification_service import notification_service
from app.period import (
    format_duration,
    format_time,
    get_period_start,
    get_target_feed_amount,
    get_target_feed_interval,
    get_target_volume,
)
from app.repository import (
    get_all_feedings,
    get_feeding_by_id,
    get_feeding_gap,
    get_last_feeding,
    get_or_create_config,
    get_previous_feeding,
)
from app.summary import get_chart_data, get_current_period_start, get_period_summary

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["format_duration"] = format_duration
templates.env.filters["format_time"] = format_time


def get_feeding_or_404(session: Session, feeding_id: int) -> Feeding:
    feeding = get_feeding_by_id(session, feeding_id)
    if not feeding:
        raise HTTPException(status_code=404, detail="Feeding not found")
    return feeding


def _compute_target_per_feed(
    session: Session,
    config: TargetConfig,
    timestamp: datetime,
    exclude_feeding_id: Optional[int] = None,
) -> int:
    period_start = get_period_start(timestamp)
    target = get_target_volume(config, period_start.date())
    previous_feeding = get_previous_feeding(
        session, timestamp, exclude_feeding_id=exclude_feeding_id
    )
    previous_timestamp = previous_feeding.timestamp if previous_feeding else None
    return get_target_feed_amount(target, timestamp, previous_timestamp)


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


@router.get("/summary-cards", response_class=HTMLResponse)
def summary_cards(
    request: Request,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    config = get_or_create_config(session)
    summary = get_period_summary(session, config, get_current_period_start())
    return templates.TemplateResponse(
        "partials/summary_cards.html",
        {"request": request, "summary": summary},
    )


@router.get("/api/feed-target")
def feed_target(
    target_date: Optional[date] = Query(None, alias="date"),
    target_timestamp: Optional[datetime] = Query(None, alias="timestamp"),
    feeding_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    if target_timestamp:
        selected_timestamp = target_timestamp
    elif target_date:
        selected_timestamp = datetime.combine(target_date, time(6, 0))
    else:
        selected_timestamp = datetime.now()

    config = get_or_create_config(session)
    period_start = get_period_start(selected_timestamp)
    target = get_target_volume(config, period_start.date())
    previous_feeding = get_previous_feeding(
        session, selected_timestamp, exclude_feeding_id=feeding_id
    )
    previous_timestamp = previous_feeding.timestamp if previous_feeding else None
    per_feed = get_target_feed_amount(
        target, selected_timestamp, previous_timestamp
    )
    if previous_timestamp:
        interval = get_target_feed_interval(selected_timestamp, previous_timestamp)
        assert interval is not None
        interval_minutes = int(interval.total_seconds() // 60)
        actual_interval = selected_timestamp - previous_timestamp
        actual_interval_minutes = int(actual_interval.total_seconds() // 60)
    else:
        interval_minutes = None
        actual_interval_minutes = None
    return {
        "target": target,
        "per_feed": per_feed,
        "interval_minutes": interval_minutes,
        "actual_interval_minutes": actual_interval_minutes,
    }


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

    config = get_or_create_config(session)
    target_per_feed = _compute_target_per_feed(session, config, timestamp)
    feeding = Feeding(
        timestamp=timestamp,
        po_amount=po_amount,
        ng_amount=ng_amount,
        target_per_feed=target_per_feed,
        notes=notes,
    )
    session.add(feeding)
    session.commit()

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
    feeding = get_feeding_or_404(session, feeding_id)
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
    feeding = get_feeding_or_404(session, feeding_id)
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

    feeding = get_feeding_or_404(session, feeding_id)
    config = get_or_create_config(session)
    target_per_feed = _compute_target_per_feed(
        session, config, timestamp, exclude_feeding_id=feeding_id
    )

    feeding.timestamp = timestamp
    feeding.po_amount = po_amount
    feeding.ng_amount = ng_amount
    feeding.target_per_feed = target_per_feed
    feeding.notes = notes
    feeding.updated_at = datetime.utcnow()
    session.add(feeding)
    session.commit()

    gap = get_feeding_gap(session, feeding)
    response = templates.TemplateResponse(
        "partials/feeding_row.html",
        {
            "request": request,
            "feeding": feeding,
            "gap": gap,
        },
    )
    response.headers["HX-Trigger"] = "feeding-updated"
    return response


@router.delete("/feedings/{feeding_id}", response_class=HTMLResponse)
def delete_feeding(
    request: Request,
    feeding_id: int,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    feeding = get_feeding_or_404(session, feeding_id)
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


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    message: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    config = get_or_create_config(session)
    notification = notification_service.get_status(session)
    backup = backup_service.get_status(session)
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "config": config,
            "message": message,
            "notification": notification,
            "backup": backup,
        },
    )


@router.post("/settings/test-notify")
async def test_notify(
    request: Request,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    if not notification_service.topic:
        message = "Notifications are not configured: NTFY_TOPIC is not set."
        return RedirectResponse(
            url=f"/settings?message={quote(message)}", status_code=303
        )
    ok = await notification_service.send_test(session)
    if ok:
        message = "Test notification sent successfully."
    else:
        message = "Failed to send test notification. Check the server logs."
    return RedirectResponse(url=f"/settings?message={quote(message)}", status_code=303)


@router.post("/settings/backup")
async def manual_backup(
    request: Request,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    if not backup_service.enabled:
        message = "Backup is not configured: set B2_KEY_ID, B2_APPLICATION_KEY, and B2_BUCKET_NAME."
        return RedirectResponse(
            url=f"/settings?message={quote(message)}", status_code=303
        )
    ok = await backup_service.run_backup(session)
    if ok:
        message = "Backup completed successfully."
    else:
        message = "Backup failed. Check the server logs."
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
    feedings = get_all_feedings(session)
    writer = FeedingCsvWriter()
    content = writer.write_feedings(feedings)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=feedings.csv"},
    )
