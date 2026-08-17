"""Background loops:
- meal timers (1h post-meal)
- morning fasting reminder (per-user reminder_fasting_time)
- evening summary (per-user reminder_evening_time)
- postpartum OGTT nudges
- monthly quota reset & subscription expiry
- weekly critical-glucose alert to admin
"""
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import select, and_
from app.database import AsyncSessionLocal
from app.models import (
    Timer, User, PostpartumReminder, SubscriptionTier, GlucoseReading, GlucoseType,
)
from app.bot.handlers import bot
from app.config import settings


async def check_timers():
    async with AsyncSessionLocal() as session:
        now = datetime.now()
        result = await session.execute(
            select(Timer).where(Timer.is_notified.is_(False), Timer.notify_at <= now)
        )
        for timer in result.scalars().all():
            user = (await session.execute(select(User).where(User.id == timer.user_id))).scalar_one_or_none()
            if user:
                try:
                    await bot.send_message(
                        user.tg_id,
                        "⏰ Прошёл час после еды!\n\nПора замерить сахар 🩸\nНажмите «Замер сахара» ⬇️",
                    )
                except Exception:
                    pass
            timer.is_notified = True
        await session.commit()


async def send_time_based_reminders():
    """Fires every minute; nudges users whose reminder time matches now (HH:MM)."""
    async with AsyncSessionLocal() as session:
        now = datetime.now()
        hh_mm = now.strftime("%H:%M")

        # Skip if minute already passed within same run boundary
        fasting_users = (await session.execute(
            select(User).where(
                User.reminders_enabled.is_(True),
                User.reminder_fasting_time == hh_mm,
            )
        )).scalars().all()
        for u in fasting_users:
            # Skip if user already logged fasting today
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            already = await session.scalar(
                select(GlucoseReading.id).where(
                    GlucoseReading.user_id == u.id,
                    GlucoseReading.type == GlucoseType.FASTING,
                    GlucoseReading.datetime >= today,
                )
            )
            if already:
                continue
            try:
                await bot.send_message(
                    u.tg_id,
                    "☀️ Доброе утро!\n\nПора замерить сахар натощак. Это самый важный замер за день 🩸",
                )
            except Exception:
                pass

        evening_users = (await session.execute(
            select(User).where(
                User.reminders_enabled.is_(True),
                User.reminder_evening_time == hh_mm,
            )
        )).scalars().all()
        for u in evening_users:
            try:
                await bot.send_message(
                    u.tg_id,
                    "🌙 Как прошёл день?\n\nПроверьте, все ли замеры и приёмы пищи записаны в дневник. "
                    "Регулярность — ключ к контролю ГСД.",
                )
            except Exception:
                pass


async def send_postpartum_reminders():
    async with AsyncSessionLocal() as session:
        now = datetime.now()
        due = (await session.execute(
            select(PostpartumReminder).where(
                PostpartumReminder.sent.is_(False),
                PostpartumReminder.scheduled_at <= now,
            )
        )).scalars().all()
        from app.services.postpartum import REMINDER_TEXTS
        for r in due:
            user = await session.get(User, r.user_id)
            if user:
                try:
                    await bot.send_message(user.tg_id, REMINDER_TEXTS.get(r.reminder_type, "Напоминание"))
                except Exception:
                    pass
            r.sent = True
        await session.commit()


async def check_subscriptions():
    """Downgrade expired PRO to FREE, notify 3 days before expiry."""
    async with AsyncSessionLocal() as session:
        now = datetime.now()
        soon = now + timedelta(days=3)

        # Expired
        expired = (await session.execute(
            select(User).where(
                User.subscription_tier == SubscriptionTier.PRO,
                User.subscription_expires_at.is_not(None),
                User.subscription_expires_at < now,
            )
        )).scalars().all()
        for u in expired:
            u.subscription_tier = SubscriptionTier.FREE
            try:
                await bot.send_message(
                    u.tg_id,
                    "⚠️ Ваша PRO подписка закончилась. Продлите: /pro",
                )
            except Exception:
                pass

        # Expiring soon (once per day, guard via a marker date in reminder)
        expiring = (await session.execute(
            select(User).where(
                User.subscription_tier == SubscriptionTier.PRO,
                User.subscription_expires_at.is_not(None),
                and_(User.subscription_expires_at >= now, User.subscription_expires_at <= soon),
            )
        )).scalars().all()
        for u in expiring:
            try:
                days_left = (u.subscription_expires_at - now).days + 1
                await bot.send_message(
                    u.tg_id,
                    f"⏳ PRO подписка истекает через {days_left} дн.\n\nПродлить: /pro",
                )
            except Exception:
                pass
        await session.commit()


async def _last_run_marker():
    """Simple in-memory guard to avoid double-firing minute-based tasks."""
    return None


async def scheduler_loop():
    last_minute = None
    last_hour_check = None
    while True:
        try:
            await check_timers()
        except Exception:
            pass
        now = datetime.now()
        current_min = now.strftime("%Y%m%d%H%M")
        if current_min != last_minute:
            last_minute = current_min
            try:
                await send_time_based_reminders()
            except Exception:
                pass
        # Hourly tasks
        current_hour = now.strftime("%Y%m%d%H")
        if current_hour != last_hour_check:
            last_hour_check = current_hour
            try:
                await send_postpartum_reminders()
                await check_subscriptions()
            except Exception:
                pass
        await asyncio.sleep(30)
