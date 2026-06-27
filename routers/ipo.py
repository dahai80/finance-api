from __future__ import annotations

from fastapi import APIRouter, HTTPException

from config import get_logger, settings
from data_provider import akshare_fetcher
from data_provider.ipo_scorer import score_ipo
import storage

router = APIRouter(prefix="/api/ipo", tags=["ipo"])
log = get_logger("finance.ipo")


@router.get("")
async def list_ipo(limit: int = 50) -> list[dict]:
    log.info("GET /api/ipo limit=%d", limit)
    return await storage.list_ipo(limit=limit)


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
            result = score_ipo(row)
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
