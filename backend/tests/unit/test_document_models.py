from sqlalchemy import inspect

from app.db.models import (
    Document,
    DocumentUploadStatus,
    ReviewJob,
    ReviewJobStatus,
)


def test_document_model_records_original_file_storage_metadata() -> None:
    mapper = inspect(Document)
    columns = mapper.columns

    assert mapper.local_table.name == "documents"
    assert set(columns.keys()) == {
        "id",
        "original_filename",
        "media_type",
        "size_bytes",
        "checksum_sha256",
        "original_storage_key",
        "upload_status",
        "created_at",
        "updated_at",
    }
    assert not columns["original_filename"].nullable
    assert not columns["media_type"].nullable
    assert not columns["size_bytes"].nullable
    assert not columns["checksum_sha256"].nullable
    assert columns["checksum_sha256"].unique
    assert not columns["original_storage_key"].nullable
    assert columns["original_storage_key"].unique
    assert not columns["upload_status"].nullable


def test_review_job_model_is_linked_to_document_and_queued_first() -> None:
    mapper = inspect(ReviewJob)
    columns = mapper.columns

    assert mapper.local_table.name == "review_jobs"
    assert set(columns.keys()) == {
        "id",
        "document_id",
        "status",
        "created_at",
        "updated_at",
    }
    assert not columns["document_id"].nullable
    assert not columns["status"].nullable
    assert list(columns["document_id"].foreign_keys)[0].target_fullname == "documents.id"

    assert DocumentUploadStatus.STORED.value == "stored"
    assert ReviewJobStatus.QUEUED.value == "queued"
