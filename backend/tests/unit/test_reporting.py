from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.domain.rules import ClauseDefinition, ClauseRule, RuleBase, RuleCitation, RuleSource
from app.rag.reporting import (
    build_clause_retrieval_queries,
    generate_report_payload,
    render_report_markdown,
    select_relevant_chunks,
)
from app.services.document_chunks import StoredDocumentChunk

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


def make_clause() -> ClauseDefinition:
    return ClauseDefinition(
        clause_id="probation",
        title="Probation",
        priority="high",
        description="Review probation terms.",
        search_terms=("probation", "notice"),
        retrieval_queries=("probation period notice",),
        rules=(
            ClauseRule(
                rule_id="probation_max",
                type="maximum",
                severity="high",
                text="Probation must be clear.",
                recommendation="Confirm probation period and notice.",
                expected_offer_evidence=("probation period",),
                citations=(RuleCitation(source_id="uae_law", reference="Article 9"),),
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


def test_select_relevant_chunks_prefers_clause_terms() -> None:
    chunks = (
        make_chunk(0, "Base salary is AED 20,000."),
        make_chunk(1, "Probation period is six months with notice."),
    )

    selected = select_relevant_chunks(make_clause(), chunks, limit=1)

    assert selected[0].chunk_ordinal == 1


def test_build_clause_retrieval_queries_focuses_each_retrieval_query() -> None:
    clause = ClauseDefinition(
        clause_id="compensation",
        title="Compensation",
        priority="high",
        description="Review salary, allowances, and payment terms.",
        search_terms=("salary",),
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

    queries = build_clause_retrieval_queries(clause)

    assert queries == (
        "Compensation\nReview salary, allowances, and payment terms.\nbase salary amount",
        "Compensation\nReview salary, allowances, and payment terms.\nhousing allowance amount",
    )


@pytest.mark.asyncio
async def test_generate_report_payload_normalizes_citations_and_renders_markdown() -> None:
    class FakeRetriever:
        async def retrieve_clause_chunks(
            self,
            *,
            clause: ClauseDefinition,
            chunks: tuple[StoredDocumentChunk, ...],
            limit: int,
        ) -> tuple[StoredDocumentChunk, ...]:
            assert clause.clause_id == "probation"
            assert limit == 5
            return (chunks[0],)

    class FakeModel:
        async def analyze_clause(
            self,
            *,
            clause: ClauseDefinition,
            chunks: tuple[StoredDocumentChunk, ...],
        ) -> dict[str, Any]:
            assert clause.clause_id == "probation"
            assert chunks[0].chunk_ordinal == 0
            return {
                "score": 82,
                "summary": "Probation is present but should be checked.",
                "observations": ["The offer includes a probation term."],
                "risks": [],
                "recommendations": ["Confirm notice obligations."],
                "evidence_citations": [
                    {
                        "chunk_ordinal": 0,
                        "page_number": 1,
                        "quote": "Probation period is six months.",
                    }
                ],
                "rule_citations": [{"source_id": "uae_law", "reference": "Article 9"}],
            }

    result = await generate_report_payload(
        document_id=DOCUMENT_ID,
        original_filename="offer.txt",
        rule_base=make_rule_base(),
        chunks=(make_chunk(0, "Probation period is six months."),),
        model=FakeModel(),
        relevant_chunk_limit=5,
        chunk_retriever=FakeRetriever(),
    )

    assert result.report_json["clauses"][0]["score"] == 82
    assert "Probation (82/100)" in result.markdown
    assert "uae_law: Article 9" in result.markdown


def test_render_report_markdown_includes_disclaimer() -> None:
    markdown = render_report_markdown(
        {
            "original_filename": "offer.txt",
            "jurisdiction": "United Arab Emirates",
            "clauses": [
                {
                    "title": "Compensation",
                    "score": 90,
                    "summary": "Clear.",
                    "observations": [],
                    "risks": [],
                    "recommendations": [],
                    "evidence_citations": [],
                    "rule_citations": [{"source_id": "source", "reference": "ref"}],
                }
            ],
        }
    )

    assert "AI-assisted review only" in markdown
    assert "No direct offer evidence cited" in markdown
