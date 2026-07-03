from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.guardrails.input import GuardrailFinding
from app.rag.embeddings import EmbeddingProviderError
from app.rag.pipeline import DocumentIndexingResult
from app.services.document_chunks import StoredDocumentChunk
from app.services.documents import DocumentRecord
from app.services.uploads import PreparedUpload, StoredDocumentUpload
from app.workflows.document_review import DocumentReviewRunResult


def configure_test_app(monkeypatch, settings: Settings) -> tuple[FastAPI, Any]:
    monkeypatch.setenv(
        "OFFERGUARD_DATABASE_URL",
        "postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
    )
    from app.main import app

    resources = SimpleNamespace(
        postgres_engine=object(),
        storage_client=object(),
        weaviate_client=object(),
    )

    def create_app_resources(_: Settings) -> object:
        return resources

    async def check_startup_dependencies(_: Settings, checked_resources: object) -> None:
        assert checked_resources is resources

    async def close_app_resources(closed_resources: object) -> None:
        assert closed_resources is resources
        return None

    monkeypatch.setattr("app.main.create_app_resources", create_app_resources)
    monkeypatch.setattr("app.main.check_startup_dependencies", check_startup_dependencies)
    monkeypatch.setattr("app.main.close_app_resources", close_app_resources)
    app.dependency_overrides[get_settings] = lambda: settings

    return app, resources


def test_upload_document_accepts_supported_file_extension(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
        max_upload_bytes=1024,
        allowed_upload_extensions=".txt,.md",
    )
    app, _ = configure_test_app(monkeypatch, settings)

    async def store_prepared_upload(
        prepared_upload: PreparedUpload,
        _: Settings,
        __: object,
        ___: object,
    ) -> StoredDocumentUpload:
        assert prepared_upload.original_filename == "offer.txt"
        assert prepared_upload.media_type == "text/plain"
        assert prepared_upload.size_bytes == 5
        return StoredDocumentUpload(
            document_id=UUID("11111111-1111-1111-1111-111111111111"),
            job_id=UUID("22222222-2222-2222-2222-222222222222"),
            original_filename=prepared_upload.original_filename,
            media_type=prepared_upload.media_type,
            size_bytes=prepared_upload.size_bytes,
            checksum_sha256=prepared_upload.checksum_sha256,
            original_storage_key="documents/11111111-1111-1111-1111-111111111111/original.txt",
            upload_status="stored",
            review_job_status="queued",
        )

    monkeypatch.setattr(
        "app.api.v1.routes.documents.store_prepared_upload",
        store_prepared_upload,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("offer.txt", b"hello", "text/plain")},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json() == {
        "document_id": "11111111-1111-1111-1111-111111111111",
        "job_id": "22222222-2222-2222-2222-222222222222",
        "original_filename": "offer.txt",
        "media_type": "text/plain",
        "size_bytes": 5,
        "checksum_sha256": ("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"),
        "original_storage_key": ("documents/11111111-1111-1111-1111-111111111111/original.txt"),
        "upload_status": "stored",
        "review_job_status": "queued",
    }


def test_upload_document_rejects_unsupported_file_extension(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
        max_upload_bytes=1024,
        allowed_upload_extensions=".txt",
    )
    app, _ = configure_test_app(monkeypatch, settings)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("offer.exe", b"hello", "application/octet-stream")},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 415
    assert response.json() == {"detail": "unsupported file extension"}


def test_upload_document_rejects_file_larger_than_configured_limit(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
        max_upload_bytes=4,
        allowed_upload_extensions=".txt",
    )
    app, _ = configure_test_app(monkeypatch, settings)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/documents",
            files={"file": ("offer.txt", b"hello", "text/plain")},
        )

    app.dependency_overrides.clear()
    assert response.status_code == 413
    assert response.json() == {"detail": "file is too large"}


