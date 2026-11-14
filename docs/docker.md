# Локальная сверка через Docker Compose и NVIDIA GPU

Нужны Linux-контейнеры x86-64, Docker Compose 2.30 или новее и доступный
контейнерам NVIDIA GPU. Для Windows нужен Docker Desktop с WSL 2 и драйвером
NVIDIA. Для Linux нужен NVIDIA Container Toolkit. Первичная сборка и
загрузка базовых весов требуют доступа к реестрам.

- [GPU в Docker Desktop](https://docs.docker.com/desktop/features/gpu/)
- [Настройка NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)

## Подготовка

Для проверки версии из PR клонируйте ветку `codex/nrt-41-docker-gpu`.
Если репозиторий уже скачан, переключитесь на эту ветку и обновите её.

```sh
git clone --branch codex/nrt-41-docker-gpu https://github.com/VCyberPunk2077/doccheck.git
cd doccheck
```

Скопируйте `.env.example` в `.env` из корня репозитория. В PowerShell
используйте `Copy-Item .env.example .env`, в Linux — `cp .env.example .env`.
В `.env` задайте `DOCCHECK_DB_PASSWORD` случайной строкой из 32
шестнадцатеричных символов. Если порт 8080 занят, измените `DOCCHECK_PORT`.

## Скачивание весов и запуск

### Способ 1. Docker скачивает всё автоматически

Если сеть блокирует скачивание с Hugging Face, включите VPN или другое
средство обхода блокировки перед запуском. Через него должен идти и трафик
Docker. Из корня репозитория выполните команду.

```sh
docker compose -f compose.yaml -f compose.gpu.yaml up --build --wait --wait-timeout 1800
```

Docker сам соберёт образы, скачает базу Qwen MLX в том `qwen-base` и
опубликованный LoRA с конфигурацией в `data/models/lora/`. Он проверит
SHA-256 базовых весов и обоих файлов LoRA. [Базовая модель](https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit/tree/32f3e8ecf65426fc3306969496342d504bfa13f3) · [Релиз LoRA](https://github.com/VCyberPunk2077/doccheck/releases/tag/doccheck-lora-0000100)

### Способ 2. Два файла скачиваются вручную

Если Docker не может скачать веса через CDN, откройте эти ссылки в браузере
через работающую сеть или VPN. Сохраните файлы под исходными именами.

- [model.safetensors, 3,03 ГБ](https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit/resolve/32f3e8ecf65426fc3306969496342d504bfa13f3/model.safetensors?download=true)
- [tokenizer.json, около 20 МБ](https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit/resolve/32f3e8ecf65426fc3306969496342d504bfa13f3/tokenizer.json?download=true)

Если файлы лежат в папке «Загрузки», в PowerShell из корня проекта выполните
эти команды. При другом расположении подставьте свои пути.

```powershell
$modelDir = 'data/models/base/32f3e8ecf65426fc3306969496342d504bfa13f3'
New-Item -ItemType Directory -Force $modelDir
Copy-Item "$env:USERPROFILE/Downloads/model.safetensors" $modelDir
Copy-Item "$env:USERPROFILE/Downloads/tokenizer.json" $modelDir
docker compose -f compose.yaml -f compose.gpu.yaml up --build --wait --wait-timeout 1800
```

В Linux положите оба файла в тот же каталог относительно корня проекта
и запустите ту же команду Compose. Docker использует эти файлы и скачает
остальные файлы модели и LoRA. Для этого по-прежнему нужен доступ к
Hugging Face и GitHub. С полным снимком и готовым LoRA подготовка весов
проходит без сети. Другой родительский каталог снимков можно указать через
`DOCCHECK_QWEN_SNAPSHOT_DIR`.

После старта PostgreSQL применяются миграции. API и интерфейс ждут загрузки
модели с адаптером на GPU и готовности очереди. Worker получает оба
набора весов только для чтения и обрабатывает документы во внутренней
сети Docker без внешнего API. CUDA 12, MLX и Tesseract с языками `rus`
и `eng` входят в образ worker.

Откройте [DocCheck](http://127.0.0.1:8080), добавьте КФЗ и первичные
документы. После приёма пакета нажмите «Запустить проверку». Из карточки
завершённой проверки можно посмотреть доказательства и скачать XLSX.
Для быстрой ручной проверки загрузите `frontend/public/demo/report.xlsx`
как КФЗ и `frontend/public/demo/act.docx` как первичный документ.
В результате по общехозяйственным расходам ожидаются 10 000,00 ₽ в КФЗ,
8 112,50 ₽ по акту и статус «Расхождение». Для проверки модельного чтения
используйте растровый первичный документ и проверьте его статус и источники.

## Диагностика и перезапуск

```sh
docker compose -f compose.yaml -f compose.gpu.yaml ps -a
docker compose -f compose.yaml -f compose.gpu.yaml logs --tail=100 model-prepare document-worker
```

После успешной подготовки `model-prepare` и `migrate` имеют состояние
`Exited (0)`. У `db`, `document-worker`, `api` и `frontend` должно быть
`healthy`. Откройте `http://127.0.0.1:8080/health` и проверьте, что поля
`status` и `database` равны `ok`. Если меняли порт, используйте его здесь.
При сбое запуска worker проверьте доступ к CUDA, наличие и
совместимость весов LoRA и доступ контейнера к смонтированному каталогу.

```sh
docker compose -f compose.yaml -f compose.gpu.yaml down
docker compose -f compose.yaml -f compose.gpu.yaml up --wait --wait-timeout 1800
```

Обычный `down` сохраняет тома `postgres-data`, `run-files` и `qwen-base`.
Флаг `--volumes` удаляет задания, оригиналы и скачанную базу.
