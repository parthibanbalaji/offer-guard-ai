from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.config import Settings
from app.domain.rules import ClauseDefinition, ClauseRule, RuleBase, RuleCitation, RuleSource
from app.services.document_chunks import StoredDocumentChunk
from app.services.documents import DocumentRecord
from app.services.reports import DocumentReportRecord
from app.services.weaviate import RetrievedChunkMatch
from app.workflows import report_generation

DOCUMENT_ID = UUID("11111111-1111-1111-1111-111111111111")
JOB_ID = UUID("22222222-2222-2222-2222-222222222222")
REPORT_ID = UUID("44444444-4444-4444-4444-444444444444")


def make_chunk(ordinal: int, text: str) -> StoredDocumentChunk:
    return StoredDocumentChunk(
        id=UUID(f"33333333-3333-3333-3333-{ordinal + 1:012d}"),
        document_id=DOCUMENT_ID,
        chunk_ordinal=ordinal,
        text=text,
        checksum_sha256="a" * 64,
        language="en",
        extraction_quality="good",
        page_number=ordinal + 1,
        section_heading=None,
        is_suspicious=False,
        guardrail_flags=(),
        created_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
    )


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:password@db.example.test:5432/offerguard",
        embedding_provider="hash",
    )


def make_clause() -> ClauseDefinition:
    return ClauseDefinition(
        clause_id="compensation",
        title="Compensation",
        priority="high",
        description="Review salary and allowances.",
        search_terms=("salary", "allowance"),
        retrieval_queries=("base salary amount", "housing allowance amount"),
        rules=(
            ClauseRule(
                rule_id="salary_clear",
                type="presence",
                severity="high",
                text="Salary should be clear.",
                recommendation="Confirm salary.",
                expected_offer_evidence=("salary",),
                citations=(RuleCitation(source_id="uae_law", reference="Article 22"),),
            ),
        ),
    )


def make_rule_base() -> RuleBase:
    return RuleBase(
        schema_version="1",
        rule_base_id="uae_rules",
        title="UAE rules",
        jurisdiction="United Arab Emirates",
        retrieved_on="2026-07-03",
        limitations=(),
        sources=(
            RuleSource(
                source_id="uae_law",
                title="UAE Labour Law",
                publisher="MOHRE",
                url="https://example.test",
                retrieved_on="2026-07-03",
                notes="Test source",
            ),
        ),
        clauses=(make_clause(),),
    )


def make_document_record(review_job_status: str = "completed") -> DocumentRecord:
    return DocumentRecord(
        document_id=DOCUMENT_ID,
        job_id=JOB_ID,
        original_filename="offer.txt",
        media_type="text/plain",
        size_bytes=5,
        checksum_sha256="checksum",
        original_storage_key="documents/111/original.txt",
        upload_status="stored",
        review_job_status=review_job_status,
        report_status="not_started",
        report_storage_key=None,
        report_error_message=None,
        report_generated_at=None,
        created_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
    )


def make_report_record(status: str = "completed") -> DocumentReportRecord:
    return DocumentReportRecord(
        id=REPORT_ID,
        document_id=DOCUMENT_ID,
        status=status,
        report_storage_key="reports/111/offer-review-report.md" if status == "completed" else None,
        report_json={"status": status} if status == "completed" else None,
        error_message=None,
        generated_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC) if status == "completed" else None,
        created_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
    )


def test_sort_distance_pushes_unknown_distance_last() -> None:
    match = RetrievedChunkMatch(chunk_ordinal=1, distance=None)

    assert report_generation.sort_distance(match) == float("inf")


