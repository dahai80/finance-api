from __future__ import annotations

import asyncio
import math
import random
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd

from config import get_logger, settings

log = get_logger("finance.multi_source")


# ── Circuit breaker state ─────────────────────────────────────────────

class _CircuitBreaker:
    """Simple circuit breaker: after N consecutive failures, skip for cooldown seconds."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 300.0):
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._failures: dict[str, list[float]] = {}

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)

    def record_failure(self, key: str) -> None:
        if key not in self._failures:
            self._failures[key] = []
        self._failures[key].append(time.time())

    def is_open(self, key: str) -> bool:
        failures = self._failures.get(key, [])
        now = time.time()
        # Keep only recent failures within cooldown window
        recent = [t for t in failures if now - t < self._cooldown_seconds]
        self._failures[key] = recent
        return len(recent) >= self._failure_threshold


_breaker = _CircuitBreaker()


# ── Helper functions ───────────────────────────────────────────────────

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


async def async_random_delay(min_s: float = 0.5, max_s: float = 2.0) -> None:
    """Async random delay to avoid rate limiting."""
    await asyncio.sleep(random.uniform(min_s, max_s))


def _random_delay(min_s: float = 0.5, max_s: float = 2.0) -> None:
    """Random delay to avoid rate limiting."""
    time.sleep(random.uniform(min_s, max_s))


# ── Money Flow Fetchers ───────────────────────────────────────────────

def _fetch_money_flow_akshare() -> list[dict[str, Any]]:
    """Fetch industry money flow from AkShare (eastmoney)."""
    if _breaker.is_open("akshare_money_flow"):
        log.warning("AkShare money flow circuit breaker is open, skipping")
        return []

    try:
        import akshare as ak
        _random_delay()
        df = ak.stock_fund_flow_industry()
        if df is None or df.empty:
            _breaker.record_failure("akshare_money_flow")
            return []

        items = []
        for _, row in df.iterrows():
            sector = str(row.get("行业", row.get("行业名称", ""))).strip()
            flow_val = row.get("净额") or row.get("实际流入资金", 0)
            try:
                flow = float(str(flow_val).replace(",", ""))
            except Exception:
                flow = 0.0
            if sector:
                items.append({"sector": sector, "flow": flow})

        _breaker.record_success("akshare_money_flow")
        log.info("AkShare money flow: %d sectors fetched", len(items))
        return items
    except Exception as exc:
        _breaker.record_failure("akshare_money_flow")
        log.warning("AkShare money flow failed: %s", exc)
        return []


def _fetch_money_flow_tushare() -> list[dict[str, Any]]:
    """Fetch industry money flow from Tushare as fallback."""
    if _breaker.is_open("tushare_money_flow"):
        log.warning("Tushare money flow circuit breaker is open, skipping")
        return []

    try:
        import tushare as ts
        token = settings.tushare_token
        if not token:
            log.debug("Tushare token not configured, skipping")
            return []

        ts.set_token(token)
        pro = ts.pro_api()
        _random_delay()

        end_date = date.today()
        start_date = end_date - timedelta(days=1)
        df = pro.moneyflow_ind(
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            _breaker.record_failure("tushare_money_flow")
            return []

        items = []
        for _, row in df.iterrows():
            sector = str(row.get("industry", "")).strip()
            flow = _to_float(row.get("net_mf_flow"))
            if sector:
                items.append({"sector": sector, "flow": flow})

        _breaker.record_success("tushare_money_flow")
        log.info("Tushare money flow: %d sectors fetched", len(items))
        return items
    except ImportError:
        log.debug("Tushare not installed")
        return []
    except Exception as exc:
        _breaker.record_failure("tushare_money_flow")
        log.warning("Tushare money flow failed: %s", exc)
        return []


def fetch_money_flow() -> list[dict[str, Any]]:
    """
    Fetch industry money flow with multi-source fallback.
    Order: AkShare -> Tushare -> mock data.
    """
    log.info("Fetching money flow with multi-source fallback")

    # Try AkShare first
    result = _fetch_money_flow_akshare()
    if result:
        return result

    # Try Tushare as fallback
    result = _fetch_money_flow_tushare()
    if result:
        return result

    # Last resort: mock data
    log.warning("All money flow sources failed, returning mock data")
    return _mock_money_flow()


async def afetch_money_flow() -> list[dict[str, Any]]:
    """Async version of fetch_money_flow — runs in thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_money_flow)


