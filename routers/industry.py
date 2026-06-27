from __future__ import annotations

from fastapi import APIRouter

from config import get_logger
import storage

router = APIRouter(prefix="/api/industry", tags=["industry"])
log = get_logger("finance.industry_router")


@router.get("/events")
async def get_industry_events(limit: int = 20) -> list[dict]:
    log.info("GET /api/industry/events limit=%d", limit)
    return await storage.get_industry_events(limit)


@router.post("/events")
async def add_industry_event(
    event_title: str,
    industry_tags: list[str],
    impact_analysis: str | None = None,
    related_stock_codes: list[str] | None = None,
    event_time: str | None = None,
) -> dict:
    log.info("POST /api/industry/events title=%s", event_title)
    import json as _json
    from datetime import datetime

    time_val = event_time and datetime.fromisoformat(event_time)
    evt_id = await storage.insert_industry_event(
        event_title=event_title,
        industry_tags=industry_tags,
        impact_analysis=impact_analysis,
        related_stock_codes=related_stock_codes or [],
        event_time=time_val,
    )
    return {"event_id": evt_id}
