# DocCheck

**[Открыть DocCheck онлайн](https://responses-determined-prison-utilities.trycloudflare.com/checks/new)**

DocCheck помогает бухгалтеру сверять карточку фактических затрат (КФЗ) с первичными документами. В результате видны суммы по статьям, расхождения и ссылки на источники.

Проект команды «Буткемперы», хакатон МФТИ, трек 5.

## Запуск DocCheck с моделью через Docker Compose

Нужны Git, Docker с Linux-контейнерами, Docker Compose 2.30 или новее и видеокарта NVIDIA, доступная контейнерам. На Windows используйте Docker Desktop с WSL 2. При первом запуске Docker скачает образы, базу Qwen и адаптер LoRA. [Требования и подготовка весов](docs/docker.md)

```sh
git clone https://github.com/VCyberPunk2077/doccheck.git
cd doccheck
```

Если файла `.env` ещё нет, скопируйте в него `.env.example`. В Linux и macOS выполните `cp .env.example .env`, в PowerShell — `Copy-Item .env.example .env`. Задайте в `.env` пароль `DOCCHECK_DB_PASSWORD` из случайных латинских букв и цифр.

```sh
docker compose -f compose.yaml -f compose.gpu.yaml up --build --wait --wait-timeout 1800
```

После успешного запуска откройте [DocCheck](http://127.0.0.1:8080), загрузите КФЗ и первичные документы и нажмите «Запустить проверку». В результате доступны источники, оригиналы и отчёт XLSX. Если порт занят, измените `DOCCHECK_PORT` в `.env`.

Чтобы остановить сервисы и сохранить файлы, историю и веса, выполните `docker compose -f compose.yaml -f compose.gpu.yaml down`.

## Документация

- [Как проходит сверка](docs/case/README.md)
- [Как показать DocCheck](docs/demo-runbook.md)
- [Два учебных сценария](docs/case/use-cases.md)
- [План пилота в вузе](docs/pilot-roadmap.md)
- [Архитектура](docs/architecture.md), [контракты](contracts/README.md), [работа с данными](docs/data-policy.md) и [участие в разработке](CONTRIBUTING.md)
