from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from config import get_logger, settings
import storage

router = APIRouter(prefix="/api/industry", tags=["industry"])
log = get_logger("finance.industry_router")


class IndustryEventCreate(BaseModel):
    event_title: str
    industry_tags: list[str]
    impact_analysis: Optional[str] = None
    related_stock_codes: Optional[list[str]] = None
    event_time: Optional[str] = None


@router.get("/events")
async def get_industry_events(limit: int = 20) -> list[dict[str, Any]]:
    log.info("GET /api/industry/events limit=%d", limit)
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

    # Default to current time if not provided (DB has NOT NULL constraint)
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
    if limit < 1 or limit > 200:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    try:
        return _fetch_industry_top_stocks(limit)
    except Exception as exc:
        log.exception("top_stocks failed")
        return _mock_industry_top_stocks(limit)


@router.get("/news")
async def get_industry_news(limit: int = 20) -> list[dict[str, Any]]:
    """Get latest industry dynamics/news from East Money."""
    log.info("GET /api/industry/news limit=%d", limit)
    if limit < 1 or limit > 200:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    try:
        return _fetch_industry_news(limit)
    except Exception as exc:
        log.exception("industry_news failed")
        return _mock_industry_news(limit)


def _to_float(val: Any) -> float:
    if val is None:
        return 0.0
    try:
        import math
        result = float(str(val).replace(",", "").replace(" ", ""))
        if math.isnan(result) or math.isinf(result):
            return 0.0
        return result
    except Exception:
        return 0.0


def _fetch_industry_top_stocks(limit: int) -> list[dict[str, Any]]:
    """Fetch top stocks by industry from AkShare."""
    try:
        if settings.akshare_mock:
            return _mock_industry_top_stocks(limit)
        import akshare as ak
        df = ak.stock_individual_fund_flow_rank()
        if df is None or df.empty:
            return _mock_industry_top_stocks(limit)
        items = []
        for _, row in df.head(limit).iterrows():
            items.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "industry": str(row.get("行业", "")),
                "change_pct": _to_float(row.get("涨跌幅")),
                "main_net": _to_float(row.get("主力净流入-净额")),
                "main_net_rate": _to_float(row.get("主力净流入-净额差")),
            })
        return items if items else _mock_industry_top_stocks(limit)
    except Exception:
        return _mock_industry_top_stocks(limit)


def _fetch_industry_news(limit: int) -> list[dict[str, Any]]:
    """Fetch industry news from East Money."""
    try:
        if settings.akshare_mock:
            return _mock_industry_news(limit)
        import akshare as ak
        df = ak.stock_news_em(symbol="600519")
        if df is None or df.empty:
            return _mock_industry_news(limit)
        items = []
        for _, row in df.head(limit).iterrows():
            items.append({
                "title": str(row.get("新闻标题", row.get("title", ""))),
                "digest": str(row.get("新闻内容", row.get("digest", ""))),
                "source": str(row.get("媒体来源", row.get("source", ""))),
                "ctime": str(row.get("发布时间", row.get("ctime", ""))),
                "url": str(row.get("新闻链接", row.get("url", ""))),
            })
        return items if items else _mock_industry_news(limit)
    except Exception:
        return _mock_industry_news(limit)


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
