"""S3-compatible object storage helpers."""

from typing import Any, BinaryIO

import anyio
import boto3  # type: ignore[import-untyped]

from app.core.config import Settings


def create_storage_client(settings: Settings) -> Any:
    """Create an S3-compatible client for MinIO or cloud object storage."""
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
    )


async def upload_file_object(
    client: Any,
    bucket: str,
    key: str,
    file: BinaryIO,
    content_type: str,
) -> None:
    """Upload a file-like object without reading it fully into memory."""

    def upload() -> None:
        client.upload_fileobj(
            file,
            bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    await anyio.to_thread.run_sync(upload)


async def get_file_object(client: Any, bucket: str, key: str) -> Any:
    """Return an object from S3-compatible storage."""

    def get_object() -> Any:
        return client.get_object(Bucket=bucket, Key=key)

    return await anyio.to_thread.run_sync(get_object)
