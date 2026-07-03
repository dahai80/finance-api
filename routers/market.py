from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import get_logger, settings
from data_provider import kronos_client
from data_provider import multi_source_fetcher
from async_utils import spawn_background_task
import storage

router = APIRouter(prefix="/api/market", tags=["market"])
log = get_logger("finance.market")


class MarketAlertCreate(BaseModel):
    stock_code: str = Field(..., min_length=1, max_length=16)
    alert_type: str = Field(..., min_length=1, max_length=32)
    direction: int = Field(1, ge=-1, le=1)
    severity: str = Field("INFO", max_length=32)
    event_description: str = Field("", max_length=500)


def _market_phase(now: datetime | None = None) -> str:
    # A 股交易时段：9:30-11:30 / 13:00-15:00（周一至周五）
    now = now or datetime.now()
    if now.weekday() >= 5:
        return "CLOSED"
    t = now.time()
    if time(9, 30) <= t < time(11, 30) or time(13, 0) <= t < time(15, 0):
        return "TRADING"
    if time(9, 15) <= t < time(9, 30):
        return "PRE_MARKET"
    if time(11, 30) <= t < time(13, 0):
        return "LUNCH"
    return "CLOSED"


def _validate_limit(limit: int, max_val: int = 200) -> int:
    """Validate and clamp limit parameter."""
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    return min(limit, max_val)


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


@router.get("/money-flow")
async def get_money_flow(limit: int = 30) -> list[dict]:
    log.info("GET /api/market/money-flow limit=%d", limit)
    limit = _validate_limit(limit, max_val=100)
    return await storage.get_live_money_flow(limit=limit)


@router.get("/individual-money-flow")
async def get_individual_money_flow(limit: int = 20) -> dict[str, Any]:
    """Get individual stock money flow ranking with multi-source fallback.

    Cache-first: 命中缓存 <10ms 返回；缓存为空或过期(>60s)时立即返回当前数据
    并触发后台刷新。东财接口被代理阻断时首次重试需 1-2s，缓存把该延迟
    从用户请求路径上移除，保证生产时延稳定 sub-second。
    Returns {data: [...], source: "real"|"mock", ok: true}.
    """
    log.info("GET /api/market/individual-money-flow limit=%d", limit)
    limit = _validate_limit(limit)
    try:
        cached = multi_source_fetcher.get_cached_individual_money_flow(limit)
        if not cached["data"] or cached["stale"]:
            spawn_background_task(multi_source_fetcher.arefresh_individual_money_flow_cache(20), "individual_money_flow")
        if cached["data"]:
            source = "mock" if cached["is_mock"] else "real"
            return {"data": cached["data"], "source": source, "ok": True}
        # 缓存为空（冷启动）：立即返回 mock 并标注 ok=False，绝不阻塞用户请求
        # 等待东财重试。后台任务会在 60s 内填充真实/缓存数据供后续请求使用。
        return {"data": _mock_individual_money_flow(limit), "source": "mock", "ok": False}
    except Exception as exc:
        log.exception("individual_money_flow failed")
        return {"data": _mock_individual_money_flow(limit), "source": "mock", "ok": False}


@router.get("/quotes")
async def get_realtime_quotes(codes: str) -> dict[str, Any]:
    """Get real-time quotes for comma-separated stock codes.

    Example: GET /api/market/quotes?codes=600519,000001
    Max 50 codes per request.
    """
    log.info("GET /api/market/quotes codes=%s", codes)
    stock_codes = [c.strip() for c in codes.split(",") if c.strip()]
    if not stock_codes:
        return {}
    if len(stock_codes) > 50:
        raise HTTPException(status_code=400, detail="max 50 codes per request")

    # Validate code format (6 digits for A-shares)
    for code in stock_codes:
        if len(code) != 6 or not code.isdigit():
            raise HTTPException(status_code=400, detail=f"invalid stock code: {code}")

    try:
        quotes = await multi_source_fetcher.afetch_realtime_quotes(stock_codes)
        # NEVER fall back to mock/random prices — stock price accuracy is critical.
        # Return whatever real quotes were obtained (possibly partial/empty).
        return quotes
    except Exception as exc:
        log.exception("quotes fetch failed")
        return {}


