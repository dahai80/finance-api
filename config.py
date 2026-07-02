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
        self.force_real_data: bool = os.environ.get("FINANCE_FORCE_REAL_DATA", "0") == "1"
        self.kronos_url: str = os.environ.get("KRONOS_URL", "http://localhost:8001")
        self.kronos_timeout: int = int(os.environ.get("KRONOS_TIMEOUT", "15"))
        self.llm_url: str = os.environ.get("LLM_URL", "http://localhost:8080")
        self.llm_model: str = os.environ.get("LLM_MODEL", "qwen2.5-7b-instruct")
        self.llm_timeout: int = int(os.environ.get("LLM_TIMEOUT", "60"))
        self.redis_ttl: int = int(os.environ.get("REDIS_TTL", "86400"))
        self.cors_origins: list[str] = [
            o.strip() for o in
            os.environ.get("FINANCE_CORS_ORIGINS", "http://localhost:3000").split(",")
            if o.strip()
        ]


settings = Settings()
