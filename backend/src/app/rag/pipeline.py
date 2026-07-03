"""End-to-end retrieval indexing pipeline for uploaded documents."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.guardrails.input import GuardrailFinding, check_extracted_document
from app.observability.tracing import (
    process_pipeline_inputs,
    process_pipeline_outputs,
    process_storage_read_inputs,
    process_storage_read_outputs,
    traceable,
)
from app.rag.chunking import ChunkingConfig, DocumentChunk, chunk_document
from app.rag.embeddings import EmbeddingModel, create_embedding_model
from app.rag.extraction import extension_for_filename, extract_document
from app.services.document_chunks import replace_document_chunks
from app.services.documents import get_document_record
from app.services.storage import get_file_object
from app.services.weaviate import index_document_chunks


@dataclass(frozen=True)
class DocumentIndexingResult:
    """Outcome of extracting, chunking, and indexing a document."""

    document_id: UUID
    chunk_count: int
    stored_count: int
    indexed_count: int
    findings: tuple[GuardrailFinding, ...]
    chunks: tuple[DocumentChunk, ...]


class DocumentIndexingError(RuntimeError):
    """Raised when a document cannot be indexed."""


@traceable(
    name="PrepareUploadedDocument",
    run_type="chain",
    process_inputs=process_pipeline_inputs,
    process_outputs=process_pipeline_outputs,
)
async def index_uploaded_document(
    *,
    document_id: UUID,
    settings: Settings,
    postgres_engine: AsyncEngine,
    storage_client: object,
    weaviate_client: object | None,
    embedding_model: EmbeddingModel | None = None,
) -> DocumentIndexingResult:
    """Extract, guard, chunk, embed, and index one uploaded document."""
    record = await get_document_record(postgres_engine, document_id)
    if record is None:
        msg = f"document not found: {document_id}"
        raise DocumentIndexingError(msg)

    content = await read_stored_document(
        storage_client,
        bucket=settings.s3_bucket,
        key=record.original_storage_key,
    )
    extracted_document = extract_document(
        content,
        filename=record.original_filename,
        media_type=record.media_type,
    )
    extension = extension_for_filename(record.original_filename)
    guardrail_result = check_extracted_document(
        extracted_document,
        extension=extension,
        size_bytes=record.size_bytes,
        max_size_bytes=settings.max_upload_bytes,
        allowed_extensions=settings.allowed_upload_extension_set,
    )
    chunks = chunk_document(
        extracted_document,
        document_id=document_id,
        config=ChunkingConfig(
            target_chars=settings.chunk_target_chars,
            overlap_chars=settings.chunk_overlap_chars,
        ),
    )
    stored_count = await replace_document_chunks(postgres_engine, document_id, chunks)
    indexed_count = await index_document_chunks(
        weaviate_client,
        chunks,
        embedding_model or create_embedding_model(settings),
    )

    return DocumentIndexingResult(
        document_id=document_id,
        chunk_count=len(chunks),
        stored_count=stored_count,
        indexed_count=indexed_count,
        findings=guardrail_result.findings,
        chunks=chunks,
    )


@traceable(
    name="ReadStoredDocument",
    run_type="tool",
    process_inputs=process_storage_read_inputs,
    process_outputs=process_storage_read_outputs,
)
async def read_stored_document(storage_client: object, *, bucket: str, key: str) -> bytes:
    """Read original document bytes from object storage."""
    stored_object = await get_file_object(storage_client, bucket, key)
    body = stored_object["Body"]
    try:
        chunks: list[bytes] = []
        while chunk := body.read(1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        body.close()
