from uuid import UUID

from app.observability.tracing import summarize_chunks, summarize_texts, summarize_vectors
from app.rag.chunking import DocumentChunk


def test_summarize_texts_counts_without_returning_content() -> None:
    summary = summarize_texts(["Salary is AED 10,000.", "Notice is 30 days."])

    assert summary["text_count"] == 2
    assert summary["total_chars"] == 39
    assert summary["estimated_input_tokens"] > 0
    assert "Salary" not in str(summary)


def test_summarize_chunks_redacts_text_by_default() -> None:
    chunk = DocumentChunk(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        chunk_ordinal=3,
        text="Confidential offer text should not be traced by default.",
        checksum_sha256="a" * 64,
        language="en",
        extraction_quality="good",
        page_number=2,
        section_heading="Compensation",
        is_suspicious=False,
        guardrail_flags=(),
    )

    summary = summarize_chunks((chunk,))

    assert summary["chunk_count"] == 1
    assert summary["chunks"][0]["chunk_ordinal"] == 3
    assert summary["chunks"][0]["section_heading"] == "Compensation"
    assert "text" not in summary["chunks"][0]
    assert "Confidential offer text" not in str(summary)


def test_summarize_vectors_hides_values() -> None:
    summary = summarize_vectors(([0.1, 0.2, 0.3],))

    assert summary == {"vector_count": 1, "dimensions": 3}
