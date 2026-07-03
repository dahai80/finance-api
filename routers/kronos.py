from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import get_logger

router = APIRouter(prefix="/api/kronos", tags=["kronos"])
log = get_logger("finance.kronos")

# 项目根（finance-api/）—— model 包位于其下，需加入 sys.path 才能 `from model.kronos import ...`
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


class PredictRequest(BaseModel):
    stock_code: str = Field(..., min_length=1, max_length=16)
    days: int = Field(5, ge=1, le=365)


def _ensure_model_importable() -> None:
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)


@router.get("/health")
async def kronos_health() -> dict[str, Any]:
    # Real check: is the Kronos model importable? Report degraded (not ok)
    # when the model is absent so monitoring reflects reality.
    model_available = False
    try:
        _ensure_model_importable()
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
        _ensure_model_importable()
        from model.kronos import KronosPredictor

        model = KronosPredictor()
        predictions = model.predict(req.stock_code, req.days)
        return {"stock_code": req.stock_code, "predictions": predictions}
    except ImportError:
        # 模型不可用时绝不返回捏造价格——股价准确零容忍。如实返回 503。
        log.warning("kronos predict: model not available, returning 503")
        raise HTTPException(status_code=503, detail="kronos model unavailable") from None
    except Exception:
        log.exception("kronos predict failed for %s", req.stock_code)
        # 不泄露内部异常细节，只返回脱敏错误
        raise HTTPException(status_code=500, detail="kronos predict failed") from None
