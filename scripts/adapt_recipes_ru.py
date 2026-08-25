#!/usr/bin/env python3
"""Адаптация рецептов для русской аудитории.

Берёт рецепты с иностранными названиями и продуктами, адаптирует их
под понятный русский язык и доступные продукты.

Запуск:
    docker compose exec app python3 /app/scripts/adapt_recipes_ru.py --dry-run --limit 5
    docker compose exec app python3 /app/scripts/adapt_recipes_ru.py
"""
import argparse
import asyncio
import json
import sys

import httpx
from sqlalchemy import select

sys.path.insert(0, "/app")
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Recipe

MODEL = "gpt-4o-mini"
MAX_RETRIES = 3

PROMPT = """Ты редактор кулинарных рецептов для русской аудитории.

Получаешь рецепт в JSON. Адаптируй его под российского читателя и верни
СТРОГО JSON с теми же ключами, без markdown и пояснений.

Что адаптировать:

1. НАЗВАНИЕ — понятное русскому человеку:
   - Иностранные названия блюд оставь если они широко известны в России
     (фриттата, равиоли, мусака, киш — оставляем, это устоявшиеся названия)
   - Дословные кальки замени на русские: "corned beef" → "солонина",
     "asparagus" → "спаржа" (не "аспарагус"), "ziti" → "трубочки"
   - Странные конструкции упрости: "Киш заранее" → "Киш (приготовление заранее)"
   - Сохрани смысл, но сделай читаемым

2. ИНГРЕДИЕНТЫ — замени редкие продукты на доступные ТОЛЬКО если замена
   не меняет суть блюда:
   - Экзотические сыры (Грюйер, Чаври) → укажи русский аналог в скобках:
     "сыр Грюйер (или швейцарский)"
   - Редкую зелень (мангольд) → аналог: "мангольд (или шпинат)"
   - Если продукт ключевой для блюда — НЕ заменяй, оставь оригинал
   - Количества и меры НЕ трогай (уже в метрической системе)

3. ИНСТРУКЦИИ — упрости формулировки:
   - Профессиональные термины → простые: "бланшировать" → "отварить 1-2 мин"
   - Сложные техники опиши пошагово
   - Убери культурные отсылки непонятные в РФ

НЕ меняй суть рецепта, состав ингредиентов (только аналоги в скобках),
последовательность приготовления.

Рецепт:
"""


async def adapt_one(client: httpx.AsyncClient, texts: dict) -> dict:
    """Адаптирует один рецепт."""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = await client.post(
                f"{settings.VIBECODE_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {settings.VIBECODE_API_KEY}"},
                json={
                    "model": MODEL,
                    "messages": [{
                        "role": "user",
                        "content": PROMPT + json.dumps(texts, ensure_ascii=False),
                    }],
                    "temperature": 0.3,
                },
                timeout=120,
            )
            if r.status_code == 429:
                await asyncio.sleep(5 * attempt)
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(content)
            if not all(k in data for k in ("title", "ingredients", "instructions")):
                raise ValueError("нет нужных ключей")
            if not data["title"].strip() or not data["instructions"].strip():
                raise ValueError("пустой title или instructions")
            return data
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(3 * attempt)
    raise RuntimeError(f"не удалось после {MAX_RETRIES} попыток: {last_err}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only-id", type=int)
    args = ap.parse_args()

    if not settings.VIBECODE_API_KEY:
        print("ERROR: VIBECODE_API_KEY не задан")
        sys.exit(1)

    async with AsyncSessionLocal() as s:
        q = select(Recipe).order_by(Recipe.id)
        if args.only_id:
            q = q.where(Recipe.id == args.only_id)
        recipes = list((await s.execute(q)).scalars().all())

    if args.limit:
        recipes = recipes[:args.limit]

    print(f"К адаптации: {len(recipes)} рецептов")
    if args.dry_run:
        print("РЕЖИМ: dry-run\n")

    ok = 0
    failed = []

    async with httpx.AsyncClient() as client:
        for rec in recipes:
            src = {
                "title": rec.title or "",
                "ingredients": rec.ingredients or "",
                "instructions": rec.instructions or "",
            }
            orig_title = rec.title or ""
            try:
                adapted = await adapt_one(client, src)
            except Exception as e:
                print(f"  ! id={rec.id} {orig_title[:40]}: {e}")
                failed.append((rec.id, str(e)))
                continue

            changed = adapted["title"].strip() != orig_title.strip()
            mark = "~" if changed else "="

            if changed:
                print(f"  {mark} id={rec.id}")
                print(f"     ДО:  {orig_title}")
                print(f"     ПОСЛЕ: {adapted['title'][:70]}")
            else:
                print(f"  {mark} id={rec.id} {adapted['title'][:55]}")

            if not args.dry_run:
                async with AsyncSessionLocal() as s:
                    db_rec = await s.get(Recipe, rec.id)
                    db_rec.title = adapted["title"].strip()[:255]
                    db_rec.ingredients = adapted["ingredients"].strip()
                    db_rec.instructions = adapted["instructions"].strip()
                    await s.commit()
            ok += 1

    print(f"\n=== ИТОГО ===")
    print(f"обработано: {ok}")
    if failed:
        print(f"ошибки ({len(failed)}): " + ", ".join(str(i) for i, _ in failed))


if __name__ == "__main__":
    asyncio.run(main())
