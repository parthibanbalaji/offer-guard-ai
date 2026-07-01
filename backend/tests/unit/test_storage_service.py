from io import BytesIO
from typing import Any

import pytest

from app.services.storage import get_file_object, upload_file_object


class FakeStorageClient:
    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []
        self.objects: dict[tuple[str, str], dict[str, object]] = {}

    def upload_fileobj(
        self,
        file: BytesIO,
        bucket: str,
        key: str,
        ExtraArgs: dict[str, str],
    ) -> None:
        self.uploads.append(
            {
                "body": file.read(),
                "bucket": bucket,
                "key": key,
                "extra_args": ExtraArgs,
            }
        )

    def get_object(self, Bucket: str, Key: str) -> dict[str, object]:
        return self.objects[(Bucket, Key)]


@pytest.mark.asyncio
async def test_upload_file_object_sends_content_type() -> None:
    client = FakeStorageClient()
    file = BytesIO(b"hello")

    await upload_file_object(
        client,
        "offer-documents",
        "documents/1/original.txt",
        file,
        "text/plain",
    )

    assert client.uploads == [
        {
            "body": b"hello",
            "bucket": "offer-documents",
            "key": "documents/1/original.txt",
            "extra_args": {"ContentType": "text/plain"},
        }
    ]


@pytest.mark.asyncio
async def test_get_file_object_returns_storage_response() -> None:
    client = FakeStorageClient()
    body = BytesIO(b"hello")
    client.objects[("offer-documents", "documents/1/original.txt")] = {"Body": body}

    result = await get_file_object(client, "offer-documents", "documents/1/original.txt")

    assert result == {"Body": body}
