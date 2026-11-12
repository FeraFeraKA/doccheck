# Карта репозитория DocCheck

Снимок для NRT-105 на 12 ноября 2026 года, базовый коммит `14c2185467707726641b67ca22566fe8c5eb5552`. Карта описывает файлы этой ревизии; последующие изменения и код в других ветках в неё не входят.

В репозитории есть frontend-каркас со стартовой страницей, тестами и CI. Реализация backend, HTTP API, worker и модуля обработки Семёна в этой ревизии отсутствует. Единый машинный контракт ещё не зафиксирован. Планируемое устройство описано в [архитектуре](../architecture.md), текущий этап — в [корневом README](../../README.md).

## Каталоги и документы

| Путь | Что находится в проверенной версии |
| --- | --- |
| [frontend/](../../frontend/) | React/TypeScript-приложение на Vite, настройки pnpm, исходники и тесты. Установка и запуск — в [README](../../frontend/README.md). |
| [backend/](../../backend/) | [Описание будущих модулей](../../backend/README.md), [правила backend](../../backend/AGENTS.md) и [правила тестов](../../backend/tests/AGENTS.md). Исполняемого Python-кода, API-маршрутов, worker, миграций и backend-тестов пока нет. |
| [contracts/](../../contracts/) | Только [README о статусе контракта](../../contracts/README.md). JSON Schema, Pydantic-модели и общие типы результата здесь ещё не размещены. |
| [docs/](../) | [Целевая архитектура](../architecture.md), [режим данных](../data-policy.md), материалы кейса, инструкции и отчёты агентов. |
| [docs/case/](../case/) | [Формулировка кейса](../case/Case_Track_5.docx) и [разрешённый комплект примеров](../case/examples/). Ограничения использования определяет режим данных; независимый эталон в комплект не входит. |
| [docs/agents/](./) | [Датированный контекст проекта](project-context-2026-11-12.docx), инструкции [ревьюера](reviewer.md), [тестировщика](tester.md) и [ночных агентов](nightly/README.md). Гипотезы и планы контекстного документа не подтверждают наличие реализации. |
| [docs/nightly/](../nightly/) | [Порядок запуска для людей](../nightly/README.md), инструкции [первому участнику](../nightly/first-person.md) и [worker-b на macOS](../nightly/second-person.md). |
| [docs/agent-runs/](../agent-runs/) | Краткие отчёты о выполненных задачах, проверках и ограничениях. |
| [.github/workflows/](../../.github/workflows/) | [Frontend checks](../../.github/workflows/frontend.yml): установка зависимостей, проверка типов, тесты, сборка и браузерная проверка. |

`data/` предназначен для локальных файлов и исключён из Git. Его нет в дереве проверенного коммита; порядок создания и ограничения описаны в [режиме данных](../data-policy.md) и [.gitignore](../../.gitignore). Секреты, OCR-текст, реальные результаты и независимые ожидаемые ответы в карту не включаются.

## Инструкции перед работой

Начать с [AGENTS.md](../../AGENTS.md), [CONTRIBUTING.md](../../CONTRIBUTING.md) и актуальной задачи в Linear. Для затронутого направления прочитать [frontend/AGENTS.md](../../frontend/AGENTS.md) или [backend/AGENTS.md](../../backend/AGENTS.md), для тестов — [frontend/tests/AGENTS.md](../../frontend/tests/AGENTS.md) или [backend/tests/AGENTS.md](../../backend/tests/AGENTS.md).

Ночной запуск регулируют [README](nightly/README.md), [протокол сообщений](nightly/protocol.md), инструкции [координатора](nightly/coordinator.md) и [рабочего агента](nightly/worker.md). Подготовка Mac описана в [macos.md](nightly/macos.md). Назначения и сроки поступают через NRT-90; сам каталог инструкций не доказывает работу расписания.

## Точки входа и границы реализации

- [frontend/index.html](../../frontend/index.html) загружает [src/app/main.tsx](../../frontend/src/app/main.tsx), где создаются React root и BrowserRouter. [App.tsx](../../frontend/src/app/App.tsx) задаёт единственный маршрут `/` со [стартовой страницей](../../frontend/src/pages/home/HomePage.tsx).
- [src/app/styles.css](../../frontend/src/app/styles.css) содержит общие стили. [shared/lib/classes.ts](../../frontend/src/shared/lib/classes.ts) объединяет классы; [shared/api/requestJson.ts](../../frontend/src/shared/api/requestJson.ts) оборачивает `fetch` и HTTP-ошибки. Тип `T` не проверяет JSON во время выполнения; наличие обёртки не означает подключения к работающему API.
- Команды и версии зависимостей закреплены в [package.json](../../frontend/package.json), [pnpm-lock.yaml](../../frontend/pnpm-lock.yaml) и [.node-version](../../frontend/.node-version); настройки сборки и Vitest — в [vite.config.ts](../../frontend/vite.config.ts).
- Backend-точек входа, исполняемого `process_package`, OCR/парсеров и адаптера модуля Семёна в этой ревизии нет. [backend/README.md](../../backend/README.md) и [backend/AGENTS.md](../../backend/AGENTS.md) описывают будущие границы и необходимость проверки фактического модуля; они не подтверждают его интерфейс или доступность вне этой ветки. Docker Compose и команды запуска backend также отсутствуют.

## Проверки

| Область | Где смотреть |
| --- | --- |
| Unit | [classes.test.ts](../../frontend/tests/unit/classes.test.ts), [requestJson.test.ts](../../frontend/tests/unit/requestJson.test.ts). |
| Компоненты и стартовый маршрут | [app.test.tsx](../../frontend/tests/integration/app.test.tsx), общее окружение [setup.ts](../../frontend/tests/setup.ts). |
| Браузерная проверка | [smoke.spec.ts](../../frontend/tests/e2e/smoke.spec.ts), [playwright.config.ts](../../frontend/playwright.config.ts). |
| Автоматические проверки | [.github/workflows/frontend.yml](../../.github/workflows/frontend.yml) запускается по push, pull request и вручную. |

Команды из каталога `frontend`: `pnpm typecheck`, `pnpm test`, `pnpm build`, `pnpm test:e2e`; установка зависимостей и Chromium описана в [frontend/README.md](../../frontend/README.md). Это проверки каркаса и HTTP-обёртки с подменой запросов, а не реальной обработки документов. Наличие тестов и workflow не подтверждает их успешный запуск на произвольном коммите. Реализованных backend-тестов в этой версии нет.

## Статус контракта

По [contracts/README.md](../../contracts/README.md), присланные JSON Schema 0.1, `synthetic_result.json` и `acceptance_scenarios.json` остаются материалами для рассмотрения. В проверенном дереве они не импортированы; утверждённой схемы и реализации общего контракта нет. Агенты могут подготовить единый версионированный технический контракт с независимым ревью для ночной ветки, а человеческая приёмка остаётся владельцам обработки и интеграции.

Уже записанные принципы: точные расчёты в Python, деньги в JSON строками, неизвестное значение отдельно от нуля, статус показателя отдельно от состояния задания и ошибок файла, адресные источники результата. Планируемые FastAPI, PostgreSQL и отдельный worker из [архитектуры](../architecture.md) не следует считать готовым сквозным процессом.
