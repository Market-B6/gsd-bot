"""Обработчики для раздела Рецепты."""
import logging
from pathlib import Path

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
)
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models import Recipe, User, SubscriptionTier

logger = logging.getLogger(__name__)
router = Router()


def get_categories_keyboard():
    """Клавиатура выбора категории рецептов."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌅 Завтрак", callback_data="recipes_cat_breakfast")],
            [InlineKeyboardButton(text="🍎 Перекус", callback_data="recipes_cat_snack")],
            [InlineKeyboardButton(text="🍽 Обед", callback_data="recipes_cat_lunch")],
            [InlineKeyboardButton(text="🌙 Ужин", callback_data="recipes_cat_dinner")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="recipes_back")],
        ]
    )


def get_recipe_card_keyboard(recipe_id: int, has_prev: bool, has_next: bool, category: str,
                             with_full: bool = False):
    """Навигация по карточкам рецептов.

    with_full=True добавляет кнопку раскрытия полного рецепта — она нужна,
    когда под фото показана только компактная подпись.
    """
    buttons = []

    if with_full:
        buttons.append([
            InlineKeyboardButton(text="👨‍🍳 Показать рецепт",
                                 callback_data=f"recipe_full_{recipe_id}_{category}")
        ])

    nav_row = []
    if has_prev:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"recipe_prev_{recipe_id}_{category}"))
    nav_row.append(InlineKeyboardButton(text="📋 К категориям", callback_data="recipes_categories"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"recipe_next_{recipe_id}_{category}"))

    buttons.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Метки нагрузки из импортёра — короткие, пользователю непонятно, о чём речь.
# Разворачиваем в явную формулировку про сахар в крови.
TAG_LABELS = {
    "🟢 низкая нагрузка": "🟢 Низкая нагрузка — сахар почти не поднимет",
    "🟡 средняя нагрузка": "🟡 Средняя нагрузка — сахар поднимет умеренно",
}


def format_recipe_short(recipe: Recipe) -> str:
    """Компактная подпись под фото: влезает в лимит caption Telegram (1024)."""
    text = f"📖 **{recipe.title}**\n\n"

    if recipe.carb_g:
        text += f"🍞 Углеводы: {recipe.carb_g} г"
        if recipe.xe:
            text += f" — {recipe.xe} ХЕ (хлебных единиц)"
        text += "\n"
    if recipe.protein_g:
        text += f"🥚 Белки: {recipe.protein_g} г\n"
    if recipe.fat_g:
        text += f"🧈 Жиры: {recipe.fat_g} г\n"
    if recipe.kcal:
        text += f"🔥 {recipe.kcal} ккал\n"

    labels = [
        TAG_LABELS.get(tag.strip(), tag.strip())
        for tag in (recipe.tags or "").split(",")
        if tag.strip() and not tag.strip().startswith("spoon:")
    ]
    if labels:
        text += "\n" + "\n".join(labels)

    return text[:1024]


def format_recipe_card(recipe: Recipe) -> str:
    """Полная карточка рецепта."""
    text = f"📖 **{recipe.title}**\n\n"

    # БЖУ и калории
    if recipe.protein_g or recipe.fat_g or recipe.carb_g or recipe.kcal:
        text += "📊 **Пищевая ценность (на порцию):**\n"
        if recipe.protein_g:
            text += f"• Белки: {recipe.protein_g} г\n"
        if recipe.fat_g:
            text += f"• Жиры: {recipe.fat_g} г\n"
        if recipe.carb_g:
            text += f"• Углеводы: {recipe.carb_g} г"
            if recipe.xe:
                text += f" — {recipe.xe} ХЕ (хлебных единиц)"
            text += "\n"
        if recipe.kcal:
            text += f"• Калории: {recipe.kcal} ккал\n"
        text += "\n"

    # Ингредиенты
    text += "🛒 **Ингредиенты:**\n"
    for line in recipe.ingredients.strip().split('\n'):
        if line.strip():
            text += f"• {line.strip()}\n"
    text += "\n"

    # Инструкции
    text += "👨‍🍳 **Приготовление:**\n"
    instructions = recipe.instructions.strip().split('\n')
    step = 1
    for line in instructions:
        line = line.strip()
        if line:
            text += f"{step}. {line}\n"
            step += 1

    # Теги. В поле лежит и служебный маркер источника (spoon:<id>), по которому
    # импортёр ищет дубли — пользователю он не нужен, показываем только метки.
    visible_tags = [
        TAG_LABELS.get(tag.strip(), tag.strip())
        for tag in (recipe.tags or "").split(",")
        if tag.strip() and not tag.strip().startswith("spoon:")
    ]
    if visible_tags:
        text += "\n" + "\n".join(visible_tags)

    return text


async def replace_message(callback: CallbackQuery, text: str,
                          reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Заменяет сообщение текстом, чем бы оно ни было.

    Карточка рецепта приходит как фото, а у сообщения с фото нет текста —
    edit_text на нём падает («there is no text in the message to edit»),
    и если это происходит до callback.answer(), Telegram крутит загрузку.
    Поэтому для фото удаляем сообщение и отправляем новое.
    """
    if callback.message.photo:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=reply_markup)
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass  # старше 48 часов — Telegram удалять не даёт
        return
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        logger.warning("edit_text не удался (%s), отправляю новым сообщением", e)
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=reply_markup)


