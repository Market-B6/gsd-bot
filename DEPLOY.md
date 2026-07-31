# Инструкция по деплою GSD Bot

## Вариант 1: На сервере с Docker (рекомендуется)

### 1. Подключиться к серверу в Москве
```bash
ssh user@your-moscow-server
```

### 2. Установить Docker (если нет)
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# Перелогиниться
```

### 3. Скопировать проект на сервер
```bash
# С локальной машины:
cd "/Users/andreykhomenkov/Desktop/Проект Ани"
scp -r gsd-bot user@your-moscow-server:~/
```

### 4. Запустить на сервере
```bash
cd ~/gsd-bot
docker compose up -d

# Проверить логи
docker compose logs -f app
```

## Вариант 2: Локально без Docker

Требуется установить PostgreSQL и Redis локально, затем:

```bash
cd "/Users/andreykhomenkov/Desktop/Проект Ани/gsd-bot"

# Настроить .env для локальных подключений
# DATABASE_URL=postgresql://user:pass@localhost:5432/gsd_db
# REDIS_URL=redis://localhost:6379/0

# Установить зависимости
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Запустить
uvicorn app.main:app --reload
```

## Проверка работы

После запуска:
1. Открыть Telegram
2. Найти бота @glukomama_bot
3. Написать `/start`
4. Протестировать запись еды и замера

## Что делать если бот не отвечает:

```bash
# Проверить логи контейнера
docker compose logs app

# Проверить что все контейнеры запущены
docker compose ps

# Перезапустить
docker compose restart app
```

## Быстрый тест без установки

Бот уже настроен с токеном. Просто запусти на любом сервере с Docker:

```bash
git clone <repo-url>  # или скопируй папку gsd-bot
cd gsd-bot
docker compose up -d
```

Токен уже в `.env`, база поднимется автоматически.
