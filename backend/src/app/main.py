"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.router import api_router
from app.core.config import get_settings
from app.core.resources import (
    check_startup_dependencies,
    close_app_resources,
    create_app_resources,
)
from app.observability.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Initialize and release application-scoped resources."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    logger = get_logger(__name__)
    resources = create_app_resources(settings)
    application.state.resources = resources
    try:
        await check_startup_dependencies(settings, resources)
    except Exception:
        await close_app_resources(resources)
        raise
    logger.info("application_started", extra={"environment": settings.environment})
    try:
        yield
    finally:
        await close_app_resources(resources)
        logger.info("application_stopped")


def create_app() -> FastAPI:
    """Build the ASGI application without module-level side effects."""
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.include_router(api_router)
    return application


app = create_app()
