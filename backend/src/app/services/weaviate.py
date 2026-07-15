"""Weaviate client lifecycle helpers."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import weaviate

from app.core.config import Settings
from app.observability.tracing import process_index_inputs, process_index_outputs, traceable
from app.rag.chunking import DocumentChunk
from app.rag.embeddings import EmbeddingModel

CHUNK_COLLECTION = "OfferDocumentChunk"
EVAL_CHUNK_COLLECTION = "OfferGuardEvalTestChunk"


class WeaviateNotReadyError(RuntimeError):
    """Raised when Weaviate reports that it is not ready."""


@dataclass(frozen=True)
class RetrievedChunkMatch:
    """One semantic retrieval hit from Weaviate."""

    chunk_ordinal: int
    distance: float | None


def create_weaviate_client(settings: Settings) -> Any | None:
    """Create the process-wide Weaviate client."""
    if settings.vector_store != "weaviate":
        return None

    return weaviate.connect_to_custom(
        http_host=settings.vector_host,
        http_port=settings.vector_http_port,
        http_secure=False,
        grpc_host=settings.vector_host,
        grpc_port=settings.vector_grpc_port,
        grpc_secure=False,
        skip_init_checks=True,
    )


async def check_weaviate(client: Any | None) -> None:
    """Verify that the configured Weaviate client is ready."""
    if client is None:
        return

    is_ready = await asyncio.to_thread(client.is_ready)
    if not is_ready:
        msg = "Weaviate client is not ready"
        raise WeaviateNotReadyError(msg)


async def close_weaviate_client(client: Any | None) -> None:
    """Close the Weaviate client."""
    if client is not None:
        client.close()


async def ensure_chunk_collection(client: Any | None) -> None:
    """Create the document chunk collection if Weaviate does not have it yet."""
    await ensure_named_chunk_collection(client, collection_name=CHUNK_COLLECTION)


async def ensure_named_chunk_collection(client: Any | None, *, collection_name: str) -> None:
    """Create a chunk-shaped collection if Weaviate does not have it yet."""
    if client is None:
        return

    await asyncio.to_thread(_ensure_chunk_collection, client, collection_name)


@traceable(
    name="IndexDocumentChunks",
    run_type="tool",
    process_inputs=process_index_inputs,
    process_outputs=process_index_outputs,
)
async def index_document_chunks(
    client: Any | None,
    chunks: Sequence[DocumentChunk],
    embedding_model: EmbeddingModel,
    *,
    collection_name: str = CHUNK_COLLECTION,
) -> int:
    """Embed and store chunks with metadata in Weaviate."""
    if client is None or not chunks:
        return 0

    vectors = await embedding_model.embed_texts([chunk.text for chunk in chunks])
    await ensure_named_chunk_collection(client, collection_name=collection_name)
    await asyncio.to_thread(_index_document_chunks, client, chunks, vectors, collection_name)
    return len(chunks)


async def search_document_chunk_ordinals(
    client: Any | None,
    *,
    document_id: UUID,
    query_text: str,
    embedding_model: EmbeddingModel,
    limit: int,
    collection_name: str = CHUNK_COLLECTION,
) -> tuple[RetrievedChunkMatch, ...]:
    """Return semantically relevant chunk ordinals for one prepared document."""
    if client is None or limit <= 0:
        return ()

    vectors = await embedding_model.embed_texts([query_text])
    if not vectors:
        return ()

    await ensure_named_chunk_collection(client, collection_name=collection_name)
    return await asyncio.to_thread(
        _search_document_chunk_ordinals,
        client,
        document_id,
        vectors[0],
        limit,
        collection_name,
    )


async def list_indexed_document_chunks(
    client: Any | None,
    *,
    document_id: UUID,
    collection_name: str = CHUNK_COLLECTION,
) -> tuple[dict[str, Any], ...]:
    """Return indexed chunk properties for a document from a Weaviate collection."""
    if client is None:
        return ()

    await ensure_named_chunk_collection(client, collection_name=collection_name)
    return await asyncio.to_thread(
        _list_indexed_document_chunks,
        client,
        document_id,
        collection_name,
    )


def _ensure_chunk_collection(client: Any, collection_name: str) -> None:
    """Synchronous Weaviate collection creation helper."""
    if client.collections.exists(collection_name):
        return

    from weaviate.classes.config import Configure, DataType, Property

    client.collections.create(
        name=collection_name,
        vectorizer_config=Configure.Vectorizer.none(),
        properties=[
            Property(name="document_id", data_type=DataType.TEXT),
            Property(name="chunk_ordinal", data_type=DataType.INT),
            Property(name="text", data_type=DataType.TEXT),
            Property(name="checksum_sha256", data_type=DataType.TEXT),
            Property(name="language", data_type=DataType.TEXT),
            Property(name="extraction_quality", data_type=DataType.TEXT),
            Property(name="page_number", data_type=DataType.INT),
            Property(name="section_heading", data_type=DataType.TEXT),
            Property(name="is_suspicious", data_type=DataType.BOOL),
            Property(name="guardrail_flags", data_type=DataType.TEXT_ARRAY),
        ],
    )


def _search_document_chunk_ordinals(
    client: Any,
    document_id: UUID,
    vector: Sequence[float],
    limit: int,
    collection_name: str,
) -> tuple[RetrievedChunkMatch, ...]:
    """Synchronous Weaviate semantic search helper."""
    from weaviate.classes.query import Filter, MetadataQuery

    collection = client.collections.get(collection_name)
    response = collection.query.near_vector(
        near_vector=list(vector),
        filters=Filter.by_property("document_id").equal(str(document_id)),
        limit=limit,
        return_metadata=MetadataQuery(distance=True),
        return_properties=["chunk_ordinal"],
    )

    matches: list[RetrievedChunkMatch] = []
    for item in response.objects:
        ordinal = item.properties.get("chunk_ordinal")
        if not isinstance(ordinal, int):
            continue
        metadata = getattr(item, "metadata", None)
        distance = getattr(metadata, "distance", None)
        matches.append(
            RetrievedChunkMatch(
                chunk_ordinal=ordinal,
                distance=distance if isinstance(distance, float) else None,
            )
        )
    return tuple(matches)


def _index_document_chunks(
    client: Any,
    chunks: Sequence[DocumentChunk],
    vectors: Sequence[Sequence[float]],
    collection_name: str,
) -> None:
    """Synchronous Weaviate batch indexing helper."""
    collection = client.collections.get(collection_name)
    with collection.batch.dynamic() as batch:
        for chunk, vector in zip(chunks, vectors, strict=True):
            batch.add_object(
                uuid=chunk_object_id(chunk),
                properties={
                    "document_id": str(chunk.document_id),
                    "chunk_ordinal": chunk.chunk_ordinal,
                    "text": chunk.text,
                    "checksum_sha256": chunk.checksum_sha256,
                    "language": chunk.language,
                    "extraction_quality": chunk.extraction_quality,
                    "page_number": chunk.page_number,
                    "section_heading": chunk.section_heading,
                    "is_suspicious": chunk.is_suspicious,
                    "guardrail_flags": list(chunk.guardrail_flags),
                },
                vector=list(vector),
            )


def _list_indexed_document_chunks(
    client: Any,
    document_id: UUID,
    collection_name: str,
) -> tuple[dict[str, Any], ...]:
    """Synchronous Weaviate document chunk listing helper."""
    from weaviate.classes.query import Filter

    collection = client.collections.get(collection_name)
    response = collection.query.fetch_objects(
        filters=Filter.by_property("document_id").equal(str(document_id)),
        limit=10_000,
        return_properties=[
            "document_id",
            "chunk_ordinal",
            "text",
            "checksum_sha256",
            "language",
            "extraction_quality",
            "page_number",
            "section_heading",
            "is_suspicious",
            "guardrail_flags",
        ],
    )
    return tuple(
        sorted(
            (dict(item.properties) for item in response.objects),
            key=lambda properties: int(properties.get("chunk_ordinal", 0)),
        )
    )


def chunk_object_id(chunk: DocumentChunk) -> str:
    """Return a stable Weaviate object id for idempotent manual processing."""
    return str(
        uuid5(
            NAMESPACE_URL,
            f"offerguard:{chunk.document_id}:{chunk.chunk_ordinal}:{chunk.checksum_sha256}",
        )
    )
