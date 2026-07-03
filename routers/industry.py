from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import get_logger, settings
from data_provider import multi_source_fetcher
from async_utils import spawn_background_task
import storage

router = APIRouter(prefix="/api/industry", tags=["industry"])
log = get_logger("finance.industry_router")


class IndustryEventCreate(BaseModel):
    event_title: str = Field(..., min_length=1, max_length=200)
    industry_tags: list[str] = Field(..., max_length=20)
    impact_analysis: Optional[str] = Field(None, max_length=2000)
    related_stock_codes: Optional[list[str]] = Field(None, max_length=50)
    event_time: Optional[str] = None


def _validate_limit(limit: int, max_val: int = 200) -> int:
    """Validate and clamp limit parameter."""
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    return min(limit, max_val)


@router.get("/list")
async def list_industries() -> list[str]:
    """Get available industry list."""
    return multi_source_fetcher.get_industry_list()


@router.get("/events")
async def get_industry_events(limit: int = 20) -> list[dict[str, Any]]:
    log.info("GET /api/industry/events limit=%d", limit)
    limit = _validate_limit(limit)
    return await storage.get_industry_events(limit)


@router.post("/events")
async def add_industry_event(event: IndustryEventCreate) -> dict[str, Any]:
    log.info("POST /api/industry/events title=%s", event.event_title)
    time_val = None
    if event.event_time:
        try:
            time_val = datetime.fromisoformat(event.event_time)
        except ValueError:
            pass

    if time_val is None:
        time_val = datetime.now()

    evt_id = await storage.insert_industry_event(
        event_title=event.event_title,
        industry_tags=event.industry_tags,
        impact_analysis=event.impact_analysis,
        related_stock_codes=event.related_stock_codes or [],
        event_time=time_val,
    )
    return {"event_id": evt_id}


@router.get("/top-stocks")
async def get_industry_top_stocks(limit: int = 20) -> dict[str, Any]:
    # Top stocks by industry, served from a 10-min cache refreshed by the
    # scheduler (sub-10ms). The live fetch is ~8s (AkShare East Money per
    # industry) so it never runs on the request path. Cache miss triggers a
    # background refresh and returns mock honestly labeled.
    log.info("GET /api/industry/top-stocks limit=%d", limit)
    limit = _validate_limit(limit)
    cached = multi_source_fetcher.get_cached_industry_top_stocks()
    if not cached["data"] or cached["stale"]:
        spawn_background_task(multi_source_fetcher.afetch_all_industry_top_stocks(10), "industry_top_stocks")
    if cached["data"]:
        data = [{**g, "stocks": g.get("stocks", [])[:limit]} for g in cached["data"]]
        # 缓存可能已过时（调度器仅交易日 08-15 刷新；深夜/周末/调度挂掉时数据陈旧）。
        # 如实暴露 stale 并把 ok 置为 not stale——旧价不谎报为可信。
        return {"data": data, "source": "real", "ok": not cached["stale"], "stale": cached["stale"]}
    return {"data": multi_source_fetcher._mock_industry_top_stocks(limit), "source": "mock", "ok": False}


@router.get("/news")
async def get_industry_news(
    limit: int = 20,
    industry: Optional[str] = None,
) -> dict[str, Any]:
    # Latest industry dynamics/news. No-industry: served from grouped cache
    # (flatten + sort by pub_time desc, sub-10ms). With-industry: live fetch.
    # Mock fallback is flagged via source="mock".
    log.info("GET /api/industry/news limit=%d industry=%s", limit, industry)
    limit = _validate_limit(limit)
    try:
        if industry:
            items = await multi_source_fetcher.afetch_industry_news(limit, industry=industry)
            return {"data": items, "source": "real", "ok": True}
        # Flatten grouped cache into a latest-news stream
        cached = multi_source_fetcher.get_cached_industry_news_grouped()
        if not cached["data"]:
            spawn_background_task(multi_source_fetcher.afetch_all_industry_news_grouped(), "industry_news")
            return {"data": [], "source": "real", "ok": True}
        flat: list[dict[str, Any]] = []
        for group in cached["data"]:
            for item in group.get("items", []):
                flat.append(item)
        flat.sort(key=lambda x: x.get("pub_time", "") or "", reverse=True)
        return {"data": flat[:limit], "source": "real", "ok": True}
    except Exception as exc:
        log.exception("industry_news failed")
        return {"data": _mock_industry_news(limit), "source": "mock", "ok": False}


@router.get("/news/grouped")
async def get_industry_news_grouped() -> dict[str, Any]:
    """Latest dynamics for EVERY industry, served from an in-process cache
    refreshed every 10 minutes by the scheduler. Sub-10ms response.

    Returns {data: [{industry, items, count}], updated_at, age_seconds, stale}.
    Triggers a background refresh when the cache is empty or stale.
    """
    cached = multi_source_fetcher.get_cached_industry_news_grouped()
    if not cached["data"] or cached["stale"]:
        spawn_background_task(multi_source_fetcher.afetch_all_industry_news_grouped(), "industry_news_grouped")
    log.info(
        "GET /api/industry/news/grouped cached=%d stale=%s",
        len(cached["data"]), cached["stale"],
    )
    return cached


@router.post("/trigger/top-stocks")
async def trigger_industry_top_stocks() -> dict[str, Any]:
    """Manually trigger industry top stocks data fetch."""
    log.info("POST /api/industry/trigger/top-stocks")
    try:
        items = await multi_source_fetcher.afetch_all_industry_top_stocks(10)
        return {"status": "ok", "count": len(items)}
    except Exception:
        log.exception("trigger industry_top_stocks failed")
        return {"status": "error", "message": "trigger_industry_top_stocks failed"}


# ── Mock Data ───────────────────────────────────────────────────────────

def _mock_industry_news(limit: int) -> list[dict[str, Any]]:
    news = [
        ("AI芯片需求激增，半导体板块持续走强", "科技", "东方财富"),
        ("新能源汽车销量再创新高，产业链受益明显", "汽车", "财联社"),
        ("医药集采政策调整，创新药企迎来机遇", "医药", "证券时报"),
        ("光伏行业产能出清，龙头企业份额提升", "能源", "上海证券报"),
        ("消费复苏加速，白酒板块估值修复", "消费", "每日经济"),
        ("数据中心建设提速，服务器需求增长", "科技", "第一财经"),
        ("房地产政策放松，地产链有望回暖", "地产", "新浪财经"),
        ("稀土价格反弹，相关概念股上涨", "材料", "东方财富"),
    ]
    import random
    from datetime import datetime, timedelta
    return [{
        "title": n[0], "source": n[1] + " " + n[2],
        "digest": n[0],
        "ctime": (datetime.now() - timedelta(hours=random.randint(1, 72))).strftime("%Y-%m-%d %H:%M"),
        "url": "",
    } for n in news[:limit]]
