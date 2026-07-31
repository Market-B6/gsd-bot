from datetime import datetime, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User, Meal, GlucoseReading, InsulinDose, GlucoseType, InsulinType


async def get_user_stats(session: AsyncSession, user: User) -> str:
    """Generate personal statistics for a user"""
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    # Glucose stats for the week
    glucose_week = await session.execute(
        select(GlucoseReading).where(
            GlucoseReading.user_id == user.id,
            GlucoseReading.datetime >= week_ago
        )
    )
    readings = glucose_week.scalars().all()

    # Insulin stats for the week
    insulin_week = await session.execute(
        select(InsulinDose).where(
            InsulinDose.user_id == user.id,
            InsulinDose.datetime >= week_ago
        )
    )
    doses = insulin_week.scalars().all()

    # Meals for the week
    meals_week = await session.execute(
        select(Meal).where(
            Meal.user_id == user.id,
            Meal.datetime >= week_ago
        )
    )
    meals = meals_week.scalars().all()

    # Total records (all time)
    total_meals = await session.scalar(
        select(func.count(Meal.id)).where(Meal.user_id == user.id)
    )
    total_glucose = await session.scalar(
        select(func.count(GlucoseReading.id)).where(GlucoseReading.user_id == user.id)
    )

    # Build stats text
    text = "📊 **Моя статистика за неделю**\n\n"

    # Glucose
    if readings:
        values = [r.value for r in readings]
        avg_glucose = sum(values) / len(values)
        min_glucose = min(values)
        max_glucose = max(values)
        normal_count = sum(1 for r in readings if r.is_normal)
        normal_pct = (normal_count / len(readings)) * 100

        fasting = [r.value for r in readings if r.type == GlucoseType.FASTING]
        postmeal = [r.value for r in readings if r.type == GlucoseType.POSTMEAL]

        text += "🩸 **Глюкоза:**\n"
        text += f"  Замеров: {len(readings)}\n"
        text += f"  Средняя: {avg_glucose:.1f} ммоль/л\n"
        text += f"  Мин/Макс: {min_glucose:.1f} / {max_glucose:.1f}\n"
        text += f"  В норме: {normal_pct:.0f}%\n"
        if fasting:
            text += f"  Натощак (средн.): {sum(fasting)/len(fasting):.1f}\n"
        if postmeal:
            text += f"  После еды (средн.): {sum(postmeal)/len(postmeal):.1f}\n"
        text += "\n"
    else:
        text += "🩸 Замеров глюкозы нет\n\n"

    # Insulin
    if doses:
        total_units = sum(d.units for d in doses)
        short_units = sum(d.units for d in doses if d.type == InsulinType.SHORT)
        long_units = sum(d.units for d in doses if d.type == InsulinType.LONG)
        days_with_insulin = len(set(d.datetime.date() for d in doses))
        avg_per_day = total_units / max(days_with_insulin, 1)

        text += "💉 **Инсулин:**\n"
        text += f"  Всего за неделю: {total_units:.0f} Ед\n"
        text += f"  Короткий: {short_units:.0f} Ед\n"
        text += f"  Длинный: {long_units:.0f} Ед\n"
        text += f"  В среднем/день: {avg_per_day:.1f} Ед\n\n"
    else:
        text += "💉 Инсулин не вводился\n\n"

    # Meals
    if meals:
        days_with_meals = len(set(m.datetime.date() for m in meals))
        avg_meals_day = len(meals) / max(days_with_meals, 1)
        text += "🍽 **Питание:**\n"
        text += f"  Приёмов пищи: {len(meals)}\n"
        text += f"  В среднем/день: {avg_meals_day:.1f}\n\n"
    else:
        text += "🍽 Приёмов пищи нет\n\n"

    # Summary
    text += f"📈 **Всего записей:**\n"
    text += f"  Приёмов пищи: {total_meals or 0}\n"
    text += f"  Замеров сахара: {total_glucose or 0}\n"

    # Tips based on data
    if readings:
        normal_pct = (sum(1 for r in readings if r.is_normal) / len(readings)) * 100
        if normal_pct >= 80:
            text += "\n✅ Отличный контроль! Так держать!"
        elif normal_pct >= 60:
            text += "\n⚠️ Неплохо, но есть куда расти. Обсудите с врачом."
        else:
            text += "\n🔴 Много выходов за норму. Обязательно покажите дневник врачу."

    return text
