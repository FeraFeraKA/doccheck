# NRT-93. Проверка границы ML-модуля

[Задача NRT-93](https://linear.app/andreiakimov/issue/NRT-93/soglasovat-interfejs-ml-modulya-i-rezultat-obrabotki)
прочитана напрямую 13.11.2026 около 07:29 МСК. Назначение
`n90-20261112-2352 / a5`, база `ccbffbb8ccc2ff60bf8c7663a70476e4e6334af4`.
Сверены NRT-92, NRT-85, NRT-94 и NRT-95. В базе присутствуют аудит,
семантический контракт и публичный код `doccheck-ml`.

[Описание границы](../ml-module-boundary.md) фиксирует вызов из worker,
поля, ошибки, адреса и допуск наблюдений к общему результату. Окончательная
проверка реквизитов и расчёты остаются за обработчиком. Адаптер
реализуется в NRT-94.

## Выполненные проверки

- Python 3.12.12, Windows. Через публичный `process_documents` с
  `synthetic=True` переданы вымышленные наблюдения, временные байты и SHA.
  Сумма `"73.49"` вернулась с адресом страницы, строки и ненормализованной
  рамкой. Адрес XLSX `QA!C6` сохранился, а `A0` без имени листа API принял.
  Значение с одной страницей вернулось как кандидат без адреса фрагмента.
- Синтетика подтвердила `InputError` на неверных полях, две ошибки
  `source_unavailable` и `source_changed` с `partial`, группировку
  побайтовых копий и отдельную группу при разных байтах. Конфликт сумм дал
  `null` и карточку ревью. Строка из prediction осталась в `facts`.
  При двух номерах договора остался первый без отметки конфликта.
  Три известных P2 PR #8 воспроизведены на вымышленных входах.
- `QwenReader` вернул `QwenInputError` для отсутствующего фрагмента и
  `QwenUnavailableError` при отсутствующем каталоге модели. Это
  проверки отказа до inference.
- Набор `backend/tests/ml_module` запущен через `unittest` с
  `PYTHONPATH=backend/ml_module/src`. Выполнено 165 тестов, из них 160
  прошли и 5 ожидаемо упали по известным P2. Полный прогон на этой
  машине завершился с `WinError 1314` при создании символьной ссылки.
  Этот тест исключён из указанного прогона. Отдельно подтверждён отказ
  CLI для абсолютного пути и пути за пределами каталога манифеста.
- Сверены ТЗ и все 25 разрешённых примеров. Проверены текст и структура,
  включая оба README, КФЗ, формулы XLSX и адреса DOCX. Четыре сканированных
  PDF и PNG просмотрены локально через OCR ОС. Эти файлы не передавались
  модулю, OCR-текст не включён в изменения.
- По независимому ревью `a5-r1` уточнены два правила. На Python 3.12.12
  один синтетический смешанный вход при `native` дал `native_source`
  с заполненным `usable_value`, а при `scan` дал `ocr_source_only`,
  `usable_value=null` и требование ручной проверки. Вложенное поле
  `acquisition` вызвало `InputError`. CLI при недоступном исходнике
  вернул 2, создал JSON и напечатал сводку `partial`. Повтор с ошибкой
  аргументов вернул 2, вывел диагностику и сохранил прежний JSON побайтно.
  С корректными аргументами и занятым путём вывода CLI вернул 1.
  [Отзыв](https://github.com/VCyberPunk2077/doccheck/pull/16#issuecomment-6844536088)

Базовый адресный вызов можно повторить с Python 3.12 и
`PYTHONPATH=backend/ml_module/src` из корня репозитория:

```python
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from doccheck_ml import DocumentInput, process_documents

with TemporaryDirectory() as directory:
    path = Path(directory) / "synthetic.txt"
    raw = "Итого: 73,49"
    path.write_bytes(raw.encode("utf-8"))
    line = {"text": raw, "page": 1, "line": 1, "bbox": [20, 42, 55, 51]}
    document = DocumentInput(
        "qa", path, hashlib.sha256(path.read_bytes()).hexdigest(), "native", [line]
    )
    result = process_documents([document], synthetic=True)
    record = result["records"][0]
    assert record["source_facts"]["amount"] == "73.49"
    assert record["fact_evidence"]["amount"] == [line]
    assert result["synthetic"] and not result["inference_performed"]
```

Предметная применимость, проверка готового GPU runtime и исходных весов,
реальный inference, офлайн-запуск и интеграция маршрутов остаются
отдельными задачами. Независимое ревью технического решения проходит
через ночной PR. Семёну передаётся граница наблюдений и требования к
проверке готовой модели, Николаю — адреса, ошибки и подключение схемы.
Исходный вопрос о комплекте весов остаётся в NRT-92.
