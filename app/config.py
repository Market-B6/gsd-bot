from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://gsd_user:gsd_pass@localhost:5432/gsd_db"

    # Telegram Bot
    BOT_TOKEN: str
    WEBHOOK_URL: Optional[str] = None
    # Set when the host blocks outbound traffic to api.telegram.org.
    # Example: socks5://user:pass@45.38.19.51:1080
    TELEGRAM_PROXY_URL: Optional[str] = None
    ADMIN_TG_ID: int = 6935167265
    ADMIN_USERNAME: str = "av69ru"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # API
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    SECRET_KEY: str
    PUBLIC_BASE_URL: Optional[str] = None  # for doctor portal links

    # Timezone
    DEFAULT_TIMEZONE: str = "Europe/Moscow"

    # AI — via vibecode (OpenAI-compatible gateway), called directly OR via n8n
    VIBECODE_API_KEY: Optional[str] = None
    SPOONACULAR_API_KEY: Optional[str] = None
    VIBECODE_BASE_URL: str = "https://vibecode-api.online/v1"
    AI_MODEL: str = "claude-sonnet-5"
    AI_MODEL_FALLBACK: str = "claude-haiku-4-5-20251001"  # used on 429 from primary

    # n8n Integration
    N8N_WEBHOOK_URL: Optional[str] = None  # bot -> n8n
    N8N_CALLBACK_TOKEN: Optional[str] = None  # bearer token n8n -> bot API

    # Payments — Telegram Stars (primary)
    STARS_ENABLED: bool = True
    # Prices in Stars (XTR)
    PRICE_SUB_MONTHLY_XTR: int = 175      # ~ 299 RUB
    PRICE_SUB_YEARLY_XTR: int = 1290      # ~ 2600 RUB (7 mo. discount)
    PRICE_PDF_REPORT_XTR: int = 49
    PRICE_AI_PHOTO_PACK_XTR: int = 79     # 50 photos
    PRICE_COURSE_XTR: int = 499
    PRICE_DOCTOR_SEAT_XTR: int = 490
    PRICE_CONSULTATION_XTR: int = 249

    # RUB display prices (shown in copy)
    PRICE_SUB_MONTHLY_RUB: int = 299
    PRICE_SUB_YEARLY_RUB: int = 2490

    # Quotas — FREE tier
    FREE_PDF_PER_MONTH: int = 1
    FREE_AI_PHOTOS_PER_MONTH: int = 5
    FREE_AI_CHAT_PER_MONTH: int = 10
    PRO_AI_PHOTOS_PER_MONTH: int = 100
    FREE_HISTORY_DAYS: int = 7
    FREE_RECIPES_COUNT: int = 10

    # Trial
    TRIAL_DAYS: int = 7

    # YooKassa (optional secondary)
    YOOKASSA_SHOP_ID: Optional[str] = None
    YOOKASSA_SECRET_KEY: Optional[str] = None
    YOOKASSA_PROVIDER_TOKEN: Optional[str] = None  # telegram payments token

    # Referral
    REFERRAL_REWARD_DAYS: int = 30

    # Preeclampsia thresholds
    BP_SYS_ALERT: int = 140
    BP_DIA_ALERT: int = 90

    # Kick counter (Cardiff count-to-10)
    KICK_TARGET: int = 10
    KICK_WINDOW_HOURS: int = 2

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
