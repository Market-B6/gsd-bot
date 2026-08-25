"""Client for AI operations. Delegates to n8n webhook when configured, else calls vibecode directly.

All LLM traffic goes through vibecode (OpenAI-compatible gateway at VIBECODE_BASE_URL).
No direct Anthropic keys are used anywhere.

n8n contract (POST N8N_WEBHOOK_URL):
  {
    "task_type": "photo_meal" | "weekly_analysis" | "chat" | "portion_advice",
    "user_id": int,
    "callback_url": str,   # bot API endpoint n8n should POST result to
    "callback_token": str, # Bearer token for callback
    "data": { ... task-specific payload ... }
  }

n8n callback: POST {callback_url}
  Header:  Authorization: Bearer {callback_token}
  Body:    { "task_id": int, "status": "done"|"failed", "result": {...}, "error": "..." }
"""
import json
from typing import Any
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models import AITask


async def _create_task(session: AsyncSession, user_id: int, task_type: str, input_data: dict) -> AITask:
    task = AITask(
        user_id=user_id,
        task_type=task_type,
        status="pending",
        input_data=json.dumps(input_data, ensure_ascii=False),
    )
    session.add(task)
    # Commit before dispatch: n8n may call back faster than we flush.
    await session.commit()
    return task


async def _dispatch_to_n8n(task: AITask, payload: dict) -> bool:
    if not settings.N8N_WEBHOOK_URL:
        return False
    callback_url = f"{settings.PUBLIC_BASE_URL}/api/v1/ai/callback" if settings.PUBLIC_BASE_URL else ""
    body = {
        "task_id": task.id,
        "task_type": task.task_type,
        "user_id": task.user_id,
        "callback_url": callback_url,
        "callback_token": settings.N8N_CALLBACK_TOKEN or "",
        "data": payload,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(settings.N8N_WEBHOOK_URL, json=body)
            r.raise_for_status()
        task.status = "processing"
        return True
    except Exception as e:
        task.status = "failed"
        task.error = f"n8n dispatch failed: {e}"
        return False


async def analyze_meal_photo(
    session: AsyncSession,
    user_id: int,
    file_id: str,
    image_b64: str | None = None,
    mime: str = "image/jpeg",
    placeholder_message_id: int | None = None,
) -> AITask:
    """Kick off photo -> BJU/XE/risk analysis.

    The image is passed as base64 rather than a Telegram file URL on purpose:
    a Telegram file URL embeds BOT_TOKEN, which must not leak to the LLM gateway.
    """
    # Stored input_data stays small — the base64 blob is dispatch-only.
    task = await _create_task(
        session, user_id, "photo_meal",
        {"tg_file_id": file_id, "placeholder_message_id": placeholder_message_id},
    )
    await _dispatch_to_n8n(
        task, {"tg_file_id": file_id, "image_b64": image_b64, "mime": mime}
    )
    return task


async def weekly_analysis(
    session: AsyncSession,
    user_id: int,
    diary_data: dict,
    placeholder_message_id: int | None = None,
) -> AITask:
    payload = {"diary": diary_data}
    task = await _create_task(
        session, user_id, "weekly_analysis",
        {**payload, "placeholder_message_id": placeholder_message_id},
    )
    await _dispatch_to_n8n(task, payload)
    return task


MEMORY_PAIRS = 3
MEMORY_HOURS = 24

BOT_CAPABILITIES = """
**Возможности бота «Глюко-Мама»**

Главное меню: 🍽 Приём пищи, 🩸 Замер сахара, 💉 Инсулин, 📊 Мой дневник, 💬 Спросить Милу, ⭐ PRO.

**Дневник** (📊): история (Сегодня/Неделя), статистика, 📄 PDF-отчёт врачу (FREE: 1/мес, PRO: без лимита), 📎 Excel, 🤖 AI-анализ недели (PRO).

**Команды**: /weight (вес), /bp (давление), /kicks (шевеления), /start (сброс).

**FREE vs PRO** (250⭐/мес ~299₽, пробный 7 дн):
FREE: 5 фото + 10 сообщений Миле в месяц, 1 PDF, полный дневник.
PRO: 100 фото, Мила без лимита, AI-анализ недели, умные напоминания (утро натощак + вечерняя сводка), PDF без лимита.

**Фото-анализ**: пришли фото тарелки → БЖУ, ХЕ, риск скачка.

**Реферальная программа**: /pro → «Пригласить подругу» — за каждую подругу с PRO +7 дней вам обеим.

**Что ты умеешь**: отвечать про питание/ХЕ/порции (с конкретными граммами), помнить разговор (3 пары за 24ч), анализировать дневник (PRO), разбирать фото еды. Не ставишь диагнозы, не назначаешь лечение/дозы, при тревоге направляешь к врачу.
"""


async def _load_chat_history(session: AsyncSession, user_id: int) -> list[dict]:
    """Last few answered chat turns, oldest first.

    Only completed chat tasks are used: an unanswered question would leave
    a dangling user turn and confuse the model.
    """
    from datetime import datetime, timedelta
    from sqlalchemy import select
    since = datetime.now() - timedelta(hours=MEMORY_HOURS)
    rows = (await session.execute(
        select(AITask)
        .where(
            AITask.user_id == user_id,
            AITask.task_type == "chat",
            AITask.result_data.isnot(None),
            AITask.created_at >= since,
        )
        .order_by(AITask.id.desc())
        .limit(MEMORY_PAIRS)
    )).scalars().all()

    history: list[dict] = []
    for task in reversed(rows):
        try:
            q = (json.loads(task.input_data or "{}")).get("question")
            a = (json.loads(task.result_data or "{}")).get("answer")
        except (ValueError, TypeError):
            continue
        if q and a:
            history.append({"q": str(q), "a": str(a)})
    return history


async def chat_query(
    session: AsyncSession,
    user_id: int,
    question: str,
    context: dict,
    placeholder_message_id: int | None = None,
) -> AITask:
    # History is read before the new task exists, so it cannot include itself.
    history = await _load_chat_history(session, user_id)
    context["bot_capabilities"] = BOT_CAPABILITIES
    payload = {"question": question, "context": context}
    task = await _create_task(
        session, user_id, "chat",
        {**payload, "placeholder_message_id": placeholder_message_id},
    )
    # Dispatch-only: storing history would duplicate it in every row.
    await _dispatch_to_n8n(task, {**payload, "history": history})
    return task


async def portion_advice(session: AsyncSession, user_id: int, food: str, context: dict) -> AITask:
    payload = {"food": food, "context": context}
    task = await _create_task(session, user_id, "portion_advice", payload)
    await _dispatch_to_n8n(task, payload)
    return task
