from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services.documents import (
    document_record_query,
    to_document_record,
    update_review_job_status,
)


def test_document_record_query_orders_newest_first() -> None:
    query_sql = str(document_record_query())

    assert "JOIN review_jobs ON review_jobs.document_id = documents.id" in query_sql
    assert "ORDER BY documents.created_at DESC" in query_sql


def test_to_document_record_maps_document_and_job_rows() -> None:
    document = SimpleNamespace(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        original_filename="offer.txt",
        media_type="text/plain",
        size_bytes=5,
        checksum_sha256="checksum",
        original_storage_key="documents/111/original.txt",
        upload_status="stored",
        created_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
    )
    review_job = SimpleNamespace(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        status="queued",
    )

    record = to_document_record(document, review_job)

    assert record.document_id == document.id
    assert record.job_id == review_job.id
    assert record.original_filename == "offer.txt"
    assert record.review_job_status == "queued"
    assert record.report_status == "not_started"
    assert record.report_storage_key is None


@pytest.mark.asyncio
async def test_update_review_job_status_persists_transition(monkeypatch) -> None:
    executed: list[object] = []

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def execute(self, statement: object) -> None:
            executed.append(statement)

        async def commit(self) -> None:
            executed.append("commit")

    class FakeSessionFactory:
        def __call__(self) -> FakeSession:
            return FakeSession()

    def async_sessionmaker(_: object, **__: object) -> FakeSessionFactory:
        return FakeSessionFactory()

    monkeypatch.setattr("app.services.documents.async_sessionmaker", async_sessionmaker)

    await update_review_job_status(
        SimpleNamespace(),
        UUID("22222222-2222-2222-2222-222222222222"),
        "processing",
    )

    assert "UPDATE review_jobs SET status=:status" in str(executed[0])
    assert executed[1] == "commit"
