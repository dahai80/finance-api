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
      2. growth       (20): revenue & profit growth (stub until data source)
      3. industry_heat(20): sector capital flow ranking (stub)
      4. institution  (20): offline subscription multiple (stub)
      5. low_risk     (20): break-even risk inverse
    """
    fm = item.get("fundamental_metrics") or {}
    pe = _safe(fm.get("pe"))
    industry_pe = _safe(fm.get("industry_pe"))
    price = _safe(fm.get("price"))

    scores: dict[str, float] = {}

    # 1. valuation discount: (industry_pe - pe) / industry_pe * 100, cap 20
    if industry_pe > 0 and pe > 0:
        discount = (industry_pe - pe) / industry_pe
        scores["valuation"] = _clamp(discount * 100, 0, 20)
    else:
        scores["valuation"] = 10.0

    # 2. growth: stub — need prospectus data
    scores["growth"] = 10.0

    # 3. industry_heat: stub — need sector capital flow
    scores["industry_heat"] = 10.0

    # 4. institution: stub — need offline subscription data
    scores["institution"] = 10.0

    # 5. break-even risk: lower PE / industry_pe ratio = lower risk
    if pe > 0 and industry_pe > 0:
        risk_raw = 100 - (pe / industry_pe * 50)
        scores["low_risk"] = _clamp(risk_raw / 5, 0, 20)
    else:
        scores["low_risk"] = 10.0

    total = int(sum(scores.values()))
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
