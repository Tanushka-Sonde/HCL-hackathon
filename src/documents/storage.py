"""S3-compatible object storage client (MinIO).

All boto3 calls are wrapped in ``asyncio.to_thread`` because boto3
is synchronous. The overhead is negligible compared to network I/O.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from src.core.exceptions import ExternalServiceError
from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)


class ObjectStorage:
    """Async wrapper around boto3 S3 client for MinIO.

    Usage::

        storage = ObjectStorage(settings)
        await storage.ensure_bucket()
        await storage.upload("docs/file.pdf", data, "application/pdf")
        data = await storage.download("docs/file.pdf")
    """

    def __init__(self, settings: Settings) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=BotoConfig(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 3},
            ),
        )
        self._bucket = settings.minio_bucket_name

    async def ensure_bucket(self) -> None:
        """Create the bucket if it does not exist."""

        def _ensure() -> None:
            try:
                self._client.head_bucket(Bucket=self._bucket)
            except ClientError as exc:
                code = exc.response["Error"].get("Code", "")
                if code in ("404", "NoSuchBucket"):
                    try:
                        self._client.create_bucket(Bucket=self._bucket)
                        logger.info("bucket_created", bucket=self._bucket)
                    except ClientError as create_exc:
                        create_code = create_exc.response["Error"].get("Code", "")
                        if create_code not in (
                            "BucketAlreadyOwnedByYou",
                            "BucketAlreadyExists",
                        ):
                            raise
                        logger.info("bucket_already_exists", bucket=self._bucket)
                else:
                    raise

        try:
            await asyncio.to_thread(_ensure)
        except ClientError as exc:
            raise ExternalServiceError("MinIO", str(exc)) from exc

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        """Upload an object to the bucket."""
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            logger.debug("object_uploaded", key=key, size=len(data))
        except ClientError as exc:
            raise ExternalServiceError("MinIO", str(exc)) from exc

    async def download(self, key: str) -> bytes:
        """Download an object from the bucket."""

        def _download() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()

        try:
            return await asyncio.to_thread(_download)
        except ClientError as exc:
            raise ExternalServiceError("MinIO", str(exc)) from exc

    async def delete(self, key: str) -> None:
        """Delete an object from the bucket. No error if missing."""
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=key,
            )
        except ClientError as exc:
            raise ExternalServiceError("MinIO", str(exc)) from exc
