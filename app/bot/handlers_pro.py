"""PRO features handlers: subscription, payments, photo AI, vitals, kicks,
recipes, referral, chat, portion advice. Plugged into main dispatcher.
"""
import base64
import io
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    PreCheckoutQuery, LabeledPrice, ReplyKeyboardMarkup, KeyboardButton,
)
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import User, ProductType, PostpartumStage
from app.services import subscription as sub_svc
from app.services import payments as pay_svc
from app.services import vitals as vit_svc
from app.services import kick_counter as kick_svc
from app.services import postpartum as pp_svc
from app.services import referral as ref_svc
from app.services import recipes as rec_svc
from app.services import ai_client
from app.services.analytics import log_event
from app.config import settings

import logging

logger = logging.getLogger(__name__)

pro_router = Router()


class PROStates(StatesGroup):
    waiting_weight = State()
    waiting_bp = State()
    waiting_photo = State()
    chat_question = State()
    portion_food = State()
    birth_date = State()
    ref_code = State()


async def _get_user(tg_id: int) -> User | None:
    async with AsyncSessionLocal() as s:
        r = await s.execute(select(User).where(User.tg_id == tg_id))
        return r.scalar_one_or_none()


# ---------- PRO menu / paywall ----------
def _pro_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⭐ Месяц · {settings.PRICE_SUB_MONTHLY_XTR}⭐", callback_data="buy:sub_monthly")],
        [InlineKeyboardButton(text="🎁 Активировать пробный период (7 дн)", callback_data="trial")],
        [InlineKeyboardButton(text="🧾 Разовые покупки", callback_data="shop")],
        [InlineKeyboardButton(text="👥 Пригласить подругу", callback_data="referral")],
    ])


def _shop_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📄 PDF-отчёт врачу · {settings.PRICE_PDF_REPORT_XTR}⭐", callback_data="buy:pdf_report")],
        [InlineKeyboardButton(text=f"📸 50 AI-фото · {settings.PRICE_AI_PHOTO_PACK_XTR}⭐", callback_data="buy:ai_photo_pack")],
        [InlineKeyboardButton(text="🎓 Курс «Жизнь с ГСД» · скоро", callback_data="buy:course")],
        [InlineKeyboardButton(text="👨‍⚕️ Консультация врача · скоро", callback_data="buy:consultation")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="pro_menu")],
    ])


@pro_router.message(Command("pro"))
@pro_router.message(F.text == "⭐ PRO")
async def cmd_pro(message: Message):
    user = await _get_user(message.from_user.id)
    if not user:
        return
    text = (
        f"⭐ **PRO подписка**\n\n"
        f"{sub_svc.subscription_status_text(user)}\n\n"
        "Что даёт PRO:\n"
        "• 📸 100 фото-анализов блюд в месяц (в FREE — 5)\n"
        "• 💬 Общение с Милой без ограничений (в FREE — 10 сообщений)\n"
        "• 📊 AI-анализ дневника за неделю с советами\n"
        "• 🎯 Конкретные порции: сколько чего можно\n"
        "• ⏰ Умные напоминания и вечерние сводки\n"
        "• 📄 PDF-отчёт для врача с графиками\n"
        "• 🍽 База рецептов ГСД с ХЕ/БЖУ\n\n"
        "Бесплатно навсегда: дневник, статистика, экспорт в Excel,\n"
        "вес, давление, шевеления.\n"
    )
    await message.answer(text, reply_markup=_pro_menu_kb(), parse_mode="Markdown")


@pro_router.callback_query(F.data == "pro_menu")
async def cb_pro_menu(cb: CallbackQuery):
    await cb.message.edit_reply_markup(reply_markup=_pro_menu_kb())
    await cb.answer()


@pro_router.callback_query(F.data == "shop")
async def cb_shop(cb: CallbackQuery):
    await cb.message.edit_text(
        "🧾 Разовые покупки", reply_markup=_shop_kb()
    )
    await cb.answer()


@pro_router.callback_query(F.data == "trial")
async def cb_trial(cb: CallbackQuery):
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == cb.from_user.id))).scalar_one_or_none()
        if not user:
            return
        ok = await sub_svc.start_trial(s, user)
        await s.commit()
    if ok:
        await cb.message.answer(
            f"🎉 Пробный период на {settings.TRIAL_DAYS} дней активирован!\n"
            "Все PRO-функции открыты."
        )
    else:
        await cb.answer("Пробный период уже использован", show_alert=True)


