from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Response

from config import get_logger, settings
import storage

router = APIRouter()
log = get_logger("finance.health")


@router.get("/health")
async def health(response: Response) -> dict[str, Any]:
    # 真实存活探测：DB + Redis。任一依赖不可用即返回 503——负载均衡只看状态码时，
    # 绝不可把流量路由到依赖掉线的节点（伪健康检查比没有更糟）。每探测加超时，
    # 半开连接不会让 /health 无限挂起。错误信息只暴露类型，不泄露连接串细节。
    checks: dict[str, Any] = {}
    overall = "ok"

    try:
        pg = await asyncio.wait_for(storage.get_pg(), timeout=3.0)
        await asyncio.wait_for(pg.fetchval("SELECT 1"), timeout=2.0)
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {type(exc).__name__}"
        overall = "degraded"
        log.warning("health db check failed: %s", exc)

    try:
        redis = await asyncio.wait_for(storage.get_redis(), timeout=3.0)
        await asyncio.wait_for(redis.ping(), timeout=2.0)
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
        overall = "degraded"
        log.warning("health redis check failed: %s", exc)

    if overall != "ok":
        response.status_code = 503

    return {
        "status": overall,
        "service": "finance-api",
        "akshare_mock": settings.akshare_mock,
        "checks": checks,
    }
