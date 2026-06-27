from __future__ import annotations

import os

import httpx

from config import get_logger

log = get_logger("finance.kronos")

KRONOS_BASE = os.environ.get("FINANCE_KRONOS_BASE_URL", "http://localhost:8001")
KRONOS_TIMEOUT = float(os.environ.get("FINANCE_KRONOS_TIMEOUT", "15"))


async def predict_kline(stock_code: str, days: int = 5) -> list[dict] | None:
    """
    Fetch predicted K-line data from facecat-kronos microservice.
    Returns list of {date, open, high, low, close} or None if unavailable.
    """
    log.info("kronos predict: %s days=%d", stock_code, days)
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{KRONOS_BASE}/predict",
                json={"stock_code": stock_code, "days": days},
                timeout=KRONOS_TIMEOUT,
            )
            res.raise_for_status()
            data = res.json()
            predictions = data.get("predictions", [])
            log.info("kronos response: %s -> %d predictions", stock_code, len(predictions))
            return predictions
    except httpx.ConnectError:
        log.warning("kronos not available at %s (is kronos-api running?)", KRONOS_BASE)
        return None
    except Exception as exc:
        log.error("kronos predict failed: %s", exc)
        return None


async def health_check() -> bool:
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{KRONOS_BASE}/health", timeout=5)
            return res.status_code == 200
    except Exception:
        return False