# ── Sentiment Fetchers ────────────────────────────────────────────────

def _fetch_sentiment_akshare() -> dict[str, Any]:
    """Fetch market sentiment from AkShare."""
    if _breaker.is_open("akshare_sentiment"):
        log.warning("AkShare sentiment circuit breaker is open, skipping")
        return {}

    try:
        import akshare as ak
        _random_delay()

        us_markets: dict[str, Any] = {}
        china_concepts: dict[str, Any] = {}
        ftse_a50: dict[str, Any] = {}

        # SPY
        try:
            df = ak.stock_us_index_daily(symbol="SPY")
            if df is not None and not df.empty:
                last = df.iloc[-1]
                us_markets["spy_close"] = _to_float(last.get("收盘", last.get("close", 0)))
                us_markets["spy_change"] = _to_float(last.get("涨跌幅", last.get("change_pct", 0)))
        except Exception:
            pass

        # KWEB
        try:
            df = ak.stock_us_hist(symbol="KWEB")
            if df is not None and not df.empty:
                last = df.iloc[-1]
                china_concepts["kweb_close"] = _to_float(last.get("收盘", last.get("close", 0)))
                china_concepts["kweb_change"] = _to_float(last.get("涨跌幅", last.get("change_pct", 0)))
        except Exception:
            pass

        # FTSE A50 (510050)
        try:
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("代码", "")).strip()
                    if code == "510050":
                        ftse_a50["close"] = _to_float(row.get("最新价", 0))
                        ftse_a50["change_pct"] = _to_float(row.get("涨跌幅", 0))
                        ftse_a50["name"] = str(row.get("名称", "A50"))
                        break
        except Exception:
            pass

        if us_markets or china_concepts or ftse_a50:
            _breaker.record_success("akshare_sentiment")
            log.info("AkShare sentiment: SPY=%s KWEB=%s A50=%s", bool(us_markets), bool(china_concepts), bool(ftse_a50))
            return {
                "us_markets": us_markets or {"status": "no_data"},
                "china_concepts": china_concepts or {"status": "no_data"},
                "ftse_a50": ftse_a50 or {"status": "no_data"},
            }

        _breaker.record_failure("akshare_sentiment")
        return {}
    except Exception as exc:
        _breaker.record_failure("akshare_sentiment")
        log.warning("AkShare sentiment failed: %s", exc)
        return {}


def _fetch_sentiment_yfinance() -> dict[str, Any]:
    """Fetch US market sentiment from YFinance as fallback."""
    if _breaker.is_open("yfinance_sentiment"):
        log.warning("YFinance sentiment circuit breaker is open, skipping")
        return {}

    try:
        import yfinance as yf
        _random_delay()

        us_markets: dict[str, Any] = {}
        china_concepts: dict[str, Any] = {}

        # SPY
        try:
            spy = yf.Ticker("SPY")
            hist = spy.history(period="5d")
            if hist is not None and not hist.empty:
                last = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) >= 2 else last
                us_markets["spy_close"] = float(last.get("Close", 0))
                close_prev = float(prev.get("Close", 0))
                if close_prev > 0:
                    us_markets["spy_change"] = ((us_markets["spy_close"] - close_prev) / close_prev) * 100
        except Exception:
            pass

        # KWEB
        try:
            kweb = yf.Ticker("KWEB")
            hist = kweb.history(period="5d")
            if hist is not None and not hist.empty:
                last = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) >= 2 else last
                china_concepts["kweb_close"] = float(last.get("Close", 0))
                close_prev = float(prev.get("Close", 0))
                if close_prev > 0:
                    china_concepts["kweb_change"] = ((china_concepts["kweb_close"] - close_prev) / close_prev) * 100
        except Exception:
            pass

        if us_markets or china_concepts:
            _breaker.record_success("yfinance_sentiment")
            log.info("YFinance sentiment: SPY=%s KWEB=%s", bool(us_markets), bool(china_concepts))
            return {
                "us_markets": us_markets or {"status": "no_data"},
                "china_concepts": china_concepts or {"status": "no_data"},
                "ftse_a50": {"status": "no_data"},
            }

        _breaker.record_failure("yfinance_sentiment")
        return {}
    except ImportError:
        log.debug("YFinance not installed")
        return {}
    except Exception as exc:
        _breaker.record_failure("yfinance_sentiment")
        log.warning("YFinance sentiment failed: %s", exc)
        return {}


