from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import get_logger
from data_provider import kronos_client
import storage

router = APIRouter(prefix="/api/market", tags=["market"])
log = get_logger("finance.market")


class MarketAlertCreate(BaseModel):
    stock_code: str
    alert_type: str
    direction: int = 1
    severity: str = "INFO"
    event_description: str = ""


@router.get("/money-flow")
async def get_money_flow(limit: int = 30) -> list[dict]:
    log.info("GET /api/market/money-flow limit=%d", limit)
    return await storage.get_live_money_flow(limit=limit)


@router.get("/alerts")
async def get_alerts(
    limit: int = 50,
    severity: str | None = None,
    is_handled: bool | None = None,
) -> list[dict[str, Any]]:
    """Get market alerts from fc_market_alerts table."""
    log.info("GET /api/market/alerts limit=%d severity=%s handled=%s", limit, severity, is_handled)
    return await storage.get_market_alerts(limit=limit, severity=severity, is_handled=is_handled)


@router.post("/alerts")
async def create_alert(alert: MarketAlertCreate) -> dict[str, Any]:
    """Create a market alert in fc_market_alerts table."""
    log.info("POST /api/market/alerts code=%s type=%s severity=%s", alert.stock_code, alert.alert_type, alert.severity)
    alert_id = await storage.insert_market_alert(
        stock_code=alert.stock_code,
        alert_type=alert.alert_type,
        direction=alert.direction,
        severity=alert.severity,
        event_description=alert.event_description,
    )
    return {"alert_id": alert_id}


@router.get("/sentiment")
async def get_sentiment() -> dict[str, Any]:
    """Get market sentiment from fc_market_sentiment_snapshot + live data."""
    log.info("GET /api/market/sentiment")

    # Try to get persisted snapshot first
    snapshot = await storage.get_sentiment_snapshot()

    # Always include live money flow context
    money_flow = await storage.get_live_money_flow(limit=10)
    high_score = await storage.get_ipo_by_score(min_score=70, limit=5)

    result: dict[str, Any] = {
        "top_inflow": money_flow[:3] if money_flow else [],
        "top_outflow": money_flow[-3:] if len(money_flow) >= 3 else [],
        "high_score_ipos": high_score,
        "market_phase": "PRE_MARKET" if not money_flow else "TRADING",
    }

    # Merge persisted snapshot data if available
    if snapshot:
        result["snapshot_date"] = snapshot.get("trade_date")
        result["us_markets"] = snapshot.get("us_markets", {})
        result["china_concepts"] = snapshot.get("china_concepts_idx", {})
        result["ftse_a50"] = snapshot.get("ftse_a50", {})
        result["prev_day_flow"] = snapshot.get("prev_day_money_flow", [])

    return result


@router.post("/sentiment/snapshot")
async def save_sentiment_snapshot() -> dict[str, Any]:
    """Capture and persist today's market sentiment snapshot."""
    log.info("POST /api/market/sentiment/snapshot")
    money_flow = await storage.get_live_money_flow(limit=10)

    today = date.today()
    await storage.upsert_sentiment_snapshot(
        trade_date=today,
        us_markets={"sp500": 0.0, "nasdaq": 0.0, "dow": 0.0},
        china_concepts_idx={"k金龙": 0.0},
        ftse_a50={"change_pct": 0.0},
        prev_day_money_flow=money_flow,
    )
    return {"status": "ok", "date": today.isoformat()}


@router.get("/kline/predict")
async def get_kline_prediction(stock_code: str, days: int = 5) -> dict[str, Any]:
    log.info("GET /api/market/kline/predict stock=%s days=%d", stock_code, days)
    predictions = await kronos_client.predict_kline(stock_code, days)
    if predictions is None:
        raise HTTPException(status_code=503, detail="kronos service unavailable")
    return {"stock_code": stock_code, "predictions": predictions}


@router.get("/kronos/health")
async def kronos_health() -> dict[str, str]:
    ok = await kronos_client.health_check()
    return {"status": "ok" if ok else "unavailable"}


