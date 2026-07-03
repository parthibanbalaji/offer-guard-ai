"""Document read models and database queries."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import Document, ReviewJob


@dataclass(frozen=True)
class DocumentRecord:
    """Stored document metadata with its review job status."""

    document_id: UUID
    job_id: UUID
    original_filename: str
    media_type: str
    size_bytes: int
    checksum_sha256: str
    original_storage_key: str
    upload_status: str
    review_job_status: str
    created_at: datetime


def document_record_query() -> Select[tuple[Document, ReviewJob]]:
    """Return the current document list query."""
    return (
        select(Document, ReviewJob)
        .join(ReviewJob, ReviewJob.document_id == Document.id)
        .order_by(Document.created_at.desc())
    )


def to_document_record(document: Document, review_job: ReviewJob) -> DocumentRecord:
    """Convert ORM rows into an API-facing read model."""
    return DocumentRecord(
        document_id=document.id,
        job_id=review_job.id,
        original_filename=document.original_filename,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        checksum_sha256=document.checksum_sha256,
        original_storage_key=document.original_storage_key,
        upload_status=document.upload_status,
        review_job_status=review_job.status,
        created_at=document.created_at,
    )


async def list_document_records(postgres_engine: AsyncEngine) -> list[DocumentRecord]:
    """List stored documents with their queued review jobs."""
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(document_record_query())

    return [to_document_record(document, review_job) for document, review_job in result.all()]


async def get_document_record(
    postgres_engine: AsyncEngine,
    document_id: UUID,
) -> DocumentRecord | None:
    """Return one stored document read model by id."""
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            document_record_query().where(Document.id == document_id).limit(1)
        )
        row = result.one_or_none()

    if row is None:
        return None

    document, review_job = row
    return to_document_record(document, review_job)


async def update_review_job_status(
    postgres_engine: AsyncEngine,
    job_id: UUID,
    review_job_status: str,
) -> None:
    """Update the stored status for a review job."""
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.execute(
            update(ReviewJob)
            .where(ReviewJob.id == job_id)
            .values(status=review_job_status)
        )
        await session.commit()
