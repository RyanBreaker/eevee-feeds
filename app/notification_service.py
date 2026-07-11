import logging
import os
from datetime import datetime, timedelta
from typing import Callable, List, Optional

import httpx
from sqlmodel import Session, select

from app.database import session_factory
from app.models import Feeding, NotificationLog
from app.period import format_duration
from app.repository import get_last_feeding

logger = logging.getLogger("uvicorn")

DEFAULT_THRESHOLDS = [2, 3, 4]
DEFAULT_SERVER = "https://ntfy.sh"


class NotificationService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        topic: Optional[str] = None,
        server: Optional[str] = None,
        thresholds: Optional[str] = None,
        app_url: Optional[str] = None,
    ):
        self.session_factory = session_factory
        self.topic = topic or os.getenv("NTFY_TOPIC")
        self.server = (server or os.getenv("NTFY_SERVER") or DEFAULT_SERVER).rstrip("/")
        self.app_url = app_url or os.getenv("APP_URL")
        self.thresholds = self.parse_thresholds(thresholds or os.getenv("NTFY_THRESHOLDS"))

    @staticmethod
    def parse_thresholds(raw: Optional[str]) -> List[int]:
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

    def body_for_feeding(self, feeding: Feeding) -> str:
        return (
            f"Last feeding: PO {feeding.po_amount} ml / NG {feeding.ng_amount} ml "
            f"at {feeding.timestamp.strftime('%I:%M %p')}."
        )

    def priority(self, crossed_thresholds: List[int]) -> int:
        if crossed_thresholds and crossed_thresholds[-1] == self.thresholds[-1]:
            return 4
        return 3

    def build_payload(self, title: str, body: str, priority: int) -> dict:
        payload = {
            "topic": self.topic,
            "title": title,
            "message": body,
            "priority": priority,
            "tags": ["🍼"],
        }
        if self.app_url:
            payload["click"] = self.app_url
        return payload

    async def _send_notification_for(
        self,
        client: httpx.AsyncClient,
        feeding: Feeding,
        since: timedelta,
        crossed_thresholds: List[int],
    ) -> bool:
        if not client or not self.topic:
            return False

        title = f"🍼 {format_duration(since)} since last feed"
        body = self.body_for_feeding(feeding)
        priority = self.priority(crossed_thresholds)
        payload = self.build_payload(title, body, priority)
        url = f"{self.server}/"

        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info("Sent ntfy notification: %s", title)
            return True
        except Exception as exc:
            logger.error("Failed to send ntfy notification: %s", exc)
            return False

    def _is_sent(self, session: Session, feeding_id: int, threshold: int) -> bool:
        log = session.exec(
            select(NotificationLog).where(
                NotificationLog.feeding_id == feeding_id,
                NotificationLog.threshold_hours == threshold,
            )
        ).first()
        return log is not None

    def _record_sent(self, session: Session, feeding_id: int, threshold: int) -> None:
        log = NotificationLog(
            feeding_id=feeding_id,
            threshold_hours=threshold,
            sent_at=datetime.utcnow(),
        )
        session.add(log)
        session.commit()

    def get_status(self, session: Session) -> dict:
        last_feeding = get_last_feeding(session)

        next_notification = None
        if self.topic and last_feeding:
            sent_thresholds = {
                row
                for row in session.exec(
                    select(NotificationLog.threshold_hours).where(
                        NotificationLog.feeding_id == last_feeding.id
                    )
                ).all()
            }
            now = datetime.now()
            for threshold in self.thresholds:
                if threshold in sent_thresholds:
                    continue
                threshold_time = last_feeding.timestamp + timedelta(hours=threshold)
                if threshold_time > now:
                    next_notification = threshold_time
                    break

        return {
            "enabled": bool(self.topic),
            "topic": self.topic,
            "server": self.server,
            "thresholds": self.thresholds,
            "next_notification": next_notification,
        }

    async def send_test(
        self, session: Session, client: Optional[httpx.AsyncClient] = None
    ) -> bool:
        last_feeding = get_last_feeding(session)
        if not last_feeding:
            return False

        now = datetime.now()
        gap = now - last_feeding.timestamp
        crossed = [t for t in self.thresholds if gap >= timedelta(hours=t)]
        if client is None:
            async with httpx.AsyncClient(timeout=10.0) as client:
                return await self._send_notification_for(client, last_feeding, gap, crossed)
        return await self._send_notification_for(client, last_feeding, gap, crossed)

    async def run_check(
        self,
        session: Session,
        client: httpx.AsyncClient,
        now: Optional[datetime] = None,
        app_start_time: Optional[datetime] = None,
    ) -> None:
        if now is None:
            now = datetime.now()

        last_feeding = get_last_feeding(session)
        if not last_feeding:
            logger.debug("No feedings logged yet; skipping notification check")
            return
        assert last_feeding.id is not None

        for threshold in self.thresholds:
            threshold_time = last_feeding.timestamp + timedelta(hours=threshold)
            if app_start_time and threshold_time < app_start_time:
                continue
            if now < threshold_time:
                continue
            already_sent = self._is_sent(session, last_feeding.id, threshold)
            if already_sent:
                continue
            ok = await self._send_notification_for(
                client,
                last_feeding,
                timedelta(hours=threshold),
                [threshold],
            )
            if ok:
                self._record_sent(session, last_feeding.id, threshold)


notification_service = NotificationService(session_factory)
