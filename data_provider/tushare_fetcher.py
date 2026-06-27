from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from config import get_logger, settings

log = get_logger("finance.tushare")


def _to_float(val: Any) -> float:
    if val is None:
        return 0.0
    try:
        result = float(str(val).replace(",", "").replace(" ", ""))
        if math.isnan(result) or math.isinf(result):
            return 0.0
        return result
    except Exception:
        return 0.0


def _get_pro():
    """Get tushare pro API instance."""
    try:
        import tushare as ts
        token = settings.tushare_token
        if not token:
            log.warning("TUSHARE_TOKEN not set, returning None")
            return None
        ts.set_token(token)
        return ts.pro_api()
    except ImportError:
        log.warning("tushare not installed")
        return None


def fetch_daily_kline(stock_code: str, days: int = 30) -> list[dict[str, Any]]:
    """Fetch historical daily K-line data from Tushare."""
    pro = _get_pro()
    if not pro:
        return []

    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        df = pro.daily(
            ts_code=stock_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            results.append({
                "trade_date": str(row.get("trade_date", "")),
                "open": _to_float(row.get("open")),
                "high": _to_float(row.get("high")),
                "low": _to_float(row.get("low")),
                "close": _to_float(row.get("close")),
                "vol": _to_float(row.get("vol")),
                "pct_chg": _to_float(row.get("pct_chg")),
            })
        log.info("fetched %d kline records for %s", len(results), stock_code)
        return results
    except Exception:
        log.exception("fetch_daily_kline failed for %s", stock_code)
        return []


def fetch_money_flow_history(days: int = 30) -> list[dict[str, Any]]:
    """Fetch historical money flow data from Tushare."""
    pro = _get_pro()
    if not pro:
        return []

    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        df = pro.moneyflow(
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            results.append({
                "trade_date": str(row.get("trade_date", "")),
                "code": str(row.get("ts_code", "")),
                "lrg_amount": _to_float(row.get("lrg_amount")),
                "mlg_amount": _to_float(row.get("mlg_amount")),
                "sm_amount": _to_float(row.get("sm_amount")),
                "min_amount": _to_float(row.get("min_amount")),
            })
        log.info("fetched %d money flow records", len(results))
        return results
    except Exception:
        log.exception("fetch_money_flow_history failed")
        return []


def fetch_financial_data(stock_code: str) -> dict[str, Any]:
    """Fetch financial indicators for a stock from Tushare."""
    pro = _get_pro()
    if not pro:
        return {}

    try:
        df = pro.fina_indicator(ts_code=stock_code)
        if df is None or df.empty:
            return {}

        row = df.iloc[0]
        return {
            "roe": _to_float(row.get("roe")),
            "gross_margin": _to_float(row.get("gross_profit_rate")),
            "net_margin": _to_float(row.get("net_profit_rate")),
            "debt_ratio": _to_float(row.get("debtoquityratio")),
            "current_ratio": _to_float(row.get("currentratio")),
        }
    except Exception:
        log.exception("fetch_financial_data failed for %s", stock_code)
        return {}


def fetch_index_daily(index_code: str = "000001.SH", days: int = 30) -> list[dict[str, Any]]:
    """Fetch daily data for a market index (e.g., Shanghai Composite)."""
    pro = _get_pro()
    if not pro:
        return []

    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        df = pro.index_daily(
            ts_code=index_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            results.append({
                "trade_date": str(row.get("trade_date", "")),
                "open": _to_float(row.get("open")),
                "high": _to_float(row.get("high")),
                "low": _to_float(row.get("low")),
                "close": _to_float(row.get("close")),
                "vol": _to_float(row.get("vol")),
            })
        return results
    except Exception:
        log.exception("fetch_index_daily failed for %s", index_code)
        return []