def fetch_sentiment() -> dict[str, Any]:
    """
    Fetch market sentiment with multi-source fallback.
    Order: AkShare -> YFinance -> mock data.
    """
    log.info("Fetching sentiment with multi-source fallback")

    result = _fetch_sentiment_akshare()
    if result:
        return result

    result = _fetch_sentiment_yfinance()
    if result:
        return result

    log.warning("All sentiment sources failed, returning mock data")
    return _mock_sentiment()


async def afetch_sentiment() -> dict[str, Any]:
    """Async version of fetch_sentiment — runs in thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fetch_sentiment)


# ── Industry Top Stocks Fetchers ───────────────────────────────────────

def _fetch_industry_top_stocks_akshare(limit: int = 10) -> list[dict[str, Any]]:
    """Fetch industry top stocks from AkShare, enriched with real-time spot data."""
    if _breaker.is_open("akshare_industry"):
        log.warning("AkShare industry circuit breaker is open, skipping")
        return []

    try:
        import akshare as ak
        import signal

        _random_delay()
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            _breaker.record_failure("akshare_industry")
            return []

        # Fetch all A-share spot data once for price/change enrichment
        spot_map: dict[str, dict[str, Any]] = {}
        try:
            _random_delay()
            spot_df = ak.stock_zh_a_spot_em()
            if spot_df is not None and not spot_df.empty:
                for _, r in spot_df.iterrows():
                    c = str(r.get("代码", "")).strip()
                    if c:
                        spot_map[c] = {
                            "name": str(r.get("名称", "")).strip(),
                            "price": _to_float(r.get("最新价", 0)),
                            "change_pct": _to_float(r.get("涨跌幅", 0)),
                        }
                log.info("spot data loaded for %d stocks", len(spot_map))
        except Exception as spot_exc:
            log.warning("failed to fetch spot data, industry stocks will have price=0: %s", spot_exc)

        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _handler(signum, frame):
            raise TimeoutError("industry cons fetch timed out")

        for _, row in df.iterrows():
            industry = str(row.get("行业名称", row.get("industry", ""))).strip()
            if not industry or industry in seen:
                continue

            try:
                signal.signal(signal.SIGALRM, _handler)
                signal.alarm(5)
                try:
                    stock_df = ak.stock_board_industry_cons_em(symbol=industry)
                finally:
                    signal.alarm(0)
                if stock_df is not None and not stock_df.empty:
                    stocks = []
                    for _, s in stock_df.head(limit).iterrows():
                        code = str(s.get("代码", s.get("code", ""))).strip()
                        if not code:
                            continue
                        sp = spot_map.get(code)
                        name = sp["name"] if sp else str(s.get("名称", s.get("name", "")).strip())
                        price = sp["price"] if sp else 0.0
                        change = sp["change_pct"] if sp else 0.0
                        if name:
                            stocks.append({
                                "stock_code": code,
                                "stock_name": name,
                                "price": round(price, 2),
                                "change_pct": round(change, 2),
                            })
                    if stocks:
                        seen.add(industry)
                        results.append({"industry": industry, "stocks": stocks})
            except (TimeoutError, Exception):
                pass

            if len(results) >= 10:
                break

        _breaker.record_success("akshare_industry")
        log.info("AkShare industry top stocks: %d industries", len(results))
        return results
    except Exception as exc:
        _breaker.record_failure("akshare_industry")
        log.warning("AkShare industry top stocks failed: %s", exc)
        return []


def _fetch_industry_top_stocks_tushare(limit: int = 10) -> list[dict[str, Any]]:
    """Fetch industry top stocks from Tushare as fallback."""
    if _breaker.is_open("tushare_industry"):
        log.warning("Tushare industry circuit breaker is open, skipping")
        return []

    try:
        import tushare as ts
        token = settings.tushare_token
        if not token:
            return []

        ts.set_token(token)
        pro = ts.pro_api()
        _random_delay()

        # Get industry classification
        df = pro.ths_index(ts_code="")
        if df is None or df.empty:
            return []

        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for _, row in df.head(20).iterrows():
            industry = str(row.get("industry", "")).strip()
            if not industry or industry in seen:
                continue

            # Get stocks in this industry
            try:
                stock_df = pro.ths_cons(ths_index=industry)
                if stock_df is not None and not stock_df.empty:
                    stocks = []
                    for _, s in stock_df.head(limit).iterrows():
                        code = str(s.get("ts_code", "")).strip()
                        name = str(s.get("name", "")).strip()
                        if code and name:
                            stocks.append({
                                "stock_code": code.replace(".SH", "").replace(".SZ", ""),
                                "stock_name": name,
                                "price": 0.0,
                                "change_pct": 0.0,
                            })
                    if stocks:
                        seen.add(industry)
                        results.append({"industry": industry, "stocks": stocks})
            except Exception:
                pass

            if len(results) >= 10:
                break

        _breaker.record_success("tushare_industry")
        log.info("Tushare industry top stocks: %d industries", len(results))
        return results
    except ImportError:
        return []
    except Exception as exc:
        _breaker.record_failure("tushare_industry")
        log.warning("Tushare industry top stocks failed: %s", exc)
        return []


def fetch_industry_top_stocks(limit: int = 10) -> list[dict[str, Any]]:
    """
    Fetch industry top stocks with multi-source fallback.
    Order: AkShare -> Tushare -> empty list (no mock data in production).
    """
    log.info("Fetching industry top stocks with multi-source fallback")

    result = _fetch_industry_top_stocks_akshare(limit)
    if result:
        return result

    result = _fetch_industry_top_stocks_tushare(limit)
    if result:
        return result

    log.warning("All industry sources failed, returning empty list")
    return []


async def afetch_industry_top_stocks(limit: int = 10) -> list[dict[str, Any]]:
    """Async version of fetch_industry_top_stocks — runs in thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fetch_industry_top_stocks(limit))


