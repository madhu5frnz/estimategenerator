from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    abstract,
    ai,
    auth,
    calculations,
    dashboard,
    estimates,
    me,
    projects,
    rates,
    system,
)
from app.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.app_env != "development")

    app = FastAPI(
        title="EstimateAI API",
        version="0.1.0",
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)

    app.include_router(system.router)
    for module in (calculations, auth, me, projects, estimates, abstract, rates, ai, dashboard):
        app.include_router(module.router, prefix="/api/v1")
    return app


app = create_app()
