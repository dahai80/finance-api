from __future__ import annotations

import math
from typing import Any

from config import get_logger

log = get_logger("finance.ipo_scorer")


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _safe(val: Any, default: float = 0.0) -> float:
    try:
        v = float(str(val).replace(",", "").replace(" ", ""))
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def score_ipo(item: dict[str, Any]) -> dict[str, Any]:
    """
    Five-dimension radar scoring (0-100 total, 5 dims x 20pts each):
      1. valuation    (20): PE discount vs industry
      2. growth       (20): ballot rate inverse as demand proxy
      3. industry_heat(20): sector capital flow ranking (from akshare)
      4. institution  (20): inquiry multiple + quoting institutions
      5. low_risk     (20): break-even risk inverse
    """
    fm = item.get("fundamental_metrics") or {}
    pe = _safe(fm.get("pe"))
    industry_pe = _safe(fm.get("industry_pe"))
    price = _safe(fm.get("price"))
    inquiry_multiple = _safe(fm.get("inquiry_multiple"))
    quoting_institutions = _safe(fm.get("quoting_institutions"))
    ballot_rate = _safe(fm.get("ballot_rate"))
    board_type = str(fm.get("board_type", ""))

    scores: dict[str, float] = {}

    # 1. valuation discount: (industry_pe - pe) / industry_pe * 100, cap 20
    if industry_pe > 0 and pe > 0:
        discount = (industry_pe - pe) / industry_pe
        scores["valuation"] = _clamp(discount * 100, 0, 20)
    else:
        scores["valuation"] = 10.0

    # 2. growth: ballot rate inverse as demand proxy
    # Lower ballot rate = scarcer = higher growth expectation
    if ballot_rate > 0:
        growth_raw = (1.0 - min(ballot_rate, 1.0)) * 20
        scores["growth"] = _clamp(growth_raw, 0, 20)
    else:
        scores["growth"] = 10.0

    # 3. industry_heat: will be filled by async call in ipo router
    # For now use board type heuristic
    scores["industry_heat"] = _board_type_heat(board_type)

    # 4. institution: inquiry multiple + quoting institutions
    if inquiry_multiple > 0 and quoting_institutions > 0:
        inst_score = _clamp((inquiry_multiple / 500.0) * (quoting_institutions / 1000.0) * 20, 0, 20)
        scores["institution"] = inst_score
    elif inquiry_multiple > 0:
        scores["institution"] = _clamp(inquiry_multiple / 250.0, 0, 20)
    else:
        scores["institution"] = 10.0

    # 5. break-even risk: lower PE / industry_pe ratio = lower risk
    if pe > 0 and industry_pe > 0:
        risk_raw = 100 - (pe / industry_pe * 50)
        scores["low_risk"] = _clamp(risk_raw / 5, 0, 20)
    else:
        scores["low_risk"] = 10.0

    total = int(round(sum(scores.values())))
    if total >= 70:
        rec = "HIGH"
    elif total >= 50:
        rec = "MID"
    else:
        rec = "LOW"

    log.info(
        "scored %s(%s): pe=%.1f ind_pe=%.1f -> total=%d rec=%s dims=%s",
        item.get("stock_name", "?"),
        item.get("stock_code", "?"),
        pe, industry_pe, total, rec,
        {k: round(v, 1) for k, v in scores.items()},
    )
    return {
        "scores": scores,
        "total": total,
        "recommendation": rec,
    }


def _board_type_heat(board_type: str) -> float:
    """
    Heuristic industry heat based on board type.
    More detailed async lookup available via industry_map.get_industry_heat().
    """
    heat_map = {
        "科创板": 16.0,
        "创业板": 14.0,
        "主板": 12.0,
        "北交所": 10.0,
    }
    return heat_map.get(board_type, 10.0)