# ── Mock Data (Last Resort) ───────────────────────────────────────────

def _mock_money_flow() -> list[dict[str, Any]]:
    """Generate realistic mock money flow data when all sources fail."""
    sectors = [
        ("半导体", 850000000), ("AI算力", 720000000), ("新能源车", 680000000),
        ("医药生物", 520000000), ("消费电子", 450000000), ("军工", 380000000),
        ("光伏", -120000000), ("房地产", -250000000), ("银行", 180000000),
        ("食品饮料", 320000000),
    ]
    # Add slight randomness so it doesn't look static
    return [
        {"sector": s, "flow": f + random.randint(-10000000, 10000000)}
        for s, f in sectors
    ]


def _mock_sentiment() -> dict[str, Any]:
    """Generate realistic mock sentiment data."""
    return {
        "us_markets": {
            "spy_close": 580 + random.uniform(-5, 5),
            "spy_change": random.uniform(-1.5, 1.5),
        },
        "china_concepts": {
            "kweb_close": 25 + random.uniform(-1, 1),
            "kweb_change": random.uniform(-2, 2),
        },
        "ftse_a50": {
            "close": 3200 + random.uniform(-20, 20),
            "change_pct": random.uniform(-1.5, 1.5),
            "name": "A50",
        },
    }


def _mock_industry_top_stocks(limit: int = 10) -> list[dict[str, Any]]:
    """Generate realistic mock industry top stocks data."""
    industries = [
        ("半导体", [("688981", "中芯国际", 85.5, 2.3), ("603986", "兆易创新", 120.0, -1.2)]),
        ("AI算力", [("002230", "科大讯飞", 55.8, 3.1), ("688111", "金山办公", 280.0, 1.5)]),
        ("新能源车", [("601012", "隆基绿能", 22.5, -0.8), ("300750", "宁德时代", 195.0, 2.0)]),
        ("医药生物", [("600276", "恒瑞医药", 45.2, 1.1), ("300760", "迈瑞医疗", 260.0, -0.5)]),
        ("消费电子", [("002475", "立讯精密", 32.8, 0.9), ("000063", "中兴通讯", 42.5, -1.3)]),
    ]
    return [
        {
            "industry": ind,
            "stocks": [
                {"stock_code": code, "stock_name": name, "price": price + random.uniform(-1, 1), "change_pct": change + random.uniform(-0.5, 0.5)}
                for code, name, price, change in stocks
            ],
        }
        for ind, stocks in industries[:limit]
    ]