# ---------- Buy via Stars ----------
@pro_router.callback_query(F.data.startswith("buy:"))
async def cb_buy(cb: CallbackQuery):
    product_key = cb.data.split(":", 1)[1]
    if product_key == "course":
        await cb.answer()
        await cb.message.answer(
            "🎓 Курс «Жизнь с ГСД» \u2014 готовим!\n\n"
            "10 коротких уроков: что такое ГСД, как считать ХЕ, "
            "что делать при высоком сахаре, питание, подготовка к родам.\n\n"
            "Напишем вам, когда откроем."
        )
        return
    if product_key == "consultation":
        await cb.answer()
        await cb.message.answer(
            "👨\u200D⚕️ Консультации специалистов \u2014 скоро!\n\n"
            "Сейчас подключаем эндокринологов и нутрициологов, "
            "которые ведут беременных с ГСД.\n\n"
            "Напишем вам, когда появятся первые врачи."
        )
        return
    try:
        product = ProductType(product_key)
    except ValueError:
        await cb.answer("Неизвестный товар")
        return
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == cb.from_user.id))).scalar_one_or_none()
        if not user:
            return
        from app.bot.handlers import bot
        await pay_svc.create_stars_invoice(bot, s, user, product, chat_id=cb.message.chat.id)
        await s.commit()
    await cb.answer()


@pro_router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    from app.bot.handlers import bot
    from app.models import Payment, PaymentStatus

    async with AsyncSessionLocal() as s:
        pay = (await s.execute(
            select(Payment).where(Payment.invoice_payload == q.invoice_payload)
        )).scalar_one_or_none()

    if pay is None or pay.status == PaymentStatus.PAID:
        logger.error("pre_checkout: payload %r rejected (found=%s)", q.invoice_payload, pay is not None)
        await bot.answer_pre_checkout_query(
            q.id, ok=False,
            error_message="Счёт устарел. Откройте /pro и создайте новый.",
        )
        return

    await bot.answer_pre_checkout_query(q.id, ok=True)


@pro_router.message(F.successful_payment)
async def on_successful_payment(message: Message):
    sp = message.successful_payment
    async with AsyncSessionLocal() as s:
        user, product = await pay_svc.handle_successful_payment(
            s,
            invoice_payload=sp.invoice_payload,
            telegram_charge_id=sp.telegram_payment_charge_id,
            total_amount=sp.total_amount,
        )
        if user and product:
            # Referral reward on first PRO purchase
            if product in (ProductType.SUB_MONTHLY, ProductType.SUB_YEARLY):
                await ref_svc.grant_referral_rewards(s, user)
            await log_event(s, user.id, f"paid:{product.value}")
        await s.commit()

    if product is None:
        logger.error(
            "PAYMENT NOT APPLIED: charge_id=%s payload=%s amount=%s",
            sp.telegram_payment_charge_id, sp.invoice_payload, sp.total_amount,
        )
        await message.answer(
            "⚠️ Платёж прошёл, но активировать покупку не удалось.\n\n"
            f"Напишите нам, код платежа: `{sp.telegram_payment_charge_id}`\n"
            "Мы всё активируем вручную или вернём звёзды.",
            parse_mode="Markdown",
        )
        return

    if product in (ProductType.SUB_MONTHLY, ProductType.SUB_YEARLY):
        await message.answer(
            "🎉 PRO активирована! Все функции разблокированы.\n\n"
            "Спасибо, что поддерживаете проект 💜"
        )
    else:
        await message.answer("✅ Покупка совершена!")


# ---------- Vitals: weight & BP ----------
@pro_router.message(Command("weight"))
async def cmd_weight(message: Message, state: FSMContext):
    await message.answer("⚖️ Введите ваш вес в кг (например: 68.5)")
    await state.set_state(PROStates.waiting_weight)


@pro_router.message(PROStates.waiting_weight)
async def input_weight(message: Message, state: FSMContext):
    try:
        w = float(message.text.replace(",", "."))
        if not 30 <= w <= 250:
            raise ValueError
    except Exception:
        await message.answer("Введите корректное значение, например 68.5")
        return
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == message.from_user.id))).scalar_one_or_none()
        if user:
            await vit_svc.log_weight(s, user.id, w)
            await log_event(s, user.id, "log_weight")
            await s.commit()
    await state.clear()
    await message.answer(f"✅ Вес {w:.1f} кг записан")


