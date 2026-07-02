from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

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
    try:
        yield
    finally:
        log.info("finance-api shutdown")
        try:
            sched.shutdown(wait=False)
        except Exception:
            log.exception("scheduler shutdown failed")
        try:
            await asyncio.wait_for(storage.close(), timeout=10.0)
        except asyncio.TimeoutError:
            log.warning("storage close timed out (10s), abandoning")
        except Exception:
            log.exception("storage close failed")


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
    except Exception:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "ok": False},
        )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
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