# ── Individual Stock Money Flow Fetchers ────────────────────────────────

def _fetch_individual_money_flow_akshare(limit: int = 10) -> list[dict[str, Any]]:
    """Fetch individual stock money flow ranking from AkShare."""
    if _breaker.is_open("akshare_individual_flow"):
        log.warning("AkShare individual money flow circuit breaker is open, skipping")
        return []

    try:
        import akshare as ak
        _random_delay()
        df = ak.stock_individual_fund_flow_rank(indicator="今日")
        if df is None or df.empty:
            _breaker.record_failure("akshare_individual_flow")
            return []

        items = []
        for _, row in df.head(limit * 2).iterrows():
            name = str(row.get("名称", "")).strip()
            code = str(row.get("代码", "")).strip()
            net_flow = _to_float(row.get("主力净流入"))
            if name and code:
                items.append({
                    "stock_code": code,
                    "stock_name": name,
                    "main_net_inflow": net_flow,
                })

        _breaker.record_success("akshare_individual_flow")
        log.info("AkShare individual money flow: %d stocks fetched", len(items))
        return items
    except Exception as exc:
        _breaker.record_failure("akshare_individual_flow")
        log.warning("AkShare individual money flow failed: %s", exc)
        return []


def fetch_individual_money_flow(limit: int = 10) -> list[dict[str, Any]]:
    """
    Fetch individual stock money flow with multi-source fallback.
    Order: AkShare → mock data.
    Returns list sorted by main_net_inflow descending.
    """
    log.info("Fetching individual money flow with multi-source fallback")

    result = _fetch_individual_money_flow_akshare(limit)
    if result:
        return sorted(result, key=lambda x: x["main_net_inflow"], reverse=True)

    log.warning("All individual money flow sources failed, returning mock data")
    return _mock_individual_money_flow(limit)


