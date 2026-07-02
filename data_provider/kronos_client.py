from __future__ import annotations

import math

import httpx

from config import get_logger, settings

log = get_logger("finance.kronos")


def _valid_pred(p: dict) -> bool:
    # 预测价必须为有限正数——负数/0/NaN/inf 一律丢弃，绝不把脏数据透传给客户端。
    try:
        for k in ("open", "high", "low", "close"):
            v = float(p.get(k, 0))
            if not (v > 0) or not math.isfinite(v):
                return False
        return True
    except (TypeError, ValueError):
        return False


async def predict_kline(stock_code: str, days: int = 5) -> list[dict] | None:
    # 从 kronos 微服务拉取预测 K 线，返回经校验的预测列表；服务不可用返回 None。
    # 统一从 settings 取地址/超时，避免与 config.py 的 KRONOS_URL 双源漂移。
    log.info("kronos predict: %s days=%d", stock_code, days)
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                f"{settings.kronos_url}/predict",
                json={"stock_code": stock_code, "days": days},
                timeout=settings.kronos_timeout,
            )
            res.raise_for_status()
            data = res.json()
            preds = data.get("predictions", [])
            cleaned = [p for p in preds if isinstance(p, dict) and _valid_pred(p)]
            if len(cleaned) != len(preds):
                log.warning("kronos dropped %d invalid predictions for %s", len(preds) - len(cleaned), stock_code)
            log.info("kronos response: %s -> %d/%d predictions valid", stock_code, len(cleaned), len(preds))
            return cleaned
    except httpx.ConnectError:
        log.warning("kronos not available at %s (is kronos-api running?)", settings.kronos_url)
        return None
    except Exception as exc:
        log.error("kronos predict failed: %s", exc)
        return None


async def health_check() -> bool:
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{settings.kronos_url}/health", timeout=5)
            return res.status_code == 200
    except Exception:
        return False
