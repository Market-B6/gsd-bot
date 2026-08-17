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
    await session.flush()
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
) -> AITask:
    """Kick off photo -> BJU/XE/risk analysis.

    The image is passed as base64 rather than a Telegram file URL on purpose:
    a Telegram file URL embeds BOT_TOKEN, which must not leak to the LLM gateway.
    """
    # Stored input_data stays small — the base64 blob is dispatch-only.
    task = await _create_task(session, user_id, "photo_meal", {"tg_file_id": file_id})
    await _dispatch_to_n8n(
        task, {"tg_file_id": file_id, "image_b64": image_b64, "mime": mime}
    )
    return task


async def weekly_analysis(session: AsyncSession, user_id: int, diary_data: dict) -> AITask:
    payload = {"diary": diary_data}
    task = await _create_task(session, user_id, "weekly_analysis", payload)
    await _dispatch_to_n8n(task, payload)
    return task


async def chat_query(session: AsyncSession, user_id: int, question: str, context: dict) -> AITask:
    payload = {"question": question, "context": context}
    task = await _create_task(session, user_id, "chat", payload)
    await _dispatch_to_n8n(task, payload)
    return task


async def portion_advice(session: AsyncSession, user_id: int, food: str, context: dict) -> AITask:
    payload = {"food": food, "context": context}
    task = await _create_task(session, user_id, "portion_advice", payload)
    await _dispatch_to_n8n(task, payload)
    return task
