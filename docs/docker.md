# Локальный запуск DocCheck через Docker Compose и NVIDIA GPU

Нужны Docker с контейнерами Linux x86-64, Docker Compose 2.30 или новее и
доступная контейнерам видеокарта NVIDIA. На Windows нужен Docker Desktop
с WSL 2 и драйвером NVIDIA. На Linux нужен NVIDIA Container Toolkit.
Для первой сборки и подготовки модели нужен доступ к реестрам.

- [Поддержка GPU в Docker Desktop](https://docs.docker.com/desktop/features/gpu/)
- [Настройка NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)

Скопируйте `.env.example` в `.env` в корне репозитория. Задайте
`DOCCHECK_DB_PASSWORD` случайной строкой из 32 шестнадцатеричных символов.
Если порт 8080 занят, укажите свободный `DOCCHECK_PORT` в `.env`.

```sh
docker compose -f compose.yaml -f compose.gpu.yaml up --build --wait --wait-timeout 1800
```

Откройте [мастер загрузки](http://127.0.0.1:8080) и добавьте КФЗ и первичные
документы. Нажмите «Запустить проверку» после сообщения «Пакет загружен».
Откройте завершённое задание в очереди. Результат и выгрузка XLSX доступны
из карточки проверки.

Compose ждёт готовности PostgreSQL и применяет миграции. Сервис
`model-prepare` скачивает базовую модель `qwen3.5:4b-q4_K_M` в том
`ollama-models`, если весов ещё нет. Размер весов вместе с визуальным
проектором — около 3,3 ГБ. Сервис `model-ready` сверяет полный SHA-256
манифеста и проверяет, что Ollama 0.40.16 (MIT) загрузила модель целиком на GPU.
После этих проверок запускаются обработчик документов, API и интерфейс.

Контейнер Ollama обслуживает worker во внутренней сети Compose.
Порт модели не опубликован, облачные возможности Ollama отключены.
Для подготовки весов используется отдельный контейнер с сетевым доступом.
Worker и модель работают без доступа к внешней сети. Используются базовые
веса Qwen (Apache 2.0). Для этого сценария установка Ollama на хост и
отдельный LoRA-адаптер не требуются.

## Диагностика и перезапуск

```sh
docker compose -f compose.yaml -f compose.gpu.yaml ps -a
docker compose -f compose.yaml -f compose.gpu.yaml logs --tail=100 model-prepare model model-ready document-worker
docker compose -f compose.yaml -f compose.gpu.yaml exec model ollama ps
```

`model-prepare`, `model-ready` и `migrate` — одноразовые сервисы.
После успешного выполнения они имеют состояние `Exited (0)`.
Ошибка подготовки весов, несовпадение SHA-256 или нехватка видеопамяти
останавливают запуск рабочего контура. Если модель становится недоступна
во время работы, задание получает ошибку `v32_model_unavailable`.

```sh
docker compose -f compose.yaml -f compose.gpu.yaml down
docker compose -f compose.yaml -f compose.gpu.yaml up --wait --wait-timeout 1800
```

Обычный `down` сохраняет тома `postgres-data` (задания и результаты),
`run-files` (оригиналы) и `ollama-models` (веса). Флаг `--volumes`
удаляет эти данные. Пароль базы задаётся при создании тома, поэтому
изменение `.env` само по себе не меняет пароль в существующей базе.

## Границы обработки

Для поддерживаемого XLSX КФЗ и читаемых первичных документов адаптер v3.2
показывает подтверждённые источниками значения. При неизвестной полноте
комплекта показатель остаётся «Не проверен», даже если есть частичная
сумма. Для растровой КФЗ нужно подтвердить договор, период, строку и
денежные ячейки на оригинале. Без такого подтверждения адаптер завершает
задание с ошибкой чтения или подтверждения скана.
