from fastapi import APIRouter

from config import get_logger, settings

router = APIRouter()
log = get_logger("finance.health")


@router.get("/health")
async def health() -> dict:
    log.info("health probe")
    return {
        "status": "ok",
        "service": "finance-api",
        "akshare_mock": settings.akshare_mock,
    }
