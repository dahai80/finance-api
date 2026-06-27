from __future__ import annotations

from fastapi import APIRouter

from config import get_logger
from data_provider import backtest_engine

router = APIRouter(prefix="/api/backtest", tags=["backtest"])
log = get_logger("finance.backtest_router")


@router.get("/accuracy")
async def get_accuracy(days: int = 30) -> list[dict]:
    log.info("GET /api/backtest/accuracy days=%d", days)
    return await backtest_engine.get_backtest_accuracy(days)