def test_list_documents_returns_stored_documents(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
    )
    app, _ = configure_test_app(monkeypatch, settings)

    async def list_document_records(_: object) -> list[DocumentRecord]:
        return [
            DocumentRecord(
                document_id=UUID("11111111-1111-1111-1111-111111111111"),
                job_id=UUID("22222222-2222-2222-2222-222222222222"),
                original_filename="offer.txt",
                media_type="text/plain",
                size_bytes=5,
                checksum_sha256="checksum",
                original_storage_key="documents/111/original.txt",
                upload_status="stored",
                review_job_status="queued",
                created_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
            )
        ]

    monkeypatch.setattr(
        "app.api.v1.routes.documents.list_document_records",
        list_document_records,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/documents")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == [
        {
            "document_id": "11111111-1111-1111-1111-111111111111",
            "job_id": "22222222-2222-2222-2222-222222222222",
            "original_filename": "offer.txt",
            "media_type": "text/plain",
            "size_bytes": 5,
            "checksum_sha256": "checksum",
            "upload_status": "stored",
            "review_job_status": "queued",
            "created_at": "2026-07-01T12:00:00Z",
        }
    ]


def test_download_document_streams_original_file(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
    )
    app, _ = configure_test_app(monkeypatch, settings)

    async def get_document_record(_: object, document_id: UUID) -> DocumentRecord | None:
        assert document_id == UUID("11111111-1111-1111-1111-111111111111")
        return DocumentRecord(
            document_id=document_id,
            job_id=UUID("22222222-2222-2222-2222-222222222222"),
            original_filename="offer.txt",
            media_type="text/plain",
            size_bytes=5,
            checksum_sha256="checksum",
            original_storage_key="documents/111/original.txt",
            upload_status="stored",
            review_job_status="queued",
            created_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        )

    async def get_file_object(_: object, bucket: str, key: str) -> dict[str, BytesIO]:
        assert bucket == "offer-documents"
        assert key == "documents/111/original.txt"
        return {"Body": BytesIO(b"hello")}

    monkeypatch.setattr(
        "app.api.v1.routes.documents.get_document_record",
        get_document_record,
    )
    monkeypatch.setattr("app.api.v1.routes.documents.get_file_object", get_file_object)

    with TestClient(app) as client:
        response = client.get("/api/v1/documents/11111111-1111-1111-1111-111111111111/download")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.content == b"hello"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"] == ("attachment; filename*=UTF-8''offer.txt")


