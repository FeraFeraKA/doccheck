# NRT-49 — короткие проверки CI

[Задача Linear](https://linear.app/andreiakimov/issue/NRT-49/ci-korotkie-proverki-kontrakta-logiki-i-sborki)
прочитана 13 ноября 2026 года. Каркас NRT-8 и контракт NRT-13 доступны в main.

- Frontend CI запускает закреплённый Oxlint 1.93.0 с плагинами TypeScript и
  React. Исправлены обнаруженные диагностикой постоянное условие теста
  и синхронное обновление статуса внутри эффекта проверки API.
- Backend CI использует закреплённый jsonschema 4.26.0. Тесты Draft 2020-12
  входят в обычный pytest и завершаются ошибкой при отсутствии зависимости.
- Node 26.12.1 и pnpm 12.14.0. Прошли frozen install, lint, typecheck,
  13 тестов Vitest, сборка и 2 сценария Playwright. Временный компонент
  с двумя свойствами id отклонён правилом react(jsx-no-duplicate-props).
  После его удаления lint прошёл.
- Ruff check, Ruff format check, 102 теста контракта и git diff --check прошли.
  GitHub Actions проверяется на PR. Проверки используют синтетические данные.

После [независимого ревью](https://github.com/VCyberPunk2077/doccheck/pull/25#issuecomment-6862157085)
команда воспроизведения использует версию `jsonschema` из `backend/uv.lock`.
Backend CI отдельно валидирует OpenAPI NRT-13 с `openapi-spec-validator` 0.7.2
и проверяет разрешение ссылок на схемы. На Python 3.12.12 исходный OpenAPI
прошёл валидацию. Валидатор отклонил копию со ссылкой на отсутствующий файл
и копию со ссылкой на отсутствующее определение в `$defs` существующей схемы.
Повторный запуск штатных тестов контракта прошёл, 102 теста. Проверка
OpenAPI статическая. Запуск CI для актуальной пары base/head предстоит.

## Проверки после обновления базы

На базе `3b199025ffa678c7d41fe74950f855b91f36ada7` проверено дерево
`df2e1f06c0a0b644aff45fc0dc46f80f8d92dfd4`. После объединения lockfile
сохранены все 35 версий пакетов из базы, включая `python-multipart` 0.0.33.
`openapi-spec-validator` 0.7.2 с его зависимостями и `jsonschema` 4.26.0
устанавливаются из общего `backend/uv.lock`, `uv lock --check` прошёл.

- На Python 3.12.12 прошли `uv sync --frozen --managed-python`, Ruff check
  и Ruff format check. `uv run --frozen openapi-spec-validator
  ../contracts/doccheck-api.v0.openapi.yaml` принял контракт. Две копии
  с отсутствующим файлом схемы и отсутствующим определением отклонены.
- На отдельном PostgreSQL 18.4 прошли 124 теста командой `uv run --frozen
  pytest tests --ignore=tests/ml_module -q`. TestClient выдал предупреждение
  Starlette об устаревшей поддержке `httpx`.
- На Node 26.12.1 и pnpm 12.14.0 прошли `pnpm install --frozen-lockfile`,
  `pnpm lint`, `pnpm typecheck`, `pnpm test` (13 тестов) и `pnpm build`.
  Контрольный TSX с дублирующимся `id` отклонён правилом
  `react(jsx-no-duplicate-props)`. После удаления файла линтер прошёл.
- `docker compose config --quiet` и `git diff --check` прошли.
  Docker daemon локально недоступен. Локальный Playwright ждёт
  освобождения порта 4173. GitHub Actions проверяется после публикации.
