from __future__ import annotations

from fastapi import APIRouter, HTTPException

from config import get_logger, settings
from data_provider import akshare_fetcher
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
        return {"synced": len(rows), "upserted": upserted, "mock": settings.akshare_mock}
    except Exception as exc:
        log.exception("ipo sync failed")
        raise HTTPException(status_code=500, detail=f"sync failed: {exc}") from exc
