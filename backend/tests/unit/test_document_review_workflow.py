from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.config import Settings
from app.guardrails.input import GuardrailFinding
from app.rag.pipeline import DocumentIndexingResult
from app.services.documents import DocumentRecord
from app.workflows import document_review

DOCUMENT_ID = UUID("11111111-1111-1111-1111-111111111111")
JOB_ID = UUID("22222222-2222-2222-2222-222222222222")


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:password@db.example.test:5432/offerguard",
    )


def make_record() -> DocumentRecord:
    return DocumentRecord(
        document_id=DOCUMENT_ID,
        job_id=JOB_ID,
        original_filename="offer.txt",
        media_type="text/plain",
        size_bytes=5,
        checksum_sha256="checksum",
        original_storage_key="documents/111/original.txt",
        upload_status="stored",
        review_job_status="queued",
        report_status="not_started",
        report_storage_key=None,
        report_error_message=None,
        report_generated_at=None,
        created_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_prepare_document_review_run_wraps_status_and_indexing(monkeypatch) -> None:
    record = make_record()
    statuses: list[str] = []

    async def get_document_record(_: object, document_id: UUID) -> DocumentRecord:
        assert document_id == DOCUMENT_ID
        return record

    async def update_review_job_status(_: object, job_id: UUID, review_job_status: str) -> None:
        assert job_id == JOB_ID
        statuses.append(review_job_status)

    async def index_uploaded_document(**kwargs: object) -> DocumentIndexingResult:
        assert kwargs["document_id"] == DOCUMENT_ID
        return DocumentIndexingResult(
            document_id=DOCUMENT_ID,
            chunk_count=2,
            stored_count=2,
            indexed_count=2,
            findings=(GuardrailFinding(code="prompt_injection_signal", message="flagged"),),
            chunks=(),
        )

    monkeypatch.setattr(document_review, "get_document_record", get_document_record)
    monkeypatch.setattr(document_review, "update_review_job_status", update_review_job_status)
    monkeypatch.setattr(document_review, "index_uploaded_document", index_uploaded_document)

    result = await document_review.prepare_document_review_run(
        document_id=DOCUMENT_ID,
        settings=make_settings(),
        postgres_engine=SimpleNamespace(),
        storage_client=SimpleNamespace(),
        weaviate_client=SimpleNamespace(),
        rule_base=None,
    )

    assert statuses == ["processing", "completed"]
    assert result.document == record
    assert result.review_job_status == "completed"
    assert result.guardrail_flags == ("prompt_injection_signal",)


@pytest.mark.asyncio
async def test_prepare_document_review_run_marks_failed_on_error(monkeypatch) -> None:
    record = make_record()
    statuses: list[str] = []

    async def get_document_record(_: object, __: UUID) -> DocumentRecord:
        return record

    async def update_review_job_status(_: object, __: UUID, review_job_status: str) -> None:
        statuses.append(review_job_status)

    async def index_uploaded_document(**_: object) -> DocumentIndexingResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(document_review, "get_document_record", get_document_record)
    monkeypatch.setattr(document_review, "update_review_job_status", update_review_job_status)
    monkeypatch.setattr(document_review, "index_uploaded_document", index_uploaded_document)

    with pytest.raises(RuntimeError, match="boom"):
        await document_review.prepare_document_review_run(
            document_id=DOCUMENT_ID,
            settings=make_settings(),
            postgres_engine=SimpleNamespace(),
            storage_client=SimpleNamespace(),
            weaviate_client=SimpleNamespace(),
            rule_base=None,
        )

    assert statuses == ["processing", "failed"]
