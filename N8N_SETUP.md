# Настройка n8n для GSD-бота

n8n централизует всю AI-обработку и часть напоминаний. Бот шлёт в n8n
webhook `POST /gsd-ai` с `task_type`, n8n вызывает Claude, возвращает
результат на бот-API `POST /api/v1/ai/callback`.

## 1. Установка n8n

Самый быстрый способ — Docker Compose. Добавьте сервис в
`docker-compose.yml` рядом с ботом:

```yaml
  n8n:
    image: n8nio/n8n:latest
    restart: always
    ports:
      - "5678:5678"
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=admin
      - N8N_BASIC_AUTH_PASSWORD=<STRONG_PASSWORD>
      - N8N_HOST=n8n.your-domain.ru
      - N8N_PROTOCOL=https
      - WEBHOOK_URL=https://n8n.your-domain.ru/
      - GENERIC_TIMEZONE=Europe/Moscow
    volumes:
      - n8n_data:/home/node/.n8n

volumes:
  n8n_data:
```

## 2. Импорт workflow

1. Открыть n8n → Workflows → **Import from file**.
2. Загрузить `n8n/gsd-bot-workflow.json`.
3. Отдельные credentials создавать **не нужно** — узлы «Claude: ...» берут
   ключ vibecode из переменных окружения самого n8n (`$env.VIBECODE_API_KEY`).
   Нужно только прокинуть эти переменные в контейнер n8n (см. п. 4).
4. В настройках Webhook-узла запомнить URL (например `https://n8n.your-domain.ru/webhook/gsd-ai`).

## 3. Переменные окружения бота (.env)

```env
# n8n
N8N_WEBHOOK_URL=https://n8n.your-domain.ru/webhook/gsd-ai
N8N_CALLBACK_TOKEN=<длинная случайная строка, любая>
PUBLIC_BASE_URL=https://api.your-domain.ru  # URL, по которому n8n сможет достучаться до /api/v1/ai/callback

# AI — через vibecode (OpenAI-совместимый шлюз), НЕ прямой ключ Anthropic
VIBECODE_API_KEY=<ключ из ~/.claude/library/secrets/.env>
VIBECODE_BASE_URL=https://vibecode-api.online/v1
AI_MODEL=claude-sonnet-5
AI_MODEL_FALLBACK=claude-haiku-4-5-20251001
```

### Переменные окружения n8n

Те же три AI-переменные надо прокинуть в контейнер n8n, иначе узлы
«Claude: ...» не найдут ключ. В `docker-compose.yml` сервиса n8n:

```yaml
    environment:
      - VIBECODE_API_KEY=${VIBECODE_API_KEY}
      - VIBECODE_BASE_URL=https://vibecode-api.online/v1
      - AI_MODEL=claude-sonnet-5
      - BOT_API_URL=https://api.your-domain.ru
      - N8N_CALLBACK_TOKEN=${N8N_CALLBACK_TOKEN}
      - BOT_TOKEN=${BOT_TOKEN}
```

Проверка ключа одной командой:

```bash
curl -s https://vibecode-api.online/v1/models -H "Authorization: Bearer $VIBECODE_API_KEY" | head -c 300
```

### Про лимиты vibecode

Шлюз иногда отдаёт `429 upstream load ... saturated`. Узлы уже настроены на
3 повтора с паузой 5 секунд, а при финальной ошибке бот получает
`status: failed` и пишет пользователю об ошибке, а не молчит. Если 429
случается часто — переключите `AI_MODEL` на `claude-haiku-4-5-20251001`
(он проходил стабильнее на тестах, и он же прописан в `AI_MODEL_FALLBACK`).

`N8N_CALLBACK_TOKEN` также нужно прописать в n8n — в узлах, которые
делают HTTP-запрос обратно к боту (`POST {callback_url}` с заголовком
`Authorization: Bearer <token>`). Токен уже подставляется автоматически
из payload webhook, но самому n8n нужно знать какое значение прокидывать.

## 4. Что делает workflow

Один webhook, четыре ветки по `task_type`:

| task_type | Что делает |
|---|---|
| `photo_meal` | Клод-Vision получает URL фото → возвращает JSON `{dish, protein_g, fat_g, carb_g, xe, gi, risk_level, advice}` |
| `weekly_analysis` | Клод пишет структурированный анализ дневника за неделю |
| `chat` | Ответ на свободный вопрос про питание/сахар |
| `portion_advice` | Совет по безопасной порции продукта |

После получения ответа от Клода Function-узел парсит JSON и POST-ит на
`{callback_url}` с `{task_id, status, result}`. Бот сохраняет в
`ai_tasks`, форматирует и отправляет пользователю.

## 5. Дополнительные workflow (опционально)

Отдельные cron-workflow в том же n8n:

**Ежедневный дайджест админу (10:00):**
```
Cron 0 10 * * * → HTTP GET {PUBLIC_BASE_URL}/api/v1/internal/admin/digest
  ↳ Telegram send_message → chat_id={admin_tg_id}, text={text}
```

**Утренние напоминания натощак (каждую минуту, отбираем только тех, у кого сейчас 7:30):**
```
Cron * * * * * → HTTP GET {base}/api/v1/internal/users/reminders?kind=fasting
  ↳ Loop → Telegram send_message
```

Это дублирует scheduler бота — можно использовать что-то одно. n8n удобнее для нетехнических правок.

## 6. Проверка

```bash
curl -X POST https://n8n.your-domain.ru/webhook/gsd-ai \
  -H "content-type: application/json" \
  -d '{
    "task_type": "chat",
    "user_id": 1,
    "callback_url": "https://api.your-domain.ru/api/v1/ai/callback",
    "callback_token": "TEST_TOKEN",
    "data": {"question": "Можно ли есть манго при ГСД?", "context": {}}
  }'
```

Ответ должен вернуться в endpoint бота и залогироваться в таблицу `ai_tasks`.

## 7. Безопасность

- `N8N_CALLBACK_TOKEN` — только на сервере, никогда не логировать.
- Endpoint `/api/v1/ai/callback` защищён Bearer-токеном.
- Публичный URL `PUBLIC_BASE_URL` рекомендуется закрыть nginx allow-list
  на IP-адрес n8n, если он в другой сети.
