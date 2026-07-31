from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User, Meal, GlucoseReading, InsulinDose, UserEvent


async def log_event(session: AsyncSession, user_id: int, event_type: str):
    """Log a user event for analytics"""
    event = UserEvent(user_id=user_id, event_type=event_type)
    session.add(event)


async def get_stats(session: AsyncSession) -> dict:
    """Get bot statistics"""
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    # Total users
    total_users = await session.scalar(select(func.count(User.id)))

    # New users today
    new_today = await session.scalar(
        select(func.count(User.id)).where(User.created_at >= today)
    )

    # New users this week
    new_week = await session.scalar(
        select(func.count(User.id)).where(User.created_at >= week_ago)
    )

    # Active users today (have any event today)
    active_today = await session.scalar(
        select(func.count(func.distinct(UserEvent.user_id))).where(
            UserEvent.created_at >= today
        )
    )

    # Active users this week
    active_week = await session.scalar(
        select(func.count(func.distinct(UserEvent.user_id))).where(
            UserEvent.created_at >= week_ago
        )
    )

    # Total meals
    total_meals = await session.scalar(select(func.count(Meal.id)))

    # Total glucose readings
    total_glucose = await session.scalar(select(func.count(GlucoseReading.id)))

    # Total insulin doses
    total_insulin = await session.scalar(select(func.count(InsulinDose.id)))

    # Meals today
    meals_today = await session.scalar(
        select(func.count(Meal.id)).where(Meal.datetime >= today)
    )

    # Glucose today
    glucose_today = await session.scalar(
        select(func.count(GlucoseReading.id)).where(GlucoseReading.datetime >= today)
    )

    # Retention: users who used bot more than 1 day
    retention_result = await session.execute(
        select(func.count(func.distinct(UserEvent.user_id))).where(
            UserEvent.created_at >= week_ago
        ).group_by(UserEvent.user_id).having(
            func.count(func.distinct(func.date_trunc('day', UserEvent.created_at))) > 1
        )
    )
    retained_users = len(retention_result.all())

    return {
        'total_users': total_users or 0,
        'new_today': new_today or 0,
        'new_week': new_week or 0,
        'active_today': active_today or 0,
        'active_week': active_week or 0,
        'total_meals': total_meals or 0,
        'total_glucose': total_glucose or 0,
        'total_insulin': total_insulin or 0,
        'meals_today': meals_today or 0,
        'glucose_today': glucose_today or 0,
        'retained_week': retained_users,
    }
