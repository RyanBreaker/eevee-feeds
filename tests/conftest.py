import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("AUTH_USERNAME", "admin")
os.environ.setdefault("AUTH_PASSWORD", "secret")

import app.database  # noqa: E402
import app.notifier  # noqa: E402
import app.notification_service  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402


@fastapi_app.get("/__test_error")
def _raise_test_error():
    raise RuntimeError("intentional test error")


@pytest.fixture(scope="function")
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(autouse=True)
def patch_engines(test_engine, monkeypatch):
    monkeypatch.setattr(app.database, "engine", test_engine)


@pytest.fixture(autouse=True)
def reset_notifier(monkeypatch):
    for service in (app.notification_service.notification_service, app.notifier.notifier.service):
        monkeypatch.setattr(service, "topic", None)
        monkeypatch.setattr(service, "server", "https://ntfy.sh")
        monkeypatch.setattr(service, "app_url", None)
        monkeypatch.setattr(service, "thresholds", [2, 3, 4])
    monkeypatch.setattr(app.notifier.notifier, "client", None)
    monkeypatch.setattr(app.notifier.notifier, "task", None)
    monkeypatch.setattr(app.notifier.notifier, "app_start_time", None)


@pytest.fixture
def client(test_engine):
    app.database.create_db_and_tables()
    with TestClient(fastapi_app) as c:
        yield c
