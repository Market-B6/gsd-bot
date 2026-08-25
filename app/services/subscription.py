"""Subscription and quota management."""
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User, SubscriptionTier, ProductType
from app.config import settings


def is_pro(user: User) -> bool:
    from app.config import settings
    if user.tg_id == settings.ADMIN_TG_ID:
        return True
    if user.subscription_tier != SubscriptionTier.PRO:
        return False
    if user.subscription_expires_at is None:
        return False
    return user.subscription_expires_at > datetime.now()


def _reset_quota_if_needed(user: User) -> None:
    now = datetime.now()
    if user.quota_reset_at is None or user.quota_reset_at < now:
        user.ai_photos_used_month = 0
        user.ai_chat_used_month = 0
        user.pdf_reports_used_month = 0
        # next reset in 30 days
        user.quota_reset_at = now + timedelta(days=30)


async def can_use_ai_photo(session: AsyncSession, user: User) -> bool:
    _reset_quota_if_needed(user)
    if is_pro(user):
        return True
    limit = settings.FREE_AI_PHOTOS_PER_MONTH + (user.ai_photos_extra or 0)
    return user.ai_photos_used_month < limit


async def consume_ai_photo(session: AsyncSession, user: User) -> None:
    _reset_quota_if_needed(user)
    if is_pro(user):
        return
    if user.ai_photos_extra and user.ai_photos_extra > 0:
        # use extra pack first
        user.ai_photos_extra -= 1
    else:
        user.ai_photos_used_month += 1


async def can_use_ai_chat(session: AsyncSession, user: User) -> bool:
    _reset_quota_if_needed(user)
    if is_pro(user):
        return True
    limit = settings.FREE_AI_CHAT_PER_MONTH
    return user.ai_chat_used_month < limit


async def consume_ai_chat(session: AsyncSession, user: User) -> None:
    _reset_quota_if_needed(user)
    if is_pro(user):
        return
    user.ai_chat_used_month += 1


async def can_use_pdf(session: AsyncSession, user: User) -> bool:
    _reset_quota_if_needed(user)
    if is_pro(user):
        return True
    return user.pdf_reports_used_month < settings.FREE_PDF_PER_MONTH


async def consume_pdf(session: AsyncSession, user: User) -> None:
    _reset_quota_if_needed(user)
    if is_pro(user):
        return
    user.pdf_reports_used_month += 1


async def start_trial(session: AsyncSession, user: User) -> bool:
    """Activate trial if not used before. Returns True if activated."""
    if user.trial_used:
        return False
    user.trial_used = True
    user.subscription_tier = SubscriptionTier.PRO
    user.subscription_expires_at = datetime.now() + timedelta(days=settings.TRIAL_DAYS)
    return True


async def grant_subscription(session: AsyncSession, user: User, product: ProductType) -> None:
    """Extend PRO subscription based on purchased product."""
    now = datetime.now()
    base = user.subscription_expires_at if (
        user.subscription_expires_at and user.subscription_expires_at > now
    ) else now

    if product == ProductType.SUB_MONTHLY:
        user.subscription_expires_at = base + timedelta(days=30)
    elif product == ProductType.SUB_YEARLY:
        user.subscription_expires_at = base + timedelta(days=365)

    user.subscription_tier = SubscriptionTier.PRO


async def grant_pack(session: AsyncSession, user: User, product: ProductType) -> None:
    """Apply one-time purchases: AI photo pack, PDF report token."""
    if product == ProductType.AI_PHOTO_PACK:
        user.ai_photos_extra = (user.ai_photos_extra or 0) + 50
    elif product == ProductType.PDF_REPORT:
        # give one PDF token by lowering used counter
        user.pdf_reports_used_month = max(0, user.pdf_reports_used_month - 1)


async def grant_referral_reward(session: AsyncSession, user: User) -> None:
    """Add REFERRAL_REWARD_DAYS to expiry (activating PRO if needed)."""
    now = datetime.now()
    base = user.subscription_expires_at if (
        user.subscription_expires_at and user.subscription_expires_at > now
    ) else now
    user.subscription_expires_at = base + timedelta(days=settings.REFERRAL_REWARD_DAYS)
    user.subscription_tier = SubscriptionTier.PRO


def subscription_status_text(user: User) -> str:
    if is_pro(user):
        exp_dt = user.subscription_expires_at
        if exp_dt is None:
            return "⭐ PRO активна (бессрочно)"
        return f"⭐ PRO активна до {exp_dt.strftime('%d.%m.%Y')}"
    photos_left = max(
        0,
        settings.FREE_AI_PHOTOS_PER_MONTH
        + (user.ai_photos_extra or 0)
        - (user.ai_photos_used_month or 0),
    )
    chat_left = max(
        0, settings.FREE_AI_CHAT_PER_MONTH - (user.ai_chat_used_month or 0)
    )
    quota = f"\n📸 Фото: {photos_left} · 💬 Сообщений Миле: {chat_left}"
    if user.trial_used:
        return "🆓 Бесплатный тариф (пробный период использован)" + quota
    return "🆓 Бесплатный тариф · доступен пробный период 7 дней" + quota
