from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from evals import ragas_offer_review

from app.domain.rules import ClauseDefinition, ClauseRule, RuleBase, RuleCitation, RuleSource
from app.services.document_chunks import StoredDocumentChunk

DOCUMENT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def make_chunk(text: str, ordinal: int = 0) -> StoredDocumentChunk:
    return StoredDocumentChunk(
        id=UUID(f"bbbbbbbb-bbbb-bbbb-bbbb-{ordinal + 1:012d}"),
        document_id=DOCUMENT_ID,
        chunk_ordinal=ordinal,
        text=text,
        checksum_sha256="c" * 64,
        language="en",
        extraction_quality="good",
        page_number=1,
        section_heading=None,
        is_suspicious=False,
        guardrail_flags=(),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
    )


def make_clause(clause_id: str, title: str, search_term: str) -> ClauseDefinition:
    return ClauseDefinition(
        clause_id=clause_id,
        title=title,
        priority="high",
        description=f"Review {title}.",
        search_terms=(search_term,),
        retrieval_queries=(f"Find {search_term} wording.",),
        rules=(
            ClauseRule(
                rule_id=f"{clause_id}_rule",
                type="legal_requirement",
                severity="high",
                text=f"{title} must be clear.",
                recommendation=f"Flag unclear {title}.",
                expected_offer_evidence=(search_term,),
                citations=(RuleCitation(source_id="uae_law", reference="Article 1"),),
            ),
        ),
    )


def make_rule_base() -> RuleBase:
    return RuleBase(
        schema_version="1",
        rule_base_id="rules",
        title="Rules",
        jurisdiction="UAE",
        retrieved_on="2026-07-03",
        limitations=(),
        sources=(
            RuleSource(
                source_id="uae_law",
                title="Law",
                publisher="Publisher",
                url="https://example.test",
                retrieved_on="2026-07-03",
                notes="Test",
            ),
        ),
        clauses=(
            make_clause("probation_period", "Probation period", "probation"),
            make_clause("notice_period", "Notice period", "notice"),
        ),
    )


@pytest.mark.asyncio
async def test_build_ragas_rows_covers_every_offer_and_clause(monkeypatch) -> None:
    offer_cases = (
        ragas_offer_review.OfferCase(
            filename="offer_a.pdf",
            path=Path("offer_a.pdf"),
            case_summary="A",
            expected_outcomes={"probation_period": "risk", "*": "not_primary_fixture_focus"},
        ),
        ragas_offer_review.OfferCase(
            filename="offer_b.pdf",
            path=Path("offer_b.pdf"),
            case_summary="B",
            expected_outcomes={"notice_period": "missing", "*": "not_primary_fixture_focus"},
        ),
    )

    def extract_offer_chunks(*_: object, **__: object) -> tuple[StoredDocumentChunk, ...]:
        return (
            make_chunk("The probation period is eight months.", 0),
            make_chunk("The notice period is 15 days.", 1),
        )

    monkeypatch.setattr(ragas_offer_review, "extract_offer_chunks", extract_offer_chunks)

    rows = await ragas_offer_review.build_ragas_rows(
        rule_base=make_rule_base(),
        offer_cases=offer_cases,
        retrieval_limit=1,
        answer_mode="reference",
        settings=None,
        chunk_target_chars=1200,
        chunk_overlap_chars=180,
        retriever_mode="lexical",
    )

    assert len(rows) == 4
    assert {row["sample_id"] for row in rows} == {
        "offer_a:probation_period",
        "offer_a:notice_period",
        "offer_b:probation_period",
        "offer_b:notice_period",
    }
    assert rows[0]["expected_outcome"] == "risk"
    assert rows[0]["contexts"] == ["The probation period is eight months."]
    assert rows[0]["question"].startswith("Review offer_a.pdf")
    assert rows[0]["answer"] == rows[0]["reference"]


@pytest.mark.asyncio
async def test_build_ragas_rows_uses_fixture_specific_ground_truth(monkeypatch) -> None:
    offer_cases = (
        ragas_offer_review.OfferCase(
            filename="offer_a.pdf",
            path=Path("offer_a.pdf"),
            case_summary="A",
            expected_outcomes={"probation_period": "risk", "*": "not_primary_fixture_focus"},
            ground_truth={
                "probation_period": {
                    "reference": "Fixture-specific probation reference.",
                    "required_offer_evidence": ["probation period is eight months"],
                }
            },
        ),
    )

    def extract_offer_chunks(*_: object, **__: object) -> tuple[StoredDocumentChunk, ...]:
        return (make_chunk("The probation period is eight months.", 0),)

    monkeypatch.setattr(ragas_offer_review, "extract_offer_chunks", extract_offer_chunks)

    rows = await ragas_offer_review.build_ragas_rows(
        rule_base=make_rule_base(),
        offer_cases=offer_cases,
        retrieval_limit=1,
        answer_mode="reference",
        settings=None,
        chunk_target_chars=1200,
        chunk_overlap_chars=180,
        retriever_mode="lexical",
    )

    assert rows[0]["reference"] == "Fixture-specific probation reference."
    assert rows[0]["ground_truth"] == "Fixture-specific probation reference."
    assert rows[0]["expected_evidence"] == ["probation period is eight months"]


def test_sample_offer_expected_outcomes_manifest_matches_fixture_pdfs() -> None:
    offer_cases = ragas_offer_review.load_offer_cases(
        ragas_offer_review.DEFAULT_DATASET_DIR,
        ragas_offer_review.DEFAULT_EXPECTED_OUTCOMES,
    )

    assert len(offer_cases) == 8
    assert {case.filename for case in offer_cases} == {
        path.name for path in ragas_offer_review.DEFAULT_DATASET_DIR.glob("*.pdf")
    }
    assert all(case.expected_outcomes for case in offer_cases)
    compliant_case = next(
        case
        for case in offer_cases
        if case.filename == "01_mainland_software_engineer_compliant.pdf"
    )
    assert compliant_case.ground_truth["probation_period"]["expected_outcome"] == "acceptable"


def test_real_rule_base_and_fixture_manifest_cover_all_criteria() -> None:
    rule_base = ragas_offer_review.load_rule_base()
    offer_cases = ragas_offer_review.load_offer_cases(
        ragas_offer_review.DEFAULT_DATASET_DIR,
        ragas_offer_review.DEFAULT_EXPECTED_OUTCOMES,
    )

    row_count = len(rule_base.clauses) * len(offer_cases)

    assert row_count == 104
    assert {clause.clause_id for clause in rule_base.clauses} >= {
        "probation_period",
        "notice_period",
        "salary_and_compensation",
        "working_hours",
        "annual_leave",
        "sick_leave",
        "termination",
        "end_of_service_gratuity",
        "non_compete_restrictive_covenants",
        "confidentiality",
        "governing_law_jurisdiction",
        "visa_sponsorship_employment_eligibility",
        "missing_unclear_mandatory_terms",
    }
