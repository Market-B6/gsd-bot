from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio
import logging
from app.config import settings
from app.bot.handlers import bot, dp
from app.database import async_engine, Base
from app.api.routes import router as api_router
from app.scheduler import scheduler_loop

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting application...")
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Starting bot polling...")
    asyncio.create_task(dp.start_polling(bot))
    logger.info("Bot polling started")

    logger.info("Starting scheduler...")
    asyncio.create_task(scheduler_loop())

    yield

    # Shutdown
    logger.info("Shutting down...")
    await bot.session.close()

app = FastAPI(title="GSD Diary API", version="1.0.0", lifespan=lifespan)

app.include_router(api_router, prefix="/api/v1", tags=["api"])

@app.get("/")
async def root():
    return {"message": "GSD Diary API is running"}

@app.get("/health")
async def health():
    return {"status": "ok"}
