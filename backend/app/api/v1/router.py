from fastapi import APIRouter

from app.api.v1.routes.action_pin import action_pin_router
from app.api.v1.routes.admin import admin_router
from app.api.v1.routes.audit import audit_router
from app.api.v1.routes.auth import auth_router, devices_router
from app.api.v1.routes.device_actions import device_actions_router
from app.api.v1.routes.device_commands import device_commands_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.password_reset import password_reset_router
from app.api.v1.routes.telegram import telegram_router

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(devices_router)
router.include_router(telegram_router)
router.include_router(action_pin_router)
router.include_router(admin_router)
router.include_router(audit_router)
router.include_router(password_reset_router)
router.include_router(device_commands_router)
router.include_router(device_actions_router)