@router.get("/alerts")
async def get_alerts(
    limit: int = 50,
    severity: str | None = None,
    is_handled: bool | None = None,
) -> list[dict[str, Any]]:
    """Get market alerts from fc_market_alerts table."""
    log.info("GET /api/market/alerts limit=%d severity=%s handled=%s", limit, severity, is_handled)
    limit = _validate_limit(limit, max_val=200)
    return await storage.get_market_alerts(limit=limit, severity=severity, is_handled=is_handled)


@router.post("/alerts")
async def create_alert(alert: MarketAlertCreate) -> dict[str, Any]:
    """Create a market alert in fc_market_alerts table."""
    log.info("POST /api/market/alerts code=%s type=%s severity=%s", alert.stock_code, alert.alert_type, alert.severity)
    alert_id = await storage.insert_market_alert(
        stock_code=alert.stock_code,
        alert_type=alert.alert_type,
        direction=alert.direction,
        severity=alert.severity,
        event_description=alert.event_description,
    )
    return {"alert_id": alert_id}


@router.get("/sentiment")
async def get_sentiment() -> dict[str, Any]:
    """Get market sentiment from fc_market_sentiment_snapshot + live data."""
    log.info("GET /api/market/sentiment")

    snapshot = await storage.get_sentiment_snapshot()
    money_flow = await storage.get_live_money_flow(limit=10)
    high_score = await storage.get_ipo_by_score(min_score=70, limit=5)

    # top_outflow 需与 top_inflow 不重叠：资金流按 flow 降序，至少 6 条才能取末 3 条
    result: dict[str, Any] = {
        "top_inflow": money_flow[:3] if money_flow else [],
        "top_outflow": money_flow[-3:] if len(money_flow) >= 6 else [],
        "high_score_ipos": high_score,
        # market_phase 用实际交易时段判断，不依赖 money_flow 是否为空（Redis 空不代表盘前）
        "market_phase": _market_phase(),
    }

    if snapshot:
        result["snapshot_date"] = snapshot.get("trade_date")
        result["us_markets"] = snapshot.get("us_markets", {})
        result["china_concepts"] = snapshot.get("china_concepts_idx", {})
        result["ftse_a50"] = snapshot.get("ftse_a50", {})
        result["prev_day_flow"] = snapshot.get("prev_day_money_flow", [])

    return result


@router.post("/sentiment/snapshot")
async def save_sentiment_snapshot() -> dict[str, Any]:
    """Capture and persist today's market sentiment snapshot."""
    log.info("POST /api/market/sentiment/snapshot")
    money_flow = await storage.get_live_money_flow(limit=10)

    sentiment = await multi_source_fetcher.afetch_sentiment()
    today = date.today()
    await storage.upsert_sentiment_snapshot(
        trade_date=today,
        us_markets=sentiment.get("us_markets", {"status": "no_data"}),
        china_concepts_idx=sentiment.get("china_concepts", {"status": "no_data"}),
        ftse_a50=sentiment.get("ftse_a50", {"status": "no_data"}),
        prev_day_money_flow=money_flow,
    )
    return {"status": "ok", "date": today.isoformat()}


@router.get("/kline/predict")
async def get_kline_prediction(stock_code: str, days: int = 5) -> dict[str, Any]:
    log.info("GET /api/market/kline/predict stock=%s days=%d", stock_code, days)
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    predictions = await kronos_client.predict_kline(stock_code, days)
    if predictions is None:
        raise HTTPException(status_code=503, detail="kronos service unavailable")
    return {"stock_code": stock_code, "predictions": predictions}


