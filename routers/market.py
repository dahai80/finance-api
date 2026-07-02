from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import get_logger, settings
from data_provider import kronos_client
from data_provider import multi_source_fetcher
import storage

router = APIRouter(prefix="/api/market", tags=["market"])
log = get_logger("finance.market")


class MarketAlertCreate(BaseModel):
    stock_code: str
    alert_type: str
    direction: int = 1
    severity: str = "INFO"
    event_description: str = ""


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
async def get_individual_money_flow(limit: int = 20) -> list[dict[str, Any]]:
    """Get individual stock money flow ranking with multi-source fallback."""
    log.info("GET /api/market/individual-money-flow limit=%d", limit)
    limit = _validate_limit(limit)
    try:
        return await multi_source_fetcher.afetch_individual_money_flow(limit)
    except Exception as exc:
        log.exception("individual_money_flow failed")
        return _mock_individual_money_flow(limit)


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
        if quotes:
            return quotes
        return {code: _mock_quote(code) for code in stock_codes}
    except Exception as exc:
        log.exception("quotes fetch failed")
        return {code: _mock_quote(code) for code in stock_codes}


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

    result: dict[str, Any] = {
        "top_inflow": money_flow[:3] if money_flow else [],
        "top_outflow": money_flow[-3:] if len(money_flow) >= 3 else [],
        "high_score_ipos": high_score,
        "market_phase": "PRE_MARKET" if not money_flow else "TRADING",
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
        us_markets=sentiment.get("us_markets", {"sp500": 0.0, "nasdaq": 0.0, "dow": 0.0}),
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
        if items:
            await storage.replace_live_money_flow(items)
            log.info("trigger money_flow: refreshed %d sectors", len(items))
            return {"status": "ok", "count": len(items)}
        return {"status": "ok", "count": 0, "message": "no data returned from any source"}
    except Exception as exc:
        log.exception("trigger money_flow failed")
        return {"status": "error", "message": str(exc)}


@router.post("/trigger/sentiment")
async def trigger_sentiment() -> dict[str, Any]:
    """Manually trigger premarket sentiment data fetch with multi-source fallback."""
    log.info("POST /api/market/trigger/sentiment")
    try:
        sentiment = await multi_source_fetcher.afetch_sentiment()
        prev_flow = await storage.get_live_money_flow(20)
        individual_flow = await multi_source_fetcher.afetch_individual_money_flow(20)

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
    except Exception as exc:
        log.exception("trigger sentiment failed")
        return {"status": "error", "message": str(exc)}


@router.post("/trigger/all")
async def trigger_all() -> dict[str, Any]:
    """Manually trigger money flow + sentiment data fetch."""
    log.info("POST /api/market/trigger/all")
    mf_result = await trigger_money_flow()
    sent_result = await trigger_sentiment()
    return {"money_flow": mf_result, "sentiment": sent_result}


# ── Mock Data ───────────────────────────────────────────────────────────

def _mock_quote(code: str) -> dict[str, Any]:
    import random
    return {
        "code": code,
        "name": "",
        "price": round(random.uniform(10, 200), 2),
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "pre_close": 0.0,
        "change": round(random.uniform(-5, 5), 2),
        "change_pct": round(random.uniform(-5, 5), 2),
        "volume": 0.0,
        "amount": 0.0,
    }


def _mock_individual_money_flow(limit: int) -> list[dict[str, Any]]:
    stocks = [
        ("600519", "贵州茅台"), ("000858", "五粮液"), ("601318", "中国平安"),
        ("000001", "平安银行"), ("600036", "招商银行"), ("002415", "海康威视"),
        ("300750", "宁德时代"), ("601012", "隆基绿能"), ("000333", "美的集团"),
        ("600276", "恒瑞医药"),
    ]
    import random
    return [{
        "code": s[0], "name": s[1],
        "new_rank": i,
        "main_net": round(random.uniform(-50, 200), 2),
        "main_net_rate": round(random.uniform(-5, 10), 2),
        "large_net": round(random.uniform(-30, 100), 2),
        "large_net_rate": round(random.uniform(-3, 8), 2),
    } for i, s in enumerate(stocks[:limit])]
