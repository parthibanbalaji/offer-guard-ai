"""Version 1 API router composition."""

from fastapi import APIRouter

from app.api.v1.routes.documents import router as documents_router
from app.api.v1.routes.health import router as health_router

router = APIRouter(prefix="/v1")
router.include_router(documents_router, tags=["documents"])
router.include_router(health_router, tags=["health"])
