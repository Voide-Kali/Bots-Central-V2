from fastapi import APIRouter

from app.api.v1.routes.audit import audit_router
from app.api.v1.routes.auth import auth_router, devices_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.telegram import telegram_router

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(devices_router)
router.include_router(telegram_router)
router.include_router(audit_router)
