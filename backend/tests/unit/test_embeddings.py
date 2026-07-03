from typing import Any

import pytest

from app.core.config import Settings
from app.rag import embeddings
from app.rag.embeddings import (
    CachedEmbeddingModel,
    EmbeddingProviderError,
    create_cached_embedding_model,
    create_embedding_model,
)


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


@pytest.mark.asyncio
async def test_cached_embedding_model_embeds_each_text_once() -> None:
    calls: list[list[str]] = []

    class Inner:
        async def embed_texts(self, texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[float(len(text))] for text in texts]

    model = CachedEmbeddingModel(Inner(), namespace="test-cache")

    assert await model.embed_texts(["alpha", "beta", "alpha"]) == [[5.0], [4.0], [5.0]]
    assert await model.embed_texts(["beta", "gamma"]) == [[4.0], [5.0]]
    assert calls == [["alpha", "beta"], ["gamma"]]


def test_create_cached_embedding_model_uses_model_specific_namespace(monkeypatch) -> None:
    class FakeEmbeddingModel:
        async def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[1.0] for _ in texts]

    monkeypatch.setattr(embeddings, "create_embedding_model", lambda _: FakeEmbeddingModel())

    model = create_cached_embedding_model(
        make_settings(embedding_model="test-model", embedding_dimensions=12),
        namespace="report-retrieval",
    )

    assert isinstance(model, CachedEmbeddingModel)
    assert model.namespace == (
        "report-retrieval|openai|test-model|https://openrouter.ai/api/v1|12"
    )


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
