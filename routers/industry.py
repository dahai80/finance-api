from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import get_logger, settings
from data_provider import multi_source_fetcher
import storage

router = APIRouter(prefix="/api/industry", tags=["industry"])
log = get_logger("finance.industry_router")


class IndustryEventCreate(BaseModel):
    event_title: str
    industry_tags: list[str]
    impact_analysis: Optional[str] = None
    related_stock_codes: Optional[list[str]] = None
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
async def get_industry_top_stocks(limit: int = 20) -> list[dict[str, Any]]:
    """Get top performing stocks by industry with multi-source fallback."""
    log.info("GET /api/industry/top-stocks limit=%d", limit)
    limit = _validate_limit(limit)
    try:
        return await multi_source_fetcher.afetch_industry_top_stocks(limit)
    except Exception as exc:
        log.exception("top_stocks failed")
        return _mock_industry_top_stocks(limit)


@router.get("/news")
async def get_industry_news(
    limit: int = 20,
    industry: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Get latest industry dynamics/news.

    No-industry (latest stream): served from the grouped cache — flatten all
    industries and sort by pub_time desc. Sub-10ms, no live 5s fetch.
    With-industry: live fetch for the requested industry only.
    """
    log.info("GET /api/industry/news limit=%d industry=%s", limit, industry)
    limit = _validate_limit(limit)
    try:
        if industry:
            return await multi_source_fetcher.afetch_industry_news(limit, industry=industry)
        # Flatten grouped cache into a latest-news stream
        cached = multi_source_fetcher.get_cached_industry_news_grouped()
        if not cached["data"]:
            asyncio.create_task(multi_source_fetcher.afetch_all_industry_news_grouped())
            return []
        flat: list[dict[str, Any]] = []
        for group in cached["data"]:
            for item in group.get("items", []):
                flat.append(item)
        flat.sort(key=lambda x: x.get("pub_time", "") or "", reverse=True)
        return flat[:limit]
    except Exception as exc:
        log.exception("industry_news failed")
        return _mock_industry_news(limit)


@router.get("/news/grouped")
async def get_industry_news_grouped() -> dict[str, Any]:
    """Latest dynamics for EVERY industry, served from an in-process cache
    refreshed every 10 minutes by the scheduler. Sub-10ms response.

    Returns {data: [{industry, items, count}], updated_at, age_seconds, stale}.
    Triggers a background refresh when the cache is empty or stale.
    """
    cached = multi_source_fetcher.get_cached_industry_news_grouped()
    if not cached["data"] or cached["stale"]:
        asyncio.create_task(multi_source_fetcher.afetch_all_industry_news_grouped())
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
        items = await multi_source_fetcher.afetch_industry_top_stocks(10)
        return {"status": "ok", "count": len(items)}
    except Exception as exc:
        log.exception("trigger industry_top_stocks failed")
        return {"status": "error", "message": str(exc)}


# ── Mock Data ───────────────────────────────────────────────────────────

def _mock_industry_top_stocks(limit: int) -> list[dict[str, Any]]:
    stocks = [
        ("600519", "贵州茅台", "白酒"), ("000858", "五粮液", "白酒"),
        ("601318", "中国平安", "保险"), ("600036", "招商银行", "银行"),
        ("300750", "宁德时代", "电池"), ("601012", "隆基绿能", "光伏"),
        ("000333", "美的集团", "家电"), ("600276", "恒瑞医药", "医药"),
        ("002415", "海康威视", "电子"), ("000001", "平安银行", "银行"),
    ]
    import random
    return [{
        "code": s[0], "name": s[1], "industry": s[2],
        "change_pct": round(random.uniform(-5, 8), 2),
        "main_net": round(random.uniform(-50, 200), 2),
        "main_net_rate": round(random.uniform(-3, 10), 2),
    } for s in stocks[:limit]]


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