@pytest.mark.asyncio
async def test_weaviate_clause_retriever_searches_each_query_and_dedupes(monkeypatch) -> None:
    calls: list[str] = []

    async def search_document_chunk_ordinals(
        _: object,
        *,
        document_id: UUID,
        query_text: str,
        embedding_model: object,
        limit: int,
    ) -> tuple[RetrievedChunkMatch, ...]:
        assert document_id == DOCUMENT_ID
        assert limit == 3
        assert embedding_model is not None
        calls.append(query_text)
        if "base salary" in query_text:
            return (
                RetrievedChunkMatch(chunk_ordinal=1, distance=0.30),
                RetrievedChunkMatch(chunk_ordinal=2, distance=0.40),
            )
        return (
            RetrievedChunkMatch(chunk_ordinal=2, distance=0.10),
            RetrievedChunkMatch(chunk_ordinal=3, distance=0.20),
        )

    monkeypatch.setattr(
        report_generation,
        "search_document_chunk_ordinals",
        search_document_chunk_ordinals,
    )
    monkeypatch.setattr(
        report_generation,
        "create_cached_embedding_model",
        lambda *_, **__: SimpleNamespace(embed_texts=lambda __: []),
    )

    retriever = report_generation.WeaviateClauseChunkRetriever(
        document_id=DOCUMENT_ID,
        weaviate_client=SimpleNamespace(),
        settings=make_settings(),
    )
    chunks = (
        make_chunk(0, "Unrelated intro."),
        make_chunk(1, "Base salary is AED 20,000."),
        make_chunk(2, "Housing allowance is AED 8,000."),
        make_chunk(3, "Transport allowance is AED 2,000."),
    )

    selected = await retriever.retrieve_clause_chunks(
        clause=make_clause(),
        chunks=chunks,
        limit=3,
    )

    assert calls == [
        "Compensation\nReview salary and allowances.\nbase salary amount",
        "Compensation\nReview salary and allowances.\nhousing allowance amount",
    ]
    assert [chunk.chunk_ordinal for chunk in selected] == [2, 3, 1]


@pytest.mark.asyncio
async def test_weaviate_clause_retriever_uses_lexical_fallback_on_search_error(
    monkeypatch,
) -> None:
    async def search_clause_queries(
        self: report_generation.WeaviateClauseChunkRetriever,
        clause: ClauseDefinition,
        *,
        limit: int,
    ) -> tuple[RetrievedChunkMatch, ...]:
        raise RuntimeError("weaviate unavailable")

    monkeypatch.setattr(
        report_generation.WeaviateClauseChunkRetriever,
        "search_clause_queries",
        search_clause_queries,
    )
    monkeypatch.setattr(
        report_generation,
        "create_cached_embedding_model",
        lambda *_, **__: SimpleNamespace(embed_texts=lambda __: []),
    )

    retriever = report_generation.WeaviateClauseChunkRetriever(
        document_id=DOCUMENT_ID,
        weaviate_client=SimpleNamespace(),
        settings=make_settings(),
    )
    selected = await retriever.retrieve_clause_chunks(
        clause=make_clause(),
        chunks=(
            make_chunk(0, "Unrelated intro."),
            make_chunk(1, "Base salary is AED 20,000."),
        ),
        limit=1,
    )

    assert [chunk.chunk_ordinal for chunk in selected] == [1]


