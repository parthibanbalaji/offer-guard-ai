"""Validated runtime settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration supplied through environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="OFFERGUARD_",
        extra="ignore",
    )

    app_name: str = "OfferGuard API"
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = False
    docs_enabled: bool = True
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    allowed_upload_extensions: str = ".txt,.md,.markdown,.pdf"
    rule_base_path: str = "/app/knowledge_base/uae_employment_rules.v1.json"

    database_url: SecretStr
    vector_store: Literal["weaviate", "pgvector"] = "weaviate"
    vector_host: str = "weaviate"
    vector_http_port: int = 8080
    vector_grpc_port: int = 50051
    startup_check_timeout_seconds: float = Field(default=5.0, gt=0)
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: SecretStr = SecretStr("offerguard")
    s3_secret_key: SecretStr = SecretStr("offerguard-local-secret")
    s3_bucket: str = "offer-documents"
    chunk_target_chars: int = Field(default=1200, gt=0)
    chunk_overlap_chars: int = Field(default=180, ge=0)
    embedding_provider: Literal["hash", "openai"] = "openai"
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_base_url: str = "https://openrouter.ai/api/v1"
    embedding_dimensions: int = Field(default=1536, gt=0)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0)
    embedding_max_retries: int = Field(default=3, ge=0)
    embedding_retry_min_seconds: int = Field(default=2, ge=0)
    embedding_retry_max_seconds: int = Field(default=20, ge=0)
    openrouter_api_key: SecretStr | None = None

    @property
    def allowed_upload_extension_set(self) -> frozenset[str]:
        """Return normalized supported upload filename extensions."""
        extensions: list[str] = []
        for value in self.allowed_upload_extensions.split(","):
            extension = value.strip().lower()
            if not extension:
                continue
            if not extension.startswith("."):
                extension = f".{extension}"
            extensions.append(extension)

        return frozenset(extensions)


@lru_cache
def get_settings() -> Settings:
    """Return one settings instance per process."""
    return Settings()
