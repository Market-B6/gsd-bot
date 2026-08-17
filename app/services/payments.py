"""Telegram Stars payment flow."""
import uuid
from datetime import datetime
from aiogram import Bot
from aiogram.types import LabeledPrice
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models import (
    User, Payment, PaymentProvider, PaymentStatus, ProductType,
)
from app.services import subscription as sub_svc


PRODUCT_CATALOG = {
    ProductType.SUB_MONTHLY: {
        "title": "PRO подписка · 1 месяц",
        "description": "AI-фото еды без лимитов, PDF-отчёт врачу, чат с AI-нутрициологом, рецепты, аналитика",
        "price_xtr": settings.PRICE_SUB_MONTHLY_XTR,
    },
    ProductType.SUB_YEARLY: {
        "title": "PRO подписка · 1 год",
        "description": "Экономия ~30%. Все PRO-возможности на 12 месяцев",
        "price_xtr": settings.PRICE_SUB_YEARLY_XTR,
    },
    ProductType.PDF_REPORT: {
        "title": "PDF-отчёт врачу",
        "description": "Расширенный отчёт с графиками за 4 недели",
        "price_xtr": settings.PRICE_PDF_REPORT_XTR,
    },
    ProductType.AI_PHOTO_PACK: {
        "title": "Пачка AI-фото · 50 шт.",
        "description": "50 распознаваний блюд по фото сверх лимита",
        "price_xtr": settings.PRICE_AI_PHOTO_PACK_XTR,
    },
    ProductType.COURSE: {
        "title": "Курс «Жизнь с ГСД»",
        "description": "10 видео-уроков, чек-листы, план питания",
        "price_xtr": settings.PRICE_COURSE_XTR,
    },
    ProductType.DOCTOR_SEAT: {
        "title": "Кабинет врача · 1 месяц",
        "description": "Просмотр дневников до 30 пациенток",
        "price_xtr": settings.PRICE_DOCTOR_SEAT_XTR,
    },
    ProductType.CONSULTATION: {
        "title": "Онлайн-консультация нутрициолога",
        "description": "30 минут, разбор дневника",
        "price_xtr": settings.PRICE_CONSULTATION_XTR,
    },
}


async def create_stars_invoice(
    bot: Bot,
    session: AsyncSession,
    user: User,
    product: ProductType,
    chat_id: int,
) -> None:
    """Send a Telegram Stars invoice to the user."""
    meta = PRODUCT_CATALOG[product]
    payload = f"{product.value}:{user.id}:{uuid.uuid4().hex[:12]}"

    payment = Payment(
        user_id=user.id,
        provider=PaymentProvider.STARS,
        product=product,
        amount=meta["price_xtr"],
        currency="XTR",
        status=PaymentStatus.PENDING,
        invoice_payload=payload,
    )
    session.add(payment)
    await session.flush()

    await bot.send_invoice(
        chat_id=chat_id,
        title=meta["title"],
        description=meta["description"],
        payload=payload,
        provider_token="",  # Stars: empty
        currency="XTR",
        prices=[LabeledPrice(label=meta["title"], amount=meta["price_xtr"])],
        start_parameter=product.value,
    )


async def handle_successful_payment(
    session: AsyncSession,
    invoice_payload: str,
    telegram_charge_id: str,
    total_amount: int,
) -> tuple[User | None, ProductType | None]:
    """Mark payment paid and apply the product. Returns (user, product) or (None, None)."""
    result = await session.execute(
        select(Payment).where(Payment.invoice_payload == invoice_payload)
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        return None, None
    if payment.status == PaymentStatus.PAID:
        return None, None

    payment.status = PaymentStatus.PAID
    payment.provider_charge_id = telegram_charge_id
    payment.paid_at = datetime.now()

    user_result = await session.execute(select(User).where(User.id == payment.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        return None, None

    product = payment.product
    if product in (ProductType.SUB_MONTHLY, ProductType.SUB_YEARLY):
        await sub_svc.grant_subscription(session, user, product)
    elif product in (ProductType.AI_PHOTO_PACK, ProductType.PDF_REPORT):
        await sub_svc.grant_pack(session, user, product)

    return user, product
