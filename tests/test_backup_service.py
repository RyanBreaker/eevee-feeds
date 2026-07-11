import hashlib
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx
import pytest
from sqlmodel import Session, select

from app.backup_service import B2_AUTH_URL, BackupService
from app.csv_io import FeedingCsvWriter
from app.models import BackupLog, Feeding
from app.period import get_period_start
from app.repository import get_all_feedings


def make_service(**overrides):
    kwargs = {
        "key_id": "test-key-id",
        "application_key": "test-app-key",
        "bucket_name": "test-bucket",
    }
    kwargs.update(overrides)
    return BackupService(**kwargs)


class B2MockTransport:
    def __init__(self, bucket_name="test-bucket", fail_upload_count=0):
        self.bucket_name = bucket_name
        self.fail_upload_count = fail_upload_count
        self.authorize_count = 0
        self.upload_count = 0
        self.captured = []

    def handler(self, request: httpx.Request):
        url = str(request.url)
        path = request.url.path

        if url == B2_AUTH_URL:
            self.authorize_count += 1
            return httpx.Response(
                200,
                json={
                    "accountId": "123",
                    "authorizationToken": "auth-token",
                    "apiUrl": "https://api900.backblazeb2.com",
                    "downloadUrl": "https://f900.backblazeb2.com",
                },
            )

        if "/b2_list_buckets" in path:
            return httpx.Response(
                200,
                json={
                    "buckets": [
                        {"bucketId": "bucket-1", "bucketName": self.bucket_name}
                    ]
                },
            )

        if "/b2_get_upload_url" in path:
            return httpx.Response(
                200,
                json={
                    "uploadUrl": "https://api900.backblazeb2.com/b2api/v2/b2_upload_file",
                    "authorizationToken": "upload-auth-token",
                },
            )

        if "/b2_upload_file" in path:
            self.upload_count += 1
            self.captured.append(
                {
                    "url": url,
                    "headers": dict(request.headers),
                    "content": request.content,
                }
            )
            if self.upload_count <= self.fail_upload_count:
                return httpx.Response(500, text="Internal Server Error")
            return httpx.Response(200, json={"fileId": "file-1", "fileName": "key"})

        return httpx.Response(404, text="Not found")


def make_async_client_factory(transport):
    original_async_client = httpx.AsyncClient

    def _make_client(*args, **kwargs):
        return original_async_client(
            transport=httpx.MockTransport(transport.handler)
        )

    return _make_client


@pytest.fixture
def no_sleep(monkeypatch):
    async def _noop(*args, **kwargs):
        pass

    monkeypatch.setattr("asyncio.sleep", _noop)


@pytest.mark.asyncio
async def test_run_backup_success(test_engine, monkeypatch, no_sleep):
    transport = B2MockTransport()
    monkeypatch.setattr(httpx, "AsyncClient", make_async_client_factory(transport))

    now = datetime(2026, 7, 10, 12, 0)
    run_timestamp = datetime(2026, 7, 10, 17, 0, 0)
    period_start = get_period_start(now)
    expected_object_key = BackupService.make_object_key(period_start, run_timestamp)

    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=now - timedelta(hours=3),
            po_amount=30,
            ng_amount=10,
            notes="backup note",
        )
        session.add(feeding)
        session.commit()

    service = make_service()

    with Session(test_engine) as session:
        ok = await service.run_backup(
            session, now=now, run_timestamp=run_timestamp
        )

    assert ok is True
    assert transport.authorize_count == 1
    assert transport.upload_count == 1
    assert len(transport.captured) == 1

    captured = transport.captured[0]
    assert captured["headers"]["x-bz-file-name"] == quote(expected_object_key, safe="")
    assert captured["headers"]["content-type"] == "text/csv"
    assert captured["headers"]["x-bz-content-sha1"] == hashlib.sha1(
        captured["content"]
    ).hexdigest()

    with Session(test_engine) as session:
        expected_csv = FeedingCsvWriter().write_feedings(get_all_feedings(session))
    assert captured["content"] == expected_csv.encode("utf-8")

    with Session(test_engine) as session:
        logs = list(session.exec(select(BackupLog)).all())
        assert len(logs) == 1
        log = logs[0]
        assert log.success is True
        assert log.period_start == period_start
        assert log.run_timestamp == run_timestamp
        assert log.object_key == expected_object_key


