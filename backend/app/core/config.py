"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings."""

    # App
    app_name: str = "EarningsEdge"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/earningsedge"
    database_url_sync: str = "postgresql://postgres:password@localhost:5432/earningsedge"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # API Keys
    polygon_api_key: str = ""
    finnhub_api_key: str = ""
    news_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    sec_edgar_user_agent: str = "EarningsEdge/1.0 (contact@earningsedge.com)"

    # Auth
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 1440

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""

    # Telegram
    telegram_bot_token: str = ""

    # Market Data (options IV)
    marketdata_api_key: str = ""

    # ML
    model_path: str = "./models"
    retrain_hour: int = 2

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