@router.get("/kronos/health")
async def kronos_health() -> dict[str, str]:
    ok = await kronos_client.health_check()
    return {"status": "ok" if ok else "unavailable"}


@router.get("/snapshots")
async def get_stock_snapshots(
    stock_code: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get stock snapshots from fc_stock_snapshot."""
    log.info("GET /api/market/snapshots code=%s status=%s limit=%d", stock_code, status, limit)
    limit = _validate_limit(limit, max_val=200)
    return await storage.get_stock_snapshots(stock_code=stock_code, status=status, limit=limit)


@router.post("/trigger/money-flow")
async def trigger_money_flow() -> dict[str, Any]:
    """Manually trigger money flow data fetch with multi-source fallback."""
    log.info("POST /api/market/trigger/money-flow")
    try:
        items = await multi_source_fetcher.afetch_money_flow()
        if not items:
            return {"status": "degraded", "count": 0, "message": "no data returned from any source"}
        ok = await storage.replace_live_money_flow(items)
        if not ok:
            # fetch 成功但写 Redis 失败——如实报告 degraded，不谎报 ok
            return {"status": "degraded", "count": len(items), "message": "fetch ok but redis write failed"}
        log.info("trigger money_flow: refreshed %d sectors", len(items))
        return {"status": "ok", "count": len(items)}
    except Exception:
        log.exception("trigger money_flow failed")
        return {"status": "error", "message": "trigger_money_flow failed"}


@router.post("/trigger/sentiment")
async def trigger_sentiment() -> dict[str, Any]:
    """Manually trigger premarket sentiment data fetch with multi-source fallback."""
    log.info("POST /api/market/trigger/sentiment")
    try:
        sentiment = await multi_source_fetcher.afetch_sentiment()
        prev_flow = await storage.get_live_money_flow(20)
        individual_flow, _ = await multi_source_fetcher.afetch_individual_money_flow(20)

        await storage.upsert_sentiment_snapshot(
            trade_date=date.today(),
            us_markets=sentiment.get("us_markets", {"status": "no_data"}),
            china_concepts_idx=sentiment.get("china_concepts", {"status": "no_data"}),
            ftse_a50=sentiment.get("ftse_a50", {"status": "no_data"}),
            prev_day_money_flow=prev_flow,
            prev_day_individual_flow=individual_flow,
        )
        log.info("trigger sentiment: snapshot saved for %s", date.today())
        return {"status": "ok", "date": date.today().isoformat()}
    except Exception:
        log.exception("trigger sentiment failed")
        return {"status": "error", "message": "trigger_sentiment failed"}


@router.post("/trigger/all")
async def trigger_all() -> dict[str, Any]:
    """Manually trigger money flow + sentiment data fetch."""
    log.info("POST /api/market/trigger/all")
    mf_result = await trigger_money_flow()
    sent_result = await trigger_sentiment()
    return {"money_flow": mf_result, "sentiment": sent_result}


# ── Mock Data ───────────────────────────────────────────────────────────
# NOTE: No mock for quotes — stock prices must never be fabricated.

def _mock_individual_money_flow(limit: int) -> list[dict[str, Any]]:
    """Fallback mock — field names MUST match the live fetcher and frontend
    (stock_code/stock_name/main_net_inflow) so the dashboard renders consistently."""
    stocks = [
        ("600519", "贵州茅台"), ("000858", "五粮液"), ("601318", "中国平安"),
        ("000001", "平安银行"), ("600036", "招商银行"), ("002415", "海康威视"),
        ("300750", "宁德时代"), ("601012", "隆基绿能"), ("000333", "美的集团"),
        ("600276", "恒瑞医药"),
    ]
    import random
    return [{
        "stock_code": s[0],
        "stock_name": s[1],
        "main_net_inflow": round(random.uniform(-50000000, 200000000), 2),
    } for s in stocks[:limit]]
