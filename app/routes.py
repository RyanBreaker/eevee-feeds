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
from app.models import Feeding, FeedingStart, TargetConfig
from app.notification_service import notification_service
from app.period import (
    format_duration,
    format_time,
    get_period_start,
)
import app.feeding_service as feeding_service
from app.repository import (
    create_feeding_start,
    delete_feeding_start,
    get_all_feedings,
    get_feeding_by_id,
    get_feeding_gap,
    get_feeding_start,
    get_or_create_config,
    update_feeding_start_timestamp,
)
from app.summary import (
    attach_feeding_number,
    get_chart_data,
    get_current_period_start,
    get_period_summary,
)
from app.target_amount import compute_feed_target, effective_target_for_feeding

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["format_duration"] = format_duration
templates.env.filters["format_time"] = format_time


def get_feeding_or_404(session: Session, feeding_id: int) -> Feeding:
    feeding = get_feeding_by_id(session, feeding_id)
    if not feeding:
        raise HTTPException(status_code=404, detail="Feeding not found")
    return feeding


def _now_truncated() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def _hx_target_is_card(request: Request) -> bool:
    hx_target = request.headers.get("HX-Target", "")
    return hx_target.startswith("feeding-card-")


def _require_timestamp_not_future(timestamp: datetime) -> None:
    if timestamp > datetime.now():
        raise HTTPException(status_code=400, detail="Timestamp cannot be in the future")


def _render_feeding_list(
    request: Request,
    session: Session,
    config: TargetConfig,
    feeding_period: datetime,
) -> Response:
    summary = get_period_summary(session, config, feeding_period)
    return templates.TemplateResponse(
        "partials/feeding_list.html",
        {
            "request": request,
            "feedings": summary["feedings"],
            "summary": summary,
            "now": datetime.now(),
        },
    )


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
    feeding_start = get_feeding_start(session)

    default_timestamp = _now_truncated()

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
            "now": default_timestamp,
            "feeding_start": feeding_start,
            "default_timestamp": default_timestamp,
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
    feed_target_result = compute_feed_target(
        session, config, selected_timestamp, exclude_feeding_id=feeding_id
    )
    return {
        "target": feed_target_result.target_volume,
        "per_feed": feed_target_result.per_feed,
        "interval_minutes": feed_target_result.interval_minutes,
        "actual_interval_minutes": feed_target_result.actual_interval_minutes,
    }


