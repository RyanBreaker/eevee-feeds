import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

import httpx
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from app.database import engine
from app.models import Feeding, NotificationLog
from app.period import format_duration

logger = logging.getLogger("uvicorn")

DEFAULT_THRESHOLDS = [2, 3, 4]
DEFAULT_SERVER = "https://ntfy.sh"


class FeedingNotifier:
    def __init__(self):
        self.topic = os.getenv("NTFY_TOPIC")
        self.server = (os.getenv("NTFY_SERVER") or DEFAULT_SERVER).rstrip("/")
        self.thresholds = self._parse_thresholds(os.getenv("NTFY_THRESHOLDS"))
        self.app_url = os.getenv("APP_URL")
        self.client: Optional[httpx.AsyncClient] = None
        self.task: Optional[asyncio.Task] = None
        self.app_start_time: Optional[datetime] = None

    @staticmethod
    def _parse_thresholds(raw: Optional[str]) -> List[int]:
        if not raw:
            return DEFAULT_THRESHOLDS
        try:
            values = [int(part.strip()) for part in raw.split(",") if part.strip()]
            values = sorted(set(value for value in values if value > 0))
            if values:
                return values
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Invalid NTFY_THRESHOLDS=%r, using default %s: %s",
                raw,
                DEFAULT_THRESHOLDS,
                exc,
            )
        return DEFAULT_THRESHOLDS

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
        try:
            last_feeding = await run_in_threadpool(self._get_last_feeding)
            if not last_feeding:
                logger.debug("No feedings logged yet; skipping notification check")
                return

            now = datetime.now()
            for threshold in self.thresholds:
                threshold_time = last_feeding.timestamp + timedelta(hours=threshold)
                if self.app_start_time and threshold_time < self.app_start_time:
                    continue
                if now < threshold_time:
                    continue
                already_sent = await run_in_threadpool(
                    self._is_sent, last_feeding.id, threshold
                )
                if already_sent:
                    continue
                ok = await self._send_notification(last_feeding, threshold)
                if ok:
                    await run_in_threadpool(self._record_sent, last_feeding.id, threshold)
        except Exception:
            logger.exception("Error in notifier check")

    def _get_last_feeding(self) -> Optional[Feeding]:
        with Session(engine) as session:
            return session.exec(
                select(Feeding).order_by(Feeding.timestamp.desc()).limit(1)
            ).first()

    def _is_sent(self, feeding_id: int, threshold: int) -> bool:
        with Session(engine) as session:
            log = session.exec(
                select(NotificationLog).where(
                    NotificationLog.feeding_id == feeding_id,
                    NotificationLog.threshold_hours == threshold,
                )
            ).first()
            return log is not None

    def _record_sent(self, feeding_id: int, threshold: int) -> None:
        with Session(engine) as session:
            log = NotificationLog(
                feeding_id=feeding_id,
                threshold_hours=threshold,
                sent_at=datetime.utcnow(),
            )
            session.add(log)
            session.commit()

    async def _send_notification(self, feeding: Feeding, threshold: int) -> bool:
        if not self.client:
            return False

        url = f"{self.server}/"
        priority = 4 if threshold == self.thresholds[-1] else 3
        title = f"🍼 {threshold} hours since last feed"
        body = (
            f"Last feeding: PO {feeding.po_amount} ml / NG {feeding.ng_amount} ml "
            f"at {feeding.timestamp.strftime('%I:%M %p')}."
        )
        payload = {
            "topic": self.topic,
            "title": title,
            "message": body,
            "priority": priority,
            "tags": ["🍼"],
        }
        if self.app_url:
            payload["click"] = self.app_url

        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            logger.info("Sent ntfy notification: %s", title)
            return True
        except Exception as exc:
            logger.error("Failed to send ntfy notification: %s", exc)
            return False

    async def send_test(self) -> bool:
        if not self.client or not self.topic:
            return False

        url = f"{self.server}/"
        payload = {
            "topic": self.topic,
            "title": "Test notification",
            "message": "This is a test from the feedings app.",
            "priority": 3,
            "tags": ["🍼"],
        }
        if self.app_url:
            payload["click"] = self.app_url

        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            logger.info("Sent test ntfy notification")
            return True
        except Exception as exc:
            logger.error("Failed to send test ntfy notification: %s", exc)
            return False

    async def send_test_current_gap(self) -> bool:
        if not self.client or not self.topic:
            return False

        feeding = await run_in_threadpool(self._get_last_feeding)
        if not feeding:
            return False

        now = datetime.now()
        gap = now - feeding.timestamp
        title = f"{format_duration(gap)} since last feed"
        body = (
            f"Last feeding: PO {feeding.po_amount} ml / NG {feeding.ng_amount} ml "
            f"at {feeding.timestamp.strftime('%I:%M %p')}."
        )
        crossed = [t for t in self.thresholds if gap >= timedelta(hours=t)]
        priority = 4 if crossed and crossed[-1] == self.thresholds[-1] else 3
        url = f"{self.server}/"
        payload = {
            "topic": self.topic,
            "title": title,
            "message": body,
            "priority": priority,
            "tags": ["🍼"],
        }
        if self.app_url:
            payload["click"] = self.app_url

        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            logger.info("Sent current-gap test ntfy notification: %s", title)
            return True
        except Exception as exc:
            logger.error("Failed to send current-gap test ntfy notification: %s", exc)
            return False


notifier = FeedingNotifier()
