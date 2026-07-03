"""Document report generation workflow."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.models import ReportGenerationStatus, ReviewJobStatus
from app.domain.rules import ClauseDefinition, RuleBase
from app.rag.embeddings import create_cached_embedding_model
from app.rag.reporting import (
    OpenRouterReportModel,
    ReportGenerationError,
    build_clause_retrieval_queries,
    generate_report_payload,
    select_relevant_chunks,
)
from app.services.document_chunks import StoredDocumentChunk, list_document_chunks
from app.services.documents import DocumentRecord, get_document_record
from app.services.reports import (
    DocumentReportRecord,
    complete_report_generation,
    fail_report_generation,
    get_document_report,
    start_report_generation,
)
from app.services.storage import upload_bytes_object
from app.services.weaviate import RetrievedChunkMatch, search_document_chunk_ordinals


@dataclass(frozen=True)
class DocumentReportGenerationResult:
    """Top-level generated report result."""

    document: DocumentRecord
    report: DocumentReportRecord


class WeaviateClauseChunkRetriever:
    """Clause retriever that prefers Weaviate semantic search with lexical fallback."""

    def __init__(
        self,
        *,
        document_id: UUID,
        weaviate_client: object | None,
        settings: Settings,
    ) -> None:
        self.document_id = document_id
        self.weaviate_client = weaviate_client
        self.embedding_model = create_cached_embedding_model(
            settings,
            namespace="report-retrieval",
        )

    async def retrieve_clause_chunks(
        self,
        *,
        clause: ClauseDefinition,
        chunks: tuple[StoredDocumentChunk, ...],
        limit: int,
    ) -> tuple[StoredDocumentChunk, ...]:
        """Return deduplicated per-query semantic matches with lexical backfill."""
        try:
            matches = await self.search_clause_queries(clause, limit=limit)
        except Exception:
            return select_relevant_chunks(clause, chunks, limit=limit)

        chunks_by_ordinal = {chunk.chunk_ordinal: chunk for chunk in chunks}
        semantic_chunks = tuple(
            chunks_by_ordinal[match.chunk_ordinal]
            for match in matches
            if match.chunk_ordinal in chunks_by_ordinal
        )
        lexical_chunks = select_relevant_chunks(clause, chunks, limit=limit)
        selected = list(semantic_chunks)
        seen_ordinals = {chunk.chunk_ordinal for chunk in selected}
        for chunk in lexical_chunks:
            if len(selected) >= limit:
                break
            if chunk.chunk_ordinal in seen_ordinals:
                continue
            selected.append(chunk)
            seen_ordinals.add(chunk.chunk_ordinal)

        return tuple(selected) or lexical_chunks

    async def search_clause_queries(
        self,
        clause: ClauseDefinition,
        *,
        limit: int,
    ) -> tuple[RetrievedChunkMatch, ...]:
        """Search every focused retrieval query and dedupe by best distance."""
        best_matches: dict[int, RetrievedChunkMatch] = {}
        for query_text in build_clause_retrieval_queries(clause):
            matches = await search_document_chunk_ordinals(
                self.weaviate_client,
                document_id=self.document_id,
                query_text=query_text,
                embedding_model=self.embedding_model,
                limit=limit,
            )
            for match in matches:
                current = best_matches.get(match.chunk_ordinal)
                if current is None or sort_distance(match) < sort_distance(current):
                    best_matches[match.chunk_ordinal] = match

        return tuple(
            sorted(
                best_matches.values(),
                key=lambda match: (sort_distance(match), match.chunk_ordinal),
            )[:limit]
        )


def sort_distance(match: RetrievedChunkMatch) -> float:
    """Return a sortable distance, pushing unknown distances behind known ones."""
    if match.distance is None:
        return float("inf")
    return match.distance


async def generate_document_report(
    *,
    document_id: UUID,
    settings: Settings,
    postgres_engine: AsyncEngine,
    storage_client: object,
    weaviate_client: object | None,
    rule_base: RuleBase,
) -> DocumentReportGenerationResult:
    """Generate and store the report for one prepared document."""
    document = await get_document_record(postgres_engine, document_id)
    if document is None:
        msg = f"document not found: {document_id}"
        raise ReportGenerationError(msg)
    if document.review_job_status != ReviewJobStatus.COMPLETED.value:
        msg = "document must be prepared before report generation"
        raise ReportGenerationError(msg)

    existing_report = await get_document_report(postgres_engine, document_id)
    if existing_report is not None and existing_report.status not in (
        ReportGenerationStatus.FAILED.value,
        ReportGenerationStatus.NOT_STARTED.value,
    ):
        msg = f"report generation is already {existing_report.status}"
        raise ReportGenerationError(msg)

    await start_report_generation(postgres_engine, document_id)
    try:
        chunks = tuple(await list_document_chunks(postgres_engine, document_id))
        payload = await generate_report_payload(
            document_id=document_id,
            original_filename=document.original_filename,
            rule_base=rule_base,
            chunks=chunks,
            model=OpenRouterReportModel(settings),
            relevant_chunk_limit=settings.report_relevant_chunk_count,
            chunk_retriever=WeaviateClauseChunkRetriever(
                document_id=document_id,
                weaviate_client=weaviate_client,
                settings=settings,
            ),
        )
        storage_key = f"reports/{document_id}/offer-review-report.md"
        await upload_bytes_object(
            storage_client,
            settings.s3_bucket,
            storage_key,
            payload.markdown.encode("utf-8"),
            "text/markdown; charset=utf-8",
        )
        report = await complete_report_generation(
            postgres_engine,
            document_id,
            report_storage_key=storage_key,
            report_json=payload.report_json,
        )
    except Exception as exc:
        await fail_report_generation(postgres_engine, document_id, error_message=str(exc))
        raise

    return DocumentReportGenerationResult(document=document, report=report)
