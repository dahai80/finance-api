from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_logger, settings
import storage
from routers import health, ipo

log = get_logger("finance.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("finance-api startup, mock=%s", settings.akshare_mock)
    yield
    log.info("finance-api shutdown")
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


@app.get("/")
async def root() -> dict:
    return {"service": "finance-api", "docs": "/docs"}
