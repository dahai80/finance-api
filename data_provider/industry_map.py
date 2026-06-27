from __future__ import annotations

import json
from datetime import date
from typing import Any

from config import get_logger
import storage

log = get_logger("finance.industry_map")

_CACHE_KEY_PREFIX = "finance:industry_heat:"


async def get_industry_heat(board_type: str) -> float:
    """
    Get industry heat score (0-20) for a given board type.
    Uses akshare fund flow data, cached in Redis.
    Falls back to 10.0 if data unavailable.
    """
    try:
        redis = await storage.get_redis()
        cache_key = f"{_CACHE_KEY_PREFIX}{date.today().isoformat()}"
        cached = await redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            return _lookup_heat(data, board_type)

        flow_data = await _fetch_industry_flow()
        if not flow_data:
            return 10.0

        await redis.set(cache_key, json.dumps(flow_data), ex=86400)
        return _lookup_heat(flow_data, board_type)
    except Exception:
        log.exception("get_industry_heat failed for %s", board_type)
        return 10.0


async def _fetch_industry_flow() -> list[dict[str, Any]]:
    """Fetch industry fund flow from akshare."""
    try:
        import akshare as ak  # type: ignore
        df = ak.stock_fund_flow_industry()
        if df is None or df.empty:
            return []

        results = []
        for _, row in df.iterrows():
            sector = str(row.get("行业", "")).strip()
            net_flow = _to_float(row.get("净额"))
            if sector:
                results.append({"sector": sector, "net_flow": net_flow})

        log.info("_fetch_industry_flow: %d sectors", len(results))
        return results
    except Exception:
        log.exception("_fetch_industry_flow failed")
        return []


def _lookup_heat(flow_data: list[dict[str, Any]], board_type: str) -> float:
    """
    Map board type to industry heat score (0-20).
    Uses net flow ranking among all sectors.
    """
    if not flow_data:
        return 10.0

    sorted_flows = sorted(flow_data, key=lambda x: x["net_flow"], reverse=True)
    total_sectors = len(sorted_flows)

    board_to_sector_map = {
        "科创板": ["半导体设备", "半导体材料", "光伏设备", "风电设备", "军工装备"],
        "创业板": ["光学光电子", "电子化学品", "自动化设备", "电池"],
        "主板": ["元件", "消费电子", "通信设备"],
        "北交所": ["教育", "养殖业", "水产饲料"],
    }

    target_sectors = board_to_sector_map.get(board_type, [])
    if not target_sectors:
        return 10.0

    scores = []
    for sector in target_sectors:
        for i, item in enumerate(sorted_flows):
            if item["sector"] == sector:
                rank_pct = 1.0 - (i / max(total_sectors - 1, 1))
                scores.append(rank_pct * 20)

    return sum(scores) / len(scores) if scores else 10.0


def _to_float(val: Any) -> float:
    if val is None:
        return 0.0
    try:
        result = float(str(val).replace(",", "").replace(" ", ""))
        if __import__("math").isnan(result) or __import__("math").isinf(result):
            return 0.0
        return result
    except Exception:
        return 0.0
