from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import get_logger

router = APIRouter(prefix="/api/kronos", tags=["kronos"])
log = get_logger("finance.kronos")


class PredictRequest(BaseModel):
    stock_code: str
    days: int = 5


@router.get("/health")
async def kronos_health() -> dict[str, Any]:
    # Real check: is the Kronos model importable? Report degraded (not ok)
    # when the model is absent so monitoring reflects reality.
    model_available = False
    try:
        model_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "model")
        if model_dir not in sys.path:
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from model.kronos import KronosPredictor  # noqa: F401
        model_available = True
    except Exception as exc:
        log.warning("kronos health: model not available: %s", exc)
    return {
        "status": "ok" if model_available else "degraded",
        "service": "kronos",
        "model_available": model_available,
    }


@router.post("/predict")
async def kronos_predict(req: PredictRequest) -> dict[str, Any]:
    """Predict future K-line data for a stock using Kronos model."""
    log.info("POST /api/kronos/predict code=%s days=%d", req.stock_code, req.days)
    try:
        # Try importing from model directory (copied from facecat-kronos)
        model_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "model")
        if model_dir not in sys.path:
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

        from model.kronos import KronosPredictor, KronosTokenizer  # noqa: F401
        from model.kronos import Kronos

        model = KronosPredictor()
        predictions = model.predict(req.stock_code, req.days)
        return {"stock_code": req.stock_code, "predictions": predictions}
    except ImportError:
        log.warning("kronos predict: model not available, returning stub data")
        base_date = datetime.now()
        predictions = []
        for i in range(req.days):
            d = base_date + timedelta(days=i + 1)
            predictions.append({
                "date": d.strftime("%Y-%m-%d"),
                "open": 10.0 + i * 0.1,
                "high": 10.5 + i * 0.1,
                "low": 9.8 + i * 0.1,
                "close": 10.2 + i * 0.1,
            })
        return {"stock_code": req.stock_code, "predictions": predictions, "stub": True}
    except Exception as exc:
        log.exception("kronos predict failed for %s", req.stock_code)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
