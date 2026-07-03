"""Document-level review preparation workflow."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.models import ReviewJobStatus
from app.domain.rules import RuleBase
from app.observability.tracing import (
    process_document_run_inputs,
    process_document_run_outputs,
    traceable,
)
from app.rag.embeddings import EmbeddingProviderError
from app.rag.pipeline import DocumentIndexingError, DocumentIndexingResult, index_uploaded_document
from app.services.documents import DocumentRecord, get_document_record, update_review_job_status


@dataclass(frozen=True)
class DocumentReviewRunResult:
    """Top-level document preparation result."""

    document: DocumentRecord
    rule_base: RuleBase | None
    review_job_status: str
    indexing_result: DocumentIndexingResult
    guardrail_flags: tuple[str, ...]


@traceable(
    name="DocumentReviewRun",
    run_type="chain",
    process_inputs=process_document_run_inputs,
    process_outputs=process_document_run_outputs,
)
async def prepare_document_review_run(
    *,
    document_id: UUID,
    settings: Settings,
    postgres_engine: AsyncEngine,
    storage_client: object,
    weaviate_client: object | None,
    rule_base: RuleBase | None,
) -> DocumentReviewRunResult:
    """Run one document-first review preparation trace."""
    record = await get_document_record(postgres_engine, document_id)
    if record is None:
        msg = f"document not found: {document_id}"
        raise DocumentIndexingError(msg)

    await update_review_job_status(
        postgres_engine,
        record.job_id,
        ReviewJobStatus.PROCESSING.value,
    )

    try:
        indexing_result = await index_uploaded_document(
            document_id=document_id,
            settings=settings,
            postgres_engine=postgres_engine,
            storage_client=storage_client,
            weaviate_client=weaviate_client,
        )
    except (DocumentIndexingError, EmbeddingProviderError):
        await update_review_job_status(
            postgres_engine,
            record.job_id,
            ReviewJobStatus.FAILED.value,
        )
        raise
    except Exception:
        await update_review_job_status(
            postgres_engine,
            record.job_id,
            ReviewJobStatus.FAILED.value,
        )
        raise

    await update_review_job_status(
        postgres_engine,
        record.job_id,
        ReviewJobStatus.COMPLETED.value,
    )

    return DocumentReviewRunResult(
        document=record,
        rule_base=rule_base,
        review_job_status=ReviewJobStatus.COMPLETED.value,
        indexing_result=indexing_result,
        guardrail_flags=tuple(sorted({finding.code for finding in indexing_result.findings})),
    )