async def show_recipe_card(callback: CallbackQuery, recipe: Recipe,
                           has_prev: bool, has_next: bool, category: str):
    """Показывает карточку: фото + компактная подпись, полный текст — по кнопке.

    edit_text не умеет превратить текстовое сообщение в фото, поэтому при наличии
    файла старое сообщение удаляется и отправляется новое с картинкой.
    Если фото нет или Telegram его не принял — остаётся текстовый вид.
    """
    photo_path = Path(recipe.photo_url) if recipe.photo_url else None

    if photo_path and photo_path.is_file():
        keyboard = get_recipe_card_keyboard(recipe.id, has_prev, has_next, category,
                                            with_full=True)
        try:
            await callback.message.answer_photo(
                FSInputFile(photo_path),
                caption=format_recipe_short(recipe),
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            try:
                await callback.message.delete()
            except TelegramBadRequest:
                pass  # сообщение старше 48 часов — Telegram удалять не даёт
            return
        except TelegramBadRequest as e:
            logger.warning("Фото рецепта %s не отправилось (%s), показываю текст", recipe.id, e)

    keyboard = get_recipe_card_keyboard(recipe.id, has_prev, has_next, category)
    await replace_message(callback, format_recipe_card(recipe), keyboard)


@router.callback_query(F.data.startswith("recipe_full_"))
async def recipe_full(callback: CallbackQuery):
    """Полный текст рецепта отдельным сообщением — под фото он не влезает."""
    await callback.answer()  # Убираем крутилку сразу

    parts = callback.data.split("_")
    recipe_id, category = int(parts[2]), parts[3]

    async with AsyncSessionLocal() as session:
        recipe = await session.get(Recipe, recipe_id)

    if not recipe:
        await callback.message.answer("⚠️ Рецепт не найден", parse_mode="Markdown")
        return

    await callback.message.answer(format_recipe_card(recipe), parse_mode="Markdown")


@router.message(F.text == "📖 Рецепты", StateFilter("*"))
async def recipes_button(message: Message, state: FSMContext):
    """Главное меню рецептов."""
    await state.clear()

    async with AsyncSessionLocal() as session:
        # Подсчёт рецептов по категориям
        counts = {}
        for cat in ["breakfast", "snack", "lunch", "dinner"]:
            result = await session.execute(
                select(func.count(Recipe.id)).where(Recipe.category == cat)
            )
            counts[cat] = result.scalar()

        result = await session.execute(
            select(func.count(Recipe.id)).where(Recipe.is_pro == True)
        )
        pro_count = result.scalar()

    text = (
        "📖 **Рецепты для ГСД**\n\n"
        "Все рецепты адаптированы для беременных с гестационным диабетом: "
        "низкая гликемическая нагрузка, оптимальный баланс БЖУ.\n\n"
        f"🌅 Завтрак — {counts['breakfast']} рецептов\n"
        f"🍎 Перекус — {counts['snack']} рецептов\n"
        f"🍽 Обед — {counts['lunch']} рецептов\n"
        f"🌙 Ужин — {counts['dinner']} рецептов\n\n"
        f"⭐️ {pro_count} PRO-рецептов (обед/ужин) доступны по подписке"
    )

    await message.answer(text, parse_mode="Markdown", reply_markup=get_categories_keyboard())


@router.callback_query(F.data == "recipes_categories")
async def recipes_categories_callback(callback: CallbackQuery):
    """Возврат к списку категорий."""
    await callback.answer()

    async with AsyncSessionLocal() as session:
        counts = {}
        for cat in ["breakfast", "snack", "lunch", "dinner"]:
            result = await session.execute(
                select(func.count(Recipe.id)).where(Recipe.category == cat)
            )
            counts[cat] = result.scalar()

        result = await session.execute(
            select(func.count(Recipe.id)).where(Recipe.is_pro == True)
        )
        pro_count = result.scalar()

    text = (
        "📖 **Рецепты для ГСД**\n\n"
        "Все рецепты адаптированы для беременных с гестационным диабетом: "
        "низкая гликемическая нагрузка, оптимальный баланс БЖУ.\n\n"
        f"🌅 Завтрак — {counts['breakfast']} рецептов\n"
        f"🍎 Перекус — {counts['snack']} рецептов\n"
        f"🍽 Обед — {counts['lunch']} рецептов\n"
        f"🌙 Ужин — {counts['dinner']} рецептов\n\n"
        f"⭐️ {pro_count} PRO-рецептов (обед/ужин) доступны по подписке"
    )

    await replace_message(callback, text, get_categories_keyboard())


@router.callback_query(F.data.startswith("recipes_cat_"))
async def recipes_category(callback: CallbackQuery):
    """Показываем первый рецепт из категории."""
    await callback.answer()

    category = callback.data.split("_")[-1]  # breakfast/snack/lunch/dinner

    async with AsyncSessionLocal() as session:
        # Получаем пользователя для проверки подписки
        result = await session.execute(
            select(User).where(User.tg_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()

        # Получаем первый рецепт категории.
        # limit(1) обязателен: scalar_one_or_none() падает с MultipleResultsFound,
        # если запрос вернул больше одной строки.
        query = select(Recipe).where(Recipe.category == category).order_by(Recipe.id).limit(1)
        result = await session.execute(query)
        recipe = result.scalar_one_or_none()

        if not recipe:
            await callback.answer("В этой категории пока нет рецептов", show_alert=True)
            return

        # Проверка PRO-доступа
        if recipe.is_pro and (not user or user.subscription_tier == SubscriptionTier.FREE):
            await replace_message(
                callback,
                f"🔒 **{recipe.title}**\n\n"
                "Этот рецепт доступен только по подписке PRO.\n\n"
                "⭐️ **Что даёт PRO:**\n"
                "• Полная база рецептов для обеда и ужина\n"
                "• AI-анализ фото еды\n"
                "• Персональные рекомендации\n"
                "• Экспорт отчётов для врача\n\n"
                "Подробнее: /pro",
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⭐️ Оформить PRO", callback_data="subscribe_pro")],
                    [InlineKeyboardButton(text="🔙 К категориям", callback_data="recipes_categories")],
                ]),
            )
            await callback.answer()
            return

        # Проверяем есть ли следующий рецепт
        next_result = await session.execute(
            select(Recipe)
            .where(Recipe.category == category, Recipe.id > recipe.id)
            .order_by(Recipe.id)
            .limit(1)
        )
        has_next = next_result.scalar_one_or_none() is not None

    await show_recipe_card(callback, recipe, False, has_next, category)


@router.callback_query(F.data.startswith("recipe_next_"))
async def recipe_next(callback: CallbackQuery):
    """Следующий рецепт в категории."""
    await callback.answer()

    _, _, current_id, category = callback.data.split("_")
    current_id = int(current_id)

    async with AsyncSessionLocal() as session:
        # Получаем пользователя
        result = await session.execute(
            select(User).where(User.tg_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()

        # Следующий рецепт
        result = await session.execute(
            select(Recipe)
            .where(Recipe.category == category, Recipe.id > current_id)
            .order_by(Recipe.id)
            .limit(1)
        )
        recipe = result.scalar_one_or_none()

        if not recipe:
            await callback.answer("Это последний рецепт в категории", show_alert=True)
            return

        # PRO-гейт
        if recipe.is_pro and (not user or user.subscription_tier == SubscriptionTier.FREE):
            await replace_message(
                callback,
                f"🔒 **{recipe.title}**\n\n"
                "Этот рецепт доступен только по подписке PRO.\n\n"
                "⭐️ **Что даёт PRO:**\n"
                "• Полная база рецептов для обеда и ужина\n"
                "• AI-анализ фото еды\n"
                "• Персональные рекомендации\n"
                "• Экспорт отчётов для врача\n\n"
                "Подробнее: /pro",
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⭐️ Оформить PRO", callback_data="subscribe_pro")],
                    [InlineKeyboardButton(text="🔙 К категориям", callback_data="recipes_categories")],
                ]),
            )
            await callback.answer()
            return

        # Проверяем prev/next
        prev_result = await session.execute(
            select(Recipe)
            .where(Recipe.category == category, Recipe.id < recipe.id)
            .order_by(Recipe.id.desc())
            .limit(1)
        )
        has_prev = prev_result.scalar_one_or_none() is not None

        next_result = await session.execute(
            select(Recipe)
            .where(Recipe.category == category, Recipe.id > recipe.id)
            .order_by(Recipe.id)
            .limit(1)
        )
        has_next = next_result.scalar_one_or_none() is not None

    await show_recipe_card(callback, recipe, has_prev, has_next, category)


@router.callback_query(F.data.startswith("recipe_prev_"))
async def recipe_prev(callback: CallbackQuery):
    """Предыдущий рецепт в категории."""
    await callback.answer()

    _, _, current_id, category = callback.data.split("_")
    current_id = int(current_id)

    async with AsyncSessionLocal() as session:
        # Получаем пользователя
        result = await session.execute(
            select(User).where(User.tg_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()

        # Предыдущий рецепт
        result = await session.execute(
            select(Recipe)
            .where(Recipe.category == category, Recipe.id < current_id)
            .order_by(Recipe.id.desc())
            .limit(1)
        )
        recipe = result.scalar_one_or_none()

        if not recipe:
            await callback.answer("Это первый рецепт в категории", show_alert=True)
            return

        # PRO-гейт (на всякий случай, хотя возврат назад обычно безопасен)
        if recipe.is_pro and (not user or user.subscription_tier == SubscriptionTier.FREE):
            await replace_message(
                callback,
                f"🔒 **{recipe.title}**\n\n"
                "Этот рецепт доступен только по подписке PRO.\n\n"
                "⭐️ **Что даёт PRO:**\n"
                "• Полная база рецептов для обеда и ужина\n"
                "• AI-анализ фото еды\n"
                "• Персональные рекомендации\n"
                "• Экспорт отчётов для врача\n\n"
                "Подробнее: /pro",
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⭐️ Оформить PRO", callback_data="subscribe_pro")],
                    [InlineKeyboardButton(text="🔙 К категориям", callback_data="recipes_categories")],
                ]),
            )
            await callback.answer()
            return

        # Проверяем prev/next
        prev_result = await session.execute(
            select(Recipe)
            .where(Recipe.category == category, Recipe.id < recipe.id)
            .order_by(Recipe.id.desc())
            .limit(1)
        )
        has_prev = prev_result.scalar_one_or_none() is not None

        next_result = await session.execute(
            select(Recipe)
            .where(Recipe.category == category, Recipe.id > recipe.id)
            .order_by(Recipe.id)
            .limit(1)
        )
        has_next = next_result.scalar_one_or_none() is not None

    await show_recipe_card(callback, recipe, has_prev, has_next, category)


@router.callback_query(F.data == "recipes_back")
async def recipes_back(callback: CallbackQuery):
    """Закрыть меню рецептов."""
    await callback.message.delete()
    await callback.answer()