@pytest.mark.asyncio
async def test_generate_document_report_stores_markdown_report(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    report_record = make_report_record()

    async def get_document_record(_: object, document_id: UUID) -> DocumentRecord:
        assert document_id == DOCUMENT_ID
        return make_document_record()

    async def get_document_report(_: object, document_id: UUID) -> None:
        assert document_id == DOCUMENT_ID
        return None

    async def start_report_generation(_: object, document_id: UUID) -> None:
        calls.append(("start", document_id))

    async def list_document_chunks(_: object, document_id: UUID) -> list[StoredDocumentChunk]:
        assert document_id == DOCUMENT_ID
        return [make_chunk(0, "Base salary is AED 20,000.")]

    async def generate_report_payload(**kwargs: object) -> SimpleNamespace:
        assert kwargs["document_id"] == DOCUMENT_ID
        assert kwargs["original_filename"] == "offer.txt"
        assert kwargs["rule_base"] == make_rule_base()
        assert kwargs["relevant_chunk_limit"] == 5
        assert kwargs["chunk_retriever"] is not None
        return SimpleNamespace(
            markdown="# Report",
            report_json={"clauses": []},
        )

    async def upload_bytes_object(
        _: object,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        calls.append(("upload", (bucket, key, content, content_type)))

    async def complete_report_generation(
        _: object,
        document_id: UUID,
        *,
        report_storage_key: str,
        report_json: dict[str, object],
    ) -> DocumentReportRecord:
        calls.append(("complete", (document_id, report_storage_key, report_json)))
        return report_record

    monkeypatch.setattr(report_generation, "get_document_record", get_document_record)
    monkeypatch.setattr(report_generation, "get_document_report", get_document_report)
    monkeypatch.setattr(report_generation, "start_report_generation", start_report_generation)
    monkeypatch.setattr(report_generation, "list_document_chunks", list_document_chunks)
    monkeypatch.setattr(report_generation, "generate_report_payload", generate_report_payload)
    monkeypatch.setattr(report_generation, "upload_bytes_object", upload_bytes_object)
    monkeypatch.setattr(report_generation, "complete_report_generation", complete_report_generation)
    monkeypatch.setattr(report_generation, "OpenRouterReportModel", lambda _: SimpleNamespace())

    result = await report_generation.generate_document_report(
        document_id=DOCUMENT_ID,
        settings=make_settings(),
        postgres_engine=SimpleNamespace(),
        storage_client=SimpleNamespace(),
        weaviate_client=SimpleNamespace(),
        rule_base=make_rule_base(),
    )

    assert result.document == make_document_record()
    assert result.report == report_record
    assert calls == [
        ("start", DOCUMENT_ID),
        (
            "upload",
            (
                "offer-documents",
                f"reports/{DOCUMENT_ID}/offer-review-report.md",
                b"# Report",
                "text/markdown; charset=utf-8",
            ),
        ),
        (
            "complete",
            (DOCUMENT_ID, f"reports/{DOCUMENT_ID}/offer-review-report.md", {"clauses": []}),
        ),
    ]


@pytest.mark.asyncio
async def test_generate_document_report_requires_prepared_document(monkeypatch) -> None:
    async def get_document_record(_: object, __: UUID) -> DocumentRecord:
        return make_document_record(review_job_status="queued")

    monkeypatch.setattr(report_generation, "get_document_record", get_document_record)

    with pytest.raises(report_generation.ReportGenerationError, match="must be prepared"):
        await report_generation.generate_document_report(
            document_id=DOCUMENT_ID,
            settings=make_settings(),
            postgres_engine=SimpleNamespace(),
            storage_client=SimpleNamespace(),
            weaviate_client=SimpleNamespace(),
            rule_base=make_rule_base(),
        )


@pytest.mark.asyncio
async def test_generate_document_report_rejects_completed_existing_report(monkeypatch) -> None:
    async def get_document_record(_: object, __: UUID) -> DocumentRecord:
        return make_document_record()

    async def get_document_report(_: object, __: UUID) -> DocumentReportRecord:
        return make_report_record(status="completed")

    monkeypatch.setattr(report_generation, "get_document_record", get_document_record)
    monkeypatch.setattr(report_generation, "get_document_report", get_document_report)

    with pytest.raises(report_generation.ReportGenerationError, match="already completed"):
        await report_generation.generate_document_report(
            document_id=DOCUMENT_ID,
            settings=make_settings(),
            postgres_engine=SimpleNamespace(),
            storage_client=SimpleNamespace(),
            weaviate_client=SimpleNamespace(),
            rule_base=make_rule_base(),
        )


@pytest.mark.asyncio
async def test_generate_document_report_marks_failed_when_generation_errors(monkeypatch) -> None:
    failures: list[str] = []

    async def get_document_record(_: object, __: UUID) -> DocumentRecord:
        return make_document_record()

    async def get_document_report(_: object, __: UUID) -> None:
        return None

    async def start_report_generation(_: object, __: UUID) -> None:
        return None

    async def list_document_chunks(_: object, __: UUID) -> list[StoredDocumentChunk]:
        return [make_chunk(0, "Base salary")]

    async def generate_report_payload(**_: object) -> SimpleNamespace:
        raise RuntimeError("model down")

    async def fail_report_generation(
        _: object,
        __: UUID,
        *,
        error_message: str,
    ) -> DocumentReportRecord:
        failures.append(error_message)
        return make_report_record(status="failed")

    monkeypatch.setattr(report_generation, "get_document_record", get_document_record)
    monkeypatch.setattr(report_generation, "get_document_report", get_document_report)
    monkeypatch.setattr(report_generation, "start_report_generation", start_report_generation)
    monkeypatch.setattr(report_generation, "list_document_chunks", list_document_chunks)
    monkeypatch.setattr(report_generation, "generate_report_payload", generate_report_payload)
    monkeypatch.setattr(report_generation, "fail_report_generation", fail_report_generation)
    monkeypatch.setattr(report_generation, "OpenRouterReportModel", lambda _: SimpleNamespace())

    with pytest.raises(RuntimeError, match="model down"):
        await report_generation.generate_document_report(
            document_id=DOCUMENT_ID,
            settings=make_settings(),
            postgres_engine=SimpleNamespace(),
            storage_client=SimpleNamespace(),
            weaviate_client=SimpleNamespace(),
            rule_base=make_rule_base(),
        )

    assert failures == ["model down"]
