import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth import AuthRequiredException
from app.database import create_db_and_tables
from app.notifier import notifier
from app.routes import router

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    tz = os.environ.get("TZ", "not set")
    local_time = time.strftime("%Y-%m-%d %H:%M:%S %Z (UTC%z)", time.localtime())
    logger.info("Starting app. TZ=%s, current local time=%s", tz, local_time)
    create_db_and_tables()
    notifier.start()
    try:
        yield
    finally:
        await notifier.stop()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
app.state.notifier = notifier

secret_key = os.environ.get("SECRET_KEY", os.environ.get("AUTH_PASSWORD", "dev-secret-key"))
max_age = int(os.environ.get("SESSION_MAX_AGE", "2592000"))
secure = os.environ.get("SESSION_SECURE", "false").lower() in ("true", "1", "yes")
app.add_middleware(
    SessionMiddleware,
    secret_key=secret_key,
    max_age=max_age,
    same_site="lax",
    https_only=secure,
)


@app.exception_handler(AuthRequiredException)
async def auth_required_handler(request: Request, exc: AuthRequiredException):
    if request.headers.get("HX-Request"):
        return Response(status_code=204, headers={"HX-Redirect": "/login"})
    return RedirectResponse(url="/login", status_code=302)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled exception: %s",
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    if request.headers.get("HX-Request"):
        return Response(
            "An unexpected error occurred.",
            status_code=500,
            media_type="text/plain",
        )
    return templates.TemplateResponse(
        "error.html",
        {"request": request},
        status_code=500,
    )


app.include_router(router)
