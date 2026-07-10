import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional

import httpx
from sqlmodel import Session

from app.notification_service import NotificationService

logger = logging.getLogger("uvicorn")


def _session_factory() -> Session:
    from app.database import engine

    return Session(engine)


class FeedingNotifier:
    def __init__(self, session_factory: Callable[[], Session]):
        self.service = NotificationService(session_factory)
        self.client: Optional[httpx.AsyncClient] = None
        self.task: Optional[asyncio.Task] = None
        self.app_start_time: Optional[datetime] = None

    @property
    def topic(self) -> Optional[str]:
        return self.service.topic

    @topic.setter
    def topic(self, value: Optional[str]) -> None:
        self.service.topic = value

    @property
    def server(self) -> str:
        return self.service.server

    @server.setter
    def server(self, value: str) -> None:
        self.service.server = value

    @property
    def app_url(self) -> Optional[str]:
        return self.service.app_url

    @app_url.setter
    def app_url(self, value: Optional[str]) -> None:
        self.service.app_url = value

    @property
    def thresholds(self) -> list[int]:
        return self.service.thresholds

    @thresholds.setter
    def thresholds(self, value: list[int]) -> None:
        self.service.thresholds = value

    def start(self) -> None:
        if not self.topic:
            logger.info("Notifications disabled: NTFY_TOPIC not set")
            return

        self.app_start_time = datetime.now()
        self.client = httpx.AsyncClient(timeout=10.0)
        self.task = asyncio.create_task(self._loop())
        logger.info(
            "Notifier started: topic=%s server=%s thresholds=%s",
            self.topic,
            self.server,
            self.thresholds,
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
        with self.service.session_factory() as session:
            await self.service.run_check(
                session, self.client, datetime.now(), self.app_start_time
            )

    async def send_test(self) -> bool:
        with self.service.session_factory() as session:
            return await self.service.send_test(session, self.client)


notifier = FeedingNotifier(_session_factory)
