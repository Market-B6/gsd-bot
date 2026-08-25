#!/usr/bin/env python3
"""Добор фото рецептов, утерянных вместе со слоем контейнера.

Spoonacular отдаёт картинки статикой по предсказуемому URL, поиск не вызывается,
поэтому квота API не тратится. ID источника берём из маркера spoon:<id> в tags —
том же, по которому импортёр ищет дубли.

Имя файла — Spoonacular-id, как это делал импортёр, чтобы уже записанные
в БД значения photo_url остались валидными.

Запуск изнутри контейнера:
    docker compose exec app python3 /app/scripts/backfill_photos.py --dry-run
    docker compose exec app python3 /app/scripts/backfill_photos.py
"""
import argparse
import asyncio
import os
import re
import sys

import httpx
from sqlalchemy import select

sys.path.insert(0, "/app")
from app.database import AsyncSessionLocal
from app.models import Recipe

MEDIA_DIR = "/app/media/recipes"
# Размеры, которые Spoonacular отдаёт для карточек; пробуем по порядку.
URL_TEMPLATES = (
    "https://img.spoonacular.com/recipes/{sid}-636x393.jpg",
    "https://img.spoonacular.com/recipes/{sid}-556x370.jpg",
    "https://img.spoonacular.com/recipes/{sid}-480x360.jpg",
)
CONCURRENCY = 5


def spoon_id(tags: str | None) -> str | None:
    m = re.search(r"spoon:(\d+)", tags or "")
    return m.group(1) if m else None


async def fetch_one(client: httpx.AsyncClient, sid: str) -> bytes | None:
    """Пробует шаблоны URL по очереди, возвращает первое удавшееся тело."""
    for url in URL_TEMPLATES:
        try:
            r = await client.get(url.format(sid=sid), timeout=30)
        except Exception:
            continue
        if r.status_code == 200 and r.content:
            return r.content
    return None


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="не скачивать, только отчёт")
    ap.add_argument("--limit", type=int, help="обработать только N рецептов")
    args = ap.parse_args()

    os.makedirs(MEDIA_DIR, exist_ok=True)

    async with AsyncSessionLocal() as s:
        recipes = list((await s.execute(select(Recipe).order_by(Recipe.id))).scalars().all())
    if args.limit:
        recipes = recipes[: args.limit]

    todo: list[tuple[int, str, str]] = []   # (db_id, spoon_id, path)
    have = 0
    no_marker: list[int] = []

    for rec in recipes:
        sid = spoon_id(rec.tags)
        if not sid:
            no_marker.append(rec.id)
            continue
        path = os.path.join(MEDIA_DIR, f"{sid}.jpg")
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            have += 1
            continue
        todo.append((rec.id, sid, path))

    print(f"Всего рецептов: {len(recipes)}")
    print(f"Фото уже на диске: {have}")
    print(f"Нужно скачать: {len(todo)}")
    if no_marker:
        print(f"Без маркера spoon: (фото взять негде): {len(no_marker)} — id {no_marker[:10]}")
    if args.dry_run:
        print("\nРЕЖИМ: dry-run, ничего не качаем")
        return
    if not todo:
        print("Качать нечего.")
        return

    ok = 0
    failed: list[int] = []
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        async def work(db_id: int, sid: str, path: str) -> None:
            nonlocal ok
            async with sem:
                body = await fetch_one(client, sid)
            if not body:
                failed.append(db_id)
                print(f"  ! id={db_id} spoon:{sid} — не скачалось")
                return
            # временный файл + rename: не оставляем битых половинок
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, path)
            ok += 1
            print(f"  + id={db_id} spoon:{sid} — {len(body) // 1024} КБ")

        await asyncio.gather(*(work(d, s_, p) for d, s_, p in todo))

    # photo_url мог быть пустым — проставляем всем, у кого файл теперь есть
    fixed = 0
    async with AsyncSessionLocal() as s:
        for db_id, sid, path in todo:
            if not os.path.isfile(path):
                continue
            rec = await s.get(Recipe, db_id)
            if rec and rec.photo_url != path:
                rec.photo_url = path
                fixed += 1
        await s.commit()

    print(f"\n=== ИТОГО ===")
    print(f"скачано: {ok}")
    print(f"photo_url обновлён: {fixed}")
    if failed:
        print(f"не скачалось ({len(failed)}): {failed}")


if __name__ == "__main__":
    asyncio.run(main())
