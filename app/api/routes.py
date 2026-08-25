from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from datetime import datetime, timedelta
import json
import logging
from pydantic import BaseModel
from app.database import get_db
from app.models import (
    User, Meal, GlucoseReading, InsulinDose, AITask, Doctor, DoctorPatient,
    WeightEntry, BPEntry, KickSession, GlucoseType,
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_n8n_token(authorization: Optional[str]) -> None:
    expected = settings.N8N_CALLBACK_TOKEN
    if not expected:
        raise HTTPException(500, "N8N_CALLBACK_TOKEN not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    if authorization.split(" ", 1)[1] != expected:
        raise HTTPException(403, "Invalid token")


# ---------- AI callback ----------
class AICallback(BaseModel):
    task_id: int
    status: str  # "done" | "failed"
    result: dict | None = None
    error: str | None = None


@router.post("/ai/callback")
async def ai_callback(
    body: AICallback,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """n8n posts AI result back here. Bot picks it up from AITask row."""
    _require_n8n_token(authorization)
    task = await db.get(AITask, body.task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task.status = body.status
    task.result_data = json.dumps(body.result, ensure_ascii=False) if body.result else None
    task.error = body.error
    task.completed_at = datetime.now()

    # Notify user via bot (import here to avoid circular)
    user = await db.get(User, task.user_id)
    if body.status == "done" and body.result:
        try:
            from app.bot.handlers import bot
            if user:
                await _delete_placeholder(task, user)
                text = _format_ai_result(task.task_type, body.result)
                if text:
                    await bot.send_message(user.tg_id, text, parse_mode="Markdown")
        except Exception:
            logger.exception("Failed to deliver AI result for task %s", task.id)
    elif body.status == "failed":
        # Refund the quota — the user should not pay for our gateway failing.
        if user and task.task_type == "photo_meal" and user.ai_photos_used_month > 0:
            user.ai_photos_used_month -= 1
        try:
            from app.bot.handlers import bot
            if user:
                await bot.send_message(
                    user.tg_id,
                    "⚠️ Не получилось обработать запрос — AI-сервис временно недоступен.\n"
                    "Попробуйте ещё раз через пару минут. Попытка не списана.",
                )
        except Exception:
            logger.exception("Failed to deliver AI failure notice for task %s", task.id)

    return {"ok": True}


async def _delete_placeholder(task: AITask, user: User) -> None:
    """Drop the "processing" stub so only the real answer stays in the chat."""
    try:
        mid = (json.loads(task.input_data) if task.input_data else {}).get("placeholder_message_id")
    except (ValueError, TypeError):
        mid = None
    if not mid:
        return
    try:
        from app.bot.handlers import bot
        await bot.delete_message(user.tg_id, mid)
    except Exception:
        # Already deleted by the user, or older than Telegram allows — not fatal.
        logger.debug("Placeholder %s gone for task %s", mid, task.id)


def _format_ai_result(task_type: str, result: dict) -> str:
    if task_type == "photo_meal":
        dish = result.get("dish", "Блюдо")
        p = result.get("protein_g")
        f = result.get("fat_g")
        c = result.get("carb_g")
        xe = result.get("xe")
        risk = result.get("risk_level", "unknown")
        advice = result.get("advice", "")
        risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")
        return (
            f"📸 **{dish}**\n\n"
            f"Б/Ж/У: {p}/{f}/{c} г  ·  ХЕ: {xe}\n"
            f"{risk_emoji} Риск скачка сахара: {risk}\n\n"
            f"💡 {advice}"
        )
    if task_type == "weekly_analysis":
        return f"📊 **AI-анализ недели**\n\n{result.get('text', '')}"
    if task_type == "chat":
        return result.get("answer", "")
    if task_type == "portion_advice":
        return (
            f"🍽 **Совет по порции**\n\n"
            f"{result.get('recommendation', '')}\n"
            f"Максимум: {result.get('max_grams', '?')} г"
        )
    return ""


# ---------- n8n data pulls ----------
@router.get("/internal/users/reminders")
async def get_users_for_reminders(
    kind: str,  # "fasting" | "postmeal" | "evening" | "digest"
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """n8n cron fetches this list to know whom to nudge."""
    _require_n8n_token(authorization)
    now = datetime.now()
    hh_mm = now.strftime("%H:%M")

    q = select(User).where(User.reminders_enabled.is_(True))
    if kind == "fasting":
        q = q.where(User.reminder_fasting_time == hh_mm)
    elif kind == "evening":
        q = q.where(User.reminder_evening_time == hh_mm)

    result = await db.execute(q)
    users = result.scalars().all()
    return [
        {"user_id": u.id, "tg_id": u.tg_id, "full_name": u.full_name}
        for u in users
    ]


@router.get("/internal/users/{user_id}/diary")
async def internal_user_diary(
    user_id: int,
    days: int = 7,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """n8n pulls diary JSON to feed Claude for weekly analysis."""
    _require_n8n_token(authorization)
    start = datetime.now() - timedelta(days=days)
    glucose = (await db.execute(
        select(GlucoseReading).where(
            GlucoseReading.user_id == user_id,
            GlucoseReading.datetime >= start,
        )
    )).scalars().all()
    meals = (await db.execute(
        select(Meal).where(Meal.user_id == user_id, Meal.datetime >= start)
    )).scalars().all()
    insulin = (await db.execute(
        select(InsulinDose).where(InsulinDose.user_id == user_id, InsulinDose.datetime >= start)
    )).scalars().all()
    weights = (await db.execute(
        select(WeightEntry).where(WeightEntry.user_id == user_id, WeightEntry.datetime >= start)
        .order_by(WeightEntry.datetime)
    )).scalars().all()
    bps = (await db.execute(
        select(BPEntry).where(BPEntry.user_id == user_id, BPEntry.datetime >= start)
    )).scalars().all()
    kicks = (await db.execute(
        select(KickSession).where(
            KickSession.user_id == user_id,
            KickSession.start_time >= start,
            KickSession.end_time.isnot(None),
        )
    )).scalars().all()
    return {
        "glucose": [
            {"datetime": g.datetime.isoformat(), "value": g.value, "type": g.type.value, "is_normal": g.is_normal}
            for g in glucose
        ],
        "meals": [{"datetime": m.datetime.isoformat(), "description": m.description} for m in meals],
        "insulin": [
            {"datetime": i.datetime.isoformat(), "units": i.units, "type": i.type.value}
            for i in insulin
        ],
        "weight": [
            {"datetime": w.datetime.isoformat(), "kg": w.weight_kg}
            for w in weights
        ],
        "blood_pressure": [
            {
                "datetime": b.datetime.isoformat(),
                "systolic": b.systolic,
                "diastolic": b.diastolic,
                "pulse": b.pulse,
                "is_alert": bool(b.is_alert),
            }
            for b in bps
        ],
        "kicks": [
            {
                "start_time": k.start_time.isoformat(),
                "kicks_count": k.kicks_count,
                "is_alert": bool(k.is_alert),
            }
            for k in kicks
        ],
    }


@router.get("/internal/admin/digest")
async def internal_admin_digest(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    _require_n8n_token(authorization)
    from app.services.admin_analytics import build_admin_digest
    text = await build_admin_digest(db)
    return {"admin_tg_id": settings.ADMIN_TG_ID, "text": text}


# ---------- Doctor portal ----------
@router.get("/doctor/{token}", response_class=HTMLResponse)
async def doctor_portal(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Doctor).where(Doctor.access_token == token))
    doctor = result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(404, "Not found")
    if doctor.subscription_expires_at and doctor.subscription_expires_at < datetime.now():
        return HTMLResponse("<h1>Доступ истёк</h1><p>Продлите подписку в боте.</p>", status_code=402)

    links = (await db.execute(
        select(DoctorPatient).where(DoctorPatient.doctor_id == doctor.id, DoctorPatient.approved.is_(True))
    )).scalars().all()
    ids = [link.user_id for link in links]
    if not ids:
        patients_html = "<p>Пока нет подключенных пациенток.</p>"
    else:
        pats = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
        rows = []
        for p in pats:
            g_count = await db.scalar(
                select(func.count(GlucoseReading.id)).where(GlucoseReading.user_id == p.id)
            ) or 0
            rows.append(
                f"<tr><td>{p.full_name or p.username or p.tg_id}</td>"
                f"<td>{g_count}</td>"
                f"<td><a href='/api/v1/doctor/{token}/patient/{p.id}'>Открыть</a></td></tr>"
            )
        patients_html = (
            "<table border='1' cellpadding='8'><tr><th>Пациентка</th><th>Замеров</th><th></th></tr>"
            + "".join(rows) + "</table>"
        )
    return HTMLResponse(
        f"<html><head><meta charset='utf-8'><title>Кабинет врача</title></head>"
        f"<body style='font-family:sans-serif;max-width:900px;margin:2rem auto'>"
        f"<h1>Кабинет: {doctor.full_name}</h1>"
        f"<p>{doctor.clinic or ''}</p>{patients_html}</body></html>"
    )


@router.get("/doctor/{token}/patient/{user_id}")
async def doctor_patient_view(token: str, user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Doctor).where(Doctor.access_token == token))
    doctor = result.scalar_one_or_none()
    if not doctor:
        raise HTTPException(404)
    link = (await db.execute(
        select(DoctorPatient).where(
            DoctorPatient.doctor_id == doctor.id,
            DoctorPatient.user_id == user_id,
            DoctorPatient.approved.is_(True),
        )
    )).scalar_one_or_none()
    if not link:
        raise HTTPException(403)
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404)
    from app.services.pdf_report import generate_pdf_report
    pdf = await generate_pdf_report(db, user, days=28)
    return StreamingResponse(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=diary_{user.id}.pdf"},
    )

# Schemas
class MealCreate(BaseModel):
    user_id: int
    description: str
    datetime: datetime

class MealResponse(BaseModel):
    id: int
    user_id: int
    description: str
    datetime: datetime

    class Config:
        from_attributes = True

class GlucoseCreate(BaseModel):
    user_id: int
    value: float
    type: str
    meal_id: int | None = None
    datetime: datetime

class GlucoseResponse(BaseModel):
    id: int
    user_id: int
    value: float
    type: str
    is_normal: bool
    datetime: datetime

    class Config:
        from_attributes = True

class InsulinCreate(BaseModel):
    user_id: int
    units: float
    type: str
    datetime: datetime

class InsulinResponse(BaseModel):
    id: int
    user_id: int
    units: float
    type: str
    datetime: datetime

    class Config:
        from_attributes = True

# Endpoints
@router.post("/meals", response_model=MealResponse)
async def create_meal(meal: MealCreate, db: AsyncSession = Depends(get_db)):
    db_meal = Meal(**meal.model_dump())
    db.add(db_meal)
    await db.flush()
    await db.refresh(db_meal)
    return db_meal

@router.get("/meals/{user_id}", response_model=List[MealResponse])
async def get_meals(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Meal).where(Meal.user_id == user_id).order_by(Meal.datetime.desc()))
    return result.scalars().all()

@router.post("/glucose", response_model=GlucoseResponse)
async def create_glucose(glucose: GlucoseCreate, db: AsyncSession = Depends(get_db)):
    db_glucose = GlucoseReading(**glucose.model_dump())
    db.add(db_glucose)
    await db.flush()
    await db.refresh(db_glucose)
    return db_glucose

@router.get("/glucose/{user_id}", response_model=List[GlucoseResponse])
async def get_glucose(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GlucoseReading).where(GlucoseReading.user_id == user_id).order_by(GlucoseReading.datetime.desc()))
    return result.scalars().all()

@router.post("/insulin", response_model=InsulinResponse)
async def create_insulin(insulin: InsulinCreate, db: AsyncSession = Depends(get_db)):
    db_insulin = InsulinDose(**insulin.model_dump())
    db.add(db_insulin)
    await db.flush()
    await db.refresh(db_insulin)
    return db_insulin

@router.get("/insulin/{user_id}", response_model=List[InsulinResponse])
async def get_insulin(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(InsulinDose).where(InsulinDose.user_id == user_id).order_by(InsulinDose.datetime.desc()))
    return result.scalars().all()
