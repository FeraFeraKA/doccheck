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
