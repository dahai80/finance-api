from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from config import get_logger, settings
import storage

router = APIRouter()
log = get_logger("finance.health")


@router.get("/health")
async def health() -> dict[str, Any]:
    # Real liveness: probe DB + Redis. Never report ok when a dependency is
    # down — fake monitoring is worse than none for a trading system. HTTP 200
    # means the process is alive; the `status` field communicates readiness.
    checks: dict[str, Any] = {}
    overall = "ok"

    try:
        pg = await storage.get_pg()
        await pg.fetchval("SELECT 1")
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"
        overall = "degraded"
        log.warning("health db check failed: %s", exc)

    try:
        redis = await storage.get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        overall = "degraded"
        log.warning("health redis check failed: %s", exc)

    return {
        "status": overall,
        "service": "finance-api",
        "akshare_mock": settings.akshare_mock,
        "checks": checks,
    }
