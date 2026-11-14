# DocCheck

DocCheck помогает бухгалтеру сверять карточку фактических затрат (КФЗ) с первичными документами. В результате видны суммы по статьям, расхождения и ссылки на источники.

Проект команды «Буткемперы», хакатон МФТИ, трек 5.

## Запуск каркаса через Docker Compose

Нужны Git, запущенный Docker с Linux-контейнерами и Docker Compose с поддержкой `up --wait`. Первая сборка скачивает образы и зависимости.

```sh
git clone https://github.com/VCyberPunk2077/doccheck.git
cd doccheck
```

Если файла `.env` ещё нет, скопируйте в него `.env.example`. В Linux и macOS выполните `cp .env.example .env`, в PowerShell — `Copy-Item .env.example .env`. Задайте в `.env` пароль `DOCCHECK_DB_PASSWORD` из случайных латинских букв и цифр.

```sh
docker compose up --build --wait
```

Откройте [DocCheck](http://127.0.0.1:8080) или [готовый учебный пример](http://127.0.0.1:8080/checks/synthetic-example) без загрузки файлов. Доступность API и базы проверяет [`/health`](http://127.0.0.1:8080/health). Если порт занят, измените `DOCCHECK_PORT` в `.env`. При остановке командой `docker compose down` файлы и история сохраняются.

## Текущий этап

При обычном запуске загруженные пакеты после нажатия «Запустить проверку» ждут обработчик в очереди. Для сверки своих документов нужен Docker Compose 2.30 или новее и доступный контейнерам NVIDIA GPU. Подготовьте `.env` по инструкции выше и выполните из корня репозитория:

```sh
docker compose -f compose.yaml -f compose.gpu.yaml up --build --wait --wait-timeout 1800
```

После подготовки модели откройте DocCheck и запустите проверку. В сохранённом результате доступны источники, оригиналы и отчёт XLSX. [Требования и подготовка весов](docs/docker.md)

## Документация

- [Как проходит сверка](docs/case/README.md)
- [Демо и запуск без Docker](docs/demo-runbook.md)
- [Два учебных сценария](docs/case/use-cases.md)
- [План пилота в вузе](docs/pilot-roadmap.md)
- [Архитектура](docs/architecture.md), [контракты](contracts/README.md), [работа с данными](docs/data-policy.md) и [участие в разработке](CONTRIBUTING.md)
