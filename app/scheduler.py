import asyncio
from datetime import datetime
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Timer, User
from app.bot.handlers import bot


async def check_timers():
    """Check for due timers and send notifications"""
    async with AsyncSessionLocal() as session:
        now = datetime.now()
        result = await session.execute(
            select(Timer).where(
                Timer.is_notified == False,
                Timer.notify_at <= now
            )
        )
        timers = result.scalars().all()

        for timer in timers:
            user_result = await session.execute(
                select(User).where(User.id == timer.user_id)
            )
            user = user_result.scalar_one_or_none()

            if user:
                try:
                    await bot.send_message(
                        user.tg_id,
                        "⏰ Прошёл час после еды!\n\n"
                        "Пора замерить сахар 🩸\n"
                        "Нажмите «Замер сахара» ⬇️"
                    )
                except Exception:
                    pass

            timer.is_notified = True

        await session.commit()


async def scheduler_loop():
    """Run timer checks every 30 seconds"""
    while True:
        try:
            await check_timers()
        except Exception:
            pass
        await asyncio.sleep(30)
