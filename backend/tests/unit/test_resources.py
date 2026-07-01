from typing import Any

import pytest

from app.core import resources as resource_module
from app.core.config import Settings
from app.core.resources import AppResources, StartupDependencyError


def make_settings(**overrides: Any) -> Settings:
    values = {
        "database_url": "postgresql+asyncpg://user:password@db.example.test:5432/offerguard",
        **overrides,
    }
    return Settings(_env_file=None, **values)


def test_create_app_resources_uses_service_factories(monkeypatch) -> None:
    settings = make_settings()
    engine = object()
    storage_client = object()
    client = object()

    def create_postgres_engine(_: Settings) -> object:
        return engine

    def create_storage_client(_: Settings) -> object:
        return storage_client

    def create_weaviate_client(_: Settings) -> object:
        return client

    monkeypatch.setattr(resource_module, "create_postgres_engine", create_postgres_engine)
    monkeypatch.setattr(resource_module, "create_storage_client", create_storage_client)
    monkeypatch.setattr(resource_module, "create_weaviate_client", create_weaviate_client)

    resources = resource_module.create_app_resources(settings)

    assert resources == AppResources(
        postgres_engine=engine,
        storage_client=storage_client,
        weaviate_client=client,
    )


@pytest.mark.asyncio
async def test_check_startup_dependencies_runs_postgres_and_weaviate(monkeypatch) -> None:
    settings = make_settings()
    checked: list[str] = []
    app_resources = AppResources(
        postgres_engine=object(),
        storage_client=object(),
        weaviate_client=object(),
    )

    async def check_postgres(_: object) -> None:
        checked.append("postgres")

    async def check_weaviate(_: object) -> None:
        checked.append("weaviate")

    monkeypatch.setattr(resource_module, "check_postgres", check_postgres)
    monkeypatch.setattr(resource_module, "check_weaviate", check_weaviate)

    await resource_module.check_startup_dependencies(settings, app_resources)

    assert checked == ["postgres", "weaviate"]


@pytest.mark.asyncio
async def test_check_startup_dependencies_names_failing_dependency(monkeypatch) -> None:
    settings = make_settings(startup_check_timeout_seconds=0.01)
    app_resources = AppResources(
        postgres_engine=object(),
        storage_client=object(),
        weaviate_client=object(),
    )

    async def check_postgres(_: object) -> None:
        raise OSError("connection refused")

    async def check_weaviate(_: object) -> None:
        raise AssertionError("should not run after postgres failure")

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(resource_module, "check_postgres", check_postgres)
    monkeypatch.setattr(resource_module, "check_weaviate", check_weaviate)
    monkeypatch.setattr(resource_module.asyncio, "sleep", no_sleep)

    with pytest.raises(StartupDependencyError, match="postgres startup check failed"):
        await resource_module.check_startup_dependencies(settings, app_resources)
