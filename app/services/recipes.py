"""Recipe catalogue with GDM-friendly picks."""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Recipe
from app.services.subscription import is_pro
from app.config import settings


async def list_recipes(session: AsyncSession, user, category: str | None = None, limit: int = 20):
    q = select(Recipe)
    if category:
        q = q.where(Recipe.category == category)
    if not is_pro(user):
        q = q.where(Recipe.is_pro.is_(False)).limit(min(limit, settings.FREE_RECIPES_COUNT))
    else:
        q = q.limit(limit)
    q = q.order_by(func.random())
    result = await session.execute(q)
    return list(result.scalars().all())


async def get_recipe(session: AsyncSession, recipe_id: int) -> Recipe | None:
    result = await session.execute(select(Recipe).where(Recipe.id == recipe_id))
    return result.scalar_one_or_none()


def format_recipe(recipe: Recipe) -> str:
    parts = [
        f"🍽 **{recipe.title}**\n",
    ]
    if recipe.protein_g and recipe.fat_g and recipe.carb_g:
        parts.append(
            f"Б/Ж/У: {recipe.protein_g:.0f}/{recipe.fat_g:.0f}/{recipe.carb_g:.0f} г"
        )
    if recipe.xe:
        parts.append(f"ХЕ: {recipe.xe:.1f}")
    if recipe.gi is not None:
        parts.append(f"ГИ: {recipe.gi}")
    if recipe.kcal:
        parts.append(f"Ккал: {recipe.kcal}")
    parts.append(f"\n📝 Ингредиенты:\n{recipe.ingredients}")
    parts.append(f"\n👩‍🍳 Приготовление:\n{recipe.instructions}")
    return "\n".join(parts)


