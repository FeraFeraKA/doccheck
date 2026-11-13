# Карта репозитория DocCheck

Проверено на `208fdf7df8387cb5b5127ec0ac8f05c41527c7bf` от 13 ноября 2026 года.
Для работы в другой ветке сначала сверьте `git rev-parse HEAD` и доступность
нужных путей в этом коммите.

## Перед работой

- Прочитайте [AGENTS.md](../../AGENTS.md), [README](../../README.md),
  [CONTRIBUTING](../../CONTRIBUTING.md) и актуальную задачу Linear. Следуйте
  вложенным правилам [frontend](../../frontend/AGENTS.md),
  [backend](../../backend/AGENTS.md) и тестов
  [frontend](../../frontend/tests/AGENTS.md) и [backend](../../backend/tests/AGENTS.md).
- Сверяйте продуктовые требования по [кейсу](../case/README.md) и текущей задаче.
  [Контекст от 12 ноября](project-context-2026-11-12.docx) содержит планы и гипотезы.
  [Режим данных](../data-policy.md) определяет условия доступа к примерам и публикации.
- Для работы в двух чатах используйте [порядок исполнителя и ревьюера](two-chat/README.md).
  Есть отдельные инструкции [ревьюеру](reviewer.md), [тестировщику](tester.md)
  и [ночной очереди](nightly/README.md).

## Точки входа

| Область | Где начать |
| --- | --- |
| Запуск | [compose.yaml](../../compose.yaml), [архитектура](../architecture.md), [инструкции backend](../../backend/README.md) и [frontend](../../frontend/README.md). |
| Frontend | [main.tsx](../../frontend/src/app/main.tsx) создаёт приложение и роутер, [App.tsx](../../frontend/src/app/App.tsx) задаёт маршруты. [Экран проверок](../../frontend/src/pages/checks/) содержит мастер, историю и детали. [runStatusApi.ts](../../frontend/src/pages/checks/runStatusApi.ts) читает историю и опрашивает состояние, [requestJson.ts](../../frontend/src/shared/api/requestJson.ts) обслуживает HTTP. |
| HTTP и хранение | [api.py](../../backend/src/doccheck_backend/api.py) регистрирует маршруты FastAPI. [uploads.py](../../backend/src/doccheck_backend/uploads.py) сохраняет пакет. [run_reads.py](../../backend/src/doccheck_backend/run_reads.py) выдаёт историю, состояние, результат, документы и фрагменты. Схема PostgreSQL в [models.py](../../backend/src/doccheck_backend/models.py) и [миграциях Alembic](../../backend/migrations/versions/). |
| Worker | [worker.py](../../backend/src/doccheck_backend/worker.py) обслуживает синтетические задания каркаса. [run_worker.py](../../backend/src/doccheck_backend/run_worker.py) обслуживает сохранённые пакеты и требует явно выбранный локальный обработчик. |
| Контракт | [OpenAPI v0](../../contracts/doccheck-api.v0.openapi.yaml) описывает HTTP. [Pydantic-модели](../../backend/src/doccheck_backend/contracts/) задают результат и адреса источников. [README контракта](../../contracts/README.md) связывает их с версионированной JSON Schema и синтетическим примером. |
| Модуль обработки | [backend/ml_module/README.md](../../backend/ml_module/README.md) описывает Python-модуль реквизитов и Qwen-reader. Источники и ограничения проверяйте по документации модуля и согласованной задаче Семёна. |
| Тесты и CI | [Тесты frontend](../../frontend/tests/), [тесты backend](../../backend/tests/) и [GitHub Actions](../../.github/workflows/). Доступный сценарий и его зависимости смотрите в [frontend README](../../frontend/README.md) и [руководстве тестов backend](../../backend/tests/README.md). Отчёты о конкретных прогонах лежат в [docs/agent-runs/](../agent-runs/). |

На этой версии браузер читает сохранённые задания и их состояния, а результат
сверки доступен в отдельном синтетическом примере. Мастер выбора файлов ещё
не отправляет пакет. Подключение сохранённого результата, просмотр источников
и экспорт из интерфейса идут отдельными задачами. Compose запускает
синтетический worker. Штатный адаптер обработки пакета и полный проход с OCR
и финансовой сверкой ещё не подключены.

## Поиск в своей версии

Из корня worktree используйте целевые каталоги с кодом и инструкциями.
`git ls-tree` показывает пути в заданном коммите, `git grep` возвращает
`коммит:файл:строка`. `rg` читает текущие файлы и подходит для незакоммиченных
изменений. Сохраняйте SHA, путь и номер строки при передаче результата.

```powershell
$rev = git rev-parse HEAD
git ls-tree -r --name-only $rev frontend/src/pages/checks backend/src/doccheck_backend
git grep -InE -e 'pollRun|next_cursor' $rev -- frontend/src/pages/checks
rg --no-config -n 'pollRun|next_cursor' frontend/src/pages/checks
```

Открывайте нужный источник и соседние строки. Для поиска по смыслу начните с
названия компонента в карте, затем ищите русский термин или идентификатор.
При обновлении кода сверяйте ссылки карты с новым деревом и указывайте новую
проверенную версию. Поиск читает дерево или файлы на месте. Сборки индекса нет.
Выборка ограничивается разрешёнными исходниками и текстовыми инструкциями.
Объём обязательного чтения, включая примеры для затронутых изменений,
задаётся AGENTS.md и режимом данных.

[Как воспроизвести оценку поиска](../agent-runs/nrt-103.md).
