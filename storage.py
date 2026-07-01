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
        await pipe.delete(key)
        for it in items:
            await pipe.zadd(key, {str(it["sector"]): float(it["flow"])})
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


# ── fc_market_alerts ─────────────────────────────────────────────


async def insert_market_alert(
    stock_code: str,
    alert_type: str,
    direction: int,
    severity: str,
    event_description: str,
) -> int:
    """Insert a market alert into fc_market_alerts."""
    pg = await get_pg()
    row = await pg.fetchrow(
        """
        INSERT INTO finance_control.fc_market_alerts
            (stock_code, alert_type, direction, severity, event_description)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING alert_id
        """,
        stock_code, alert_type, direction, severity, event_description,
    )
    alert_id = row["alert_id"] if row else 0
    log.info("inserted market alert id=%d code=%s type=%s severity=%s", alert_id, stock_code, alert_type, severity)
    return alert_id


async def get_market_alerts(
    limit: int = 50,
    severity: str | None = None,
    is_handled: bool | None = None,
) -> list[dict[str, Any]]:
    """Query market alerts from fc_market_alerts."""
    pg = await get_pg()
    where_clauses: list[str] = []
    params: list[Any] = []

    if severity:
        where_clauses.append(f"severity = ${len(params) + 1}")
        params.append(severity)
    if is_handled is not None:
        where_clauses.append(f"is_handled = ${len(params) + 1}")
        params.append(is_handled)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    rows = await pg.fetch(
        f"""
        SELECT alert_id, stock_code, alert_type, direction, severity,
               event_description, is_handled, created_at
        FROM finance_control.fc_market_alerts{where_sql}
        ORDER BY created_at DESC
        LIMIT ${len(params) + 1}
        """,
        *params, limit,
    )
    return [dict(r) for r in rows]


# ── fc_market_sentiment_snapshot ───────────────────────────────────


async def upsert_sentiment_snapshot(
    trade_date: date,
    us_markets: dict[str, Any],
    china_concepts_idx: dict[str, Any],
    ftse_a50: dict[str, Any],
    prev_day_money_flow: list[dict[str, Any]],
    prev_day_individual_flow: list[dict[str, Any]] | None = None,
) -> None:
    """Upsert daily market sentiment snapshot into fc_market_sentiment_snapshot."""
    pg = await get_pg()
    await pg.execute(
        """
        INSERT INTO finance_control.fc_market_sentiment_snapshot
            (trade_date, us_markets, china_concepts_idx, ftse_a50, prev_day_money_flow)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (trade_date) DO UPDATE SET
            us_markets = EXCLUDED.us_markets,
            china_concepts_idx = EXCLUDED.china_concepts_idx,
            ftse_a50 = EXCLUDED.ftse_a50,
            prev_day_money_flow = EXCLUDED.prev_day_money_flow
        """,
        trade_date,
        _json_mod.dumps(us_markets),
        _json_mod.dumps(china_concepts_idx),
        _json_mod.dumps(ftse_a50),
        _json_mod.dumps(prev_day_money_flow),
    )
    log.info("upserted sentiment snapshot for %s", trade_date.isoformat())


async def get_sentiment_snapshot(trade_date: date | None = None) -> dict[str, Any] | None:
    """Get a sentiment snapshot by date, or the latest one."""
    pg = await get_pg()
    if trade_date:
        row = await pg.fetchrow(
            "SELECT * FROM finance_control.fc_market_sentiment_snapshot WHERE trade_date = $1",
            trade_date,
        )
    else:
        row = await pg.fetchrow(
            "SELECT * FROM finance_control.fc_market_sentiment_snapshot ORDER BY trade_date DESC LIMIT 1"
        )
    if not row:
        return None
    result = dict(row)
    for key in ("us_markets", "china_concepts_idx", "ftse_a50", "prev_day_money_flow"):
        val = result.get(key)
        if isinstance(val, str):
            try:
                result[key] = _json_mod.loads(val)
            except Exception:
                pass
    return result


# ── fc_stock_snapshot ──────────────────────────────────────────────


async def insert_stock_snapshot(
    stock_code: str,
    trade_date: date,
    macro_signals: dict[str, Any] | None,
    fundamental_data: dict[str, Any] | None,
    kronos_prediction: dict[str, Any] | None,
    generated_content: str | None,
    status: str = "PENDING",
) -> int:
    """Insert a daily stock snapshot into fc_stock_snapshot."""
    pg = await get_pg()
    row = await pg.fetchrow(
        """
        INSERT INTO finance_control.fc_stock_snapshot
            (stock_code, trade_date, macro_signals, fundamental_data,
             kronos_prediction, generated_content, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """,
        stock_code,
        trade_date,
        _json_mod.dumps(macro_signals or {}),
        _json_mod.dumps(fundamental_data or {}),
        _json_mod.dumps(kronos_prediction or {}),
        generated_content,
        status,
    )
    snapshot_id = row["id"] if row else 0
    log.info("inserted stock_snapshot id=%d code=%s date=%s", snapshot_id, stock_code, trade_date)
    return snapshot_id


