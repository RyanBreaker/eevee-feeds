from datetime import datetime, date, timedelta
from io import StringIO
from typing import Optional
from urllib.parse import quote

import csv
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.auth import require_auth
from app.csv_import import import_feedings_from_text
from app.database import get_session
from app.models import Feeding, TargetConfig
from app.period import get_period_label, get_period_start, get_target_volume

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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


def get_period_summary(session: Session, config: TargetConfig, period_start: datetime) -> dict:
    feedings = get_feedings_for_period(session, period_start)
    po = sum(f.po_amount for f in feedings)
    ng = sum(f.ng_amount for f in feedings)
    total = po + ng
    target = get_target_volume(config, period_start.date())
    po_pct = (po / total * 100) if total > 0 else 0
    remaining = target - total
    return {
        "po": po,
        "ng": ng,
        "total": total,
        "target": target,
        "po_pct": round(po_pct, 1),
        "remaining": remaining,
        "feedings": feedings,
    }


def get_chart_data(session: Session, config: TargetConfig) -> list[dict]:
    current_period = get_current_period_start()
    periods = []
    for i in range(13, -1, -1):
        start = current_period - timedelta(days=i)
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


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    session: Session = Depends(get_session),
    _: Optional[str] = Depends(require_auth),
):
    config = get_or_create_config(session)
    current_period = get_current_period_start()
    summary = get_period_summary(session, config, current_period)
    chart_data = get_chart_data(session, config)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "summary": summary,
            "feedings": summary["feedings"],
            "chart_data": chart_data,
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
    current_period = get_current_period_start()
    summary = get_period_summary(session, config, current_period)
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
    return templates.TemplateResponse(
        "partials/feeding_row.html",
        {"request": request, "feeding": feeding},
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
    current_period = get_current_period_start()
    summary = get_period_summary(session, config, current_period)
    return templates.TemplateResponse(
        "partials/feeding_row_oob.html",
        {
            "request": request,
            "feeding": feeding,
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
    session.delete(feeding)
    session.commit()

    config = get_or_create_config(session)
    current_period = get_current_period_start()
    summary = get_period_summary(session, config, current_period)
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
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "config": config, "message": message},
    )


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
