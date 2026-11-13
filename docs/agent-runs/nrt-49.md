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
