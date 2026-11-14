# Локальная сверка через Docker Compose и NVIDIA GPU

Нужны Linux-контейнеры x86-64, Docker Compose 2.30 или новее и доступный
контейнерам NVIDIA GPU. Для Windows нужен Docker Desktop с WSL 2 и драйвером
NVIDIA. Для Linux нужен NVIDIA Container Toolkit. Первичная сборка и
загрузка базовых весов требуют доступа к реестрам.

- [GPU в Docker Desktop](https://docs.docker.com/desktop/features/gpu/)
- [Настройка NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)

1. Скопируйте `.env.example` в `.env` и задайте `DOCCHECK_DB_PASSWORD`
   случайной строкой из 32 шестнадцатеричных символов. При необходимости
   измените `DOCCHECK_PORT`.
2. Поместите разрешённый LoRA для этой базы и соседний `adapter_config.json`
   в `data/models/lora/` или задайте `DOCCHECK_LORA_DIR` с путём до каталога.
   По умолчанию файл называется `adapters.safetensors`. Для другого имени
   задайте `DOCCHECK_LORA_FILENAME`. Сверьте контрольные суммы обоих
   файлов с указанными поставщиком. Контейнер монтирует каталог только
   для чтения. Веса хранятся вне Git и вне контекста сборки.
3. Выполните из корня репозитория:

   ```sh
   docker compose -f compose.yaml -f compose.gpu.yaml up --build --wait --wait-timeout 1800
   ```

Сервис подготовки скачивает [базу Qwen3.5-4B-MLX-4bit](https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit)
на ревизии `32f3e8ecf65426fc3306969496342d504bfa13f3` в именованный том
`qwen-base`. Размер весов около 3,03 ГБ. Перед запуском проверяется
SHA-256 файла `model.safetensors`. Worker `--v32` работает на MLX/CUDA
12 и применяет подготовленный LoRA. Tesseract с языками `rus` и `eng`
входит в образ. Отдельный сервер модели на хосте не нужен.

После старта PostgreSQL применяются миграции. API и интерфейс ждут загрузки
модели с адаптером на GPU и готовности очереди. Worker получает оба
набора весов только для чтения и обрабатывает документы во внутренней
сети Docker без внешнего API.

Откройте [DocCheck](http://127.0.0.1:8080), добавьте КФЗ и первичные
документы. После приёма пакета нажмите «Запустить проверку». Из карточки
завершённой проверки можно посмотреть доказательства и скачать XLSX.

## Диагностика и перезапуск

```sh
docker compose -f compose.yaml -f compose.gpu.yaml ps -a
docker compose -f compose.yaml -f compose.gpu.yaml logs --tail=100 model-prepare document-worker
```

После успешной подготовки `model-prepare` и `migrate` имеют состояние
`Exited (0)`. При сбое запуска worker проверьте доступ к CUDA, наличие и
совместимость весов LoRA и доступ контейнера к смонтированному каталогу.

```sh
docker compose -f compose.yaml -f compose.gpu.yaml down
docker compose -f compose.yaml -f compose.gpu.yaml up --wait --wait-timeout 1800
```

Обычный `down` сохраняет тома `postgres-data`, `run-files` и `qwen-base`.
Флаг `--volumes` удаляет задания, оригиналы и скачанную базу.
