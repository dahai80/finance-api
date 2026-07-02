from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from config import get_logger
import storage
from data_provider import watchlist_fetcher
from data_provider import multi_source_fetcher

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
    """Get full 5-dimension detail for a watched stock (cache-first, live refresh if stale).

    Cache 保流畅性（避免每次重建五维），但 current_price 必须实时——
    股价不能有一点差池。命中缓存时用 Sina 实时价覆盖 current_price 并
    重算 change_pct，既快又准。
    """
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
            detail = dict(item["cached_details"])
            return await _overlay_live_price(detail, stock_code)

    detail = await watchlist_fetcher.build_detail(stock_code, days=days)
    await storage.update_watchlist_cache(stock_code, detail)
    return detail


async def _overlay_live_price(detail: dict[str, Any], stock_code: str) -> dict[str, Any]:
    """用 Sina 实时价覆盖 detail.current_price 并重算 change_pct。

    缓存命中时调用：缓存的 current_price 可能已过时（最长 2h），故默认标记
    price_live=False，仅在本次成功取到鲜活正价时置 True。取价失败则保留缓存值
    但如实标记非实时——宁可显示稍旧的真实价，也不把旧价谎报为实时。
    """
    detail["price_live"] = False
    try:
        quotes = await multi_source_fetcher.afetch_realtime_quotes([stock_code])
        q = quotes.get(stock_code)
        if q and q.get("price") is not None:
            live_price = float(q["price"])
            if live_price <= 0:
                log.warning("watchlist overlay non-positive live price for %s: %s", stock_code, live_price)
                detail["ok"] = (detail.get("source") != "mock") and detail["price_live"]
                return detail
            detail["current_price"] = live_price
            detail["price_live"] = True
            start_price = detail.get("price_history", {}).get("summary", {}).get("start_price")
            if start_price and start_price > 0:
                detail["change_pct"] = round((live_price - start_price) / start_price * 100, 2)
            else:
                log.warning("watchlist overlay invalid start_price for %s: %s", stock_code, start_price)
                detail["change_pct"] = 0.0
    except Exception as exc:
        log.warning("watchlist detail live price overlay failed for %s: %s", stock_code, exc)
    detail["ok"] = (detail.get("source") != "mock") and detail["price_live"]
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