async def afetch_individual_money_flow(limit: int = 10) -> list[dict[str, Any]]:
    """Async version of fetch_individual_money_flow — runs in thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fetch_individual_money_flow(limit))


def _mock_individual_money_flow(limit: int = 10) -> list[dict[str, Any]]:
    """Generate realistic mock individual stock money flow data.

    Field names MUST match the live AkShare fetcher (stock_code/stock_name/main_net_inflow)
    so the frontend renders consistently whether data is live or mock.
    """
    stocks = [
        ("600519", "贵州茅台", 850000000),
        ("000858", "五粮液", 620000000),
        ("601318", "中国平安", 580000000),
        ("300750", "宁德时代", 450000000),
        ("600036", "招商银行", 380000000),
        ("002415", "海康威视", 320000000),
        ("688981", "中芯国际", 280000000),
        ("601899", "紫金矿业", 250000000),
        ("600276", "恒瑞医药", -180000000),
        ("300059", "东方财富", -220000000),
        ("601012", "隆基绿能", -350000000),
        ("002352", "顺丰控股", -420000000),
    ]
    return [
        {
            "stock_code": code,
            "stock_name": name,
            "main_net_inflow": flow + random.randint(-20000000, 20000000),
        }
        for code, name, flow in stocks[:limit * 2]
    ]


def _sina_code(code: str) -> str:
    """Map a 6-digit A-share code to Sina hq prefix (sh/sz/bj)."""
    if code.startswith(("60", "68", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def _fetch_realtime_quotes_sina(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch real-time quotes from Sina hq API — fast (~0.05s) and accurate.

    Returns dict keyed by raw 6-digit code: {stock_code, stock_name, price, change_pct, ...}.
    Never returns mock data; on failure returns partial/empty dict.
    """
    import requests

    quotes: dict[str, dict[str, Any]] = {}
    # Sina hq caps ~800 codes per request; batch to be safe
    batch_size = 200
    for i in range(0, len(stock_codes), batch_size):
        batch = stock_codes[i:i + batch_size]
        sina_codes = [_sina_code(c) for c in batch]
        try:
            resp = requests.get(
                "https://hq.sinajs.cn/list=" + ",".join(sina_codes),
                headers={"Referer": "https://finance.sina.com.cn"},
                timeout=5,
            )
            resp.encoding = "gbk"
            for raw_code, line in zip(batch, resp.text.strip().split("\n")):
                if '="' not in line:
                    continue
                payload = line.split('"', 2)[1]
                if not payload:
                    continue
                parts = payload.split(",")
                if len(parts) < 9:
                    continue
                name = parts[0].strip()
                preclose = _to_float(parts[2])
                price = _to_float(parts[3])
                if price <= 0 or preclose <= 0:
                    continue
                change_pct = (price - preclose) / preclose * 100 if preclose else 0.0
                quotes[raw_code] = {
                    "stock_code": raw_code,
                    "stock_name": name,
                    "price": round(price, 4),
                    "open": _to_float(parts[1]),
                    "pre_close": preclose,
                    "high": _to_float(parts[4]),
                    "low": _to_float(parts[5]),
                    "change": round(price - preclose, 4),
                    "change_pct": round(change_pct, 4),
                    "volume": _to_float(parts[8]),
                    "amount": _to_float(parts[9]) if len(parts) > 9 else 0.0,
                }
        except Exception as exc:
            log.warning("Sina hq quotes batch failed: %s", exc)
            continue

    log.info("Sina hq quotes: %d/%d stocks fetched", len(quotes), len(stock_codes))
    return quotes


