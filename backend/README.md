# Python backend

NRT-8 добавляет FastAPI, PostgreSQL и **отдельный Python worker**. Каркас
проверяет жизненный цикл на синтетических заданиях. Документы, OCR и финансовая
сверка здесь не выполняются. [Переданный ML-модуль](ml_module/README.md) остаётся
отдельным пакетом; каркас не устанавливает его зависимости и веса.

## Установка и PostgreSQL

Нужны Python **3.12.12** (`.python-version`), uv **0.9.17** и локальный PostgreSQL
(проверялось с **18.4**). Python при необходимости может загрузить uv. Из `backend/`:

```sh
uv sync --frozen
```

Прямые зависимости закреплены в `pyproject.toml`, полное дерево — в `uv.lock`.
Подготовьте отдельную БД и пользователя PostgreSQL. Например, от имени локального
администратора:

```sh
createuser -h 127.0.0.1 -U postgres --pwprompt doccheck
createdb -h 127.0.0.1 -U postgres --owner=doccheck doccheck
```

Скопируйте корневой `.env.example` в `.env` и замените `CHANGE_ME` локальным
паролем. При необходимости URL-кодируйте пароль. `.env` исключён из Git.
API, worker и Alembic используют этот файл; переменные процесса имеют приоритет.

| Переменная | Назначение |
| --- | --- |
| `DATABASE_URL` | Обязательный URL вида `postgresql+psycopg://user:password@host:port/database` |
| `WORKER_POLL_SECONDS` | Ожидание пустой очереди: по умолчанию `0.5`, от `0.05` до `60` секунд |
| `SYNTHETIC_DELAY_SECONDS` | Искусственная задержка для наблюдения статусов: по умолчанию `2`, от `0` до `60` секунд |

Из `backend/` примените миграцию:

```sh
uv run --frozen alembic upgrade head
```

Она создаёт `synthetic_jobs` и служебную `alembic_version` в выбранной БД.
Повторное применение сохраняет задания. API не меняет схему при запуске:
`/health` вернёт 503, если PostgreSQL или таблица заданий недоступны.

## Запуск

API и worker запускаются в **разных терминалах** из `backend/`:

```sh
uv run --frozen uvicorn doccheck_backend.api:app --host 127.0.0.1 --port 8000
```

```sh
uv run --frozen python -m doccheck_backend.worker
```

В третьем терминале, из `frontend/`:

```sh
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1
```

Откройте адрес Vite и нажмите «Создать синтетическое задание». Без worker оно
останется в очереди. При запущенном worker UI покажет `queued → processing →
completed` и тестовый результат. Vite направляет `/health` и `/api` на порт
8000; другую цель задаёт `DOCCHECK_API_TARGET` (см. [frontend README](../frontend/README.md)).
Компоненты останавливаются по Ctrl+C; задания сохраняются в PostgreSQL.

Чтобы обработать не более одного задания и выйти:

```sh
uv run --frozen python -m doccheck_backend.worker --once
```

Один worker обрабатывает задания последовательно. Короткая транзакция с
`FOR UPDATE SKIP LOCKED` резервирует задание и сохраняет `processing`. Обработка
идёт после её завершения, а `completed` записывается вместе с результатом.
Синхронные маршруты FastAPI выполняют только короткие операции БД.

## Синтетический HTTP-интерфейс 0.1.0

Это интерфейс каркаса, общий контракт NRT-13 определит маршруты реальной
сверки. Источник DTO — `src/doccheck_backend/schemas.py`, OpenAPI доступен в
`/openapi.json` и `/docs`.

| Запрос | Ответ |
| --- | --- |
| `GET /health` | 200: `status: ok`, `database: ok`; 503 при недоступной БД или схеме |
| `POST /api/synthetic-jobs` без тела | 201: созданное синтетическое задание в `queued` |
| `GET /api/synthetic-jobs/{UUID}` | 200: задание; 404 для неизвестного ID, 422 для неверного UUID |

Задание содержит UUID, `synthetic: true`, статус, время создания/начала/окончания,
`result` и `error`. До обработки результат равен `null`. Синтетический
результат явно помечен, а сбой обработки даёт `failed` с безопасным кодом.

## Проверки и ограничения

```sh
uv run --frozen ruff check src migrations tests
uv run --frozen ruff format --check src migrations tests
uv run --frozen pytest
```

Задайте `DOCCHECK_TEST_DATABASE_URL` отдельной тестовой БД PostgreSQL:
[tests/README.md](tests/README.md). Без этой настройки проверки БД пропускаются.
CI `backend.yml` предоставляет PostgreSQL и запускает HTTP API и worker как
разные процессы. ML-тесты остаются в своём workflow.

После аварийной остановки worker или потери БД при записи задание может
остаться в `processing`. Восстановление относится к NRT-98, Docker Compose —
к NRT-41. Каркас предназначен для локального запуска и не принимает документы.
