"""Service health endpoints."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app import __version__
from app.core.resources import check_runtime_dependencies

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return process liveness."""
    return HealthResponse(version=__version__)


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request) -> HealthResponse:
    """Return dependency readiness."""
    try:
        await check_runtime_dependencies(request.app.state.resources)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="dependencies are not ready",
        ) from exc

    return HealthResponse(version=__version__)
