from __future__ import annotations

import math
from datetime import date
from typing import Any

from config import get_logger

log = get_logger("finance.akshare")

MOCK_IPO_ROWS: list[dict[str, Any]] = [
    {
        "stock_code": "301800",
        "stock_name": "宏鑫科技",
        "ipo_date": date.today(),
        "fundamental_metrics": {
            "price": 12.5,
            "pe": 18.3,
            "industry_pe": 25.6,
            "inquiry_multiple": 3200.0,
            "quoting_institutions": 8500.0,
            "ballot_rate": 0.025,
            "subscription_cap": 85000.0,
            "total_float": 1800.0,
            "board_type": "创业板",
            "source": "mock",
        },
    },
    {
        "stock_code": "688700",
        "stock_name": "东昂光电",
        "ipo_date": date.today(),
        "fundamental_metrics": {
            "price": 28.0,
            "pe": 32.1,
            "industry_pe": 29.4,
            "inquiry_multiple": 5800.0,
            "quoting_institutions": 12000.0,
            "ballot_rate": 0.018,
            "subscription_cap": 95000.0,
            "total_float": 2200.0,
            "board_type": "科创板",
            "source": "mock",
        },
    },
    {
        "stock_code": "001389",
        "stock_name": "广合科技",
        "ipo_date": date.today(),
        "fundamental_metrics": {
            "price": 18.7,
            "pe": 22.0,
            "industry_pe": 24.8,
            "inquiry_multiple": 1500.0,
            "quoting_institutions": 6200.0,
            "ballot_rate": 0.042,
            "subscription_cap": 70000.0,
            "total_float": 1500.0,
            "board_type": "主板",
            "source": "mock",
        },
    },
]


def fetch_upcoming_ipo_live() -> list[dict[str, Any]]:
    """
    Live AkShare fetch: upcoming IPO subscriptions.
    Uses ak.stock_xgsglb_em() and maps columns to our schema.
    Returns empty list if akshare not available or call fails.
    """
    try:
        import akshare as ak  # type: ignore
        log.info("fetch_upcoming_ipo_live: calling ak.stock_xgsglb_em()")
        df = ak.stock_xgsglb_em()
        if df is None or df.empty:
            log.warning("fetch_upcoming_ipo_live: empty dataframe")
            return []

        rows: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            code = str(row.get("股票代码", "")).strip()
            if not code:
                continue
            name = str(row.get("股票简称", "")).strip()
            ipo_date_raw = row.get("申购日期")
            try:
                ipo_date = date.fromisoformat(str(ipo_date_raw).split()[0]) if ipo_date_raw else date.today()
            except Exception:
                ipo_date = date.today()

            price = _to_float(row.get("发行价格"))
            pe = _to_float(row.get("发行市盈率"))
            industry_pe = _to_float(row.get("行业市盈率"))
            inquiry_multiple = _to_float(row.get("询价累计报价倍数"))
            quoting_institutions = _to_float(row.get("配售对象报价家数"))
            ballot_rate = _to_float(row.get("中签率"))
            subscription_cap = _to_float(row.get("申购上限"))
            total_float = _to_float(row.get("发行总数"))
            board_type = str(row.get("板块", "")).strip() or "未知"

            rows.append({
                "stock_code": code,
                "stock_name": name,
                "ipo_date": ipo_date,
                "fundamental_metrics": {
                    "price": price,
                    "pe": pe,
                    "industry_pe": industry_pe,
                    "inquiry_multiple": inquiry_multiple,
                    "quoting_institutions": quoting_institutions,
                    "ballot_rate": ballot_rate,
                    "subscription_cap": subscription_cap,
                    "total_float": total_float,
                    "board_type": board_type,
                    "source": "akshare",
                },
            })
        log.info("fetch_upcoming_ipo_live: fetched %d rows", len(rows))
        return rows
    except ImportError:
        log.warning("fetch_upcoming_ipo_live: akshare not installed")
        return []
    except Exception:
        log.exception("fetch_upcoming_ipo_live: failed")
        return []


def fetch_upcoming_ipo_mock() -> list[dict[str, Any]]:
    log.info("fetch_upcoming_ipo_mock: returning %d rows", len(MOCK_IPO_ROWS))
    return [row.copy() for row in MOCK_IPO_ROWS]


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