@pro_router.message(Command("bp"))
async def cmd_bp(message: Message, state: FSMContext):
    await message.answer("🩺 Введите давление в формате: 120/80 или 120/80/72 (систолическое/диастолическое/пульс)")
    await state.set_state(PROStates.waiting_bp)


@pro_router.message(PROStates.waiting_bp)
async def input_bp(message: Message, state: FSMContext):
    parts = message.text.replace(" ", "").split("/")
    try:
        sys_ = int(parts[0])
        dia = int(parts[1])
        pulse = int(parts[2]) if len(parts) > 2 else None
        if not (60 <= sys_ <= 250 and 40 <= dia <= 150):
            raise ValueError
    except Exception:
        await message.answer("Формат: 120/80")
        return
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == message.from_user.id))).scalar_one_or_none()
        if user:
            entry = await vit_svc.log_bp(s, user.id, sys_, dia, pulse)
            await log_event(s, user.id, "log_bp")
            await s.commit()
    cat = vit_svc.bp_category(sys_, dia)
    await state.clear()
    await message.answer(f"✅ АД {sys_}/{dia}" + (f", пульс {pulse}" if pulse else "") + f"\n{cat}")


# ---------- Kick counter ----------
@pro_router.message(Command("kicks"))
async def cmd_kicks(message: Message):
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == message.from_user.id))).scalar_one_or_none()
        if not user:
            return
        active = await kick_svc.get_active_session(s, user.id)
        if not active:
            active = await kick_svc.start_session(s, user.id)
        text = (
            f"👶 Счётчик шевелений (Cardiff count-to-10)\n\n"
            f"Считаем 10 шевелений за 2 часа. Сейчас: {active.kicks_count}/10\n"
            "Нажимайте кнопку при каждом шевелении."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"👶 Шевеление ({active.kicks_count}/10)", callback_data="kick_add")],
            [InlineKeyboardButton(text="✅ Завершить сессию", callback_data="kick_end")],
        ])
        await s.commit()
    await message.answer(text, reply_markup=kb)


@pro_router.callback_query(F.data == "kick_add")
async def cb_kick_add(cb: CallbackQuery):
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == cb.from_user.id))).scalar_one_or_none()
        active = await kick_svc.get_active_session(s, user.id) if user else None
        if not active:
            await cb.answer("Сессия истекла, начните /kicks заново", show_alert=True)
            return
        await kick_svc.register_kick(s, active)
        await s.commit()
        done = active.kicks_count >= settings.KICK_TARGET
    if done:
        await cb.message.edit_text(f"🎉 Достигнуто 10 шевелений! Малыш активен.")
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"👶 Шевеление ({active.kicks_count}/10)", callback_data="kick_add")],
            [InlineKeyboardButton(text="✅ Завершить сессию", callback_data="kick_end")],
        ])
        await cb.message.edit_reply_markup(reply_markup=kb)
    await cb.answer()


@pro_router.callback_query(F.data == "kick_end")
async def cb_kick_end(cb: CallbackQuery):
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == cb.from_user.id))).scalar_one_or_none()
        active = await kick_svc.get_active_session(s, user.id) if user else None
        if active:
            await kick_svc.finish_session(s, active)
            alert = active.is_alert
            count = active.kicks_count
            await s.commit()
        else:
            alert, count = False, 0
    if alert:
        await cb.message.edit_text(
            f"⚠️ За 2 часа зафиксировано {count} шевелений (норма 10+).\n\n"
            "Если снижение активности повторяется — обратитесь к врачу."
        )
    else:
        await cb.message.edit_text(f"✅ Сессия завершена. Шевелений: {count}")


# ---------- Recipes ----------
def _recipes_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍳 Завтрак", callback_data="rec:breakfast"),
         InlineKeyboardButton(text="🥗 Обед", callback_data="rec:lunch")],
        [InlineKeyboardButton(text="🍽 Ужин", callback_data="rec:dinner"),
         InlineKeyboardButton(text="🍎 Перекус", callback_data="rec:snack")],
        [InlineKeyboardButton(text="🎲 Случайный", callback_data="rec:any")],
    ])


@pro_router.message(Command("recipes"))
@pro_router.message(F.text == "🍽 Рецепты")
async def cmd_recipes(message: Message):
    await message.answer("🍽 Рецепты для ГСД\nВыберите категорию:", reply_markup=_recipes_kb())


