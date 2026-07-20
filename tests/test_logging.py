import json
import logging
import logging.config
import sys
from io import StringIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.logging_config import JSONFormatter
from app.main import app as fastapi_app
from app.main import unhandled_exception_handler


def _make_logger(name, formatter):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger, stream


def test_json_formatter_emits_single_line_json_with_exc_attribute():
    logger, stream = _make_logger("test_json_formatter", JSONFormatter())

    try:
        raise ValueError("boom")
    except Exception:
        logger.exception("Something failed")

    output = stream.getvalue().rstrip("\n")
    assert "\n" not in output

    entry = json.loads(output)
    assert entry["level"] == "ERROR"
    assert entry["logger"] == "test_json_formatter"
    assert entry["message"] == "Something failed"
    assert "Traceback (most recent call last)" in entry["exc"]
    assert "ValueError: boom" in entry["exc"]
    assert "time" in entry


def test_json_formatter_handles_newlines_in_message():
    logger, stream = _make_logger("test_json_message_newline", JSONFormatter())

    logger.error("Exception in ASGI application\n")

    output = stream.getvalue().rstrip("\n")
    assert "\n" not in output

    entry = json.loads(output)
    assert entry["message"] == "Exception in ASGI application\n"
    assert "exc" not in entry


def test_stray_logger_exceptions_are_single_line_json(monkeypatch):
    stdout = StringIO()
    stderr = StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    config_path = Path(__file__).parent.parent / "log_config.json"
    config = json.loads(config_path.read_text())

    names = ["uvicorn", "uvicorn.access", "uvicorn.error", "asyncio"]
    saved = {
        name: (
            logging.getLogger(name).handlers[:],
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in names
    }
    root_saved = (logging.root.handlers[:], logging.root.level)
    try:
        logging.config.dictConfig(config)
        stray = logging.getLogger("asyncio")
        try:
            raise ValueError("boom")
        except ValueError:
            stray.exception("Task exception was never retrieved")

        output = stderr.getvalue().rstrip("\n")
        assert "\n" not in output
        assert stdout.getvalue() == ""

        entry = json.loads(output)
        assert entry["message"] == "Task exception was never retrieved"
        assert "ValueError: boom" in entry["exc"]
    finally:
        for name, (handlers, level, propagate) in saved.items():
            restored = logging.getLogger(name)
            restored.handlers = handlers
            restored.level = level
            restored.propagate = propagate
        logging.root.handlers = root_saved[0]
        logging.root.level = root_saved[1]


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
