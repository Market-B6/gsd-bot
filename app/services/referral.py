"""Referral program: invite a friend, both get +30 days PRO."""
import secrets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User, Referral
from app.services import subscription as sub_svc


def _generate_code() -> str:
    return secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]


async def ensure_code(session: AsyncSession, user: User) -> str:
    if user.referral_code:
        return user.referral_code
    for _ in range(5):
        code = _generate_code()
        exists = await session.execute(select(User).where(User.referral_code == code))
        if exists.scalar_one_or_none() is None:
            user.referral_code = code
            return code
    # fallback deterministic
    user.referral_code = f"u{user.id}"
    return user.referral_code


async def attach_referrer(session: AsyncSession, referee: User, code: str) -> User | None:
    if referee.referrer_id is not None:
        return None
    result = await session.execute(select(User).where(User.referral_code == code))
    referrer = result.scalar_one_or_none()
    if referrer is None or referrer.id == referee.id:
        return None
    referee.referrer_id = referrer.id
    session.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
    return referrer


async def grant_referral_rewards(session: AsyncSession, referee: User) -> User | None:
    """Called when referee makes first PRO purchase. Rewards both parties."""
    if referee.referrer_id is None:
        return None
    result = await session.execute(
        select(Referral).where(Referral.referee_id == referee.id)
    )
    ref = result.scalar_one_or_none()
    if ref is None or ref.reward_granted:
        return None
    referrer_result = await session.execute(select(User).where(User.id == referee.referrer_id))
    referrer = referrer_result.scalar_one_or_none()
    if referrer is None:
        return None
    await sub_svc.grant_referral_reward(session, referrer)
    await sub_svc.grant_referral_reward(session, referee)
    ref.reward_granted = True
    return referrer
