"""Embedding interfaces and local deterministic fallback."""

from collections.abc import Sequence
from hashlib import blake2b
from typing import Any, Protocol

from app.core.config import Settings
from app.observability.tracing import (
    process_embedding_inputs,
    process_embedding_outputs,
    traceable,
)


class EmbeddingModel(Protocol):
    """Embeds text for vector indexing."""

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one vector per text."""


class EmbeddingProviderError(RuntimeError):
    """Raised when the configured embedding provider cannot embed text."""

    def __init__(self, message: str, *, kind: str = "provider_error") -> None:
        super().__init__(message)
        self.kind = kind


_EMBEDDING_CACHE: dict[tuple[str, str], tuple[float, ...]] = {}


class OpenAIEmbeddingModel:
    """LangChain OpenAI-compatible embedding adapter for production retrieval."""

    def __init__(
        self,
        *,
        model: str,
        dimensions: int,
        api_key: str | None,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
        retry_min_seconds: int,
        retry_max_seconds: int,
    ) -> None:
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError as exc:  # pragma: no cover - depends on runtime install
            msg = "OpenAI embeddings require langchain-openai"
            raise RuntimeError(msg) from exc

        kwargs: dict[str, Any] = {
            "model": model,
            "dimensions": dimensions,
            "base_url": base_url,
            "timeout": timeout_seconds,
            "max_retries": max_retries,
            "retry_min_seconds": retry_min_seconds,
            "retry_max_seconds": retry_max_seconds,
        }
        if api_key is not None:
            kwargs["api_key"] = api_key
        self._embeddings = OpenAIEmbeddings(**kwargs)

    @traceable(
        name="OpenRouterEmbeddings",
        run_type="embedding",
        process_inputs=process_embedding_inputs,
        process_outputs=process_embedding_outputs,
    )
    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return embedding vectors through LangChain with provider error mapping."""
        try:
            return await self._embeddings.aembed_documents(list(texts))
        except Exception as exc:
            raise classify_embedding_exception(exc) from exc


class HashEmbeddingModel:
    """Deterministic non-semantic embedding fallback for local development and tests."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    @traceable(
        name="HashEmbeddings",
        run_type="embedding",
        process_inputs=process_embedding_inputs,
        process_outputs=process_embedding_outputs,
    )
    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return stable pseudo-embeddings without calling a model service."""
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        buckets = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            buckets[bucket] += sign

        magnitude = sum(value * value for value in buckets) ** 0.5
        if magnitude == 0:
            return buckets
        return [value / magnitude for value in buckets]


class CachedEmbeddingModel:
    """Caches deterministic embedding requests by namespace and exact text."""

    def __init__(self, inner: EmbeddingModel, *, namespace: str) -> None:
        self.inner = inner
        self.namespace = namespace

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return cached vectors, embedding only missing texts."""
        missing_texts: list[str] = []
        missing_keys: list[tuple[str, str]] = []
        for text in texts:
            key = (self.namespace, text)
            if key in _EMBEDDING_CACHE or key in missing_keys:
                continue
            missing_texts.append(text)
            missing_keys.append(key)

        if missing_texts:
            vectors = await self.inner.embed_texts(missing_texts)
            for key, vector in zip(missing_keys, vectors, strict=True):
                _EMBEDDING_CACHE[key] = tuple(vector)

        return [list(_EMBEDDING_CACHE[(self.namespace, text)]) for text in texts]


def create_embedding_model(settings: Settings) -> EmbeddingModel:
    """Create the configured embedding model."""
    if settings.embedding_provider == "openai":
        configured_api_key = (
            settings.openrouter_api_key.get_secret_value()
            if settings.openrouter_api_key is not None
            else None
        )
        api_key = configured_api_key or None
        return OpenAIEmbeddingModel(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            api_key=api_key,
            base_url=settings.embedding_base_url,
            timeout_seconds=settings.embedding_timeout_seconds,
            max_retries=settings.embedding_max_retries,
            retry_min_seconds=settings.embedding_retry_min_seconds,
            retry_max_seconds=settings.embedding_retry_max_seconds,
        )

    return HashEmbeddingModel(settings.embedding_dimensions)


def create_cached_embedding_model(settings: Settings, *, namespace: str) -> EmbeddingModel:
    """Create an embedding model with a process-local cache."""
    return CachedEmbeddingModel(
        create_embedding_model(settings),
        namespace=embedding_cache_namespace(settings, namespace),
    )


def embedding_cache_namespace(settings: Settings, namespace: str) -> str:
    """Return a model-specific cache namespace without including secrets."""
    return "|".join(
        (
            namespace,
            settings.embedding_provider,
            settings.embedding_model,
            settings.embedding_base_url,
            str(settings.embedding_dimensions),
        )
    )


def classify_embedding_exception(exc: Exception) -> EmbeddingProviderError:
    """Map provider exceptions into user-facing failure categories."""
    status_code = getattr(exc, "status_code", None)
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()

    if status_code == 429 or "rate limit" in lowered or "too many requests" in lowered:
        return EmbeddingProviderError(
            "Embedding provider rate limit reached. Try again later.",
            kind="rate_limited",
        )

    if (
        status_code == 402
        or "insufficient_quota" in lowered
        or "insufficient quota" in lowered
        or "insufficient credits" in lowered
        or "usage limit" in lowered
        or "quota" in lowered
    ):
        return EmbeddingProviderError(
            "Embedding provider quota or credits are exhausted.",
            kind="quota_exceeded",
        )

    return EmbeddingProviderError(
        f"Embedding provider request failed: {message}",
        kind="provider_error",
    )
