import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_have_safe_local_defaults() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard",
    )

    assert settings.environment == "local"
    assert settings.docs_enabled is True
    assert settings.max_upload_bytes == 10 * 1024 * 1024
    assert settings.allowed_upload_extension_set == frozenset({".txt", ".md", ".markdown", ".pdf"})
    assert (
        settings.database_url.get_secret_value()
        == "postgresql+asyncpg://offerguard:offerguard@postgres:5432/offerguard"
    )
    assert settings.vector_store == "weaviate"
    assert settings.vector_host == "weaviate"
    assert settings.vector_http_port == 8080
    assert settings.vector_grpc_port == 50051
    assert settings.startup_check_timeout_seconds == 5.0


def test_settings_load_postgres_and_weaviate_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "OFFERGUARD_DATABASE_URL",
        "postgresql+asyncpg://user:password@db.example.test:5432/offerguard",
    )
    monkeypatch.setenv("OFFERGUARD_VECTOR_STORE", "weaviate")
    monkeypatch.setenv("OFFERGUARD_VECTOR_HOST", "vectors.example.test")
    monkeypatch.setenv("OFFERGUARD_VECTOR_HTTP_PORT", "18080")
    monkeypatch.setenv("OFFERGUARD_VECTOR_GRPC_PORT", "15051")
    monkeypatch.setenv("OFFERGUARD_STARTUP_CHECK_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("OFFERGUARD_MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("OFFERGUARD_ALLOWED_UPLOAD_EXTENSIONS", "txt, .pdf")

    settings = Settings(_env_file=None)

    assert (
        settings.database_url.get_secret_value()
        == "postgresql+asyncpg://user:password@db.example.test:5432/offerguard"
    )
    assert settings.vector_store == "weaviate"
    assert settings.vector_host == "vectors.example.test"
    assert settings.vector_http_port == 18080
    assert settings.vector_grpc_port == 15051
    assert settings.startup_check_timeout_seconds == 1.5
    assert settings.max_upload_bytes == 1024
    assert settings.allowed_upload_extension_set == frozenset({".txt", ".pdf"})


def test_database_url_is_required() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)
