from __future__ import annotations

from fastapi import APIRouter, HTTPException

from config import get_logger
from data_provider import kronos_client
import storage

router = APIRouter(prefix="/api/market", tags=["market"])
log = get_logger("finance.market")


@router.get("/money-flow")
async def get_money_flow(limit: int = 30) -> list[dict]:
    log.info("GET /api/market/money-flow limit=%d", limit)
    return await storage.get_live_money_flow(limit=limit)


@router.get("/alerts")
async def get_alerts(min_score: int = 60, limit: int = 20) -> list[dict]:
    log.info("GET /api/market/alerts min_score=%d limit=%d", min_score, limit)
    return await storage.get_ipo_by_score(min_score=min_score, limit=limit)


@router.get("/sentiment")
async def get_sentiment() -> dict:
    log.info("GET /api/market/sentiment")
    money_flow = await storage.get_live_money_flow(limit=10)
    high_score = await storage.get_ipo_by_score(min_score=70, limit=5)
    top_inflow = money_flow[:3] if money_flow else []
    top_outflow = money_flow[-3:] if len(money_flow) >= 3 else []
    return {
        "top_inflow": top_inflow,
        "top_outflow": top_outflow,
        "high_score_ipos": high_score,
        "market_phase": "PRE_MARKET" if not money_flow else "TRADING",
    }


@router.get("/kline/predict")
async def get_kline_prediction(stock_code: str, days: int = 5) -> dict:
    log.info("GET /api/market/kline/predict stock=%s days=%d", stock_code, days)
    predictions = await kronos_client.predict_kline(stock_code, days)
    if predictions is None:
        raise HTTPException(status_code=503, detail="kronos service unavailable")
    return {"stock_code": stock_code, "predictions": predictions}


@router.get("/kronos/health")
async def kronos_health() -> dict:
    ok = await kronos_client.health_check()
    return {"status": "ok" if ok else "unavailable"}
