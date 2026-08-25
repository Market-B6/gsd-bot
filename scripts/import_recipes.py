#!/usr/bin/env python3
"""Импорт рецептов из Spoonacular в БД gsd-bot.

- complexSearch с addRecipeNutrition: фото, БЖУ, ингредиенты, шаги в одном ответе
- фильтр по углеводам и белку на порцию (клинический смысл при ГСД)
- метка нагрузки по углеводам/порция: <=15 низкая, 16-30 средняя, >30 отброс
- перевод title/ingredients/instructions через vibecode gpt-4o-mini
- картинка скачивается в media/recipes/{spoonacular_id}.jpg
- идемпотентно: дубль по маркеру spoon:<id> в tags пропускается

Запуск изнутри контейнера:
    docker compose exec app python3 /app/scripts/import_recipes.py --per-category 50
"""
import argparse
import asyncio
import json
import os
import re
import sys

import httpx
from sqlalchemy import select

sys.path.insert(0, "/app")
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Recipe

SPOON = "https://api.spoonacular.com"
MEDIA_DIR = "/app/media/recipes"

# категория -> (spoonacular type, is_pro, русское имя)
CATEGORIES = {
    "breakfast": ("breakfast", False, "завтрак"),
    "snack": ("snack", False, "перекус"),
    "lunch": ("main course", True, "обед"),
    "dinner": ("main course", True, "ужин"),
}

MAX_CARBS_PER_SERVING = 30.0   # г, выше — не берём (высокая нагрузка)
MIN_PROTEIN_PER_SERVING = 8.0  # г, белок стабилизирует сахар

# Кухни. Узкий фильтр (eastern european,russian) отдавал 0-2 рецепта, поэтому
# берём европейскую целиком и отсекаем то, что в РФ выглядит экзотикой.
# Итальянские/греческие названия оставляем — фриттата, киш, мусака узнаваемы,
# продукты потом адаптирует adapt_recipes_ru.py.
CUISINE = "european"
EXCLUDE_CUISINE = "japanese,chinese,thai,indian,mexican,cajun,caribbean"


def gl_label(carbs_per_serving: float) -> str:
    if carbs_per_serving <= 15:
        return "🟢 низкая нагрузка"
    return "🟡 средняя нагрузка"


def nutrient(nutrition: dict, name: str) -> float:
    for n in nutrition.get("nutrients", []):
        if n.get("name") == name:
            return float(n.get("amount") or 0)
    return 0.0


async def translate(client: httpx.AsyncClient, texts: dict) -> dict:
    """Переводит словарь строк на русский одним запросом, возвращает словарь."""
    prompt = (
        "Переведи на русский кулинарный текст. Верни строго JSON с теми же ключами, "
        "без пояснений. Названия блюд — естественно по-русски, не дословно. "
        "Меры сразу в метрической системе: граммы, миллилитры, °C.\n\n"
        + json.dumps(texts, ensure_ascii=False)
    )
    r = await client.post(
        f"{settings.VIBECODE_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {settings.VIBECODE_API_KEY}"},
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        },
        timeout=60,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    return json.loads(content)


async def download_image(client: httpx.AsyncClient, url: str, recipe_id: int) -> str | None:
    if not url:
        return None
    try:
        r = await client.get(url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"  ! картинка не скачалась ({e})")
        return None
    os.makedirs(MEDIA_DIR, exist_ok=True)
    path = os.path.join(MEDIA_DIR, f"{recipe_id}.jpg")
    with open(path, "wb") as f:
        f.write(r.content)
    return path


def parse_ingredients(recipe: dict) -> list[str]:
    out = []
    for ing in recipe.get("extendedIngredients", []):
        txt = ing.get("original") or ing.get("name")
        if txt:
            out.append(txt)
    return out


def parse_steps(recipe: dict) -> list[str]:
    out = []
    for block in recipe.get("analyzedInstructions", []):
        for step in block.get("steps", []):
            t = step.get("step")
            if t:
                out.append(t)
    return out


