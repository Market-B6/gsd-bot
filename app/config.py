from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://gsd_user:gsd_pass@localhost:5432/gsd_db"

    # Telegram Bot
    BOT_TOKEN: str
    WEBHOOK_URL: Optional[str] = None

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    SECRET_KEY: str

    # n8n Integration
    N8N_WEBHOOK_URL: Optional[str] = None

    # Timezone
    DEFAULT_TIMEZONE: str = "Europe/Moscow"

    # Subscription
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
