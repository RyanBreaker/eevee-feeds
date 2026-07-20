import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional

from sqlmodel import Session, select

from app.backup_service import BackupService, backup_service
from app.database import session_factory
from app.models import BackupLog
from app.period import get_period_start

logger = logging.getLogger("uvicorn")

DEFAULT_INTERVAL_SECONDS = 60


class BackupScheduler:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        service: BackupService,
        interval: int = DEFAULT_INTERVAL_SECONDS,
        now_fn: Optional[Callable[[], datetime]] = None,
    ):
        self.session_factory = session_factory
        self.service = service
        self.interval = interval
        self.now_fn = now_fn or datetime.now
        self.task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._loop())
        if not self.service.enabled:
            logger.info("Backup scheduler started; backups disabled: B2 credentials not set")
        else:
            logger.info("Backup scheduler started")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info("Backup scheduler stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._check()
            except Exception:
                logger.exception("Backup check failed")
            await asyncio.sleep(self.interval)

    async def _check(self) -> None:
        if not self.service.enabled:
            return

        now = self.now_fn()
        period_start = get_period_start(now)
        if now < period_start:
            return

        with self.session_factory() as session:
            if self._has_attempt_for_period(session, period_start):
                logger.debug("Period %s already has a backup attempt; skipping", period_start)
                return

            logger.info("Running scheduled backup for period %s", period_start)
            await self.service.run_backup(session, now=now)

    def _has_attempt_for_period(self, session: Session, period_start: datetime) -> bool:
        log = session.exec(
            select(BackupLog).where(BackupLog.period_start == period_start)
        ).first()
        return log is not None


backup_scheduler = BackupScheduler(session_factory, backup_service)
