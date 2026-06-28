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


@lru_cache
def get_settings() -> Settings:
    """Return one settings instance per process."""
    return Settings()
