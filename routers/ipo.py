from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from config import get_logger, settings
from data_provider import akshare_fetcher
from data_provider.ipo_scorer import score_ipo
from data_provider.industry_map import get_industry_heat
from async_utils import call_with_timeout
import storage

router = APIRouter(prefix="/api/ipo", tags=["ipo"])
log = get_logger("finance.ipo")


@router.get("")
async def list_ipo(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    min_score: int | None = None,
    search: str | None = None,
) -> dict:
    # Bound inputs to protect the DB from unbounded result sets / negative
    # offsets. Search is capped so a huge pattern can't blow up ILIKE.
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    if min_score is not None:
        min_score = max(0, min(int(min_score), 100))
    if search is not None:
        search = search.strip()[:64] or None
    if status is not None:
        status = status.strip()[:32] or None
    log.info("GET /api/ipo limit=%d offset=%d status=%s search=%s", limit, offset, status, search)
    rows = await storage.list_ipo(limit=limit, offset=offset, status=status, min_score=min_score, search=search)
    total = await storage.count_ipo(status=status, min_score=min_score, search=search)
    return {"data": rows, "total": total, "limit": limit, "offset": offset}


@router.post("/sync")
async def sync_ipo() -> dict:
    log.info("POST /api/ipo/sync mock=%s", settings.akshare_mock)
    try:
        loop = asyncio.get_running_loop()
        if settings.akshare_mock:
            rows = akshare_fetcher.fetch_upcoming_ipo_mock()
        else:
            rows = await loop.run_in_executor(
                None, call_with_timeout, akshare_fetcher.fetch_upcoming_ipo_live, 20.0
            )
        upserted = await storage.upsert_ipo(rows)

        scored = 0
        for row in rows:
            try:
                result = await _score_with_industry_heat(row)
                await storage.update_ipo_score(
                    row["stock_code"], result["total"], result["recommendation"]
                )
                scored += 1
            except Exception:
                log.exception("ipo sync: score failed for %s", row.get("stock_code"))

        return {
            "synced": len(rows),
            "upserted": upserted,
            "scored": scored,
            "mock": settings.akshare_mock,
        }
    except Exception:
        log.exception("ipo sync failed")
        raise HTTPException(status_code=500, detail="ipo sync failed") from None


async def _score_with_industry_heat(row: dict) -> dict:
    """Score IPO with async industry heat lookup."""
    fm = row.get("fundamental_metrics") or {}
    board_type = str(fm.get("board_type", ""))

    base_result = score_ipo(row)
    scores = base_result["scores"]

    try:
        heat_score = await get_industry_heat(board_type)
        scores["industry_heat"] = heat_score
        # 与 ipo_scorer.score_ipo 保持一致：四舍五入而非截断，避免同一 IPO 经不同入口评分不一致
        base_result["total"] = int(round(sum(scores.values())))
        if base_result["total"] >= 70:
            base_result["recommendation"] = "HIGH"
        elif base_result["total"] >= 50:
            base_result["recommendation"] = "MID"
        else:
            base_result["recommendation"] = "LOW"
    except Exception:
        log.exception("industry heat lookup failed for %s", row.get("stock_code"))

    return base_result
