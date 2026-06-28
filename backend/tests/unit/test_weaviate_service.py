from typing import Any

import pytest

from app.core.config import Settings
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
