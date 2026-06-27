from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_logger, settings
import storage
from routers import health, ipo, market, backtest, industry, ws
from scheduler import init_scheduler

log = get_logger("finance.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("finance-api startup, mock=%s", settings.akshare_mock)
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


@app.get("/")
async def root() -> dict:
    return {"service": "finance-api", "docs": "/docs"}
