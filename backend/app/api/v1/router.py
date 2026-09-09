from fastapi import APIRouter

from app.api.v1.routes.auth import auth_router
from app.api.v1.routes.health import router as health_router

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