async def import_category(client: httpx.AsyncClient, key: str, per_category: int) -> int:
    spoon_type, is_pro, ru_name = CATEGORIES[key]
    print(f"\n=== {key} ({ru_name}), PRO={is_pro} ===")
    r = await client.get(
        f"{SPOON}/recipes/complexSearch",
        params={
            "apiKey": settings.SPOONACULAR_API_KEY,
            "type": spoon_type,
            "number": per_category * 2,  # запас на отсев
            "addRecipeNutrition": "true",
            "fillIngredients": "true",
            "instructionsRequired": "true",
            "maxCarbs": int(MAX_CARBS_PER_SERVING),
            "minProtein": int(MIN_PROTEIN_PER_SERVING),
            "sort": "healthiness",
            "cuisine": CUISINE,
            "excludeCuisine": EXCLUDE_CUISINE,
        },
        timeout=90,
    )
    r.raise_for_status()
    print(f"  quota left: {r.headers.get('x-api-quota-left')}")
    results = r.json().get("results", [])
    print(f"  получено {len(results)} кандидатов")

    added = 0
    async with AsyncSessionLocal() as s:
        for recipe in results:
            if added >= per_category:
                break
            nutrition = recipe.get("nutrition", {})
            carbs = nutrient(nutrition, "Carbohydrates")
            protein = nutrient(nutrition, "Protein")
            fat = nutrient(nutrition, "Fat")
            kcal = nutrient(nutrition, "Calories")
            if carbs <= 0 or carbs > MAX_CARBS_PER_SERVING:
                continue
            if protein < MIN_PROTEIN_PER_SERVING:
                continue

            ingredients = parse_ingredients(recipe)
            steps = parse_steps(recipe)
            if not ingredients or not steps:
                continue

            title_en = recipe.get("title", "").strip()
            if not title_en:
                continue

            # дубль ищем по маркеру источника, а не по названию
            marker = f"spoon:{recipe.get('id')}"
            exists = (await s.execute(
                select(Recipe).where(Recipe.tags.like(f"%{marker}%")).limit(1)
            )).scalar_one_or_none()
            if exists:
                print(f"  = пропуск (уже есть): {title_en}")
                continue

            try:
                tr = await translate(client, {
                    "title": title_en,
                    "ingredients": "\n".join(ingredients),
                    "instructions": "\n".join(steps),
                })
            except Exception as e:
                print(f"  ! перевод не удался ({e}): {title_en}")
                continue

            img_path = await download_image(
                client, recipe.get("image", ""), recipe.get("id")
            )

            rec = Recipe(
                title=tr.get("title", title_en)[:255],
                category=key,
                meal_time=ru_name,
                ingredients=tr.get("ingredients", "\n".join(ingredients)),
                instructions=tr.get("instructions", "\n".join(steps)),
                protein_g=round(protein, 1),
                fat_g=round(fat, 1),
                carb_g=round(carbs, 1),
                xe=round(carbs / 12, 1),
                kcal=int(kcal),
                gi=None,
                glycemic_load=None,
                is_pro=is_pro,
                photo_url=img_path,
                tags=f"{gl_label(carbs)},{marker}",
            )
            s.add(rec)
            await s.commit()
            added += 1
            print(f"  + {tr.get('title', title_en)} — У:{carbs:.0f} Б:{protein:.0f} · {gl_label(carbs)}")
    print(f"  итого добавлено: {added}")
    return added


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=15)
    ap.add_argument("--only", help="одна категория: breakfast/snack/lunch/dinner")
    args = ap.parse_args()

    if not settings.SPOONACULAR_API_KEY:
        print("ERROR: SPOONACULAR_API_KEY не задан")
        sys.exit(1)

    cats = [args.only] if args.only else list(CATEGORIES.keys())
    total = 0
    async with httpx.AsyncClient() as client:
        for key in cats:
            total += await import_category(client, key, args.per_category)
    print(f"\n=== ГОТОВО: добавлено {total} рецептов ===")


if __name__ == "__main__":
    asyncio.run(main())
