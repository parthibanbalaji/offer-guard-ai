"""Weaviate client lifecycle helpers."""

import asyncio
from collections.abc import Sequence
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import weaviate

from app.core.config import Settings
from app.observability.tracing import process_index_inputs, process_index_outputs, traceable
from app.rag.chunking import DocumentChunk
from app.rag.embeddings import EmbeddingModel

CHUNK_COLLECTION = "OfferDocumentChunk"


class WeaviateNotReadyError(RuntimeError):
    """Raised when Weaviate reports that it is not ready."""


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
    if client is None:
        return

    await asyncio.to_thread(_ensure_chunk_collection, client)


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
) -> int:
    """Embed and store chunks with metadata in Weaviate."""
    if client is None or not chunks:
        return 0

    vectors = await embedding_model.embed_texts([chunk.text for chunk in chunks])
    await ensure_chunk_collection(client)
    await asyncio.to_thread(_index_document_chunks, client, chunks, vectors)
    return len(chunks)


def _ensure_chunk_collection(client: Any) -> None:
    """Synchronous Weaviate collection creation helper."""
    if client.collections.exists(CHUNK_COLLECTION):
        return

    from weaviate.classes.config import Configure, DataType, Property

    client.collections.create(
        name=CHUNK_COLLECTION,
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


def _index_document_chunks(
    client: Any,
    chunks: Sequence[DocumentChunk],
    vectors: Sequence[Sequence[float]],
) -> None:
    """Synchronous Weaviate batch indexing helper."""
    collection = client.collections.get(CHUNK_COLLECTION)
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


def chunk_object_id(chunk: DocumentChunk) -> str:
    """Return a stable Weaviate object id for idempotent manual processing."""
    return str(
        uuid5(
            NAMESPACE_URL,
            f"offerguard:{chunk.document_id}:{chunk.chunk_ordinal}:{chunk.checksum_sha256}",
        )
    )
