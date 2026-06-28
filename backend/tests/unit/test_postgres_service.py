from typing import Any

from app.core.config import Settings
from app.services import postgres


def test_create_postgres_engine_uses_configured_database_url(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://user:password@db.example.test:5432/offerguard",
    )
    calls: list[dict[str, Any]] = []
    engine = object()

    def create_async_engine(url: str, **kwargs: Any) -> object:
        calls.append({"url": url, **kwargs})
        return engine

    monkeypatch.setattr(postgres, "create_async_engine", create_async_engine)

    assert postgres.create_postgres_engine(settings) is engine
    assert calls == [
        {
            "url": "postgresql+asyncpg://user:password@db.example.test:5432/offerguard",
            "pool_pre_ping": True,
        }
    ]
