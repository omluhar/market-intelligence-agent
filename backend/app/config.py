from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    OPENAI_API_KEY: str = ""
    DRY_RUN: bool = True
    MAX_PORTFOLIO_RISK_PCT: float = 0.05
    MAX_POSITION_SIZE_USD: float = 1000.0
    PAPER_CASH_USD: float = 20_000.0
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    CORS_ORIGIN_REGEX: str = r"https://.*\.(vercel\.app|onrender\.com|railway\.app)"
    DUCKDB_PATH: str = ""
    FRONTEND_DIST: str = ""
    SNAPTRADE_CLIENT_ID: str = ""
    SNAPTRADE_CONSUMER_KEY: str = ""
    PORTFOLIO_REDIRECT_URL: str = ""

    class Config:
        env_file = str(_ENV_FILE)

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
