from __future__ import annotations

import json
from datetime import date
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from config import get_logger, settings

log = get_logger("finance.storage")

_pool: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None


async def get_pg() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        log.info("opening asyncpg pool dsn=%s", settings.pg_dsn.split("@")[-1])
        _pool = await asyncpg.create_pool(dsn=settings.pg_dsn, min_size=1, max_size=5)
    return _pool


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        log.info("opening redis url=%s", settings.redis_url)
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close() -> None:
    global _pool, _redis
    if _pool is not None:
        await _pool.close()
        _pool = None
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def list_ipo(limit: int = 50) -> list[dict[str, Any]]:
    pg = await get_pg()
    rows = await pg.fetch(
        """
        SELECT stock_code, stock_name, ipo_date, fundamental_metrics,
               valuation_score, recommendation_level, status
        FROM finance_control.fc_ipo_factory
        ORDER BY ipo_date DESC, stock_code
        LIMIT $1
        """,
        limit,
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "stock_code": r["stock_code"],
            "stock_name": r["stock_name"],
            "ipo_date": r["ipo_date"].isoformat() if isinstance(r["ipo_date"], date) else str(r["ipo_date"]),
            "fundamental_metrics": r["fundamental_metrics"],
            "valuation_score": r["valuation_score"],
            "recommendation_level": r["recommendation_level"],
            "status": r["status"],
        })
    return out


async def upsert_ipo(items: list[dict[str, Any]]) -> int:
    pg = await get_pg()
    upserted = 0
    async with pg.acquire() as conn:
        for item in items:
            code = item.get("stock_code")
            if not code:
                log.warning("skip ipo item missing stock_code: %s", item)
                continue
            await conn.execute(
                """
                INSERT INTO finance_control.fc_ipo_factory
                    (stock_code, stock_name, ipo_date, fundamental_metrics, status)
                VALUES ($1, $2, $3, $4, 'PENDING')
                ON CONFLICT (stock_code) DO UPDATE SET
                    stock_name = EXCLUDED.stock_name,
                    ipo_date = EXCLUDED.ipo_date,
                    fundamental_metrics = EXCLUDED.fundamental_metrics
                """,
                code,
                item.get("stock_name", ""),
                item.get("ipo_date") or date.today(),
                json.dumps(item.get("fundamental_metrics") or {}),
            )
            upserted += 1
    log.info("upserted %d ipo rows", upserted)
    return upserted


async def replace_live_money_flow(items: list[dict[str, Any]]) -> None:
    r = await get_redis()
    key = "openclaw:finance:live:market_money_flow"
    async with r.pipeline() as pipe:
        pipe.delete(key)
        for it in items:
            pipe.zadd(key, {str(it["sector"]): float(it["flow"])})
        await pipe.execute()
    await r.publish("openclaw:finance:live:stream_trigger", "UPDATE")
    log.info("redis zset %s refreshed, %d items", key, len(items))
