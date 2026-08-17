"""Weight and blood pressure logging."""
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import WeightEntry, BPEntry
from app.config import settings


async def log_weight(session: AsyncSession, user_id: int, weight_kg: float) -> WeightEntry:
    entry = WeightEntry(user_id=user_id, datetime=datetime.now(), weight_kg=weight_kg)
    session.add(entry)
    await session.flush()
    return entry


async def log_bp(session: AsyncSession, user_id: int, systolic: int, diastolic: int, pulse: int | None = None) -> BPEntry:
    is_alert = systolic >= settings.BP_SYS_ALERT or diastolic >= settings.BP_DIA_ALERT
    entry = BPEntry(
        user_id=user_id,
        datetime=datetime.now(),
        systolic=systolic,
        diastolic=diastolic,
        pulse=pulse,
        is_alert=is_alert,
    )
    session.add(entry)
    await session.flush()
    return entry


def bp_category(systolic: int, diastolic: int) -> str:
    if systolic >= 160 or diastolic >= 110:
        return "🔴 Тяжёлая гипертензия — срочно к врачу!"
    if systolic >= 140 or diastolic >= 90:
        return "⚠️ Повышенное давление — сообщите врачу"
    if systolic >= 130 or diastolic >= 85:
        return "🟡 Пограничное значение — понаблюдайте"
    return "✅ В норме"
