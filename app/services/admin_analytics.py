"""Admin analytics: daily digest, revenue, retention."""
from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User, Payment, PaymentStatus, SubscriptionTier, UserEvent


async def build_admin_digest(session: AsyncSession) -> str:
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    total_users = await session.scalar(select(func.count(User.id))) or 0
    new_today = await session.scalar(
        select(func.count(User.id)).where(User.created_at >= today)
    ) or 0
    new_yesterday = await session.scalar(
        select(func.count(User.id)).where(User.created_at >= yesterday, User.created_at < today)
    ) or 0
    new_week = await session.scalar(
        select(func.count(User.id)).where(User.created_at >= week_ago)
    ) or 0

    active_today = await session.scalar(
        select(func.count(func.distinct(UserEvent.user_id))).where(UserEvent.created_at >= today)
    ) or 0
    active_week = await session.scalar(
        select(func.count(func.distinct(UserEvent.user_id))).where(UserEvent.created_at >= week_ago)
    ) or 0

    pro_active = await session.scalar(
        select(func.count(User.id)).where(
            User.subscription_tier == SubscriptionTier.PRO,
            User.subscription_expires_at > now,
        )
    ) or 0

    revenue_today = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == PaymentStatus.PAID,
            Payment.paid_at >= today,
        )
    ) or 0
    revenue_week = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == PaymentStatus.PAID,
            Payment.paid_at >= week_ago,
        )
    ) or 0
    revenue_month = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == PaymentStatus.PAID,
            Payment.paid_at >= month_ago,
        )
    ) or 0

    payments_today = await session.scalar(
        select(func.count(Payment.id)).where(
            Payment.status == PaymentStatus.PAID,
            Payment.paid_at >= today,
        )
    ) or 0

    conv = (pro_active / total_users * 100) if total_users else 0

    lines = [
        "📊 **Дайджест GSD-бота**",
        f"_{now.strftime('%d.%m.%Y %H:%M')}_",
        "",
        "👥 **Пользователи**",
        f"  Всего: {total_users}",
        f"  Новых сегодня: {new_today} (вчера: {new_yesterday})",
        f"  Новых за неделю: {new_week}",
        f"  Активные сегодня: {active_today}",
        f"  Активные за неделю: {active_week}",
        "",
        "⭐ **Подписки**",
        f"  PRO активных: {pro_active}",
        f"  Конверсия FREE→PRO: {conv:.1f}%",
        "",
        "💰 **Выручка (Stars XTR)**",
        f"  Сегодня: {revenue_today:.0f} XTR ({payments_today} платежей)",
        f"  За неделю: {revenue_week:.0f} XTR",
        f"  За месяц: {revenue_month:.0f} XTR",
    ]
    return "\n".join(lines)


async def critical_glucose_alerts(session: AsyncSession) -> list[dict]:
    """Return users with 3+ high glucose readings today. For admin alerts."""
    from app.models import GlucoseReading
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await session.execute(
        select(GlucoseReading.user_id, func.count(GlucoseReading.id).label("cnt"))
        .where(
            GlucoseReading.datetime >= today,
            GlucoseReading.is_normal.is_(False),
        )
        .group_by(GlucoseReading.user_id)
        .having(func.count(GlucoseReading.id) >= 3)
    )
    return [{"user_id": r[0], "count": r[1]} for r in result.all()]
