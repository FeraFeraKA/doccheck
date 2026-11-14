# Локальная сверка КФЗ v3.2

Конвейер читает XLSX, DOCX, текстовые PDF и сканы PDF/PNG. Локальная Qwen
извлекает реквизиты, правила сверяют суммы, отбирают источники и формируют
пояснения. Для сканов модель возвращает цитаты без подтверждённых координат.
Проверка запускается из командной строки. Мастер загрузки и worker используют
свои интерфейсы.

## Подготовка

Из корня репозитория установите зависимости в окружение Python 3.12.

```sh
python -m pip install -r bench/e2e_v32_20261114/requirements.txt
```

Запустите Ollama на отдельном локальном порту. В PowerShell:

```powershell
$env:OLLAMA_HOST = "127.0.0.1:11438"
$env:OLLAMA_NO_CLOUD = "1"
$env:OLLAMA_NOPRUNE = "1"
ollama serve
```

В macOS или Linux:

```sh
OLLAMA_HOST=127.0.0.1:11438 OLLAMA_NO_CLOUD=1 OLLAMA_NOPRUNE=1 ollama serve
```

`OLLAMA_NOPRUNE=1` отключает очистку неиспользуемых слоёв моделей при
запуске сервера. Это не гарантирует неизменность всех файлов хранилища.

Нужна локальная модель `qwen3.5:4b-q4_K_M`. Если её ещё нет, загрузите
проверенный вариант до обработки документов. Например, во втором PowerShell
с тем же `OLLAMA_HOST`:

```powershell
$env:OLLAMA_HOST = "127.0.0.1:11438"
ollama pull qwen3.5:4b-q4_K_M
```

При начале сверки код проверяет закреплённый digest модели. Если тег указывает
на другой образ, запуск остановится. В таком случае перенесите проверенные веса
в локальное хранилище Ollama.

## Сверка

Команды работают в PowerShell и в обычной оболочке. Замените пути вывода для
каждого нового прогона.

```sh
python -m bench.e2e_v32_20261114.run --manifest bench/e2e_v32_20261114/case-manifest.json --output data/v32-case-run --run-id v32-case --split original --timing-mode cold --freeze data/v32-case-freeze.json --freeze-only
python -m bench.e2e_v32_20261114.run --manifest bench/e2e_v32_20261114/case-manifest.json --output data/v32-case-run --run-id v32-case --split original --timing-mode cold --freeze data/v32-case-freeze.json
```

Входной манифест ссылается на 23 уже доступных в репозитории файла и задаёт
договор, период и допущение о полноте исторического набора. Для своих
комплектов используйте `data/` и укажите фактические договор, период и полноту.
При неизвестной полноте укажите `"status": "unknown"`.

Результат и пояснения лежат в `data/v32-case-run/original/result.json` и
`data/v32-case-run/original/explanation.txt`. Сырые ответы и подготовленные
входы остаются в локальном каталоге прогона. Время `elapsed_s` включает
подготовку файлов, модель, расчёт и сохранение результата.

## Проверки

```sh
python -m unittest discover -s bench/e2e_v32_20261114 -t .
```
