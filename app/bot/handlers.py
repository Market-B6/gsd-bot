from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.redis import RedisStorage
from datetime import datetime, timedelta
import pytz
import re
from sqlalchemy import select
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import User, Meal, GlucoseReading, InsulinDose, Timer, GlucoseType, InsulinType, UserEvent
from app.services.analytics import log_event, get_stats
import redis.asyncio as redis

def _build_bot() -> Bot:
    """Build the Bot, routing through a proxy when TELEGRAM_PROXY_URL is set.

    Some hosting providers block outbound traffic to api.telegram.org. In that
    case the bot talks to Telegram through a proxy while user data stays in the
    local database.
    """
    if settings.TELEGRAM_PROXY_URL:
        from aiogram.client.session.aiohttp import AiohttpSession
        return Bot(
            token=settings.BOT_TOKEN,
            session=AiohttpSession(proxy=settings.TELEGRAM_PROXY_URL),
        )
    return Bot(token=settings.BOT_TOKEN)


bot = _build_bot()
redis_client = redis.from_url(settings.REDIS_URL)
storage = RedisStorage(redis_client)
dp = Dispatcher(storage=storage)
router = Router()

# FSM States
class MealState(StatesGroup):
    waiting_for_description = State()
    waiting_for_time = State()

class GlucoseState(StatesGroup):
    waiting_for_value = State()
    waiting_for_type = State()
    waiting_for_time = State()

class InsulinState(StatesGroup):
    waiting_for_units = State()
    waiting_for_type = State()
    waiting_for_time = State()

# Menu buttons — если во время ввода пользователь жмёт одну из них,
# это не данные для текущего шага, а переключение сценария.
MENU_BUTTONS = frozenset({
    "🍽 Приём пищи",
    "🩸 Замер сахара",
    "💉 Инсулин",
    "📊 Мой дневник",
    "📖 Рецепты",
    "💬 Задать вопрос Миле",
    "⚙️ Настройки",
    "📈 Статистика",
    "🎁 PRO подписка",
    "❓ Помощь",
    "✉️ Написать нам",
    "⬅️ Назад",
})

# Keyboards
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍽 Приём пищи"), KeyboardButton(text="🩸 Замер сахара")],
            [KeyboardButton(text="💉 Инсулин"), KeyboardButton(text="📊 Мой дневник")],
            [KeyboardButton(text="❓ Помощь"), KeyboardButton(text="📋 Ещё")],
        ],
        resize_keyboard=True
    )

def get_more_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📖 Рецепты"), KeyboardButton(text="💬 Задать вопрос Миле")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="📈 Статистика")],
            [KeyboardButton(text="🎁 PRO подписка"), KeyboardButton(text="✉️ Написать нам")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True
    )

def get_insulin_type_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Короткий", callback_data="insulin_short")],
            [InlineKeyboardButton(text="Длинный", callback_data="insulin_long")],
        ]
    )

def get_time_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏰ Сейчас", callback_data="time_now")],
            [InlineKeyboardButton(text="🕐 Другое время", callback_data="time_custom")],
        ]
    )

def get_glucose_type_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌅 Натощак", callback_data="gtype_fasting")],
            [InlineKeyboardButton(text="🍽 После еды", callback_data="gtype_postmeal")],
        ]
    )

def parse_custom_time(text: str, tz) -> datetime | None:
    """Parse time like '14:30' or '14 30' or '1430' or '27.07 14:30'"""
    text = text.strip()
    now = datetime.now(tz)

    # Format: dd.mm HH:MM or dd.mm HH MM
    m = re.match(r'(\d{1,2})[./](\d{1,2})\s+(\d{1,2})[:.h ]?(\d{2})', text)
    if m:
        day, month, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        try:
            result = now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
            return result.replace(tzinfo=None)
        except ValueError:
            return None

    # Format: HH:MM or HH.MM or HH MM or HHMM
    m = re.match(r'^(\d{1,2})[:.h ]?(\d{2})$', text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if result > now:
                result -= timedelta(days=1)
            return result.replace(tzinfo=None)
    return None

# Cancel from ANY state (must be before state handlers)
@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=get_main_keyboard())

