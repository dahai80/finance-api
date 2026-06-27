from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from config import get_logger, settings
from data_provider import akshare_fetcher
from data_provider.ipo_scorer import score_ipo
from data_provider.industry_map import get_industry_heat
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
    log.info("GET /api/ipo limit=%d offset=%d status=%s search=%s", limit, offset, status, search)
    rows = await storage.list_ipo(limit=limit, offset=offset, status=status, min_score=min_score, search=search)
    total = await storage.count_ipo(status=status, min_score=min_score, search=search)
    return {"data": rows, "total": total, "limit": limit, "offset": offset}


@router.post("/sync")
async def sync_ipo() -> dict:
    log.info("POST /api/ipo/sync mock=%s", settings.akshare_mock)
    try:
        if settings.akshare_mock:
            rows = akshare_fetcher.fetch_upcoming_ipo_mock()
        else:
            rows = akshare_fetcher.fetch_upcoming_ipo_live()
        upserted = await storage.upsert_ipo(rows)

        scored = 0
        for row in rows:
            result = await _score_with_industry_heat(row)
            await storage.update_ipo_score(
                row["stock_code"], result["total"], result["recommendation"]
            )
            scored += 1

        return {
            "synced": len(rows),
            "upserted": upserted,
            "scored": scored,
            "mock": settings.akshare_mock,
        }
    except Exception as exc:
        log.exception("ipo sync failed")
        raise HTTPException(status_code=500, detail=f"sync failed: {exc}") from exc


async def _score_with_industry_heat(row: dict) -> dict:
    """Score IPO with async industry heat lookup."""
    fm = row.get("fundamental_metrics") or {}
    board_type = str(fm.get("board_type", ""))

    base_result = score_ipo(row)
    scores = base_result["scores"]

    try:
        heat_score = await get_industry_heat(board_type)
        scores["industry_heat"] = heat_score
        base_result["total"] = int(sum(scores.values()))
        if base_result["total"] >= 70:
            base_result["recommendation"] = "HIGH"
        elif base_result["total"] >= 50:
            base_result["recommendation"] = "MID"
        else:
            base_result["recommendation"] = "LOW"
    except Exception:
        log.exception("industry heat lookup failed for %s", row.get("stock_code"))

    return base_result
