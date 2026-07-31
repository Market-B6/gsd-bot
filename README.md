# GSD Diary Bot

Telegram-бот для ведения дневника при гестационном сахарном диабете.

## Быстрый старт

1. Скопируйте `.env.example` в `.env` и заполните переменные:
```bash
cp .env.example .env
```

2. Получите токен бота у [@BotFather](https://t.me/BotFather) и укажите в `BOT_TOKEN`

3. Запустите через Docker:
```bash
docker-compose up -d
```

Бот готов к работе!

## Структура проекта

```
gsd-bot/
├── app/
│   ├── api/          # REST API endpoints
│   ├── bot/          # Telegram bot handlers
│   ├── models/       # SQLAlchemy models
│   ├── services/     # Business logic
│   ├── utils/        # Utilities
│   ├── config.py     # Configuration
│   ├── database.py   # DB setup
│   └── main.py       # FastAPI app
├── migrations/       # Alembic migrations
├── tests/            # Tests
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## API Endpoints

- `GET /` - Health check
- `GET /health` - Status
- `POST /api/v1/meals` - Create meal
- `GET /api/v1/meals/{user_id}` - Get user meals
- `POST /api/v1/glucose` - Create glucose reading
- `GET /api/v1/glucose/{user_id}` - Get user glucose
- `POST /api/v1/insulin` - Create insulin dose
- `GET /api/v1/insulin/{user_id}` - Get user insulin

## Разработка

Локальный запуск без Docker:

```bash
# Install dependencies
pip install -r requirements.txt

# Run Postgres and Redis
docker-compose up postgres redis -d

# Run migrations
alembic upgrade head

# Start app
uvicorn app.main:app --reload
```

## Функционал MVP

- ✅ Регистрация пользователей
- ✅ Запись приёма пищи
- ✅ Автотаймер на 1 час
- ✅ Замер глюкозы (натощак/после еды)
- ✅ Запись инсулина
- ✅ REST API для всех операций
- 🔄 Напоминания (в разработке)
- 🔄 Экспорт в PDF/Excel (в разработке)
- 🔄 Просмотр дневника (в разработке)

## Технологии

- Python 3.11
- FastAPI - async web framework
- aiogram 3 - Telegram bot framework
- PostgreSQL - основная БД
- Redis - FSM storage + кеш
- SQLAlchemy 2.0 - ORM
- Alembic - миграции
- Docker & docker-compose
