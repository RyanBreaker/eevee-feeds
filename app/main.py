import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import create_db_and_tables
from app.routes import router

logger = logging.getLogger("uvicorn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    tz = os.environ.get("TZ", "not set")
    local_time = time.strftime("%Y-%m-%d %H:%M:%S %Z (UTC%z)", time.localtime())
    logger.info("Starting app. TZ=%s, current local time=%s", tz, local_time)
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

app.include_router(router)
