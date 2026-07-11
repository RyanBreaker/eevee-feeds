import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional

import httpx
from sqlmodel import Session

from app.database import session_factory
from app.notification_service import NotificationService, notification_service

logger = logging.getLogger("uvicorn")


class FeedingNotifier:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        service: NotificationService,
    ):
        self.session_factory = session_factory
        self.service = service
        self.client: Optional[httpx.AsyncClient] = None
        self.task: Optional[asyncio.Task] = None
        self.app_start_time: Optional[datetime] = None

    def start(self) -> None:
        if not self.service.topic:
            logger.info("Notifications disabled: NTFY_TOPIC not set")
            return

        self.app_start_time = datetime.now()
        self.client = httpx.AsyncClient(timeout=10.0)
        self.task = asyncio.create_task(self._loop())
        logger.info(
            "Notifier started: topic=%s server=%s thresholds=%s",
            self.service.topic,
            self.service.server,
            self.service.thresholds,
        )

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.client:
            await self.client.aclose()
        logger.info("Notifier stopped")

    async def _loop(self) -> None:
        await self._check()
        while True:
            await asyncio.sleep(60)
            await self._check()

    async def _check(self) -> None:
        with self.session_factory() as session:
            await self.service.run_check(
                session, self.client, datetime.now(), self.app_start_time
            )

    async def send_test(self) -> bool:
        with self.session_factory() as session:
            return await self.service.send_test(session, self.client)


notifier = FeedingNotifier(session_factory, notification_service)
