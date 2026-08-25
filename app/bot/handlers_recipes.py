"""Обработчики для раздела Рецепты."""
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models import Recipe, User, SubscriptionTier

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


def get_recipe_card_keyboard(recipe_id: int, has_prev: bool, has_next: bool, category: str):
    """Навигация по карточкам рецептов."""
    buttons = []

    nav_row = []
    if has_prev:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"recipe_prev_{recipe_id}_{category}"))
    nav_row.append(InlineKeyboardButton(text="📋 К категориям", callback_data="recipes_categories"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"recipe_next_{recipe_id}_{category}"))

    buttons.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_recipe_card(recipe: Recipe) -> str:
    """Форматирует карточку рецепта."""
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
                text += f" ({recipe.xe} ХЕ)"
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

    # Теги
    if recipe.tags:
        text += f"\n🏷 {recipe.tags}"

    return text


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

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_categories_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("recipes_cat_"))
async def recipes_category(callback: CallbackQuery):
    """Показываем первый рецепт из категории."""
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
            await callback.message.edit_text(
                f"🔒 **{recipe.title}**\n\n"
                "Этот рецепт доступен только по подписке PRO.\n\n"
                "⭐️ **Что даёт PRO:**\n"
                "• Полная база рецептов для обеда и ужина\n"
                "• AI-анализ фото еды\n"
                "• Персональные рекомендации\n"
                "• Экспорт отчётов для врача\n\n"
                "Подробнее: /pro",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⭐️ Оформить PRO", callback_data="subscribe_pro")],
                    [InlineKeyboardButton(text="🔙 К категориям", callback_data="recipes_categories")],
                ])
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

    text = format_recipe_card(recipe)
    keyboard = get_recipe_card_keyboard(recipe.id, False, has_next, category)

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("recipe_next_"))
async def recipe_next(callback: CallbackQuery):
    """Следующий рецепт в категории."""
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
            await callback.message.edit_text(
                f"🔒 **{recipe.title}**\n\n"
                "Этот рецепт доступен только по подписке PRO.\n\n"
                "⭐️ **Что даёт PRO:**\n"
                "• Полная база рецептов для обеда и ужина\n"
                "• AI-анализ фото еды\n"
                "• Персональные рекомендации\n"
                "• Экспорт отчётов для врача\n\n"
                "Подробнее: /pro",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⭐️ Оформить PRO", callback_data="subscribe_pro")],
                    [InlineKeyboardButton(text="🔙 К категориям", callback_data="recipes_categories")],
                ])
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

    text = format_recipe_card(recipe)
    keyboard = get_recipe_card_keyboard(recipe.id, has_prev, has_next, category)

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("recipe_prev_"))
async def recipe_prev(callback: CallbackQuery):
    """Предыдущий рецепт в категории."""
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
            await callback.message.edit_text(
                f"🔒 **{recipe.title}**\n\n"
                "Этот рецепт доступен только по подписке PRO.\n\n"
                "⭐️ **Что даёт PRO:**\n"
                "• Полная база рецептов для обеда и ужина\n"
                "• AI-анализ фото еды\n"
                "• Персональные рекомендации\n"
                "• Экспорт отчётов для врача\n\n"
                "Подробнее: /pro",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⭐️ Оформить PRO", callback_data="subscribe_pro")],
                    [InlineKeyboardButton(text="🔙 К категориям", callback_data="recipes_categories")],
                ])
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

    text = format_recipe_card(recipe)
    keyboard = get_recipe_card_keyboard(recipe.id, has_prev, has_next, category)

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "recipes_back")
async def recipes_back(callback: CallbackQuery):
    """Закрыть меню рецептов."""
    await callback.message.delete()
    await callback.answer()
