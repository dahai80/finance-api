from __future__ import annotations

import json as _json_mod
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


async def list_ipo(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    min_score: int | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    pg = await get_pg()
    where_clauses: list[str] = []
    params: list[Any] = []

    if status:
        where_clauses.append(f"status = ${len(params) + 1}")
        params.append(status)
    if min_score is not None:
        where_clauses.append(f"valuation_score >= ${len(params) + 1}")
        params.append(min_score)
    if search:
        where_clauses.append(f"(stock_code ILIKE ${len(params) + 1} OR stock_name ILIKE ${len(params) + 1})")
        params.append(f"%{search}%")

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    rows = await pg.fetch(
        f"""
        SELECT stock_code, stock_name, ipo_date, fundamental_metrics,
               valuation_score, recommendation_level, status, ai_generated_script
        FROM finance_control.fc_ipo_factory{where_sql}
        ORDER BY ipo_date DESC, stock_code
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params, limit, offset,
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        fm = r["fundamental_metrics"] or {}
        if isinstance(fm, str):
            try:
                fm = _json_mod.loads(fm)
            except Exception:
                fm = {}
        fm_dict = dict(fm) if isinstance(fm, dict) else {}
        fm_dict["scores"] = fm_dict.get("scores", {}) if isinstance(fm_dict.get("scores"), dict) else {}
        out.append({
            "stock_code": r["stock_code"],
            "stock_name": r["stock_name"],
            "ipo_date": r["ipo_date"].isoformat() if isinstance(r["ipo_date"], date) else str(r["ipo_date"]),
            "fundamental_metrics": fm_dict,
            "valuation_score": r["valuation_score"],
            "recommendation_level": r["recommendation_level"],
            "status": r["status"],
            "ai_generated_script": r["ai_generated_script"],
        })
    return out


async def count_ipo(
    status: str | None = None,
    min_score: int | None = None,
    search: str | None = None,
) -> int:
    pg = await get_pg()
    where_clauses: list[str] = []
    params: list[Any] = []

    if status:
        where_clauses.append(f"status = ${len(params) + 1}")
        params.append(status)
    if min_score is not None:
        where_clauses.append(f"valuation_score >= ${len(params) + 1}")
        params.append(min_score)
    if search:
        where_clauses.append(f"(stock_code ILIKE ${len(params) + 1} OR stock_name ILIKE ${len(params) + 1})")
        params.append(f"%{search}%")

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    row = await pg.fetchval(
        f"SELECT COUNT(*) FROM finance_control.fc_ipo_factory{where_sql}",
        *params,
    )
    return row or 0


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
                _json_mod.dumps(item.get("fundamental_metrics") or {}),
            )
            upserted += 1
    log.info("upserted %d ipo rows", upserted)
    return upserted


async def update_ipo_score(stock_code: str, total: int, recommendation: str) -> None:
    pg = await get_pg()
    await pg.execute(
        """
        UPDATE finance_control.fc_ipo_factory
        SET valuation_score = $1, recommendation_level = $2
        WHERE stock_code = $3
        """,
        total,
        recommendation,
        stock_code,
    )


async def get_live_money_flow(limit: int = 30) -> list[dict[str, Any]]:
    r = await get_redis()
    key = "openclaw:finance:live:market_money_flow"
    pairs = await r.zrevrange(key, 0, limit - 1, withscores=True)
    return [{"sector": s, "flow": float(v)} for s, v in pairs]


async def get_ipo_by_score(min_score: int = 60, limit: int = 20) -> list[dict[str, Any]]:
    pg = await get_pg()
    rows = await pg.fetch(
        """
        SELECT stock_code, stock_name, ipo_date, fundamental_metrics,
               valuation_score, recommendation_level, status
        FROM finance_control.fc_ipo_factory
        WHERE valuation_score >= $1
        ORDER BY valuation_score DESC
        LIMIT $2
        """,
        min_score,
        limit,
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        fm = r["fundamental_metrics"] or {}
        if isinstance(fm, str):
            try:
                fm = _json_mod.loads(fm)
            except Exception:
                fm = {}
        out.append({
            "stock_code": r["stock_code"],
            "stock_name": r["stock_name"],
            "ipo_date": r["ipo_date"].isoformat() if isinstance(r["ipo_date"], date) else str(r["ipo_date"]),
            "valuation_score": r["valuation_score"],
            "recommendation_level": r["recommendation_level"],
            "pe": fm.get("pe"),
            "industry_pe": fm.get("industry_pe"),
            "price": fm.get("price"),
        })
    return out


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


async def get_industry_events(limit: int = 20) -> list[dict[str, Any]]:
    pg = await get_pg()
    rows = await pg.fetch(
        """
        SELECT event_id, event_title, industry_tags, impact_analysis,
               related_stock_codes, event_time
        FROM finance_control.fc_industry_events
        ORDER BY event_time DESC
        LIMIT $1
        """,
        limit,
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "event_id": r["event_id"],
            "event_title": r["event_title"],
            "industry_tags": r["industry_tags"] or [],
            "impact_analysis": r["impact_analysis"],
            "related_stock_codes": r["related_stock_codes"] or [],
            "event_time": r["event_time"].isoformat() if r["event_time"] else None,
        })
    return out


async def insert_industry_event(
    event_title: str,
    industry_tags: list[str],
    impact_analysis: str | None = None,
    related_stock_codes: list[str] | None = None,
    event_time: Any = None,
) -> int:
    pg = await get_pg()
    row = await pg.fetchrow(
        """
        INSERT INTO finance_control.fc_industry_events
            (event_title, industry_tags, impact_analysis, related_stock_codes, event_time)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING event_id
        """,
        event_title,
        _json_mod.dumps(industry_tags),
        impact_analysis,
        _json_mod.dumps(related_stock_codes or []),
        event_time,
    )
    return row["event_id"] if row else 0