@router.get("/snapshots")
async def get_stock_snapshots(
    stock_code: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get stock snapshots from fc_stock_snapshot."""
    log.info("GET /api/market/snapshots code=%s status=%s limit=%d", stock_code, status, limit)
    return await storage.get_stock_snapshots(stock_code=stock_code, status=status, limit=limit)


@router.post("/trigger/money-flow")
async def trigger_money_flow() -> dict[str, Any]:
    """Manually trigger money flow data fetch."""
    log.info("POST /api/market/trigger/money-flow")
    try:
        import akshare as ak

        df = ak.stock_fund_flow_industry()
        if df is not None and not df.empty:
            items = []
            for _, row in df.iterrows():
                sector = str(row.get("行业", row.get("行业名称", "")))
                flow_val = row.get("净额") or row.get("实际流入资金", 0)
                try:
                    flow = float(str(flow_val).replace(",", ""))
                except Exception:
                    flow = 0.0
                items.append({"sector": sector, "flow": flow})
            if items:
                await storage.replace_live_money_flow(items)
                log.info("trigger money_flow: refreshed %d sectors", len(items))
                return {"status": "ok", "count": len(items)}
        return {"status": "ok", "count": 0, "message": "no data returned from AkShare"}
    except Exception as exc:
        log.exception("trigger money_flow failed")
        return {"status": "error", "message": str(exc)}


@router.post("/trigger/sentiment")
async def trigger_sentiment() -> dict[str, Any]:
    """Manually trigger premarket sentiment data fetch."""
    log.info("POST /api/market/trigger/sentiment")
    try:
        import akshare as ak
        from datetime import date

        us_markets: dict[str, Any] = {}
        china_concepts: dict[str, Any] = {}
        ftse_a50: dict[str, Any] = {}

        # SPY (US market proxy)
        try:
            df = ak.stock_us_index_daily(symbol="SPY")
            if df is not None and not df.empty:
                last = df.iloc[-1]
                us_markets["spy_close"] = float(last.get("收盘", last.get("close", 0)))
                us_markets["spy_change"] = float(last.get("涨跌幅", last.get("change_pct", 0)))
        except Exception:
            pass

        # KWEB (China concept stocks ETF)
        try:
            df = ak.stock_us_hist(symbol="KWEB")
            if df is not None and not df.empty:
                last = df.iloc[-1]
                china_concepts["kweb_close"] = float(last.get("收盘", last.get("close", 0)))
                china_concepts["kweb_change"] = float(last.get("涨跌幅", last.get("change_pct", 0)))
        except Exception:
            pass

        # FTSE China A50 (ETF code: 510050)
        try:
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("代码", "")).strip()
                    if code == "510050":
                        ftse_a50["close"] = float(row.get("最新价", 0))
                        ftse_a50["change_pct"] = float(row.get("涨跌幅", 0))
                        ftse_a50["name"] = str(row.get("名称", "A50"))
                        break
        except Exception:
            pass

        prev_flow = await storage.get_live_money_flow(20)

        await storage.upsert_sentiment_snapshot(
            trade_date=date.today(),
            us_markets=us_markets or {"status": "no_data"},
            china_concepts_idx=china_concepts or {"status": "no_data"},
            ftse_a50=ftse_a50 or {"status": "no_data"},
            prev_day_money_flow=prev_flow,
        )
        log.info("trigger sentiment: snapshot saved for %s", date.today())
        return {"status": "ok", "date": date.today().isoformat()}
    except Exception as exc:
        log.exception("trigger sentiment failed")
        return {"status": "error", "message": str(exc)}


@router.post("/trigger/all")
async def trigger_all() -> dict[str, Any]:
    """Manually trigger money flow + sentiment data fetch."""
    log.info("POST /api/market/trigger/all")
    mf_result = await trigger_money_flow()
    sent_result = await trigger_sentiment()
    return {"money_flow": mf_result, "sentiment": sent_result}
