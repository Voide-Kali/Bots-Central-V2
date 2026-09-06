import asyncio
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.db.session import database_is_available

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    application: str
    database: Literal["connected", "unavailable"]


@router.get("/health", response_model=HealthResponse, status_code=200)
async def health() -> HealthResponse:
    settings = get_settings()
    database_available = await asyncio.to_thread(database_is_available)
    database = "connected" if database_available else "unavailable"
    status = "ok" if database == "connected" else "degraded"
    return HealthResponse(status=status, application=settings.app_name, database=database)
