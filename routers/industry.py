from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from config import get_logger
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
