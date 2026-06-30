from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from config import get_logger
import storage
from data_provider import watchlist_fetcher

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])
log = get_logger("finance.watchlist")


class WatchlistAddRequest(BaseModel):
    stock_code: str = Field(..., min_length=1)
    stock_name: str = ""
    note: str | None = None


# ── Routes without path params first (avoids {stock_code} conflicts) ──

@router.get("")
async def list_watchlist() -> list[dict[str, Any]]:
    """List all watched stocks."""
    return await storage.get_watchlist()


@router.post("")
async def add_to_watchlist(req: WatchlistAddRequest) -> dict[str, Any]:
    """Add a stock to the watchlist."""
    wid = await storage.add_to_watchlist(
        stock_code=req.stock_code,
        stock_name=req.stock_name or "",
        note=req.note,
    )
    item = await storage.get_watchlist_item(req.stock_code)
    return item or {"id": wid, "stock_code": req.stock_code}


@router.get("/search")
async def search_stocks(q: str = "") -> list[dict[str, Any]]:
    """Search A-share stocks by code or Chinese name."""
    if not q or len(q) < 1:
        return []
    results = watchlist_fetcher.search_stock(q)
    return results


@router.post("/refresh-all")
async def refresh_all_watchlist(days: int = Query(90, ge=1, le=365)) -> dict[str, Any]:
    """Force-refresh all watched stocks."""
    items = await storage.get_watchlist()
    updated = 0
    for it in items:
        code = it["stock_code"]
        try:
            detail = await watchlist_fetcher.build_detail(code, days=days)
            await storage.update_watchlist_cache(code, detail)
            updated += 1
        except Exception:
            log.exception("refresh-all failed for %s", code)
    return {"total": len(items), "updated": updated}


# ── Routes with {stock_code} path param ──

@router.delete("/{stock_code}")
async def remove_from_watchlist(stock_code: str) -> dict[str, Any]:
    """Remove a stock from the watchlist."""
    ok = await storage.remove_from_watchlist(stock_code)
    if not ok:
        raise HTTPException(404, f"Stock {stock_code} not in watchlist")
    return {"removed": stock_code}


@router.get("/{stock_code}/detail")
async def watchlist_detail(
    stock_code: str,
    days: int = Query(90, ge=1, le=365),
) -> dict[str, Any]:
    """Get full 5-dimension detail for a watched stock (cache-first, live refresh if stale)."""
    item = await storage.get_watchlist_item(stock_code)
    now = datetime.utcnow()

    if item and item.get("cached_details") and item.get("cached_at"):
        cached_at = item["cached_at"]
        if isinstance(cached_at, str):
            try:
                cached_at = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
                # Make timezone-naive for comparison
                cached_at = cached_at.replace(tzinfo=None)
            except Exception:
                cached_at = None
        elif hasattr(cached_at, "replace"):
            # Remove timezone info if present
            cached_at = cached_at.replace(tzinfo=None)
        if cached_at and (now - cached_at) < timedelta(hours=2):
            return item["cached_details"]

    detail = await watchlist_fetcher.build_detail(stock_code, days=days)
    await storage.update_watchlist_cache(stock_code, detail)
    return detail


@router.post("/{stock_code}/refresh")
async def refresh_watchlist_item(
    stock_code: str,
    days: int = Query(90, ge=1, le=365),
) -> dict[str, Any]:
    """Force-refresh a single watched stock's detail data."""
    detail = await watchlist_fetcher.build_detail(stock_code, days=days)
    await storage.update_watchlist_cache(stock_code, detail)
    return detail
