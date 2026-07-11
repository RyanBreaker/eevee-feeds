import asyncio
import hashlib
import logging
import os
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import httpx
from sqlmodel import Session, desc, select

from app.csv_io import FeedingCsvWriter
from app.models import BackupLog, Feeding
from app.period import get_period_start
from app.repository import get_all_feedings

logger = logging.getLogger("uvicorn")

B2_AUTH_URL = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0


class BackupService:
    def __init__(
        self,
        key_id: Optional[str] = None,
        application_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
    ):
        self.key_id = key_id or os.getenv("B2_KEY_ID")
        self.application_key = application_key or os.getenv("B2_APPLICATION_KEY")
        self.bucket_name = bucket_name or os.getenv("B2_BUCKET_NAME")
        self._enabled = all((self.key_id, self.application_key, self.bucket_name))

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get_status(self, session: Session) -> dict:
        last_log = session.exec(
            select(BackupLog).order_by(desc(BackupLog.run_timestamp)).limit(1)
        ).first()
        return {
            "enabled": self.enabled,
            "bucket_name": self.bucket_name,
            "last_run": last_log.run_timestamp if last_log else None,
            "last_result": (
                ("success" if last_log.success else "failure") if last_log else None
            ),
            "last_object_key": last_log.object_key if last_log else None,
        }

    @staticmethod
    def make_object_key(period_start: datetime, run_timestamp: datetime) -> str:
        period_part = period_start.strftime("%Y-%m-%d")
        run_part = run_timestamp.strftime("%Y-%m-%dT%H%M%SZ")
        return f"feedings/feedings_backup_{period_part}_{run_part}.csv"

    async def run_backup(
        self,
        session: Session,
        now: Optional[datetime] = None,
        run_timestamp: Optional[datetime] = None,
    ) -> bool:
        if not self.enabled:
            logger.info("Backup skipped: B2 credentials are not configured")
            return False

        if now is None:
            now = datetime.now()
        if run_timestamp is None:
            run_timestamp = datetime.utcnow()

        period_start = get_period_start(now)
        object_key = self.make_object_key(period_start, run_timestamp)

        feedings = get_all_feedings(session)
        csv_content = self._build_csv(feedings)
        csv_bytes = csv_content.encode("utf-8")
        sha1 = hashlib.sha1(csv_bytes).hexdigest()

        success = False
        for attempt in range(1, MAX_RETRIES + 2):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    await self._upload_to_b2(client, csv_bytes, object_key, sha1)
                success = True
                break
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "Backup attempt %d failed: B2 returned %s - %s",
                    attempt,
                    exc.response.status_code,
                    exc.response.text,
                )
                if attempt <= MAX_RETRIES:
                    await asyncio.sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
            except Exception as exc:
                logger.warning(
                    "Backup attempt %d failed: %s", attempt, type(exc).__name__
                )
                if attempt <= MAX_RETRIES:
                    await asyncio.sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))

        log = BackupLog(
            period_start=period_start,
            run_timestamp=run_timestamp,
            object_key=object_key,
            success=success,
        )
        session.add(log)
        session.commit()

        if success:
            logger.info("Backup uploaded to %s", object_key)
        else:
            logger.error("Backup failed after %d attempts", MAX_RETRIES + 1)

        return success

    def _build_csv(self, feedings: list[Feeding]) -> str:
        writer = FeedingCsvWriter()
        return writer.write_feedings(feedings)

    async def _upload_to_b2(
        self,
        client: httpx.AsyncClient,
        csv_bytes: bytes,
        object_key: str,
        sha1: str,
    ) -> None:
        auth_response = await self._authorize_account(client)
        api_url = auth_response["apiUrl"].rstrip("/")
        account_id = auth_response["accountId"]
        auth_token = auth_response["authorizationToken"]

        bucket_id = await self._get_bucket_id(client, api_url, auth_token, account_id)
        upload_url, upload_auth_token = await self._get_upload_url(
            client, api_url, auth_token, bucket_id
        )
        await self._upload_file(
            client, upload_url, upload_auth_token, object_key, csv_bytes, sha1
        )

    async def _authorize_account(self, client: httpx.AsyncClient) -> dict:
        logger.debug("Authorizing B2 account")
        try:
            response = await client.get(
                B2_AUTH_URL,
                auth=(self.key_id, self.application_key),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "B2 authorization failed: %s - %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise
        data = response.json()
        logger.debug("B2 account authorized: %s", data.get("accountId"))
        return data

    async def _get_bucket_id(
        self,
        client: httpx.AsyncClient,
        api_url: str,
        auth_token: str,
        account_id: str,
    ) -> str:
        logger.debug("Listing B2 buckets for account %s", account_id)
        try:
            response = await client.get(
                f"{api_url}/b2api/v2/b2_list_buckets",
                params={"accountId": account_id},
                headers={"Authorization": auth_token},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "B2 list_buckets failed: %s - %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise
        data = response.json()
        for bucket in data["buckets"]:
            if bucket["bucketName"] == self.bucket_name:
                logger.debug("Found B2 bucket %s with id %s", self.bucket_name, bucket["bucketId"])
                return bucket["bucketId"]
        raise RuntimeError(f"B2 bucket {self.bucket_name} not found")

    async def _get_upload_url(
        self,
        client: httpx.AsyncClient,
        api_url: str,
        auth_token: str,
        bucket_id: str,
    ) -> tuple[str, str]:
        logger.debug("Requesting B2 upload URL for bucket %s", bucket_id)
        try:
            response = await client.get(
                f"{api_url}/b2api/v2/b2_get_upload_url",
                params={"bucketId": bucket_id},
                headers={"Authorization": auth_token},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "B2 get_upload_url failed: %s - %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise
        data = response.json()
        return data["uploadUrl"], data["authorizationToken"]

    async def _upload_file(
        self,
        client: httpx.AsyncClient,
        upload_url: str,
        upload_auth_token: str,
        object_key: str,
        csv_bytes: bytes,
        sha1: str,
    ) -> None:
        encoded_key = quote(object_key, safe="")
        logger.debug("Uploading backup to B2: %s (%d bytes)", object_key, len(csv_bytes))
        try:
            response = await client.post(
                upload_url,
                headers={
                    "Authorization": upload_auth_token,
                    "X-Bz-File-Name": encoded_key,
                    "Content-Type": "text/csv",
                    "Content-Length": str(len(csv_bytes)),
                    "X-Bz-Content-Sha1": sha1,
                },
                content=csv_bytes,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "B2 file upload failed: %s - %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise


backup_service = BackupService()
