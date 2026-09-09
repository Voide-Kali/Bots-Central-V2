from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.api.v1.routes.auth import configure_auth_http, verification_page_router
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
    )
    configure_auth_http(app, settings)
    app.include_router(v1_router, prefix="/api/v1")
    app.include_router(verification_page_router)
    return app


app = create_app()
