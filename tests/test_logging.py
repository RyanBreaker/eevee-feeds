import logging
from io import StringIO

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.logging_config import SingleLineFormatter
from app.main import app as fastapi_app
from app.main import unhandled_exception_handler


def test_single_line_formatter_escapes_newlines():
    formatter = SingleLineFormatter(fmt="%(levelname)s: %(message)s")
    logger = logging.getLogger("test_single_line_formatter")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    try:
        raise ValueError("boom")
    except Exception:
        logger.exception("Something failed")

    output = stream.getvalue().rstrip("\n")
    assert "Something failed" in output
    assert "ValueError: boom" in output
    assert "\n" not in output


@pytest.mark.asyncio
async def test_unhandled_exception_handler_returns_error_page():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
        "raw_path": b"/",
        "session": {},
    }
    request = Request(scope)
    response = await unhandled_exception_handler(request, RuntimeError("test error"))
    assert response.status_code == 500
    assert b"unexpected error" in response.body.lower()


@pytest.mark.asyncio
async def test_unhandled_exception_handler_htmx_returns_plain_text():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [(b"hx-request", b"true")],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
        "raw_path": b"/",
    }
    request = Request(scope)
    response = await unhandled_exception_handler(request, RuntimeError("test error"))
    assert response.status_code == 500
    assert response.body == b"An unexpected error occurred."
    assert response.headers["content-type"].startswith("text/plain")


@pytest.mark.asyncio
async def test_unhandled_exception_handler_logs_error(caplog):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
        "raw_path": b"/",
        "session": {},
    }
    request = Request(scope)
    with caplog.at_level(logging.ERROR, logger="uvicorn"):
        await unhandled_exception_handler(request, RuntimeError("test error"))

    assert "Unhandled exception" in caplog.text
    assert "RuntimeError: test error" in caplog.text


def test_unhandled_exception_endpoint(test_engine):
    with TestClient(fastapi_app, raise_server_exceptions=False) as client:
        response = client.get("/__test_error")
    assert response.status_code == 500
    assert "unexpected error" in response.text.lower()
