from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import get_logger, settings
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


@router.get("/individual-money-flow")
async def get_individual_money_flow(limit: int = 20) -> list[dict[str, Any]]:
    """Get individual stock money flow ranking with multi-source fallback."""
    log.info("GET /api/market/individual-money-flow limit=%d", limit)
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    try:
        if settings.akshare_mock:
            return _mock_individual_money_flow(limit)
        import akshare as ak
        df = ak.stock_individual_fund_flow_rank()
        if df is None or df.empty:
            return _mock_individual_money_flow(limit)
        items = []
        for _, row in df.head(limit).iterrows():
            items.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "new_rank": float(row.get("新增持仓排名", 0)),
                "main_net": _to_float(row.get("主力净流入-净额")),
                "main_net_rate": _to_float(row.get("主力净流入-净额差")),
                "large_net": _to_float(row.get("超大单净流入-净额")),
                "large_net_rate": _to_float(row.get("超大单净流入-净额差")),
            })
        return items if items else _mock_individual_money_flow(limit)
    except Exception as exc:
        log.exception("individual_money_flow failed")
        return _mock_individual_money_flow(limit)


@router.get("/quotes")
async def get_realtime_quotes(codes: str) -> dict[str, Any]:
    """Get real-time quotes for comma-separated stock codes."""
    log.info("GET /api/market/quotes codes=%s", codes)
    stock_codes = [c.strip() for c in codes.split(",") if c.strip()]
    if not stock_codes:
        return {}
    try:
        if settings.akshare_mock:
            return {code: _mock_quote(code) for code in stock_codes}
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return {code: _mock_quote(code) for code in stock_codes}
        results = {}
        for _, row in df.iterrows():
            code = str(row.get("代码", "")).strip()
            if code in stock_codes:
                results[code] = {
                    "code": code,
                    "name": str(row.get("名称", "")),
                    "price": _to_float(row.get("最新价")),
                    "open": _to_float(row.get("今开")),
                    "high": _to_float(row.get("最高")),
                    "low": _to_float(row.get("最低")),
                    "pre_close": _to_float(row.get("昨收")),
                    "change": _to_float(row.get("涨跌额")),
                    "change_pct": _to_float(row.get("涨跌幅")),
                    "volume": _to_float(row.get("成交量")),
                    "amount": _to_float(row.get("成交额")),
                }
        return results if results else {code: _mock_quote(code) for code in stock_codes}
    except Exception as exc:
        log.exception("quotes fetch failed")
        return {code: _mock_quote(code) for code in stock_codes}


def _to_float(val: Any) -> float:
    if val is None:
        return 0.0
    try:
        import math
        result = float(str(val).replace(",", "").replace(" ", ""))
        if math.isnan(result) or math.isinf(result):
            return 0.0
        return result
    except Exception:
        return 0.0


def _mock_quote(code: str) -> dict[str, Any]:
    import random
    return {
        "code": code,
        "name": "",
        "price": round(random.uniform(10, 200), 2),
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "pre_close": 0.0,
        "change": round(random.uniform(-5, 5), 2),
        "change_pct": round(random.uniform(-5, 5), 2),
        "volume": 0.0,
        "amount": 0.0,
    }


def _mock_individual_money_flow(limit: int) -> list[dict[str, Any]]:
    stocks = [
        ("600519", "贵州茅台"), ("000858", "五粮液"), ("601318", "中国平安"),
        ("000001", "平安银行"), ("600036", "招商银行"), ("002415", "海康威视"),
        ("300750", "宁德时代"), ("601012", "隆基绿能"), ("000333", "美的集团"),
        ("600276", "恒瑞医药"),
    ]
    import random
    return [{
        "code": s[0], "name": s[1],
        "new_rank": i,
        "main_net": round(random.uniform(-50, 200), 2),
        "main_net_rate": round(random.uniform(-5, 10), 2),
        "large_net": round(random.uniform(-30, 100), 2),
        "large_net_rate": round(random.uniform(-3, 8), 2),
    } for i, s in enumerate(stocks[:limit])]


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

    sentiment = _fetch_sentiment_data()
    today = date.today()
    await storage.upsert_sentiment_snapshot(
        trade_date=today,
        us_markets=sentiment.get("us_markets", {"sp500": 0.0, "nasdaq": 0.0, "dow": 0.0}),
        china_concepts_idx=sentiment.get("china_concepts", {"status": "no_data"}),
        ftse_a50=sentiment.get("ftse_a50", {"status": "no_data"}),
        prev_day_money_flow=money_flow,
    )
    return {"status": "ok", "date": today.isoformat()}


def _fetch_sentiment_data() -> dict[str, Any]:
    """Fetch market sentiment data from AkShare with mock fallback."""
    result: dict[str, Any] = {}
    try:
        if settings.akshare_mock:
            return {
                "us_markets": {"sp500": round(__import__("random").uniform(4000, 6000), 2),
                               "nasdaq": round(__import__("random").uniform(12000, 20000), 2),
                               "dow": round(__import__("random").uniform(30000, 50000), 2)},
                "china_concepts": {"kweb_close": round(__import__("random").uniform(20, 60), 2)},
                "ftse_a50": {"close": round(__import__("random").uniform(6000, 10000), 2)},
            }
        import akshare as ak
        # SP500 via ETF
        try:
            df = ak.stock_us_hist(symbol="SPY")
            if df is not None and not df.empty:
                last = df.iloc[-1]
                result["us_markets"] = {
                    "sp500": _to_float(last.get("收盘", last.get("close", 0))),
                    "sp500_change": _to_float(last.get("涨跌幅", last.get("change_pct", 0))),
                }
        except Exception:
            pass
        # KWEB for China concepts
        try:
            df = ak.stock_us_hist(symbol="KWEB")
            if df is not None and not df.empty:
                last = df.iloc[-1]
                result["china_concepts"] = {
                    "kweb_close": _to_float(last.get("收盘", last.get("close", 0))),
                    "kweb_change": _to_float(last.get("涨跌幅", last.get("change_pct", 0))),
                }
        except Exception:
            pass
        # FTSE A50 via 510050 ETF
        try:
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("代码", "")).strip()
                    if code == "510050":
                        result["ftse_a50"] = {
                            "close": _to_float(row.get("最新价", 0)),
                            "change_pct": _to_float(row.get("涨跌幅", 0)),
                        }
                        break
        except Exception:
            pass
    except Exception:
        log.exception("fetch_sentiment_data failed")
    return result


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
