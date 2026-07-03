"""Postgres persistence for generated document reports."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import DocumentReport, ReportGenerationStatus


@dataclass(frozen=True)
class DocumentReportRecord:
    """Stored generated report metadata."""

    id: UUID
    document_id: UUID
    status: str
    report_storage_key: str | None
    report_json: dict[str, Any] | None
    error_message: str | None
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime


async def get_document_report(
    postgres_engine: AsyncEngine,
    document_id: UUID,
) -> DocumentReportRecord | None:
    """Return generated report metadata for one document."""
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(DocumentReport).where(DocumentReport.document_id == document_id).limit(1)
        )
        row = result.scalar_one_or_none()

    if row is None:
        return None

    return to_report_record(row)


async def start_report_generation(
    postgres_engine: AsyncEngine,
    document_id: UUID,
) -> DocumentReportRecord:
    """Create or transition a report row into processing."""
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(DocumentReport).where(DocumentReport.document_id == document_id).limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = DocumentReport(document_id=document_id)
            session.add(row)
            await session.flush()

        row.status = ReportGenerationStatus.PROCESSING.value
        row.report_storage_key = None
        row.report_json = None
        row.error_message = None
        row.generated_at = None
        await session.commit()
        await session.refresh(row)

    return to_report_record(row)


async def complete_report_generation(
    postgres_engine: AsyncEngine,
    document_id: UUID,
    *,
    report_storage_key: str,
    report_json: dict[str, Any],
) -> DocumentReportRecord:
    """Persist successful report generation metadata."""
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(DocumentReport).where(DocumentReport.document_id == document_id).limit(1)
        )
        row = result.scalar_one()
        row.status = ReportGenerationStatus.COMPLETED.value
        row.report_storage_key = report_storage_key
        row.report_json = report_json
        row.error_message = None
        row.generated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(row)

    return to_report_record(row)


async def fail_report_generation(
    postgres_engine: AsyncEngine,
    document_id: UUID,
    *,
    error_message: str,
) -> DocumentReportRecord:
    """Persist failed report generation metadata."""
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(DocumentReport).where(DocumentReport.document_id == document_id).limit(1)
        )
        row = result.scalar_one()
        row.status = ReportGenerationStatus.FAILED.value
        row.error_message = error_message[:4000]
        await session.commit()
        await session.refresh(row)

    return to_report_record(row)


def to_report_record(row: DocumentReport) -> DocumentReportRecord:
    """Convert an ORM row into a read model."""
    return DocumentReportRecord(
        id=row.id,
        document_id=row.document_id,
        status=row.status,
        report_storage_key=row.report_storage_key,
        report_json=row.report_json,
        error_message=row.error_message,
        generated_at=row.generated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
