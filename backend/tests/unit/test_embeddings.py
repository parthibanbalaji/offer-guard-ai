from typing import Any

import pytest

from app.core.config import Settings
from app.rag import embeddings
from app.rag.embeddings import EmbeddingProviderError, create_embedding_model


def make_settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:password@db.example.test:5432/offerguard",
        **overrides,
    )


class ProviderStatusError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_create_embedding_model_configures_openrouter(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeOpenAIEmbeddingModel:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(embeddings, "OpenAIEmbeddingModel", FakeOpenAIEmbeddingModel)

    model = create_embedding_model(
        make_settings(
            openrouter_api_key="openrouter-key",
            embedding_timeout_seconds=12,
            embedding_max_retries=4,
            embedding_retry_min_seconds=1,
            embedding_retry_max_seconds=8,
        )
    )

    assert isinstance(model, FakeOpenAIEmbeddingModel)
    assert calls == [
        {
            "model": "openai/text-embedding-3-small",
            "dimensions": 1536,
            "api_key": "openrouter-key",
            "base_url": "https://openrouter.ai/api/v1",
            "timeout_seconds": 12,
            "max_retries": 4,
            "retry_min_seconds": 1,
            "retry_max_seconds": 8,
        }
    ]


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (ProviderStatusError("rate limit", 429), "rate_limited"),
        (ProviderStatusError("credits", 402), "quota_exceeded"),
        (RuntimeError("insufficient credits"), "quota_exceeded"),
        (RuntimeError("network down"), "provider_error"),
    ],
)
def test_classify_embedding_exception(exc: Exception, kind: str) -> None:
    error = embeddings.classify_embedding_exception(exc)

    assert isinstance(error, EmbeddingProviderError)
    assert error.kind == kind
