import logging
import os

logging.basicConfig(
    level=os.environ.get("FINANCE_LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class Settings:
    def __init__(self) -> None:
        self.pg_dsn: str = os.environ.get(
            "FINANCE_PG_DSN",
            "postgresql://dahai@localhost:5432/openclaw_finance",
        )
        self.redis_url: str = os.environ.get(
            "FINANCE_REDIS_URL", "redis://localhost:6379/0"
        )
        self.tushare_token: str = os.environ.get("TUSHARE_TOKEN", "")
        self.akshare_mock: bool = os.environ.get("FINANCE_AKSHARE_MOCK", "0") == "1"
        self.cors_origins: list[str] = [
            o.strip() for o in
            os.environ.get("FINANCE_CORS_ORIGINS", "http://localhost:3000").split(",")
            if o.strip()
        ]


settings = Settings()
