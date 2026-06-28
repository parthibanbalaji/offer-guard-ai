"""Weaviate client lifecycle helpers."""

import asyncio
from typing import Any

import weaviate

from app.core.config import Settings


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
