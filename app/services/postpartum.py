"""Postpartum tracking: OGTT reminders at 6 weeks and 1 year (SD2 risk after GDM)."""
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User, PostpartumReminder, PostpartumStage


async def register_birth(session: AsyncSession, user: User, birth_date: datetime) -> None:
    user.birth_date = birth_date
    user.postpartum_stage = PostpartumStage.POSTPARTUM

    # Schedule OGTT reminders
    ogtt_6w = PostpartumReminder(
        user_id=user.id,
        reminder_type="ogtt_6w",
        scheduled_at=birth_date + timedelta(weeks=6),
    )
    ogtt_1y = PostpartumReminder(
        user_id=user.id,
        reminder_type="ogtt_1y",
        scheduled_at=birth_date + timedelta(days=365),
    )
    weight_6m = PostpartumReminder(
        user_id=user.id,
        reminder_type="weight_6m",
        scheduled_at=birth_date + timedelta(days=180),
    )
    session.add_all([ogtt_6w, ogtt_1y, weight_6m])


async def due_reminders(session: AsyncSession) -> list[PostpartumReminder]:
    now = datetime.now()
    result = await session.execute(
        select(PostpartumReminder).where(
            PostpartumReminder.sent.is_(False),
            PostpartumReminder.scheduled_at <= now,
        )
    )
    return list(result.scalars().all())


REMINDER_TEXTS = {
    "ogtt_6w": (
        "👶 Прошло 6 недель после родов.\n\n"
        "Согласно клиническим рекомендациям, женщинам с ГСД в анамнезе показан "
        "оральный глюкозотолерантный тест (ОГТТ) через 6-12 недель после родов.\n\n"
        "Риск развития СД2 в течение 10 лет после ГСД повышен в 7 раз. "
        "Ранняя диагностика позволяет предотвратить осложнения.\n\n"
        "Запишитесь к эндокринологу на ОГТТ."
    ),
    "ogtt_1y": (
        "📆 Прошёл год после родов.\n\n"
        "Пора повторить ОГТТ и проверить гликированный гемоглобин (HbA1c). "
        "Такой скрининг рекомендуется ежегодно после ГСД."
    ),
    "weight_6m": (
        "⚖️ Полгода после родов.\n\n"
        "Возвращение к весу до беременности снижает риск СД2 в 2 раза. "
        "Хотите начать трекать вес и питание снова? Бот поможет."
    ),
}
