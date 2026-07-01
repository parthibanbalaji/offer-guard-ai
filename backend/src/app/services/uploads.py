"""Document upload validation and persistence service."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryFile
from typing import BinaryIO, cast
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings
from app.db.models import Document, DocumentUploadStatus, ReviewJob, ReviewJobStatus
from app.services.storage import upload_file_object

UPLOAD_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PreparedUpload:
    """Validated upload bytes and metadata ready for storage."""

    file: BinaryIO
    original_filename: str
    media_type: str
    size_bytes: int
    checksum_sha256: str
    extension: str


@dataclass(frozen=True)
class StoredDocumentUpload:
    """Document and review job identifiers created for an upload."""

    document_id: UUID
    job_id: UUID
    original_filename: str
    media_type: str
    size_bytes: int
    checksum_sha256: str
    original_storage_key: str
    upload_status: str
    review_job_status: str


def get_filename_extension(filename: str | None) -> str:
    """Return the lower-case file extension for an uploaded filename."""
    if not filename:
        return ""

    return Path(filename).suffix.lower()


def validate_upload_extension(filename: str | None, settings: Settings) -> str:
    """Reject files whose extension is not configured as supported."""
    extension = get_filename_extension(filename)
    if extension not in settings.allowed_upload_extension_set:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="unsupported file extension",
        )

    return extension


async def prepare_upload_file(file: UploadFile, settings: Settings) -> PreparedUpload:
    """Validate an upload while copying it to a temporary file in chunks."""
    extension = validate_upload_extension(file.filename, settings)
    checksum = sha256()
    size_bytes = 0
    temporary_file = cast(BinaryIO, TemporaryFile("w+b"))  # noqa: SIM115

    try:
        while chunk := await file.read(UPLOAD_CHUNK_BYTES):
            size_bytes += len(chunk)
            if size_bytes > settings.max_upload_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="file is too large",
                )
            checksum.update(chunk)
            temporary_file.write(chunk)

        temporary_file.seek(0)
        return PreparedUpload(
            file=temporary_file,
            original_filename=file.filename or "",
            media_type=file.content_type or "application/octet-stream",
            size_bytes=size_bytes,
            checksum_sha256=checksum.hexdigest(),
            extension=extension,
        )
    except Exception:
        temporary_file.close()
        raise


async def store_prepared_upload(
    prepared_upload: PreparedUpload,
    settings: Settings,
    postgres_engine: AsyncEngine,
    storage_client: object,
) -> StoredDocumentUpload:
    """Store original bytes and create durable document/review job records."""
    document_id = uuid4()
    job_id = uuid4()
    original_storage_key = f"documents/{document_id}/original{prepared_upload.extension}"

    await upload_file_object(
        storage_client,
        settings.s3_bucket,
        original_storage_key,
        prepared_upload.file,
        prepared_upload.media_type,
    )

    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        document = Document(
            id=document_id,
            original_filename=prepared_upload.original_filename,
            media_type=prepared_upload.media_type,
            size_bytes=prepared_upload.size_bytes,
            checksum_sha256=prepared_upload.checksum_sha256,
            original_storage_key=original_storage_key,
            upload_status=DocumentUploadStatus.STORED.value,
        )
        review_job = ReviewJob(
            id=job_id,
            document_id=document_id,
            status=ReviewJobStatus.QUEUED.value,
        )
        session.add_all([document, review_job])
        await session.commit()

    return StoredDocumentUpload(
        document_id=document_id,
        job_id=job_id,
        original_filename=prepared_upload.original_filename,
        media_type=prepared_upload.media_type,
        size_bytes=prepared_upload.size_bytes,
        checksum_sha256=prepared_upload.checksum_sha256,
        original_storage_key=original_storage_key,
        upload_status=DocumentUploadStatus.STORED.value,
        review_job_status=ReviewJobStatus.QUEUED.value,
    )
