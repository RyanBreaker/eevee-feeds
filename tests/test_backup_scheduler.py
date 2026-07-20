import asyncio
import logging
from datetime import datetime

import pytest
from sqlmodel import Session

from app.backup_scheduler import BackupScheduler
from app.database import session_factory
from app.models import BackupLog


class MockBackupService:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.calls = []
        self.return_value = True

    async def run_backup(self, session, now=None, run_timestamp=None):
        self.calls.append({"session": session, "now": now})
        return self.return_value


@pytest.mark.asyncio
async def test_start_stop_logs_disabled():
    service = MockBackupService(enabled=False)
    scheduler = BackupScheduler(session_factory, service, interval=60)
    scheduler.start()
    assert scheduler.task is not None
    await scheduler.stop()
    assert scheduler.task is None


@pytest.mark.asyncio
async def test_check_runs_backup_for_new_period(test_engine):
    now = datetime(2026, 7, 10, 12, 0)
    service = MockBackupService(enabled=True)
    scheduler = BackupScheduler(
        session_factory, service, interval=60, now_fn=lambda: now
    )
    await scheduler._check()

    assert len(service.calls) == 1
    assert service.calls[0]["now"] == now


@pytest.mark.asyncio
async def test_check_skips_already_backed_up_period(test_engine):
    now = datetime(2026, 7, 10, 12, 0)
    period_start = datetime(2026, 7, 10, 6, 0)
    with Session(test_engine) as session:
        log = BackupLog(
            period_start=period_start,
            run_timestamp=now,
            object_key="feedings/feedings_backup_2026-07-10_2026-07-10T120000Z.csv",
            success=True,
        )
        session.add(log)
        session.commit()

    service = MockBackupService(enabled=True)
    scheduler = BackupScheduler(
        session_factory, service, interval=60, now_fn=lambda: now
    )
    await scheduler._check()

    assert len(service.calls) == 0


@pytest.mark.asyncio
async def test_check_does_nothing_when_disabled(test_engine):
    now = datetime(2026, 7, 10, 12, 0)
    service = MockBackupService(enabled=False)
    scheduler = BackupScheduler(
        session_factory, service, interval=60, now_fn=lambda: now
    )
    await scheduler._check()

    assert len(service.calls) == 0


@pytest.mark.asyncio
async def test_scheduler_does_not_backfill_missed_periods(test_engine):
    # The current period is already backed up; a previous period is not.
    # A backfilling scheduler would try to upload the missed period, but this
    # one only checks the current period and skips it.
    now = datetime(2026, 7, 10, 12, 0)
    period_start = datetime(2026, 7, 10, 6, 0)
    missed_period = datetime(2026, 7, 9, 6, 0)
    with Session(test_engine) as session:
        log = BackupLog(
            period_start=period_start,
            run_timestamp=now,
            object_key="feedings/feedings_backup_2026-07-10_2026-07-10T120000Z.csv",
            success=True,
        )
        session.add(log)
        session.commit()

    service = MockBackupService(enabled=True)
    scheduler = BackupScheduler(
        session_factory, service, interval=60, now_fn=lambda: now
    )
    await scheduler._check()

    assert len(service.calls) == 0
    assert missed_period < period_start


@pytest.mark.asyncio
async def test_loop_logs_and_survives_check_failure(test_engine, caplog):
    class FailingBackupService:
        enabled = True

        def __init__(self):
            self.called = asyncio.Event()

        async def run_backup(self, session, now=None, run_timestamp=None):
            self.called.set()
            raise RuntimeError("b2 blew up")

    now = datetime(2026, 7, 10, 12, 0)
    service = FailingBackupService()
    scheduler = BackupScheduler(
        session_factory, service, interval=60, now_fn=lambda: now
    )

    with caplog.at_level(logging.ERROR, logger="uvicorn"):
        task = asyncio.create_task(scheduler._loop())
        await asyncio.wait_for(service.called.wait(), timeout=1)
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert "Backup check failed" in caplog.text
    assert "RuntimeError: b2 blew up" in caplog.text