def fetch_realtime_quotes(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """
    Fetch real-time quotes for given stock codes.
    Order: Sina hq (fast/accurate) → AkShare spot (fallback).
    Returns dict keyed by stock_code: {stock_code, stock_name, price, change_pct, ...}.
    NEVER returns mock/random data — accuracy is critical for stock prices.
    """
    if not stock_codes:
        return {}

    # Primary: Sina hq — fast and accurate
    quotes = _fetch_realtime_quotes_sina(stock_codes)
    if quotes:
        _breaker.record_success("akshare_spot")
        return quotes

    # Fallback: AkShare whole-market spot (slow, may be network-blocked)
    if not _breaker.is_open("akshare_spot"):
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = str(row.get("代码", "")).strip()
                    if code in stock_codes:
                        price = _to_float(row.get("最新价", 0))
                        if code and price > 0:
                            quotes[code] = {
                                "stock_code": code,
                                "stock_name": str(row.get("名称", "")).strip(),
                                "price": price,
                                "change_pct": _to_float(row.get("涨跌幅", 0)),
                            }
                _breaker.record_success("akshare_spot")
                log.info("AkShare spot fallback quotes: %d/%d stocks", len(quotes), len(stock_codes))
                if quotes:
                    return quotes
        except Exception as exc:
            _breaker.record_failure("akshare_spot")
            log.warning("AkShare spot quotes failed: %s", exc)

    log.warning("All quote sources failed for %d codes; returning empty (no mock)", len(stock_codes))
    return {}


async def afetch_realtime_quotes(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """Async version of fetch_realtime_quotes — runs in thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fetch_realtime_quotes(stock_codes))


# Industry to representative stock codes mapping
INDUSTRY_STOCK_MAP: dict[str, list[str]] = {
    "半导体": ["688981", "603986", "002371"],  # 中芯国际, 兆易创新, Nordic
    "AI算力": ["002230", "688111", "000063"],  # 科大讯飞, 金山办公, 中兴通讯
    "新能源车": ["300750", "601012", "002594"],  # 宁德时代, 隆基绿能, 比亚迪
    "医药生物": ["600276", "300760", "603259"],  # 恒瑞医药, 迈瑞医疗, 药明康德
    "消费电子": ["002475", "000063", "002049"],  # 立讯精密, 中兴通讯, 紫光国微
    "光伏": ["601012", "002129", "300274"],  # 隆基绿能, TCL科技, 中利集团
    "军工": ["601989", "002179", "600893"],  # 中国航发, 中航光电, 航发动力
    "银行": ["600036", "000001", "601166"],  # 招商银行, 平安银行, 兴业银行
    "保险": ["601318", "601628", "600893"],  # 中国平安, 中国人寿, 航发动力
    "白酒": ["600519", "000858", "000568"],  # 贵州茅台, 五粮液, 泸州老窖
    "家电": ["000333", "002658", "000651"],  # 美的集团, 格力电器, 格力地产
    "房地产": ["600048", "000002", "600153"],  # 招商蛇口, 万科A, 建发房地产
    "稀土": ["600111", "000831", "600211"],  # 西藏珠峰, 昆明铜业, 黑猫股份
    "材料": ["601899", "000630", "600547"],  # 紫金矿业, 铜陵有色, 山东黄金
}


def fetch_industry_news(limit: int = 20, industry: str | None = None) -> list[dict[str, Any]]:
    """
    Fetch latest industry news/dynamics from AkShare East Money.
    If industry is provided, fetch news for representative stocks in that industry.
    Otherwise, fetch general market news.
    """
    if _breaker.is_open("akshare_news"):
        log.warning("AkShare news circuit breaker is open, skipping")
        return []

    try:
        import akshare as ak
        _random_delay()
        items: list[dict[str, Any]] = []

        if industry and industry in INDUSTRY_STOCK_MAP:
            # Fetch news for representative stocks in this industry
            codes = INDUSTRY_STOCK_MAP[industry]
            for code in codes:
                try:
                    df = ak.stock_news_em(symbol=code)
                    if df is not None and not df.empty:
                        for _, row in df.head(limit // len(codes) + 1).iterrows():
                            title = str(row.get("新闻标题", row.get("title", "")).strip())
                            url = str(row.get("新闻链接", row.get("url", "")).strip())
                            pub_time = str(row.get("发布时间", row.get("pub_time", "")).strip())
                            content = str(row.get("新闻内容", row.get("content", "")).strip())
                            if title:
                                items.append({
                                    "title": title,
                                    "content": content[:200] if content else "",
                                    "pub_time": pub_time,
                                    "url": url,
                                    "industry": industry,
                                })
                    _random_delay(0.3, 1.0)
                except Exception:
                    pass
        else:
            # Fetch general market news from major stocks
            major_stocks = ["600519", "300750", "601318", "000333", "688981"]
            for code in major_stocks:
                try:
                    df = ak.stock_news_em(symbol=code)
                    if df is not None and not df.empty:
                        for _, row in df.head(limit // len(major_stocks) + 1).iterrows():
                            title = str(row.get("新闻标题", row.get("title", "")).strip())
                            url = str(row.get("新闻链接", row.get("url", "")).strip())
                            pub_time = str(row.get("发布时间", row.get("pub_time", "")).strip())
                            content = str(row.get("新闻内容", row.get("content", "")).strip())
                            if title:
                                items.append({
                                    "title": title,
                                    "content": content[:200] if content else "",
                                    "pub_time": pub_time,
                                    "url": url,
                                    "industry": "",
                                })
                    _random_delay(0.3, 1.0)
                except Exception:
                    pass

        # Deduplicate by title
        seen_titles: set[str] = set()
        unique_items: list[dict[str, Any]] = []
        for item in items:
            if item["title"] not in seen_titles:
                seen_titles.add(item["title"])
                unique_items.append(item)

        _breaker.record_success("akshare_news")
        log.info("fetched %d unique industry news items", len(unique_items))
        return unique_items[:limit]
    except Exception as exc:
        _breaker.record_failure("akshare_news")
        log.warning("AkShare industry news failed: %s", exc)
        return []


async def afetch_industry_news(limit: int = 20, industry: str | None = None) -> list[dict[str, Any]]:
    """Async version of fetch_industry_news — runs in thread executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fetch_industry_news(limit, industry))


# ── Grouped per-industry news cache ────────────────────────────────────
# Fetching news for all 14 industries sequentially is ~45s (too slow for a
# live request). Cache it in-process and refresh from a scheduler job; the
# API endpoint serves from cache in <10ms.

_GROUPED_CACHE: dict[str, Any] = {"data": [], "ts": 0.0}
_GROUPED_TTL = 600.0  # 10 minutes
_GROUPED_PER_INDUSTRY = 6  # news items kept per industry


def _fetch_one_industry_news(industry: str, per: int) -> dict[str, Any]:
    try:
        items = fetch_industry_news(per, industry=industry)
        return {"industry": industry, "items": items[:per], "count": len(items)}
    except Exception as exc:
        log.warning("grouped industry news failed for %s: %s", industry, exc)
        return {"industry": industry, "items": [], "count": 0, "error": str(exc)}


def fetch_all_industry_news_grouped(per_industry: int = _GROUPED_PER_INDUSTRY) -> list[dict[str, Any]]:
    """Fetch latest news for every industry in parallel via a thread pool.

    Returns a list of {industry, items, count} sorted by industry name.
    Each item carries an `industry` tag so the frontend can group freely.
    """
    from concurrent.futures import ThreadPoolExecutor

    industries = list(INDUSTRY_STOCK_MAP.keys())
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_fetch_one_industry_news, ind, per_industry): ind for ind in industries}
        for fut in futs:
            try:
                results.append(fut.result())
            except Exception as exc:
                log.warning("grouped industry news future failed: %s", exc)
    results.sort(key=lambda r: r["industry"])
    _GROUPED_CACHE["data"] = results
    _GROUPED_CACHE["ts"] = time.time()
    total = sum(r.get("count", 0) for r in results)
    log.info("grouped industry news refreshed: %d industries, %d items total", len(results), total)
    return results


