"""Document upload endpoints."""

from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Annotated, Protocol
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.rag.embeddings import EmbeddingProviderError
from app.rag.pipeline import DocumentIndexingError
from app.services.document_chunks import list_document_chunks
from app.services.documents import (
    DocumentRecord,
    get_document_record,
    list_document_records,
)
from app.services.storage import get_file_object
from app.services.uploads import prepare_upload_file, store_prepared_upload
from app.workflows.document_review import prepare_document_review_run

router = APIRouter()


class StorageBody(Protocol):
    """Readable object returned by object storage clients."""

    def read(self, amount: int) -> bytes: ...

    def close(self) -> None: ...


class DocumentUploadResponse(BaseModel):
    """Stored upload metadata returned after persistence."""

    document_id: UUID
    job_id: UUID
    original_filename: str
    media_type: str
    size_bytes: int
    checksum_sha256: str
    original_storage_key: str
    upload_status: str
    review_job_status: str


class DocumentListResponse(BaseModel):
    """Stored document metadata returned for list views."""

    document_id: UUID
    job_id: UUID
    original_filename: str
    media_type: str
    size_bytes: int
    checksum_sha256: str
    upload_status: str
    review_job_status: str
    created_at: datetime


class DocumentPreparationResponse(BaseModel):
    """Result returned after preparing an uploaded document for review."""

    document_id: UUID
    job_id: UUID
    review_job_status: str
    chunk_count: int
    stored_count: int
    indexed_count: int
    guardrail_flags: list[str]


class DocumentChunkResponse(BaseModel):
    """Auditable extracted chunk returned for document inspection."""

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
    guardrail_flags: list[str]
    created_at: datetime


def to_document_list_response(record: DocumentRecord) -> DocumentListResponse:
    """Convert a document read model into an API response."""
    return DocumentListResponse(
        document_id=record.document_id,
        job_id=record.job_id,
        original_filename=record.original_filename,
        media_type=record.media_type,
        size_bytes=record.size_bytes,
        checksum_sha256=record.checksum_sha256,
        upload_status=record.upload_status,
        review_job_status=record.review_job_status,
        created_at=record.created_at,
    )


def iter_storage_body(body: StorageBody) -> Iterator[bytes]:
    """Yield object storage bytes in response-sized chunks."""
    read: Callable[[int], bytes] = body.read
    try:
        while chunk := read(1024 * 1024):
            yield chunk
    finally:
        body.close()


@router.post(
    "/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentUploadResponse:
    """Store an uploaded offer document and queue it for review."""
    prepared_upload = await prepare_upload_file(file, settings)
    try:
        stored_upload = await store_prepared_upload(
            prepared_upload,
            settings,
            request.app.state.resources.postgres_engine,
            request.app.state.resources.storage_client,
        )
    finally:
        prepared_upload.file.close()

    return DocumentUploadResponse(
        document_id=stored_upload.document_id,
        job_id=stored_upload.job_id,
        original_filename=stored_upload.original_filename,
        media_type=stored_upload.media_type,
        size_bytes=stored_upload.size_bytes,
        checksum_sha256=stored_upload.checksum_sha256,
        original_storage_key=stored_upload.original_storage_key,
        upload_status=stored_upload.upload_status,
        review_job_status=stored_upload.review_job_status,
    )


@router.get("/documents", response_model=list[DocumentListResponse])
async def list_documents(request: Request) -> list[DocumentListResponse]:
    """List documents that have already been uploaded."""
    records = await list_document_records(request.app.state.resources.postgres_engine)
    return [to_document_list_response(record) for record in records]


@router.post("/documents/{document_id}/prepare", response_model=DocumentPreparationResponse)
async def prepare_document_for_review(
    document_id: UUID,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentPreparationResponse:
    """Manually prepare an uploaded document for review."""
    resources = request.app.state.resources
    try:
        result = await prepare_document_review_run(
            document_id=document_id,
            settings=settings,
            postgres_engine=resources.postgres_engine,
            storage_client=resources.storage_client,
            weaviate_client=resources.weaviate_client,
            rule_base=getattr(resources, "uae_rule_base", None),
        )
    except DocumentIndexingError as exc:
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
        if str(exc).startswith("document not found"):
            http_status = status.HTTP_404_NOT_FOUND
        raise HTTPException(
            status_code=http_status,
            detail=str(exc),
        ) from exc
    except EmbeddingProviderError as exc:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
        if exc.kind == "rate_limited":
            http_status = status.HTTP_429_TOO_MANY_REQUESTS
        elif exc.kind == "quota_exceeded":
            http_status = status.HTTP_402_PAYMENT_REQUIRED
        raise HTTPException(
            status_code=http_status,
            detail=str(exc),
        ) from exc

    return DocumentPreparationResponse(
        document_id=document_id,
        job_id=result.document.job_id,
        review_job_status=result.review_job_status,
        chunk_count=result.indexing_result.chunk_count,
        stored_count=result.indexing_result.stored_count,
        indexed_count=result.indexing_result.indexed_count,
        guardrail_flags=list(result.guardrail_flags),
    )


@router.get("/documents/{document_id}/chunks", response_model=list[DocumentChunkResponse])
async def list_document_chunk_rows(
    document_id: UUID,
    request: Request,
) -> list[DocumentChunkResponse]:
    """List auditable extracted chunks for one uploaded document."""
    postgres_engine = request.app.state.resources.postgres_engine
    record = await get_document_record(postgres_engine, document_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="document not found",
        )

    chunks = await list_document_chunks(postgres_engine, document_id)
    return [
        DocumentChunkResponse(
            id=chunk.id,
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
            created_at=chunk.created_at,
        )
        for chunk in chunks
    ]


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: UUID,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    """Download the original uploaded document bytes."""
    record = await get_document_record(request.app.state.resources.postgres_engine, document_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="document not found",
        )

    stored_object = await get_file_object(
        request.app.state.resources.storage_client,
        settings.s3_bucket,
        record.original_storage_key,
    )
    body = stored_object["Body"]
    filename = quote(record.original_filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}

    return StreamingResponse(
        iter_storage_body(body),
        media_type=record.media_type,
        headers=headers,
    )
