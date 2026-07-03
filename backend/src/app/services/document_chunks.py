"""Postgres persistence for extracted document chunks."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import DocumentChunkRow
from app.observability.tracing import (
    process_store_chunks_inputs,
    process_store_chunks_outputs,
    traceable,
)
from app.rag.chunking import DocumentChunk


@dataclass(frozen=True)
class StoredDocumentChunk:
    """Auditable stored chunk read model."""

    id: UUID
    document_id: UUID
    chunk_ordinal: int
    text: str
    checksum_sha256: str
    language: str
    extraction_quality: str
    page_number: int | None
    section_heading: str | None
    is_suspicious: bool
    guardrail_flags: tuple[str, ...]
    created_at: datetime


@traceable(
    name="StoreDocumentChunks",
    run_type="tool",
    process_inputs=process_store_chunks_inputs,
    process_outputs=process_store_chunks_outputs,
)
async def replace_document_chunks(
    postgres_engine: AsyncEngine,
    document_id: UUID,
    chunks: Sequence[DocumentChunk],
) -> int:
    """Replace the auditable chunk rows for one document."""
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.execute(
            delete(DocumentChunkRow).where(DocumentChunkRow.document_id == document_id)
        )
        session.add_all([to_chunk_row(chunk) for chunk in chunks])
        await session.commit()

    return len(chunks)


async def list_document_chunks(
    postgres_engine: AsyncEngine,
    document_id: UUID,
) -> list[StoredDocumentChunk]:
    """List stored chunks for one document in ordinal order."""
    session_factory = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with session_factory() as session:
        result = await session.execute(
            select(DocumentChunkRow)
            .where(DocumentChunkRow.document_id == document_id)
            .order_by(DocumentChunkRow.chunk_ordinal)
        )

    return [to_stored_chunk(row) for row in result.scalars().all()]


def to_chunk_row(chunk: DocumentChunk) -> DocumentChunkRow:
    """Convert an extracted chunk into an ORM row."""
    return DocumentChunkRow(
        document_id=chunk.document_id,
        chunk_ordinal=chunk.chunk_ordinal,
        text=chunk.text,
        checksum_sha256=chunk.checksum_sha256,
        language=chunk.language,
        extraction_quality=chunk.extraction_quality,
        page_number=chunk.page_number,
        section_heading=chunk.section_heading,
        is_suspicious=chunk.is_suspicious,
        guardrail_flags=list(chunk.guardrail_flags),
    )


def to_stored_chunk(row: DocumentChunkRow) -> StoredDocumentChunk:
    """Convert an ORM row into a read model."""
    return StoredDocumentChunk(
        id=row.id,
        document_id=row.document_id,
        chunk_ordinal=row.chunk_ordinal,
        text=row.text,
        checksum_sha256=row.checksum_sha256,
        language=row.language,
        extraction_quality=row.extraction_quality,
        page_number=row.page_number,
        section_heading=row.section_heading,
        is_suspicious=row.is_suspicious,
        guardrail_flags=tuple(row.guardrail_flags),
        created_at=row.created_at,
    )