@pro_router.callback_query(F.data.startswith("rec:"))
async def cb_recipes(cb: CallbackQuery):
    cat = cb.data.split(":", 1)[1]
    category = None if cat == "any" else cat
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == cb.from_user.id))).scalar_one_or_none()
        if not user:
            return
        items = await rec_svc.list_recipes(s, user, category=category, limit=5)
    if not items:
        await cb.answer("Рецептов пока нет", show_alert=True)
        return
    text = "\n\n".join(rec_svc.format_recipe(r) for r in items[:3])
    footer = ""
    if not sub_svc.is_pro(user):
        footer = "\n\n_В FREE тарифе доступно 10 рецептов. В PRO — 200+ и AI-подбор рациона._"
    await cb.message.answer(text + footer, parse_mode="Markdown")
    await cb.answer()


# ---------- Referral ----------
@pro_router.callback_query(F.data == "referral")
@pro_router.message(Command("invite"))
async def cmd_invite(event, state: FSMContext = None):
    tg_id = event.from_user.id
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
        if not user:
            return
        code = await ref_svc.ensure_code(s, user)
        await s.commit()
    from app.bot.handlers import bot
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{code}"
    text = (
        f"👥 **Пригласи подругу**\n\n"
        f"Твоя ссылка:\n`{link}`\n\n"
        f"Когда она оформит PRO, ты и она получите +{settings.REFERRAL_REWARD_DAYS} дней PRO бесплатно."
    )
    target = event.message if isinstance(event, CallbackQuery) else event
    await target.answer(text, parse_mode="Markdown")


# ---------- AI photo of meal ----------
@pro_router.message(F.photo)
async def on_photo(message: Message):
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == message.from_user.id))).scalar_one_or_none()
        if not user:
            return
        if not await sub_svc.can_use_ai_photo(s, user):
            await message.answer(
                "📸 AI-распознавание доступно 5 раз в месяц в FREE.\n"
                "Купите PRO или пачку из 50 фото: /pro"
            )
            return

        # Download the photo ourselves and pass base64 onward.
        # A Telegram file URL contains BOT_TOKEN, so it must never be sent to the LLM gateway.
        photo = message.photo[-1]
        from app.bot.handlers import bot
        buf = io.BytesIO()
        await bot.download(photo.file_id, destination=buf)
        image_b64 = base64.b64encode(buf.getvalue()).decode()

        placeholder = await message.answer(
            "📸 Анализирую блюдо... результат придёт через 5-15 секунд"
        )
        await ai_client.analyze_meal_photo(
            s, user.id, file_id=photo.file_id, image_b64=image_b64, mime="image/jpeg",
            placeholder_message_id=placeholder.message_id,
        )
        await sub_svc.consume_ai_photo(s, user)
        await log_event(s, user.id, "ai_photo")
        await s.commit()


# ---------- AI chat ----------
@pro_router.message(Command("ask"))
@pro_router.message(F.text == "💬 Спросить Милу")
async def cmd_ask(message: Message, state: FSMContext):
    user = await _get_user(message.from_user.id)
    if not user:
        return
    await message.answer("💬 Задайте вопрос Миле (например: «Можно ли манго?»)")
    await state.set_state(PROStates.chat_question)


@pro_router.message(PROStates.chat_question)
async def ask_go(message: Message, state: FSMContext):
    q = message.text
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == message.from_user.id))).scalar_one_or_none()
        if not user:
            return
        if not await sub_svc.can_use_ai_chat(s, user):
            await message.answer(
                "💬 Бесплатно доступно 10 сообщений Миле в месяц — они закончились.\n"
                "В PRO — общение без ограничений: /pro"
            )
            await s.commit()
            await state.clear()
            return
        # Minimal context: last 7 days summary
        context = {"lang": "ru", "user_id": user.id}
        placeholder = await message.answer("💭 Думаю...")
        await ai_client.chat_query(
            s, user.id, q, context, placeholder_message_id=placeholder.message_id
        )
        await sub_svc.consume_ai_chat(s, user)
        await s.commit()
    await state.clear()