@router.post("/feedings", response_class=HTMLResponse)
def create_feeding(
    request: Request,
    timestamp: datetime = Form(...),
    po_amount: int = Form(...),
    ng_amount: int = Form(...),
    notes: Optional[str] = Form(None),
    is_snack: bool = Form(False),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    config = get_or_create_config(session)
    try:
        feeding = feeding_service.create_feeding(
            session, config, timestamp, po_amount, ng_amount, notes, is_snack
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    feeding_period = get_period_start(feeding.timestamp)
    return _render_feeding_list(request, session, config, feeding_period)


def _render_feeding_start_section(
    request: Request,
    feeding_start: Optional[FeedingStart],
) -> Response:
    return templates.TemplateResponse(
        "partials/feeding_start_section.html",
        {
            "request": request,
            "feeding_start": feeding_start,
            "default_timestamp": _now_truncated(),
        },
    )


@router.get("/feedings/start-section", response_class=HTMLResponse)
def feeding_start_section(
    request: Request,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    return _render_feeding_start_section(request, get_feeding_start(session))


@router.post("/feedings/start", response_class=HTMLResponse)
def start_feeding(
    request: Request,
    timestamp: datetime = Form(...),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    existing = get_feeding_start(session)
    if existing:
        raise HTTPException(status_code=409, detail="A feed is already in progress")

    feeding_start = create_feeding_start(session, timestamp)
    return _render_feeding_start_section(request, feeding_start)


@router.put("/feedings/start", response_class=HTMLResponse)
def update_feeding_start(
    request: Request,
    timestamp: datetime = Form(...),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    _require_timestamp_not_future(timestamp)

    feeding_start = get_feeding_start(session)
    if not feeding_start:
        raise HTTPException(status_code=404, detail="No feed in progress")

    feeding_start = update_feeding_start_timestamp(session, feeding_start, timestamp)
    return _render_feeding_start_section(request, feeding_start)


@router.delete("/feedings/start", response_class=HTMLResponse)
def cancel_feeding_start(
    request: Request,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    feeding_start = get_feeding_start(session)
    if feeding_start:
        delete_feeding_start(session, feeding_start)
    return _render_feeding_start_section(request, None)


@router.get("/feedings/start-target", response_class=HTMLResponse)
def start_feed_target(
    request: Request,
    timestamp: datetime = Query(...),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    config = get_or_create_config(session)
    feed_target_result = compute_feed_target(session, config, timestamp)
    per_feed = feed_target_result.per_feed

    if feed_target_result.actual_interval_minutes is not None:
        interval_text = format_duration(
            timedelta(minutes=feed_target_result.actual_interval_minutes)
        )
        note = f"{per_feed} ml ({interval_text} after last feed)"
    else:
        note = f"{per_feed} ml (no previous feed)"

    return templates.TemplateResponse(
        "partials/start_feed_target.html",
        {"request": request, "note": note},
    )


@router.post("/feedings/complete", response_class=HTMLResponse)
def complete_feeding(
    request: Request,
    timestamp: datetime = Form(...),
    po_amount: int = Form(...),
    ng_amount: int = Form(...),
    notes: Optional[str] = Form(None),
    is_snack: bool = Form(False),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    feeding_start = get_feeding_start(session)
    if not feeding_start:
        raise HTTPException(status_code=404, detail="No feed in progress")

    config = get_or_create_config(session)
    try:
        feeding = feeding_service.complete_feeding(
            session, config, feeding_start, timestamp, po_amount, ng_amount, notes, is_snack
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    feeding_period = get_period_start(feeding.timestamp)
    response = _render_feeding_list(request, session, config, feeding_period)
    response.headers["HX-Trigger"] = "feeding-completed"
    return response


@router.get("/feedings/{feeding_id}", response_class=HTMLResponse)
def feeding_row(
    request: Request,
    feeding_id: int,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    feeding = get_feeding_or_404(session, feeding_id)
    config = get_or_create_config(session)
    gap = get_feeding_gap(session, feeding)
    effective_target = effective_target_for_feeding(session, config, feeding)
    attach_feeding_number(session, feeding)
    template = (
        "partials/feeding_card.html"
        if _hx_target_is_card(request)
        else "partials/feeding_row.html"
    )
    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "feeding": feeding,
            "gap": gap,
            "effective_target": effective_target,
            "now": datetime.now(),
        },
    )


@router.get("/feedings/{feeding_id}/edit", response_class=HTMLResponse)
def edit_feeding_form(
    request: Request,
    feeding_id: int,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    feeding = get_feeding_or_404(session, feeding_id)
    template = (
        "partials/feeding_edit_card.html"
        if _hx_target_is_card(request)
        else "partials/feeding_edit_row.html"
    )
    return templates.TemplateResponse(
        template,
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
    is_snack: bool = Form(False),
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    feeding = get_feeding_or_404(session, feeding_id)
    config = get_or_create_config(session)
    try:
        feeding = feeding_service.update_feeding(
            session, config, feeding, timestamp, po_amount, ng_amount, notes, is_snack
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    gap = get_feeding_gap(session, feeding)
    effective_target = effective_target_for_feeding(session, config, feeding)
    attach_feeding_number(session, feeding)
    template = (
        "partials/feeding_card.html"
        if _hx_target_is_card(request)
        else "partials/feeding_row.html"
    )
    response = templates.TemplateResponse(
        template,
        {
            "request": request,
            "feeding": feeding,
            "gap": gap,
            "effective_target": effective_target,
            "now": datetime.now(),
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
    feeding_service.delete_feeding(session, feeding)

    config = get_or_create_config(session)
    summary = get_period_summary(session, config, feeding_period)
    return templates.TemplateResponse(
        "partials/feeding_list.html",
        {
            "request": request,
            "feedings": summary["feedings"],
            "summary": summary,
            "now": datetime.now(),
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
    feeding_start = get_feeding_start(session)
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "config": config,
            "message": message,
            "notification": notification,
            "backup": backup,
            "feeding_start": feeding_start,
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
