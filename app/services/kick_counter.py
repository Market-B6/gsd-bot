"""Cardiff count-to-10 kick counter."""
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import KickSession
from app.config import settings


async def start_session(session: AsyncSession, user_id: int) -> KickSession:
    ks = KickSession(user_id=user_id, start_time=datetime.now(), kicks_count=0)
    session.add(ks)
    await session.flush()
    return ks


async def get_active_session(session: AsyncSession, user_id: int) -> KickSession | None:
    """Active = end_time is null and started within last KICK_WINDOW_HOURS."""
    threshold = datetime.now() - timedelta(hours=settings.KICK_WINDOW_HOURS)
    result = await session.execute(
        select(KickSession).where(
            KickSession.user_id == user_id,
            KickSession.end_time.is_(None),
            KickSession.start_time >= threshold,
        ).order_by(KickSession.start_time.desc())
    )
    return result.scalars().first()


async def register_kick(session: AsyncSession, ks: KickSession) -> KickSession:
    ks.kicks_count += 1
    if ks.kicks_count >= settings.KICK_TARGET:
        ks.end_time = datetime.now()
    return ks


async def finish_session(session: AsyncSession, ks: KickSession) -> KickSession:
    ks.end_time = datetime.now()
    if ks.kicks_count < settings.KICK_TARGET:
        ks.is_alert = True
    return ks