# ---------- AI weekly analysis ----------
async def _do_analysis(tg_id: int, target: Message) -> None:
    """Shared by /analysis command and the diary inline button.

    tg_id is passed explicitly: for a callback, target.from_user is the bot,
    so the pressing user must come from CallbackQuery.from_user.
    """
    user = await _get_user(tg_id)
    if not user or not sub_svc.is_pro(user):
        await target.answer("📊 AI-анализ недели доступен в PRO. /pro")
        return
    message = target
    async with AsyncSessionLocal() as s:
        # pull diary
        import httpx
        from app.config import settings as st
        base = st.PUBLIC_BASE_URL or f"http://localhost:{st.API_PORT}"
        headers = {"Authorization": f"Bearer {st.N8N_CALLBACK_TOKEN or ''}"}
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{base}/api/v1/internal/users/{user.id}/diary?days=7", headers=headers)
                diary = r.json() if r.status_code == 200 else {}
        except Exception:
            diary = {}
        placeholder = await message.answer("📊 Готовлю анализ вашей недели...")
        await ai_client.weekly_analysis(
            s, user.id, diary, placeholder_message_id=placeholder.message_id
        )
        await s.commit()


@pro_router.message(Command("analysis"))
async def cmd_analysis(message: Message):
    await _do_analysis(message.from_user.id, message)


@pro_router.callback_query(F.data == "diary_analysis")
async def cb_diary_analysis(cb: CallbackQuery):
    await cb.answer()
    await _do_analysis(cb.from_user.id, cb.message)


# ---------- PDF report for doctor ----------
async def _do_pdf_report(tg_id: int, target: Message) -> None:
    """Shared by /report command and the diary inline button.

    tg_id is explicit: on a callback target.from_user is the bot.
    """
    from aiogram.types import BufferedInputFile
    from app.services.pdf_report import generate_pdf_report

    async with AsyncSessionLocal() as s:
        user = (await s.execute(
            select(User).where(User.tg_id == tg_id)
        )).scalar_one_or_none()
        if not user:
            await target.answer("Ошибка. Нажмите /start")
            return

        if not await sub_svc.can_use_pdf(s, user):
            await s.commit()
            await target.answer(
                "\U0001F4C4 Бесплатный PDF-отчёт \u2014 один в месяц, он уже использован.\n\n"
                f"Купить ещё один: {settings.PRICE_PDF_REPORT_XTR}\u2b50 в разделе /pro \u2192 "
                "Разовые покупки.\nИли оформите PRO \u2014 отчёты без ограничений."
            )
            return

        note = await target.answer("\U0001F4C4 Собираю отчёт с графиками...")
        try:
            pdf = await generate_pdf_report(s, user, days=28)
        except Exception as e:
            logger.exception("PDF generation failed for user %s", user.id)
            await note.edit_text(
                "\u26A0\ufe0f Не удалось собрать отчёт. Попробуйте позже или напишите нам."
            )
            return

        await sub_svc.consume_pdf(s, user)
        await log_event(s, user.id, "pdf_report")
        await s.commit()

    filename = f"gsd_report_{datetime.now().strftime('%d%m%Y')}.pdf"
    await target.answer_document(
        BufferedInputFile(pdf.read(), filename=filename),
        caption="\U0001F4C4 Отчёт за 4 недели \u2014 можно показать врачу",
    )
    try:
        await note.delete()
    except Exception:
        pass


@pro_router.message(Command("report"))
async def cmd_report(message: Message):
    await _do_pdf_report(message.from_user.id, message)


@pro_router.callback_query(F.data == "diary_pdf")
async def cb_diary_pdf(cb: CallbackQuery):
    await cb.answer()
    await _do_pdf_report(cb.from_user.id, cb.message)


# ---------- Postpartum birth registration ----------
@pro_router.message(Command("birth"))
async def cmd_birth(message: Message, state: FSMContext):
    await message.answer("👶 Введите дату родов в формате ДД.ММ.ГГГГ")
    await state.set_state(PROStates.birth_date)


@pro_router.message(PROStates.birth_date)
async def input_birth(message: Message, state: FSMContext):
    try:
        bd = datetime.strptime(message.text.strip(), "%d.%m.%Y")
    except Exception:
        await message.answer("Формат: 15.08.2026")
        return
    async with AsyncSessionLocal() as s:
        user = (await s.execute(select(User).where(User.tg_id == message.from_user.id))).scalar_one_or_none()
        if user:
            await pp_svc.register_birth(s, user, bd)
            await s.commit()
    await state.clear()
    await message.answer(
        "🎉 Поздравляем!\n\n"
        "Я поставил напоминания об ОГТТ через 6 недель и через год — "
        "это ключевые обследования после ГСД для профилактики СД2."
    )
