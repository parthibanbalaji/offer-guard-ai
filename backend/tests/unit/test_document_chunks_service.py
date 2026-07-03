from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.rag.chunking import DocumentChunk
from app.services import document_chunks
from app.services.document_chunks import (
    replace_document_chunks,
    to_chunk_row,
    to_stored_chunk,
)

DOCUMENT_ID = UUID("11111111-1111-1111-1111-111111111111")


def make_chunk() -> DocumentChunk:
    return DocumentChunk(
        document_id=DOCUMENT_ID,
        chunk_ordinal=3,
        text="Probation period is six months.",
        checksum_sha256="a" * 64,
        language="en",
        extraction_quality="good",
        page_number=2,
        section_heading="Probation",
        is_suspicious=True,
        guardrail_flags=("prompt_injection_signal",),
    )


def test_to_chunk_row_maps_chunk_metadata() -> None:
    row = to_chunk_row(make_chunk())

    assert row.document_id == DOCUMENT_ID
    assert row.chunk_ordinal == 3
    assert row.text == "Probation period is six months."
    assert row.page_number == 2
    assert row.section_heading == "Probation"
    assert row.is_suspicious is True
    assert row.guardrail_flags == ["prompt_injection_signal"]


def test_to_stored_chunk_maps_row_to_read_model() -> None:
    row = SimpleNamespace(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        document_id=DOCUMENT_ID,
        chunk_ordinal=0,
        text="Salary is AED 10,000.",
        checksum_sha256="b" * 64,
        language="en",
        extraction_quality="good",
        page_number=None,
        section_heading=None,
        is_suspicious=False,
        guardrail_flags=[],
        created_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
    )

    stored = to_stored_chunk(row)

    assert stored.document_id == DOCUMENT_ID
    assert stored.guardrail_flags == ()
    assert stored.text == "Salary is AED 10,000."


@pytest.mark.asyncio
async def test_replace_document_chunks_deletes_existing_rows_and_commits(monkeypatch) -> None:
    executed: list[object] = []
    added: list[object] = []

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def execute(self, statement: object) -> None:
            executed.append(statement)

        def add_all(self, rows: list[object]) -> None:
            added.extend(rows)

        async def commit(self) -> None:
            executed.append("commit")

    class FakeSessionFactory:
        def __call__(self) -> FakeSession:
            return FakeSession()

    def async_sessionmaker(_: object, **__: object) -> FakeSessionFactory:
        return FakeSessionFactory()

    monkeypatch.setattr(document_chunks, "async_sessionmaker", async_sessionmaker)

    count = await replace_document_chunks(SimpleNamespace(), DOCUMENT_ID, (make_chunk(),))

    assert count == 1
    assert "DELETE FROM document_chunks" in str(executed[0])
    assert len(added) == 1
    assert added[0].document_id == DOCUMENT_ID
    assert executed[1] == "commit"
