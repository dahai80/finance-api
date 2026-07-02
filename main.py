from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import get_logger, settings
import storage
from routers import health, ipo, market, backtest, industry, ws, watchlist
from scheduler import init_scheduler

log = get_logger("finance.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("finance-api startup, mock=%s force_real=%s", settings.akshare_mock, settings.force_real_data)
    sched = init_scheduler()
    sched.start()
    yield
    log.info("finance-api shutdown")
    sched.shutdown()
    await storage.close()


app = FastAPI(
    title="OpenClaw Finance API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def exception_handler_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "type": type(exc).__name__},
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(ipo.router)
app.include_router(market.router)
app.include_router(backtest.router)
app.include_router(industry.router)
app.include_router(ws.router)
app.include_router(watchlist.router)


@app.get("/")
async def root() -> dict:
    return {"service": "finance-api", "docs": "/docs"}


# ============================================================
# Response helpers - add source flag to distinguish real vs mock
# ============================================================

def ok_response(data: Any, source: str = "real") -> dict[str, Any]:
    """Wrap a successful response with metadata."""
    return {"data": data, "source": source, "ok": True}


def mock_response(data: Any) -> dict[str, Any]:
    """Wrap a mock response - raises 503 if force_real_data is set."""
    if settings.force_real_data:
        from fastapi.exceptions import HTTPException
        raise HTTPException(status_code=503, detail="Data source unavailable (force_real_data mode)")
    return {"data": data, "source": "mock", "ok": True}


def run_async(coro):
    """Run a synchronous function in a thread executor to avoid blocking event loop."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, coro)