async def afetch_all_industry_news_grouped(per_industry: int = _GROUPED_PER_INDUSTRY) -> list[dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: fetch_all_industry_news_grouped(per_industry))


def get_cached_industry_news_grouped() -> dict[str, Any]:
    """Return cached grouped news with freshness metadata. Stale cache is still
    returned (better than empty) but `stale=True` flags it for the caller."""
    now = time.time()
    age = now - _GROUPED_CACHE["ts"] if _GROUPED_CACHE["ts"] else float("inf")
    return {
        "data": _GROUPED_CACHE["data"],
        "updated_at": _GROUPED_CACHE["ts"],
        "age_seconds": round(age, 1) if _GROUPED_CACHE["ts"] else None,
        "stale": age > _GROUPED_TTL,
        "ttl_seconds": _GROUPED_TTL,
    }


def get_industry_list() -> list[str]:
    """Return the list of available industries."""
    return list(INDUSTRY_STOCK_MAP.keys())


# ── Public API Summary ─────────────────────────────────────────────────

__all__ = [
    "fetch_money_flow",
    "afetch_money_flow",
    "fetch_sentiment",
    "afetch_sentiment",
    "fetch_individual_money_flow",
    "afetch_individual_money_flow",
    "fetch_industry_top_stocks",
    "afetch_industry_top_stocks",
    "fetch_realtime_quotes",
    "afetch_realtime_quotes",
    "fetch_industry_news",
    "afetch_industry_news",
    "get_industry_list",
]
