from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.config import Settings
from app.domain.rules import ClauseDefinition, ClauseRule, RuleCitation
from app.services.document_chunks import StoredDocumentChunk
from app.services.weaviate import RetrievedChunkMatch
from app.workflows import report_generation

DOCUMENT_ID = UUID("11111111-1111-1111-1111-111111111111")


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