@pytest.mark.asyncio
async def test_run_backup_disabled(test_engine, no_sleep):
    service = BackupService()
    with Session(test_engine) as session:
        ok = await service.run_backup(session, now=datetime(2026, 7, 10, 12, 0))

    assert ok is False
    with Session(test_engine) as session:
        logs = list(session.exec(select(BackupLog)).all())
        assert len(logs) == 0


@pytest.mark.asyncio
async def test_run_backup_retries_then_succeeds(
    test_engine, monkeypatch, no_sleep
):
    transport = B2MockTransport(fail_upload_count=2)
    monkeypatch.setattr(httpx, "AsyncClient", make_async_client_factory(transport))

    now = datetime(2026, 7, 10, 12, 0)
    run_timestamp = datetime(2026, 7, 10, 17, 0, 0)
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=now - timedelta(hours=3),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    service = make_service()
    with Session(test_engine) as session:
        ok = await service.run_backup(
            session, now=now, run_timestamp=run_timestamp
        )

    assert ok is True
    assert transport.upload_count == 3


@pytest.mark.asyncio
async def test_run_backup_logs_failure_after_retries(
    test_engine, monkeypatch, no_sleep
):
    transport = B2MockTransport(fail_upload_count=10)
    monkeypatch.setattr(httpx, "AsyncClient", make_async_client_factory(transport))

    now = datetime(2026, 7, 10, 12, 0)
    run_timestamp = datetime(2026, 7, 10, 17, 0, 0)
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=now - timedelta(hours=3),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    service = make_service()
    with Session(test_engine) as session:
        ok = await service.run_backup(
            session, now=now, run_timestamp=run_timestamp
        )

    assert ok is False
    assert transport.upload_count == 4

    with Session(test_engine) as session:
        logs = list(session.exec(select(BackupLog)).all())
        assert len(logs) == 1
        assert logs[0].success is False
        assert logs[0].run_timestamp == run_timestamp


@pytest.mark.asyncio
async def test_run_backup_logs_b2_status_on_http_error(
    test_engine, monkeypatch, no_sleep, caplog
):
    class ForbiddenTransport(B2MockTransport):
        def handler(self, request: httpx.Request):
            url = str(request.url)
            path = request.url.path
            if "/b2_upload_file" in path:
                self.upload_count += 1
                return httpx.Response(
                    403,
                    json={"code": "unauthorized", "message": "not authorized"},
                )
            return super().handler(request)

    transport = ForbiddenTransport()
    monkeypatch.setattr(httpx, "AsyncClient", make_async_client_factory(transport))

    now = datetime(2026, 7, 10, 12, 0)
    run_timestamp = datetime(2026, 7, 10, 17, 0, 0)
    with Session(test_engine) as session:
        feeding = Feeding(
            timestamp=now - timedelta(hours=3),
            po_amount=30,
            ng_amount=10,
        )
        session.add(feeding)
        session.commit()

    service = make_service()
    with caplog.at_level("WARNING", logger="uvicorn"):
        with Session(test_engine) as session:
            ok = await service.run_backup(
                session, now=now, run_timestamp=run_timestamp
            )

    assert ok is False
    assert any("B2 returned 403" in record.message for record in caplog.records)
    assert any("unauthorized" in record.message for record in caplog.records)


def test_get_status_disabled(test_engine):
    service = BackupService()
    with Session(test_engine) as session:
        status = service.get_status(session)

    assert status["enabled"] is False
    assert status["bucket_name"] is None
    assert status["last_run"] is None


def test_get_status_with_last_log(test_engine):
    run_timestamp = datetime(2026, 7, 10, 17, 0, 0)
    with Session(test_engine) as session:
        log = BackupLog(
            period_start=datetime(2026, 7, 10, 6, 0),
            run_timestamp=run_timestamp,
            object_key="feedings/feedings_backup_2026-07-10_2026-07-10T170000Z.csv",
            success=False,
        )
        session.add(log)
        session.commit()

    service = make_service()
    with Session(test_engine) as session:
        status = service.get_status(session)

    assert status["enabled"] is True
    assert status["bucket_name"] == "test-bucket"
    assert status["last_run"] == run_timestamp
    assert status["last_result"] == "failure"


def test_make_object_key():
    period_start = datetime(2026, 7, 10, 6, 0)
    run_timestamp = datetime(2026, 7, 10, 12, 0, 0)
    key = BackupService.make_object_key(period_start, run_timestamp)
    assert key == "feedings/feedings_backup_2026-07-10_2026-07-10T120000Z.csv"
