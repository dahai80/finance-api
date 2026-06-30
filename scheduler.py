from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import get_logger
from data_provider import akshare_fetcher
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
        import akshare as ak

        df = ak.stock_fund_flow_industry()
        if df is not None and not df.empty:
            items = []
            for _, row in df.iterrows():
                sector = str(row.get("行业", row.get("行业名称", "")))
                flow_val = row.get("净额") or row.get("实际流入资金", 0)
                try:
                    flow = float(str(flow_val).replace(",", ""))
                except Exception:
                    flow = 0.0
                items.append({"sector": sector, "flow": flow})
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
        import akshare as ak
        from datetime import date

        us_markets: dict[str, Any] = {}
        china_concepts: dict[str, Any] = {}
        ftse_a50: dict[str, Any] = {}

        # ── SPY (US market proxy) ──────────────────────────────
        try:
            df = ak.stock_us_index_daily(symbol="SPY")
            if df is not None and not df.empty:
                last = df.iloc[-1]
                us_markets["spy_close"] = float(last.get("收盘", last.get("close", 0)))
                us_markets["spy_change"] = float(last.get("涨跌幅", last.get("change_pct", 0)))
        except Exception:
            pass

        # ── KWEB (China concept stocks ETF) ─────────────────────
        try:
            df = ak.stock_us_hist(symbol="KWEB")
            if df is not None and not df.empty:
                last = df.iloc[-1]
                china_concepts["kweb_close"] = float(last.get("收盘", last.get("close", 0)))
                china_concepts["kweb_change"] = float(last.get("涨跌幅", last.get("change_pct", 0)))
        except Exception:
            pass

        # ── FTSE China A50 (ETF code: 510050) ──────────────────
        try:
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("代码", "")).strip()
                    if code == "510050":
                        ftse_a50["close"] = float(row.get("最新价", 0))
                        ftse_a50["change_pct"] = float(row.get("涨跌幅", 0))
                        ftse_a50["name"] = str(row.get("名称", "A50"))
                        break
        except Exception:
            pass

        prev_flow = await storage.get_live_money_flow(20)

        await storage.upsert_sentiment_snapshot(
            trade_date=date.today(),
            us_markets=us_markets or {"status": "no_data"},
            china_concepts_idx=china_concepts or {"status": "no_data"},
            ftse_a50=ftse_a50 or {"status": "no_data"},
            prev_day_money_flow=prev_flow,
        )
        log.info("premarket_sentiment: snapshot saved for %s", date.today())
    except Exception as exc:
        log.exception("premarket_sentiment failed")


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
    log.info("scheduler: 4 jobs registered (ipo_sync, premarket_sentiment, money_flow, daily_content)")
    return scheduler