def test_download_document_returns_404_when_missing(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
    )
    app, _ = configure_test_app(monkeypatch, settings)

    async def get_document_record(_: object, __: UUID) -> DocumentRecord | None:
        return None

    monkeypatch.setattr(
        "app.api.v1.routes.documents.get_document_record",
        get_document_record,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/documents/11111111-1111-1111-1111-111111111111/download")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json() == {"detail": "document not found"}


def test_prepare_document_for_review_runs_manual_processing(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
    )
    app, resources = configure_test_app(monkeypatch, settings)
    record = DocumentRecord(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        job_id=UUID("22222222-2222-2222-2222-222222222222"),
        original_filename="offer.txt",
        media_type="text/plain",
        size_bytes=5,
        checksum_sha256="checksum",
        original_storage_key="documents/111/original.txt",
        upload_status="stored",
        review_job_status="queued",
        created_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
    )

    async def prepare_document_review_run(**kwargs: object) -> DocumentReviewRunResult:
        assert kwargs["document_id"] == UUID("11111111-1111-1111-1111-111111111111")
        assert kwargs["postgres_engine"] is resources.postgres_engine
        assert kwargs["storage_client"] is resources.storage_client
        assert kwargs["weaviate_client"] is resources.weaviate_client
        return DocumentReviewRunResult(
            document=record,
            rule_base=None,
            review_job_status="completed",
            indexing_result=DocumentIndexingResult(
                document_id=record.document_id,
                chunk_count=2,
                stored_count=2,
                indexed_count=2,
                findings=(
                    GuardrailFinding(
                        code="prompt_injection_signal",
                        message="flagged",
                    ),
                ),
                chunks=(),
            ),
            guardrail_flags=("prompt_injection_signal",),
        )

    monkeypatch.setattr(
        "app.api.v1.routes.documents.prepare_document_review_run",
        prepare_document_review_run,
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/documents/11111111-1111-1111-1111-111111111111/prepare")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "document_id": "11111111-1111-1111-1111-111111111111",
        "job_id": "22222222-2222-2222-2222-222222222222",
        "review_job_status": "completed",
        "chunk_count": 2,
        "stored_count": 2,
        "indexed_count": 2,
        "guardrail_flags": ["prompt_injection_signal"],
    }


def test_prepare_document_for_review_returns_404_when_missing(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
    )
    app, _ = configure_test_app(monkeypatch, settings)

    async def prepare_document_review_run(**_: object) -> DocumentReviewRunResult:
        from app.rag.pipeline import DocumentIndexingError

        raise DocumentIndexingError("document not found: 11111111-1111-1111-1111-111111111111")

    monkeypatch.setattr(
        "app.api.v1.routes.documents.prepare_document_review_run",
        prepare_document_review_run,
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/documents/11111111-1111-1111-1111-111111111111/prepare")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json() == {
        "detail": "document not found: 11111111-1111-1111-1111-111111111111"
    }


def test_list_document_chunks_returns_auditable_rows(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
    )
    app, resources = configure_test_app(monkeypatch, settings)
    document_id = UUID("11111111-1111-1111-1111-111111111111")
    record = DocumentRecord(
        document_id=document_id,
        job_id=UUID("22222222-2222-2222-2222-222222222222"),
        original_filename="offer.pdf",
        media_type="application/pdf",
        size_bytes=5000,
        checksum_sha256="checksum",
        original_storage_key="documents/111/original.pdf",
        upload_status="stored",
        review_job_status="completed",
        created_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
    )

    async def get_document_record(_: object, requested_id: UUID) -> DocumentRecord:
        assert requested_id == document_id
        return record

    async def list_document_chunks(_: object, requested_id: UUID) -> list[StoredDocumentChunk]:
        assert requested_id == document_id
        assert resources.postgres_engine
        return [
            StoredDocumentChunk(
                id=UUID("33333333-3333-3333-3333-333333333333"),
                document_id=document_id,
                chunk_ordinal=0,
                text="Your probation period is six months.",
                checksum_sha256="a" * 64,
                language="en",
                extraction_quality="good",
                page_number=1,
                section_heading="Probation",
                is_suspicious=False,
                guardrail_flags=(),
                created_at=datetime(2026, 7, 3, 12, 0, tzinfo=UTC),
            )
        ]

    monkeypatch.setattr("app.api.v1.routes.documents.get_document_record", get_document_record)
    monkeypatch.setattr("app.api.v1.routes.documents.list_document_chunks", list_document_chunks)

    with TestClient(app) as client:
        response = client.get(f"/api/v1/documents/{document_id}/chunks")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0] == {
        "id": "33333333-3333-3333-3333-333333333333",
        "document_id": "11111111-1111-1111-1111-111111111111",
        "chunk_ordinal": 0,
        "text": "Your probation period is six months.",
        "checksum_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "language": "en",
        "extraction_quality": "good",
        "page_number": 1,
        "section_heading": "Probation",
        "is_suspicious": False,
        "guardrail_flags": [],
        "created_at": "2026-07-03T12:00:00Z",
    }


def test_prepare_document_for_review_maps_embedding_quota_failure(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
    )
    app, _ = configure_test_app(monkeypatch, settings)

    async def prepare_document_review_run(**_: object) -> DocumentReviewRunResult:
        raise EmbeddingProviderError(
            "Embedding provider quota or credits are exhausted.",
            kind="quota_exceeded",
        )

    monkeypatch.setattr(
        "app.api.v1.routes.documents.prepare_document_review_run",
        prepare_document_review_run,
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/documents/11111111-1111-1111-1111-111111111111/prepare")

    app.dependency_overrides.clear()
    assert response.status_code == 402
    assert response.json() == {"detail": "Embedding provider quota or credits are exhausted."}
