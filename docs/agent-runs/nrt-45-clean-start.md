# NRT-45 — проверка чистого запуска

[Критерии NRT-45](https://linear.app/andreiakimov/issue/NRT-45/proverka-chistogo-zapuska)
и [разъяснения кейса](../case/README.md) сверены 14 ноября 2026 года.
Проверенный кандидат `71827eea222cfef60396ab9fa2016e348e8ac840`. Дерево
`04f42a5d2ce5d4864f58b117757cfc7975f94eb1` совпадает с деревом CI merge
`86297de827a695a9ab9c05ceef67ad6ae03e69b6` для [PR #46](https://github.com/VCyberPunk2077/doccheck/pull/46).
Андрей проводит независимую предметную приёмку.

| Критерий | Результат и недостающая проверка |
| --- | --- |
| Compose с PostgreSQL, миграциями и сценарием | CI создал новые тома, собрал и поднял контейнеры, проверил успешное завершение миграции и синтетический цикл через Chromium. Обычный Compose запускал синтетический worker. Полный сценарий с документным worker и рабочим адаптером ещё не подтверждён. [Compose job](https://github.com/VCyberPunk2077/doccheck/actions/runs/43517413330/job/132202790519) |
| Доступность зависимостей и offline runtime | В новом worktree зависимости установились из прогретых кэшей без загрузок в offline-режиме pnpm и uv. В CI подготовка использовала сеть. Запуск полного контейнерного стека с отключённым внешним доступом предстоит. |
| Оба сценария, evidence, XLSX и перезапуск | CI сохранил синтетический результат после `down` и повторного `up`. Отдельные frontend/backend тесты покрывают адрес источника и XLSX. Два полных пользовательских сценария NRT-48 и их повтор после остановки требуют отдельного прогона. [Frontend](https://github.com/VCyberPunk2077/doccheck/actions/runs/43517413197) · [Backend](https://github.com/VCyberPunk2077/doccheck/actions/runs/43517413013) |
| Среда, время и артефакты | В Compose CI Ubuntu 26.04 / Linux amd64, Engine 29.4.2. `up --build --wait` занял 30 с, повтор без сборки 13 с, синтетический цикл 3,688 с. Docker вывел backend 55,3 MB, frontend 26,2 MB, PostgreSQL 162 MB. Единичный снимок достиг 70,87 MiB для API, 48,07 MiB для worker, 29,55 MiB для БД и 4,816 MiB для frontend при лимите 15,61 GiB. Пиковая память и модель CPU CI ещё не измерены. [Лог Compose](https://github.com/VCyberPunk2077/doccheck/actions/runs/43517413330/job/132202790519) |
| Эталон, сброс кеша и изменение входа | CI проверил исключение закрытых путей и каталога синтетических ожиданий из Docker-контекста. Отдельный сквозной прогон с изменённой входной суммой, проверкой новой дельты и сбросом кэша предстоит. [Шаг проверки контекста](https://github.com/VCyberPunk2077/doccheck/actions/runs/43517413330/job/132202790519#step:6:1) |

## Локальная проверка из чистого worktree

Windows 11 Pro `10.0.22631`, Intel Core i7-12700KF, 20 логических CPU,
31,8 GiB RAM. Worktree начат без `node_modules` и `.venv`. В `frontend/`
прошли `pnpm install --offline --frozen-lockfile` и `pnpm build` с
Node 26.12.1 и pnpm 12.14.0. Три выходных файла `dist` занимают 326 507 байт.
В `backend/` прошли `uv --offline sync --frozen --managed-python` и
`uv --offline run --frozen pytest tests/test_result_contract.py tests/test_public_demo.py -q`,
112 тестов на Python 3.12.12 с uv 0.9.17. Для установки использовались
заранее подготовленные локальные кэши. Из корня прошли `docker compose
config --quiet` и `git check-ignore` для `.env`, `data/`, `holdout/` и
`evaluation/`. Docker daemon на машине недоступен. Локальные контейнеры
и рабочие данные в этом прогоне не использовались.

Облачное демо NRT-108 проверяет встроенный пример и синтетический API,
маршруты рабочих документов там закрыты. [PR #46](https://github.com/VCyberPunk2077/doccheck/pull/46)

Для выпуска выбрать точный релизный SHA и получить готовые инструкции и
оба сценария NRT-48. На машине с Docker отдельно зафиксировать подготовку
образов, старт после отключения внешней сети и замеры памяти в ходе обоих
сценариев. Повторить загрузку с изменённой синтетической суммой и сверить
изменение результата после сброса разрешённого кэша. Предметная приёмка
NRT-45 остаётся открытой до этого прогона.
