"""Application-scoped dependency resources."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.services.postgres import (
    check_postgres,
    close_postgres_engine,
    create_postgres_engine,
)
from app.services.storage import create_storage_client
from app.services.weaviate import (
    check_weaviate,
    close_weaviate_client,
    create_weaviate_client,
)


@dataclass(frozen=True)
class DependencyCheck:
    """A named dependency probe."""

    name: str
    check: Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class AppResources:
    """Reusable dependency clients owned by the FastAPI lifespan."""

    postgres_engine: AsyncEngine
    storage_client: Any
    weaviate_client: Any | None


class StartupDependencyError(RuntimeError):
    """Raised when a required startup dependency cannot be reached."""


def create_app_resources(settings: Settings) -> AppResources:
    """Create reusable dependency clients for the application lifespan."""
    return AppResources(
        postgres_engine=create_postgres_engine(settings),
        storage_client=create_storage_client(settings),
        weaviate_client=create_weaviate_client(settings),
    )


async def close_app_resources(resources: AppResources) -> None:
    """Release dependency clients owned by the application lifespan."""
    await close_postgres_engine(resources.postgres_engine)
    await close_weaviate_client(resources.weaviate_client)


async def check_runtime_dependencies(resources: AppResources) -> None:
    """Check dependency readiness without startup retry behavior."""
    await check_postgres(resources.postgres_engine)
    await check_weaviate(resources.weaviate_client)


async def check_startup_dependencies(settings: Settings, resources: AppResources) -> None:
    """Run all required startup dependency checks against app-owned resources."""
    checks = (
        DependencyCheck("postgres", lambda: check_postgres(resources.postgres_engine)),
        DependencyCheck("weaviate", lambda: check_weaviate(resources.weaviate_client)),
    )
    deadline = asyncio.get_running_loop().time() + settings.startup_check_timeout_seconds

    for dependency in checks:
        last_error: Exception | None = None
        while True:
            remaining_seconds = deadline - asyncio.get_running_loop().time()
            if remaining_seconds <= 0:
                msg = f"{dependency.name} startup check failed"
                raise StartupDependencyError(msg) from last_error

            try:
                await asyncio.wait_for(dependency.check(), timeout=remaining_seconds)
                break
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(min(1.0, max(0.0, remaining_seconds)))
