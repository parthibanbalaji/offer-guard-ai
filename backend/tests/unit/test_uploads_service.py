from io import BytesIO
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.core.config import Settings
from app.db.models import Document, ReviewJob
from app.services import uploads
from app.services.uploads import PreparedUpload, prepare_upload_file, store_prepared_upload


def make_settings(**overrides: Any) -> Settings:
    values = {
        "database_url": "postgresql+asyncpg://user:password@db.example.test:5432/offerguard",
        **overrides,
    }
    return Settings(_env_file=None, **values)


@pytest.mark.asyncio
async def test_prepare_upload_file_hashes_and_buffers_upload() -> None:
    settings = make_settings(max_upload_bytes=10, allowed_upload_extensions=".txt")
    upload = UploadFile(
        filename="offer.txt",
        file=BytesIO(b"hello"),
        headers=Headers({"content-type": "text/plain"}),
    )

    prepared = await prepare_upload_file(upload, settings)
    try:
        assert prepared.original_filename == "offer.txt"
        assert prepared.media_type == "text/plain"
        assert prepared.size_bytes == 5
        assert prepared.extension == ".txt"
        assert prepared.checksum_sha256 == (
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        )
        assert prepared.file.read() == b"hello"
    finally:
        prepared.file.close()


@pytest.mark.asyncio
async def test_prepare_upload_file_rejects_oversized_upload() -> None:
    settings = make_settings(max_upload_bytes=4, allowed_upload_extensions=".txt")
    upload = UploadFile(filename="offer.txt", file=BytesIO(b"hello"))

    with pytest.raises(HTTPException) as exc_info:
        await prepare_upload_file(upload, settings)

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "file is too large"


@pytest.mark.asyncio
async def test_prepare_upload_file_rejects_unsupported_extension() -> None:
    settings = make_settings(max_upload_bytes=10, allowed_upload_extensions=".txt")
    upload = UploadFile(filename="offer.exe", file=BytesIO(b"hello"))

    with pytest.raises(HTTPException) as exc_info:
        await prepare_upload_file(upload, settings)

    assert exc_info.value.status_code == 415
    assert exc_info.value.detail == "unsupported file extension"


@pytest.mark.asyncio
async def test_store_prepared_upload_saves_object_and_database_rows(monkeypatch) -> None:
    settings = make_settings()
    prepared_upload = PreparedUpload(
        file=BytesIO(b"hello"),
        original_filename="offer.txt",
        media_type="text/plain",
        size_bytes=5,
        checksum_sha256="checksum",
        extension=".txt",
    )
    uploads_seen: list[dict[str, object]] = []
    committed_rows: list[object] = []

    async def upload_file_object(
        storage_client: object,
        bucket: str,
        key: str,
        file: BytesIO,
        content_type: str,
    ) -> None:
        uploads_seen.append(
            {
                "storage_client": storage_client,
                "bucket": bucket,
                "key": key,
                "body": file.read(),
                "content_type": content_type,
            }
        )

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        def add_all(self, rows: list[object]) -> None:
            committed_rows.extend(rows)

        async def commit(self) -> None:
            return None

    class FakeSessionFactory:
        def __call__(self) -> FakeSession:
            return FakeSession()

    def async_sessionmaker(_: object, **__: object) -> FakeSessionFactory:
        return FakeSessionFactory()

    monkeypatch.setattr(uploads, "upload_file_object", upload_file_object)
    monkeypatch.setattr(uploads, "async_sessionmaker", async_sessionmaker)
    monkeypatch.setattr(
        uploads,
        "uuid4",
        lambda: UUID("11111111-1111-1111-1111-111111111111"),
    )

    result = await store_prepared_upload(
        prepared_upload,
        settings,
        postgres_engine=SimpleNamespace(),
        storage_client="storage-client",
    )

    assert uploads_seen == [
        {
            "storage_client": "storage-client",
            "bucket": "offer-documents",
            "key": "documents/11111111-1111-1111-1111-111111111111/original.txt",
            "body": b"hello",
            "content_type": "text/plain",
        }
    ]
    assert isinstance(committed_rows[0], Document)
    assert isinstance(committed_rows[1], ReviewJob)
    assert result.document_id == UUID("11111111-1111-1111-1111-111111111111")
    assert result.job_id == UUID("11111111-1111-1111-1111-111111111111")
    assert result.upload_status == "stored"
    assert result.review_job_status == "queued"
