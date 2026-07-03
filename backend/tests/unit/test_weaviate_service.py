from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from app.core.config import Settings
from app.rag.chunking import DocumentChunk
from app.services import weaviate as weaviate_service
from app.services.weaviate import WeaviateNotReadyError


def test_create_weaviate_client_uses_configured_host_and_ports(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:password@db.example.test:5432/offerguard",
        vector_host="vectors.example.test",
        vector_http_port=18080,
        vector_grpc_port=15051,
    )
    calls: list[dict[str, Any]] = []
    client = object()

    def connect_to_custom(**kwargs: Any) -> object:
        calls.append(kwargs)
        return client

    monkeypatch.setattr(weaviate_service.weaviate, "connect_to_custom", connect_to_custom)

    assert weaviate_service.create_weaviate_client(settings) is client
    assert calls == [
        {
            "http_host": "vectors.example.test",
            "http_port": 18080,
            "http_secure": False,
            "grpc_host": "vectors.example.test",
            "grpc_port": 15051,
            "grpc_secure": False,
            "skip_init_checks": True,
        }
    ]


@pytest.mark.asyncio
async def test_check_weaviate_raises_when_client_is_not_ready() -> None:
    class Client:
        def is_ready(self) -> bool:
            return False

    with pytest.raises(WeaviateNotReadyError):
        await weaviate_service.check_weaviate(Client())


@pytest.mark.asyncio
async def test_index_document_chunks_embeds_and_batches_objects() -> None:
    class Embeddings:
        async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
            assert texts == ["Offer chunk"]
            return [[0.1, 0.2, 0.3]]

    class Batch:
        def __init__(self) -> None:
            self.objects: list[dict[str, Any]] = []

        def dynamic(self) -> "Batch":
            return self

        def __enter__(self) -> "Batch":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def add_object(self, **kwargs: Any) -> None:
            self.objects.append(kwargs)

    class Collection:
        def __init__(self) -> None:
            self.batch = Batch()

    class Collections:
        def __init__(self) -> None:
            self.collection = Collection()

        def exists(self, name: str) -> bool:
            assert name == weaviate_service.CHUNK_COLLECTION
            return True

        def get(self, name: str) -> Collection:
            assert name == weaviate_service.CHUNK_COLLECTION
            return self.collection

    class Client:
        def __init__(self) -> None:
            self.collections = Collections()

    client = Client()
    chunk = DocumentChunk(
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        chunk_ordinal=0,
        text="Offer chunk",
        checksum_sha256="a" * 64,
        language="en",
        extraction_quality="good",
        page_number=1,
        section_heading="Compensation",
        is_suspicious=False,
        guardrail_flags=(),
    )

    count = await weaviate_service.index_document_chunks(client, (chunk,), Embeddings())

    assert count == 1
    assert client.collections.collection.batch.objects == [
        {
            "uuid": weaviate_service.chunk_object_id(chunk),
            "properties": {
                "document_id": "11111111-1111-1111-1111-111111111111",
                "chunk_ordinal": 0,
                "text": "Offer chunk",
                "checksum_sha256": "a" * 64,
                "language": "en",
                "extraction_quality": "good",
                "page_number": 1,
                "section_heading": "Compensation",
                "is_suspicious": False,
                "guardrail_flags": [],
            },
            "vector": [0.1, 0.2, 0.3],
        }
    ]


@pytest.mark.asyncio
async def test_search_document_chunk_ordinals_embeds_query_and_filters_by_document() -> None:
    class Embeddings:
        async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
            assert texts == ["probation period notice"]
            return [[0.4, 0.5, 0.6]]

    class Query:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def near_vector(self, **kwargs: Any) -> SimpleNamespace:
            self.calls.append(kwargs)
            return SimpleNamespace(
                objects=[
                    SimpleNamespace(
                        properties={"chunk_ordinal": 2},
                        metadata=SimpleNamespace(distance=0.12),
                    ),
                    SimpleNamespace(
                        properties={"chunk_ordinal": 5},
                        metadata=SimpleNamespace(distance=0.22),
                    ),
                ]
            )

    class Collection:
        def __init__(self) -> None:
            self.query = Query()

    class Collections:
        def __init__(self) -> None:
            self.collection = Collection()

        def exists(self, name: str) -> bool:
            assert name == weaviate_service.CHUNK_COLLECTION
            return True

        def get(self, name: str) -> Collection:
            assert name == weaviate_service.CHUNK_COLLECTION
            return self.collection

    class Client:
        def __init__(self) -> None:
            self.collections = Collections()

    client = Client()

    matches = await weaviate_service.search_document_chunk_ordinals(
        client,
        document_id=UUID("11111111-1111-1111-1111-111111111111"),
        query_text="probation period notice",
        embedding_model=Embeddings(),
        limit=2,
    )

    assert [match.chunk_ordinal for match in matches] == [2, 5]
    assert [match.distance for match in matches] == [0.12, 0.22]
    assert client.collections.collection.query.calls[0]["near_vector"] == [0.4, 0.5, 0.6]
    assert client.collections.collection.query.calls[0]["limit"] == 2
    assert client.collections.collection.query.calls[0]["return_properties"] == ["chunk_ordinal"]
