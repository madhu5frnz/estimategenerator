from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.api.envelope import Envelope, ok
from app.config import get_settings
from app.core.errors import AppError
from app.domain import ENGINE_VERSION

router = APIRouter(tags=["system"])


class SystemInfo(BaseModel):
    engine_version: str
    ai_provider: str
    environment: str
    google_login_enabled: bool


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, str]:
    """Liveness: the process is up. No dependencies checked, no data returned."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def readyz() -> dict[str, object]:
    """Readiness: database and Redis reachable."""
    from redis import Redis
    from redis.exceptions import RedisError
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.session import get_engine

    checks: dict[str, str] = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except SQLAlchemyError:
        checks["database"] = "unavailable"
    try:
        client = Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        client.ping()
        checks["redis"] = "ok"
    except (RedisError, OSError):
        checks["redis"] = "unavailable"
    if any(v != "ok" for v in checks.values()):
        raise AppError("NOT_READY", "A required service is unavailable.", 503, {"checks": checks})
    return {"status": "ready", "checks": checks}


@router.get("/api/v1/system/info", response_model=Envelope[SystemInfo])
def system_info() -> Envelope[SystemInfo]:
    settings = get_settings()
    return ok(
        SystemInfo(
            engine_version=ENGINE_VERSION,
            ai_provider=settings.effective_ai_provider,
            environment=settings.app_env,
            google_login_enabled=settings.google_login_enabled,
        )
    )
