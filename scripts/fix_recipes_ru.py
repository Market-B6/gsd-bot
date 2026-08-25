#!/usr/bin/env python3
"""Исправление переводов рецептов и перевод мер в метрическую систему.

Идёт по рецептам в БД по одному, отдаёт title/ingredients/instructions
в vibecode gpt-4o-mini с жёстким промптом и пишет результат назад.

Почему не один большой SQL: 70 рецептов с полным текстом — это ~190 КБ,
такой скрипт нельзя ни проверить глазами, ни безопасно прогнать частями.

Запуск изнутри контейнера:
    docker compose exec app python3 /app/scripts/fix_recipes_ru.py
    docker compose exec app python3 /app/scripts/fix_recipes_ru.py --dry-run --limit 3
    docker compose exec app python3 /app/scripts/fix_recipes_ru.py --only-id 64
"""
import argparse
import asyncio
import json
import re
import sys

import httpx
from sqlalchemy import select

sys.path.insert(0, "/app")
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Recipe

MODEL = "gpt-4o-mini"
MAX_RETRIES = 3

PROMPT = """Ты редактор кулинарных текстов на русском языке.

Тебе дан рецепт в JSON. Исправь его и верни СТРОГО JSON с теми же ключами,
без markdown-обёртки и без пояснений.

Что исправить:

1. ПЕРЕВОД. Убери всё, что осталось на английском или переведено криво.
   Названия блюд — естественно по-русски, как их называют в России
   (не дословно, не транслитом). Примеры кривых названий: "Бы salat Капрезе",
   "Гнoccoни", "Питтата". Если в тексте остались английские фразы —
   переведи их.

2. МЕРЫ — ТОЛЬКО МЕТРИЧЕСКИЕ. Нигде не должно остаться чашек, стаканов,
   унций, фунтов, дюймов и градусов Фаренгейта:
   - 1 cup / чашка / стакан жидкости = 240 мл
   - 1 cup / чашка / стакан муки или сахара = 200 г
   - 1 tablespoon / столовая ложка = 15 мл
   - 1 teaspoon / чайная ложка = 5 мл
   - 1 ounce / унция = 28 г
   - 1 pound / фунт = 450 г
   - 1 inch / дюйм = 2,5 см
   - °F в °C, округляя до ближайших 5 градусов
   Сокращения приводи к виду "ст. л." и "ч. л.".

3. ЧИСТКА. Убери двойные пробелы, висячие переносы строк, обрывки фраз.
   Порядок шагов и смысл рецепта не меняй, ингредиенты не добавляй и не убирай.

Рецепт:
"""


async def fix_one(client: httpx.AsyncClient, texts: dict) -> dict:
    """Отдаёт один рецепт модели, возвращает исправленный словарь."""
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
                    "temperature": 0.2,
                },
                timeout=120,
            )
            if r.status_code == 429:
                raise RuntimeError("429 rate limit")
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            content = re.sub(
                r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE
            ).strip()
            data = json.loads(content)
            if not all(k in data for k in ("title", "ingredients", "instructions")):
                raise ValueError("в ответе нет нужных ключей")
            if not data["title"].strip() or not data["instructions"].strip():
                raise ValueError("пустой title или instructions")
            return data
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(3 * attempt)
    raise RuntimeError(f"не удалось после {MAX_RETRIES} попыток: {last_err}")


IMPERIAL_MARKERS = (
    "чашк", "стакан", "унци", "фунт", "дюйм", "cup", "ounce",
    "pound", "inch", "tablespoon", "teaspoon", "°F", "ложки",
)


def remaining_imperial(rec: dict) -> list[str]:
    """Что осталось от имперских мер — для отчёта в конце прогона."""
    blob = " ".join(
        (rec.get(k) or "") for k in ("title", "ingredients", "instructions")
    ).lower()
    return [m for m in IMPERIAL_MARKERS if m.lower() in blob]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="не писать в БД")
    ap.add_argument("--limit", type=int, help="обработать только N рецептов")
    ap.add_argument("--only-id", type=int, help="один рецепт по id")
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
        recipes = recipes[: args.limit]

    print(f"К обработке: {len(recipes)} рецептов, модель {MODEL}")
    if args.dry_run:
        print("РЕЖИМ: dry-run, в БД ничего не пишется\n")

    ok = 0
    failed: list[tuple[int, str]] = []
    dirty: list[tuple[int, list[str]]] = []

    async with httpx.AsyncClient() as client:
        for rec in recipes:
            src = {
                "title": rec.title or "",
                "ingredients": rec.ingredients or "",
                "instructions": rec.instructions or "",
            }
            try:
                fixed = await fix_one(client, src)
            except Exception as e:
                print(f"  ! id={rec.id} {rec.title[:40]}: {e}")
                failed.append((rec.id, str(e)))
                continue

            left = remaining_imperial(fixed)
            if left:
                dirty.append((rec.id, left))

            changed = fixed["title"].strip() != (rec.title or "").strip()
            mark = "~" if changed else "="
            print(f"  {mark} id={rec.id} {fixed['title'][:55]}"
                  + (f"  [осталось: {', '.join(left)}]" if left else ""))

            if not args.dry_run:
                async with AsyncSessionLocal() as s:
                    db_rec = await s.get(Recipe, rec.id)
                    db_rec.title = fixed["title"].strip()[:255]
                    db_rec.ingredients = fixed["ingredients"].strip()
                    db_rec.instructions = fixed["instructions"].strip()
                    await s.commit()
            ok += 1

    print(f"\n=== ИТОГО ===")
    print(f"обработано успешно: {ok}")
    if failed:
        print(f"ошибки ({len(failed)}): " + ", ".join(str(i) for i, _ in failed))
        print("  повторить: --only-id <id>")
    if dirty:
        print(f"остались имперские меры ({len(dirty)}):")
        for rid, markers in dirty:
            print(f"  id={rid}: {', '.join(markers)}")
    if not failed and not dirty:
        print("имперских мер не осталось, ошибок нет")


if __name__ == "__main__":
    asyncio.run(main())