async def get_stock_snapshots(
    stock_code: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query stock snapshots from fc_stock_snapshot."""
    pg = await get_pg()
    where_clauses: list[str] = []
    params: list[Any] = []

    if stock_code:
        where_clauses.append(f"stock_code = ${len(params) + 1}")
        params.append(stock_code)
    if status:
        where_clauses.append(f"status = ${len(params) + 1}")
        params.append(status)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    rows = await pg.fetch(
        f"""
        SELECT id, stock_code, trade_date, macro_signals, fundamental_data,
               kronos_prediction, generated_content, status, created_at, updated_at
        FROM finance_control.fc_stock_snapshot{where_sql}
        ORDER BY trade_date DESC, stock_code
        LIMIT ${len(params) + 1}
        """,
        *params, limit,
    )
    return [dict(r) for r in rows]


# ── fc_workflow_config ─────────────────────────────────────────────


async def get_active_workflows() -> list[dict[str, Any]]:
    """Get all active workflow configurations from fc_workflow_config."""
    pg = await get_pg()
    rows = await pg.fetch(
        """
        SELECT task_id, is_active, cron_expression, kronos_params,
               valuecell_filters, llm_prompt_template, updated_at
        FROM finance_control.fc_workflow_config
        WHERE is_active = TRUE
        ORDER BY task_id
        """
    )
    result: list[dict[str, Any]] = []
    for r in rows:
        row_dict = dict(r)
        for key in ("kronos_params", "valuecell_filters"):
            val = row_dict.get(key)
            if isinstance(val, str):
                try:
                    row_dict[key] = _json_mod.loads(val)
                except Exception:
                    pass
        result.append(row_dict)
    return result


async def update_workflow_config(
    task_id: str,
    is_active: bool | None = None,
    kronos_params: dict[str, Any] | None = None,
    valuecell_filters: dict[str, Any] | None = None,
    llm_prompt_template: str | None = None,
) -> None:
    """Update a workflow configuration in fc_workflow_config."""
    pg = await get_pg()
    sets: list[str] = []
    params: list[Any] = []

    if is_active is not None:
        sets.append(f"is_active = ${len(params) + 1}")
        params.append(is_active)
    if kronos_params is not None:
        sets.append(f"kronos_params = ${len(params) + 1}")
        params.append(_json_mod.dumps(kronos_params))
    if valuecell_filters is not None:
        sets.append(f"valuecell_filters = ${len(params) + 1}")
        params.append(_json_mod.dumps(valuecell_filters))
    if llm_prompt_template is not None:
        sets.append(f"llm_prompt_template = ${len(params) + 1}")
        params.append(llm_prompt_template)

    if not sets:
        return

    sets.append(f"updated_at = ${len(params) + 1}")
    params.append(None)  # will be set by DEFAULT in SQL, but we need a param slot

    await pg.execute(
        f"""
        UPDATE finance_control.fc_workflow_config
        SET {', '.join(sets)}
        WHERE task_id = ${len(params) + 1}
        """,
        *params, task_id,
    )
    log.info("updated workflow config for %s", task_id)


# ── fc_watchlist ───────────────────────────────────────────────────


async def get_watchlist() -> list[dict[str, Any]]:
    """Return all watchlist items ordered by added_at DESC."""
    pg = await get_pg()
    rows = await pg.fetch(
        """
        SELECT id, stock_code, stock_name, industry, note,
               added_at, cached_details, cached_at
        FROM finance_control.fc_watchlist
        ORDER BY added_at DESC
        """
    )
    result: list[dict[str, Any]] = []
    for r in rows:
        row_dict = dict(r)
        cd = row_dict.get("cached_details")
        if isinstance(cd, str):
            try:
                row_dict["cached_details"] = _json_mod.loads(cd)
            except Exception:
                pass
        result.append(row_dict)
    return result


async def count_watchlist() -> int:
    pg = await get_pg()
    row = await pg.fetchval("SELECT COUNT(*) FROM finance_control.fc_watchlist")
    return row or 0


async def add_to_watchlist(
    stock_code: str,
    stock_name: str,
    industry: str | None = None,
    note: str | None = None,
) -> int:
    pg = await get_pg()
    row = await pg.fetchrow(
        """
        INSERT INTO finance_control.fc_watchlist (stock_code, stock_name, industry, note)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (stock_code) DO UPDATE SET
            stock_name = EXCLUDED.stock_name,
            industry = EXCLUDED.industry,
            note = EXCLUDED.note
        RETURNING id
        """,
        stock_code, stock_name, industry, note,
    )
    wid = row["id"] if row else 0
    log.info("added to watchlist id=%d code=%s name=%s", wid, stock_code, stock_name)
    return wid


async def remove_from_watchlist(stock_code: str) -> bool:
    pg = await get_pg()
    result = await pg.execute(
        "DELETE FROM finance_control.fc_watchlist WHERE stock_code = $1",
        stock_code,
    )
    deleted = "DELETE 1" in result
    log.info("removed from watchlist code=%s deleted=%s", stock_code, deleted)
    return deleted


async def update_watchlist_cache(stock_code: str, details: dict[str, Any]) -> None:
    pg = await get_pg()
    await pg.execute(
        """
        UPDATE finance_control.fc_watchlist
        SET cached_details = $1, cached_at = NOW()
        WHERE stock_code = $2
        """,
        _json_mod.dumps(details),
        stock_code,
    )


async def get_watchlist_item(stock_code: str) -> dict[str, Any] | None:
    pg = await get_pg()
    row = await pg.fetchrow(
        """
        SELECT id, stock_code, stock_name, industry, note,
               added_at, cached_details, cached_at
        FROM finance_control.fc_watchlist
        WHERE stock_code = $1
        """,
        stock_code,
    )
    if not row:
        return None
    row_dict = dict(row)
    cd = row_dict.get("cached_details")
    if isinstance(cd, str):
        try:
            row_dict["cached_details"] = _json_mod.loads(cd)
        except Exception:
            pass
    return row_dict