# Commands
@router.message(Command("start"), StateFilter("*"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name
            )
            session.add(user)
            await session.flush()

            # Referral code from /start ref_XXXX
            parts = (message.text or "").split(maxsplit=1)
            if len(parts) == 2 and parts[1].startswith("ref_"):
                code = parts[1][4:].strip()
                if code:
                    from app.services.referral import attach_referrer
                    await attach_referrer(session, user, code)

            await session.commit()

            await message.answer(
                f"Привет, {message.from_user.first_name}! 👋\n\n"
                "Я помогу вести дневник при ГСД.\n\n"
                "Записывайте приёмы пищи, замеры сахара и инсулин — "
                "я буду напоминать и сохранять всё для врача.",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(
                f"С возвращением, {message.from_user.first_name}! 👋",
                reply_markup=get_main_keyboard()
            )

        await log_event(session, user.id, "start")
        await session.commit()

    # Show banner after start
    banner = await redis_client.get("bot:banner")
    if banner:
        await message.answer(f"📌 {banner.decode()}")

# Admin stats
@router.message(Command("stats"))
async def cmd_stats(message: Message):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user or not user.is_admin:
            await message.answer("Нет доступа.")
            return

        stats = await get_stats(session)

        text = (
            "📈 **Статистика бота**\n\n"
            f"👥 Всего пользователей: {stats['total_users']}\n"
            f"🆕 Новых сегодня: {stats['new_today']}\n"
            f"🆕 Новых за неделю: {stats['new_week']}\n\n"
            f"🟢 Активных сегодня: {stats['active_today']}\n"
            f"🟢 Активных за неделю: {stats['active_week']}\n"
            f"🔄 Вернулись (2+ дня за неделю): {stats['retained_week']}\n\n"
            f"🍽 Приёмов пищи всего: {stats['total_meals']} (сегодня: {stats['meals_today']})\n"
            f"🩸 Замеров сахара всего: {stats['total_glucose']} (сегодня: {stats['glucose_today']})\n"
            f"💉 Инсулина всего: {stats['total_insulin']}\n"
        )

        await message.answer(text, parse_mode="Markdown")

# Meal flow
@router.message(F.text == "🍽 Приём пищи", StateFilter("*"))
async def meal_button(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Что ели? Опишите приём пищи:")
    await state.set_state(MealState.waiting_for_description)

@router.message(MealState.waiting_for_description, ~F.text.in_(MENU_BUTTONS))
async def meal_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Когда это было?", reply_markup=get_time_keyboard())
    await state.set_state(MealState.waiting_for_time)

@router.callback_query(MealState.waiting_for_time, F.data == "time_now")
async def meal_time_now(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    description = data.get("description")

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await callback.message.answer("Ошибка. Нажмите /start")
            return

        tz = pytz.timezone(user.timezone)
        now = datetime.now(tz).replace(tzinfo=None)

        meal = Meal(
            user_id=user.id,
            datetime=now,
            description=description
        )
        session.add(meal)
        await session.flush()

        notify_at = now + timedelta(hours=1)
        timer = Timer(
            user_id=user.id,
            meal_id=meal.id,
            start_time=now,
            notify_at=notify_at
        )
        session.add(timer)
        await log_event(session, user.id, "meal")
        await session.commit()

        await callback.message.edit_text(
            f"✅ Записала!\n\n"
            f"⏱ Напомню замерить сахар в {notify_at.strftime('%H:%M')}"
        )
        await callback.message.answer("Готово!", reply_markup=get_main_keyboard())
        await state.clear()
    await callback.answer()

@router.callback_query(MealState.waiting_for_time, F.data == "time_custom")
async def meal_time_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите время (или дату и время):\n"
        "Например: 14:30 или 27.07 14:30"
    )
    await callback.answer()

@router.message(MealState.waiting_for_time, ~F.text.in_(MENU_BUTTONS))
async def meal_time_manual(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("Ошибка. Нажмите /start")
            return

        tz = pytz.timezone(user.timezone)
        parsed = parse_custom_time(message.text, tz)

        if not parsed:
            await message.answer("Не поняла время. Введите как 14:30 или 27.07 14:30")
            return

        data = await state.get_data()
        description = data.get("description")

        meal = Meal(
            user_id=user.id,
            datetime=parsed,
            description=description
        )
        session.add(meal)
        await session.flush()

        now = datetime.now(tz).replace(tzinfo=None)
        time_since_meal = (now - parsed).total_seconds() / 60

        if time_since_meal < 60:
            notify_at = parsed + timedelta(hours=1)
            timer = Timer(
                user_id=user.id,
                meal_id=meal.id,
                start_time=parsed,
                notify_at=notify_at
            )
            session.add(timer)
            timer_text = f"\n⏱ Напомню замерить сахар в {notify_at.strftime('%H:%M')}"
        else:
            timer_text = "\n(таймер не нужен — прошло больше часа)"

        await log_event(session, user.id, "meal")
        await session.commit()

        await message.answer(
            f"✅ Записала на {parsed.strftime('%d.%m %H:%M')}!{timer_text}",
            reply_markup=get_main_keyboard()
        )
        await state.clear()

# Glucose flow
@router.message(F.text == "🩸 Замер сахара", StateFilter("*"))
async def glucose_button(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Введите значение сахара (например: 5.5):")
    await state.set_state(GlucoseState.waiting_for_value)

@router.message(GlucoseState.waiting_for_value, ~F.text.in_(MENU_BUTTONS))
async def glucose_value(message: Message, state: FSMContext):
    try:
        value = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer("Пожалуйста, введите число (например: 5.5)")
        return

    await state.update_data(value=value)
    await message.answer("Тип замера:", reply_markup=get_glucose_type_keyboard())
    await state.set_state(GlucoseState.waiting_for_type)

@router.callback_query(GlucoseState.waiting_for_type, F.data.startswith("gtype_"))
async def glucose_type_selected(callback: CallbackQuery, state: FSMContext):
    gtype = callback.data.replace("gtype_", "")
    await state.update_data(glucose_type=gtype)
    await callback.message.edit_text("Когда замеряли?", reply_markup=get_time_keyboard())
    await state.set_state(GlucoseState.waiting_for_time)
    await callback.answer()

@router.callback_query(GlucoseState.waiting_for_time, F.data == "time_now")
async def glucose_time_now(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    value = data.get("value")
    glucose_type = GlucoseType(data.get("glucose_type"))

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await callback.message.answer("Ошибка. Нажмите /start")
            return

        tz = pytz.timezone(user.timezone)
        now = datetime.now(tz).replace(tzinfo=None)

        is_normal = value <= 7.0 if glucose_type == GlucoseType.POSTMEAL else value <= 5.1

        reading = GlucoseReading(
            user_id=user.id,
            datetime=now,
            value=value,
            type=glucose_type,
            is_normal=is_normal
        )
        session.add(reading)
        await log_event(session, user.id, "glucose")
        await session.commit()

        status = "✅ в норме" if is_normal else "⚠️ выше нормы"
        norm_text = "до 7.0" if glucose_type == GlucoseType.POSTMEAL else "до 5.1"
        type_label = "после еды" if glucose_type == GlucoseType.POSTMEAL else "натощак"

        await callback.message.edit_text(
            f"Записала: {value} ({type_label}) — {status}\n"
            f"(норма для ГСД: {norm_text})"
        )
        await callback.message.answer("Готово!", reply_markup=get_main_keyboard())
        await state.clear()
    await callback.answer()

@router.callback_query(GlucoseState.waiting_for_time, F.data == "time_custom")
async def glucose_time_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите время замера:\n"
        "Например: 14:30 или 27.07 14:30"
    )
    await callback.answer()

@router.message(GlucoseState.waiting_for_time, ~F.text.in_(MENU_BUTTONS))
async def glucose_time_manual(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("Ошибка. Нажмите /start")
            return

        tz = pytz.timezone(user.timezone)
        parsed = parse_custom_time(message.text, tz)

        if not parsed:
            await message.answer("Не поняла время. Введите как 14:30 или 27.07 14:30")
            return

        data = await state.get_data()
        value = data.get("value")
        glucose_type = GlucoseType(data.get("glucose_type"))

        is_normal = value <= 7.0 if glucose_type == GlucoseType.POSTMEAL else value <= 5.1

        reading = GlucoseReading(
            user_id=user.id,
            datetime=parsed,
            value=value,
            type=glucose_type,
            is_normal=is_normal
        )
        session.add(reading)
        await log_event(session, user.id, "glucose")
        await session.commit()

        status = "✅ в норме" if is_normal else "⚠️ выше нормы"
        norm_text = "до 7.0" if glucose_type == GlucoseType.POSTMEAL else "до 5.1"
        type_label = "после еды" if glucose_type == GlucoseType.POSTMEAL else "натощак"

        await message.answer(
            f"Записала на {parsed.strftime('%d.%m %H:%M')}: {value} ({type_label}) — {status}\n"
            f"(норма для ГСД: {norm_text})",
            reply_markup=get_main_keyboard()
        )
        await state.clear()

# Insulin flow
@router.message(F.text == "💉 Инсулин", StateFilter("*"))
async def insulin_button(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Сколько единиц инсулина?")
    await state.set_state(InsulinState.waiting_for_units)

@router.message(InsulinState.waiting_for_units, ~F.text.in_(MENU_BUTTONS))
async def insulin_units(message: Message, state: FSMContext):
    try:
        units = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer("Введите число (например: 10)")
        return

    await state.update_data(units=units)
    await message.answer("Какой тип инсулина?", reply_markup=get_insulin_type_keyboard())
    await state.set_state(InsulinState.waiting_for_type)

@router.callback_query(InsulinState.waiting_for_type, F.data.startswith("insulin_"))
async def insulin_type_cb(callback: CallbackQuery, state: FSMContext):
    insulin_type = InsulinType.SHORT if callback.data == "insulin_short" else InsulinType.LONG
    await state.update_data(insulin_type=insulin_type.value)
    await callback.message.edit_text("Когда вводили?")
    await callback.message.answer("Выберите:", reply_markup=get_time_keyboard())
    await state.set_state(InsulinState.waiting_for_time)
    await callback.answer()

@router.callback_query(InsulinState.waiting_for_time, F.data == "time_now")
async def insulin_time_now(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    units = data.get("units")
    insulin_type = InsulinType(data.get("insulin_type"))

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await callback.message.answer("Ошибка. Нажмите /start")
            return

        tz = pytz.timezone(user.timezone)
        now = datetime.now(tz).replace(tzinfo=None)

        dose = InsulinDose(
            user_id=user.id,
            datetime=now,
            units=units,
            type=insulin_type
        )
        session.add(dose)
        await log_event(session, user.id, "insulin")
        await session.commit()

        type_text = "короткий" if insulin_type == InsulinType.SHORT else "длинный"
        await callback.message.edit_text(f"✅ Записала: {units} Ед ({type_text})")
        await callback.message.answer("Готово!", reply_markup=get_main_keyboard())
        await state.clear()
    await callback.answer()

@router.callback_query(InsulinState.waiting_for_time, F.data == "time_custom")
async def insulin_time_custom(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите время укола:\n"
        "Например: 14:30 или 27.07 14:30"
    )
    await callback.answer()

@router.message(InsulinState.waiting_for_time, ~F.text.in_(MENU_BUTTONS))
async def insulin_time_manual(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("Ошибка. Нажмите /start")
            return

        tz = pytz.timezone(user.timezone)
        parsed = parse_custom_time(message.text, tz)

        if not parsed:
            await message.answer("Не поняла время. Введите как 14:30 или 27.07 14:30")
            return

        data = await state.get_data()
        units = data.get("units")
        insulin_type = InsulinType(data.get("insulin_type"))

        dose = InsulinDose(
            user_id=user.id,
            datetime=parsed,
            units=units,
            type=insulin_type
        )
        session.add(dose)
        await log_event(session, user.id, "insulin")
        await session.commit()

        type_text = "короткий" if insulin_type == InsulinType.SHORT else "длинный"
        await message.answer(
            f"✅ Записала на {parsed.strftime('%d.%m %H:%M')}: {units} Ед ({type_text})",
            reply_markup=get_main_keyboard()
        )
        await state.clear()

# User stats
@router.message(Command("mystats"))
async def cmd_mystats(message: Message):
    from app.services.user_stats import get_user_stats

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("Нажмите /start")
            return

        text = await get_user_stats(session, user)
        await message.answer(text, parse_mode="Markdown")

# Admin: broadcast message to all users
class BroadcastState(StatesGroup):
    waiting_for_message = State()

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user or not user.is_admin:
            await message.answer("Нет доступа.")
            return

    await message.answer("Введите сообщение для рассылки всем пользователям:")
    await state.set_state(BroadcastState.waiting_for_message)

@router.message(BroadcastState.waiting_for_message)
async def broadcast_send(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        admin = result.scalar_one_or_none()

        if not admin or not admin.is_admin:
            await state.clear()
            return

        users_result = await session.execute(select(User))
        users = users_result.scalars().all()

        sent = 0
        failed = 0
        for u in users:
            try:
                await bot.send_message(u.tg_id, message.text)
                sent += 1
            except Exception:
                failed += 1

        await message.answer(
            f"✅ Рассылка завершена\n"
            f"Доставлено: {sent}\n"
            f"Не доставлено: {failed}"
        )
        await state.clear()

# Admin: set banner (shows on /start and in diary)
class BannerState(StatesGroup):
    waiting_for_text = State()

@router.message(Command("banner"))
async def cmd_banner(message: Message, state: FSMContext):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user or not user.is_admin:
            await message.answer("Нет доступа.")
            return

    args = message.text.replace("/banner", "").strip()
    if args == "off":
        await redis_client.delete("bot:banner")
        await message.answer("Баннер отключён.")
        return

    if args:
        await redis_client.set("bot:banner", args)
        await message.answer(f"Баннер установлен:\n{args}")
    else:
        await message.answer("Введите текст баннера (или /banner off чтобы убрать):")
        await state.set_state(BannerState.waiting_for_text)

@router.message(BannerState.waiting_for_text)
async def banner_text(message: Message, state: FSMContext):
    await redis_client.set("bot:banner", message.text)
    await message.answer(f"✅ Баннер установлен:\n{message.text}")
    await state.clear()

# Diary view
@router.message(F.text == "📊 Мой дневник", StateFilter("*"))
async def diary_button(message: Message, state: FSMContext):
    await state.clear()
    # Show banner if set
    banner = await redis_client.get("bot:banner")
    if banner:
        await message.answer(f"📌 {banner.decode()}")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Сегодня", callback_data="diary_today")],
            [InlineKeyboardButton(text="📋 Неделя", callback_data="diary_week")],
            [InlineKeyboardButton(text="📈 Моя статистика", callback_data="diary_stats")],
            [InlineKeyboardButton(text="📎 Excel для врача", callback_data="diary_excel")],
        ]
    )
    await message.answer("📊 Дневник — что показать?", reply_markup=keyboard)

@router.callback_query(F.data == "diary_stats")
async def diary_stats(callback: CallbackQuery):
    from app.services.user_stats import get_user_stats

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await callback.message.answer("Ошибка. Нажмите /start")
            return

        text = await get_user_stats(session, user)
        await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "diary_today")
async def diary_today(callback: CallbackQuery):
    from app.services.export import generate_diary_text

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await callback.message.answer("Ошибка. Нажмите /start")
            return

        text = await generate_diary_text(session, user, days=1)
        await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "diary_week")
async def diary_week(callback: CallbackQuery):
    from app.services.export import generate_diary_text

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await callback.message.answer("Ошибка. Нажмите /start")
            return

        text = await generate_diary_text(session, user, days=7)
        await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "diary_excel")
async def diary_excel(callback: CallbackQuery):
    from app.services.export import generate_excel_export
    from aiogram.types import BufferedInputFile

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
        user = result.scalar_one_or_none()

        if not user:
            await callback.message.answer("Ошибка. Нажмите /start")
            return

        excel_file = await generate_excel_export(session, user, days=14)
        filename = f"diary_{datetime.now().strftime('%d%m%Y')}.xlsx"

        await callback.message.answer_document(
            BufferedInputFile(excel_file.read(), filename=filename),
            caption="📎 Дневник ГСД за 2 недели для врача"
        )
        await callback.message.edit_text("📊 Выгрузка готова ⬇️")
    await callback.answer()

# Help for users
@router.message(F.text == "❓ Помощь", StateFilter("*"))
async def help_button(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📖 **Как пользоваться ботом:**\n\n"
        "🍽 **Приём пищи** — записать что ели. Через час напомню замерить сахар.\n\n"
        "🩸 **Замер сахара** — ввести значение глюкозы. Бот определит тип (натощак/после еды) и покажет норму.\n\n"
        "💉 **Инсулин** — записать дозу и тип (короткий/длинный).\n\n"
        "📊 **Мой дневник** — просмотр записей, статистика, выгрузка Excel для врача.\n\n"
        "⏰ Можно вносить данные задним числом — бот спросит время.\n\n"
        "📎 **Команды:**\n"
        "/mystats — моя статистика за неделю\n"
        "/help — эта подсказка\n"
        "✉️ **Написать нам** — связь с поддержкой",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if user and user.is_admin:
            await message.answer(
                "🔧 **Команды админа:**\n\n"
                "/stats — статистика бота\n"
                "/broadcast — рассылка всем\n"
                "/banner текст — установить баннер\n"
                "/banner off — убрать баннер\n"
                "/help — эта подсказка\n\n"
                "📖 **Команды пользователя:**\n"
                "/start — перезапуск\n"
                "/mystats — статистика за неделю\n"
                "/help — подсказка",
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                "📖 **Команды:**\n\n"
                "/start — перезапуск бота\n"
                "/mystats — моя статистика\n"
                "/help — подсказка\n\n"
                "Используйте кнопки внизу для записи данных.",
                parse_mode="Markdown"
            )

# Contact support
class SupportState(StatesGroup):
    waiting_for_message = State()

ADMIN_TG_ID = 6935167265

@router.message(F.text == "✉️ Написать нам", StateFilter("*"))
async def support_button(message: Message, state: FSMContext):
    await message.answer(
        "✉️ Напишите ваше сообщение — мы получим и ответим.\n"
        "(Или /cancel для отмены)"
    )
    await state.set_state(SupportState.waiting_for_message)

@router.message(SupportState.waiting_for_message, ~F.text.in_(MENU_BUTTONS))
async def support_send(message: Message, state: FSMContext):
    user_info = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    try:
        await bot.send_message(
            ADMIN_TG_ID,
            f"✉️ Сообщение от {user_info} (id: {message.from_user.id}):\n\n"
            f"{message.text}"
        )
        await message.answer("✅ Сообщение отправлено! Мы ответим в ближайшее время.", reply_markup=get_main_keyboard())
    except Exception:
        await message.answer("Ошибка отправки. Попробуйте позже.", reply_markup=get_main_keyboard())
    await state.clear()

# Admin reply to user: /reply 123456789 text
@router.message(Command("reply"))
async def cmd_reply(message: Message):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.tg_id == message.from_user.id))
        user = result.scalar_one_or_none()

        if not user or not user.is_admin:
            return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: /reply <tg_id> <сообщение>")
        return

    try:
        target_id = int(parts[1])
        text = parts[2]
        await bot.send_message(target_id, f"💬 Ответ от поддержки:\n\n{text}")
        await message.answer(f"✅ Отправлено пользователю {target_id}")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

# More menu
@router.message(F.text == "📋 Ещё", StateFilter("*"))
async def more_button(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📋 Дополнительное меню:", reply_markup=get_more_keyboard())

@router.message(F.text == "⬅️ Назад", StateFilter("*"))
async def back_button(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=get_main_keyboard())

dp.include_router(router)

# PRO features router
from app.bot.handlers_pro import pro_router  # noqa: E402
dp.include_router(pro_router)

# Recipes router
from app.bot.handlers_recipes import router as recipes_router  # noqa: E402
dp.include_router(recipes_router)

