# NRT-95 — локальный запуск v3.2 через сайт на Windows

[NRT-95](https://linear.app/andreiakimov/issue/NRT-95/podklyuchit-ml-adapter-k-worker-i-sohraneniyu-rezultata) · [NRT-43](https://linear.app/andreiakimov/issue/NRT-43/skvoznaya-integraciya-i-knopka-demo)

По постановке Linear на 14.11.2026 воркер забирает сохранённый пакет из
PostgreSQL, вызывает адаптер вне HTTP-запроса и сохраняет итог со значениями
и источниками, пригодными для API. Статус задания отделён от статусов
показателей, сбой обработки не выдаётся за успешный результат. Реальная
проверка проводится отдельно от прогонов с подменой; браузерный сценарий
относится к NRT-43.

## Запуск

Из корня репозитория с адаптером нужны PowerShell 7, `uv`, Node.js с `npm`,
бинарные файлы PostgreSQL 18 и установленная локально модель
`qwen3.5:4b-q4_K_M`. Если путь к PostgreSQL отличается от стандартного,
передайте `-PostgresBin` командам `database` и `stop-database`.

Откройте отдельные терминалы и выполните команды в таком порядке:

1. `pwsh -NoProfile -File scripts/run-v32-local.ps1 -Component database`
2. `pwsh -NoProfile -File scripts/run-v32-local.ps1 -Component ollama`
3. `pwsh -NoProfile -File scripts/run-v32-local.ps1 -Component api`
4. `pwsh -NoProfile -File scripts/run-v32-local.ps1 -Component worker`
5. `pwsh -NoProfile -File scripts/run-v32-local.ps1 -Component site`

Команда `ollama` по умолчанию использует уже подготовленный комплект в
`$env:TEMP/doccheck-v32-ollama-04016`. Если он лежит в другом месте,
передайте `-OllamaDirectory` с путём к папке с `ollama.exe` и `models/`.
Или запустите свою Ollama по [инструкции v3.2](../../bench/e2e_v32_20261114/README.md)
на `127.0.0.1:11438`. Воркера интересует точная версия весов, закреплённая
в v3.2.

Откройте [сайт](http://127.0.0.1:8080/), добавьте синтетические КФЗ XLSX и
акт DOCX и запустите проверку. Сайт проксирует API на `127.0.0.1:8000`.
Для API и воркера используются одна БД и одна папка пакетов. На PostgreSQL
порту 15432 создаётся отдельный кластер с локальным случайным паролем,
общий экземпляр PostgreSQL не используется. Кластер, пароль и оригиналы
остаются в локальном каталоге `data/v32-local-15432`.

Чтобы остановить API, сайт, воркер и Ollama, нажмите Ctrl+C в их терминалах.
Для БД выполните `pwsh -NoProfile -File scripts/run-v32-local.ps1 -Component stop-database`.
При изменении `-DatabasePort` передайте то же значение командам
`database`, `api`, `worker` и `stop-database`. Аналогично, `-ApiPort`
должен совпадать для `api` и `site`.

## Проверено

На Windows 11, Python 3.12, PostgreSQL 18.4 и Ollama 0.40.16 выполнены
две разные синтетические загрузки из браузера в локальный API. Время
работы воркера в PostgreSQL составило 5,58 с и 2,53 с. Локальная Ollama
вернула HTTP 200 на два вызова `/api/chat` за 5,03 с и 2,30 с. Оба
задания сохранили результат; точная контрольная сумма модели совпала.
