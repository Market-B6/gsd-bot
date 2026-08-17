"""Seed the recipe base. Idempotent — safe to run on every deploy.

Usage (inside the app container):
    docker compose exec app python -m scripts.seed_db
"""
import asyncio

from app.database import AsyncSessionLocal
from app.services.recipes import seed_recipes


async def main() -> None:
    async with AsyncSessionLocal() as session:
        inserted = await seed_recipes(session)
        await session.commit()
    if inserted:
        print(f"Seeded {inserted} recipes.")
    else:
        print("Recipes already present — nothing to do.")


if __name__ == "__main__":
    asyncio.run(main())
