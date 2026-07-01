from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import get_logger
from data_provider import akshare_fetcher
from data_provider import multi_source_fetcher
import storage

log = get_logger("finance.scheduler")

FINANCE_API = "http://localhost:8000"

scheduler = AsyncIOScheduler()


def _log_result(task_name: str, exc: Exception | None) -> None:
    if exc:
        log.error("task %s failed: %s", task_name, exc)
    else:
        log.info("task %s completed")


# ── Task definitions ──────────────────────────────────────────────

async def _job_ipo_sync() -> None:
    """08:00 每日新股同步 + 评分"""
    log.info("scheduled job: ipo_sync")
    try:
        rows = akshare_fetcher.fetch_upcoming_ipo_live()
        from data_provider.ipo_scorer import score_ipo

        upserted = await storage.upsert_ipo(rows)
        scored = 0
        for row in rows:
            result = score_ipo(row)
            await storage.update_ipo_score(
                row["stock_code"], result["total"], result["recommendation"]
            )
            scored += 1
        log.info("ipo_sync: upserted=%d scored=%d", upserted, scored)
    except Exception as exc:
        log.exception("ipo_sync failed")


async def _job_money_flow() -> None:
    """盘中资金流刷新 (每5分钟, 9:30-15:00)"""
    log.info("scheduled job: money_flow")
    try:
        items = multi_source_fetcher.fetch_money_flow()
        if items:
            await storage.replace_live_money_flow(items)
            log.info("money_flow: refreshed %d sectors", len(items))
            from routers.ws import broadcast_alert
            await broadcast_alert({
                "type": "money_flow",
                "updated_at": datetime.now().isoformat(),
                "count": len(items),
            })
    except Exception as exc:
        log.exception("money_flow failed")


async def _job_premarket_sentiment() -> None:
    """08:30 盘前情绪快照 — 收集美股收盘、概念指数、A50数据"""
    log.info("scheduled job: premarket_sentiment")
    try:
        from datetime import date

        sentiment = multi_source_fetcher.fetch_sentiment()
        prev_flow = await storage.get_live_money_flow(20)
        individual_flow = multi_source_fetcher.fetch_individual_money_flow(20)

        await storage.upsert_sentiment_snapshot(
            trade_date=date.today(),
            us_markets=sentiment.get("us_markets", {"status": "no_data"}),
            china_concepts_idx=sentiment.get("china_concepts", {"status": "no_data"}),
            ftse_a50=sentiment.get("ftse_a50", {"status": "no_data"}),
            prev_day_money_flow=prev_flow,
            prev_day_individual_flow=individual_flow,
        )
        log.info("premarket_sentiment: snapshot saved for %s", date.today())
    except Exception as exc:
        log.exception("premarket_sentiment failed")


async def _job_watchlist_refresh() -> None:
    """15:30 盘后自选股数据刷新"""
    log.info("scheduled job: watchlist_refresh")
    try:
        items = await storage.get_watchlist()
        updated = 0
        for it in items:
            code = it["stock_code"]
            try:
                from data_provider import watchlist_fetcher
                detail = await watchlist_fetcher.build_detail(code, days=90)
                await storage.update_watchlist_cache(code, detail)
                updated += 1
            except Exception:
                log.exception("watchlist_refresh failed for %s", code)
        log.info("watchlist_refresh: %d/%d updated", updated, len(items))
    except Exception as exc:
        log.exception("watchlist_refresh failed")


async def _job_daily_content() -> None:
    """15:15 盘后内容生产 — 触发 high-score IPO 脚本生成"""
    log.info("scheduled job: daily_content")
    try:
        pg = await storage.get_pg()
        rows = await pg.fetch(
            """
            SELECT stock_code, stock_name, fundamental_metrics, valuation_score
            FROM finance_control.fc_ipo_factory
            WHERE valuation_score >= 60
            ORDER BY valuation_score DESC
            LIMIT 20
            """,
        )
        log.info("daily_content: %d high-score stocks queued for script gen", len(rows))

        from data_provider import llm_generator

        stocks = [dict(r) for r in rows]
        results = await llm_generator.generate_batch(stocks, min_score=60)
        for r in results:
            await pg.execute(
                """
                UPDATE finance_control.fc_ipo_factory
                SET ai_generated_script = $1
                WHERE stock_code = $2
                """,
                r["script"],
                r["stock_code"],
            )
        log.info("daily_content: %d scripts saved to db", len(results))
    except Exception as exc:
        log.exception("daily_content failed")


# ── Schedule registration ─────────────────────────────────────────

def init_scheduler() -> AsyncIOScheduler:
    scheduler.add_job(_job_ipo_sync, CronTrigger(day_of_week="mon-fri", hour=8, minute=0), id="ipo_sync")
    scheduler.add_job(_job_premarket_sentiment, CronTrigger(day_of_week="mon-fri", hour=8, minute=30), id="premarket_sentiment")
    scheduler.add_job(
        _job_money_flow,
        CronTrigger(day_of_week="mon-fri", hour="9-14", minute="*/5"),
        id="money_flow",
    )
    scheduler.add_job(_job_daily_content, CronTrigger(day_of_week="mon-fri", hour=15, minute=15), id="daily_content")
    scheduler.add_job(_job_watchlist_refresh, CronTrigger(day_of_week="mon-fri", hour=15, minute=30), id="watchlist_refresh")
    log.info("scheduler: 5 jobs registered (ipo_sync, premarket_sentiment, money_flow, daily_content, watchlist_refresh)")
    return scheduler