# Seed data for MVP (all GDM-friendly, low-GI)
SEED_RECIPES = [
    dict(title="Омлет с брокколи и сыром", category="breakfast",
         ingredients="Яйца 2 шт, брокколи 100 г, сыр 30 г, оливковое масло 5 г",
         instructions="Обжарить брокколи 3 мин, залить яйцами, посыпать сыром, готовить под крышкой 5 мин.",
         protein_g=22, fat_g=18, carb_g=6, xe=0.5, kcal=280, gi=25, is_pro=False),
    dict(title="Гречка с курицей и овощами", category="lunch",
         ingredients="Гречка 60 г (сухая), куриная грудка 150 г, кабачок 100 г, лук, зелень",
         instructions="Гречку отварить. Курицу и овощи потушить. Смешать, добавить зелень.",
         protein_g=38, fat_g=8, carb_g=42, xe=3.5, kcal=380, gi=45, is_pro=False),
    dict(title="Творог с ягодами и орехами", category="snack",
         ingredients="Творог 5% 150 г, малина 50 г, миндаль 15 г, корица",
         instructions="Смешать творог с ягодами, посыпать миндалём и корицей.",
         protein_g=25, fat_g=12, carb_g=10, xe=1, kcal=250, gi=30, is_pro=False),
    dict(title="Салат с киноа, лососем и авокадо", category="lunch",
         ingredients="Киноа 40 г, лосось 120 г, авокадо 1/2, огурец, шпинат, лимон, оливковое масло",
         instructions="Киноа отварить. Лосось запечь. Смешать с овощами, заправить.",
         protein_g=30, fat_g=25, carb_g=30, xe=2.5, kcal=480, gi=35, is_pro=True),
    dict(title="Хумус с овощами", category="snack",
         ingredients="Нут 50 г, тахини 15 г, лимон, чеснок, оливковое масло, овощи для макания",
         instructions="Нут отварить, взбить с тахини, лимоном и чесноком. Подавать с овощами.",
         protein_g=10, fat_g=15, carb_g=20, xe=1.5, kcal=270, gi=25, is_pro=False),
    dict(title="Запечённая рыба с овощами", category="dinner",
         ingredients="Треска 200 г, цветная капуста 150 г, брокколи 100 г, лимон, специи",
         instructions="Овощи и рыбу выложить на пергамент, посолить, запечь 25 мин при 180°C.",
         protein_g=42, fat_g=6, carb_g=12, xe=1, kcal=280, gi=15, is_pro=False),
    dict(title="Смузи-боул с семенами чиа", category="breakfast",
         ingredients="Кефир 200 мл, чиа 15 г, ягоды 100 г, орехи 10 г",
         instructions="Смешать кефир и чиа, дать настояться 15 мин. Украсить ягодами и орехами.",
         protein_g=15, fat_g=12, carb_g=25, xe=2, kcal=290, gi=35, is_pro=True),
    dict(title="Индейка с чечевицей", category="dinner",
         ingredients="Филе индейки 150 г, чечевица 60 г, морковь, лук, томатная паста",
         instructions="Чечевицу отварить. Индейку и овощи потушить. Соединить.",
         protein_g=40, fat_g=8, carb_g=35, xe=3, kcal=380, gi=30, is_pro=False),
    dict(title="Овсяная каша с яблоком и корицей", category="breakfast",
         ingredients="Овсянка (не быстрая) 40 г, молоко 200 мл, яблоко 1/2, корица, орехи",
         instructions="Овсянку сварить на молоке. Добавить яблоко и корицу, посыпать орехами.",
         protein_g=12, fat_g=8, carb_g=45, xe=3.5, kcal=310, gi=55, is_pro=False),
    dict(title="Тыквенный суп-пюре", category="lunch",
         ingredients="Тыква 300 г, куриный бульон 400 мл, сливки 10% 50 мл, имбирь, мускатный орех",
         instructions="Тыкву отварить в бульоне, взбить блендером, добавить сливки и специи.",
         protein_g=8, fat_g=6, carb_g=20, xe=1.5, kcal=180, gi=35, is_pro=False),
    dict(title="Куриные котлеты на пару с киноа", category="dinner",
         ingredients="Куриный фарш 150 г, киноа 50 г, лук, зелень, яйцо 1 шт",
         instructions="Смешать фарш с яйцом и луком. Сформировать котлеты, готовить на пару 20 мин.",
         protein_g=35, fat_g=10, carb_g=30, xe=2.5, kcal=350, gi=35, is_pro=True),
    dict(title="Греческий йогурт с семенами льна", category="snack",
         ingredients="Йогурт 200 г, семена льна 10 г, ягоды 50 г",
         instructions="Смешать все ингредиенты.",
         protein_g=18, fat_g=6, carb_g=12, xe=1, kcal=180, gi=20, is_pro=False),
    dict(title="Стейк из говядины с салатом", category="dinner",
         ingredients="Говядина 150 г, микс салатов, помидоры черри, огурец, оливковое масло",
         instructions="Стейк обжарить на гриле. Овощи заправить маслом. Подавать вместе.",
         protein_g=40, fat_g=20, carb_g=8, xe=0.5, kcal=380, gi=15, is_pro=True),
    dict(title="Панкейки из творога", category="breakfast",
         ingredients="Творог 150 г, яйцо 1 шт, овсяная мука 30 г, сахарозаменитель, ягоды",
         instructions="Смешать творог, яйцо и муку. Жарить на сухой сковороде 3 мин с каждой стороны.",
         protein_g=25, fat_g=8, carb_g=20, xe=1.5, kcal=280, gi=40, is_pro=True),
    dict(title="Салат с тунцом и фасолью", category="lunch",
         ingredients="Тунец 100 г, красная фасоль 80 г, лук, зелень, лимон, оливковое масло",
         instructions="Смешать все ингредиенты, заправить.",
         protein_g=30, fat_g=8, carb_g=25, xe=2, kcal=310, gi=30, is_pro=False),
]


async def seed_recipes(session: AsyncSession) -> int:
    """Idempotent seed. Returns count inserted."""
    count = await session.scalar(select(func.count(Recipe.id)))
    if count and count > 0:
        return 0
    for row in SEED_RECIPES:
        session.add(Recipe(**row))
    return len(SEED_RECIPES)
