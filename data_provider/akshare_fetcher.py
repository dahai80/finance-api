from __future__ import annotations

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
            "source": "mock",
        },
    },
]


def fetch_upcoming_ipo_live() -> list[dict[str, Any]]:
    """
    Stub：真实实现应调用 ak.stock_new_gh_tpl() 并映射字段。
    AkShare 接口名在 2.x 多次变动，这里保留占位，待联调期打通。
    """
    log.warning("fetch_upcoming_ipo_live: live akshare fetch not implemented, returning empty")
    return []


def fetch_upcoming_ipo_mock() -> list[dict[str, Any]]:
    log.info("fetch_upcoming_ipo_mock: returning %d rows", len(MOCK_IPO_ROWS))
    return [row.copy() for row in MOCK_IPO_ROWS]
