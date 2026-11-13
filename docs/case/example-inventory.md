# Инвентарь разрешённых примеров

[Манифест](example-inventory.json) описывает 25 файлов из `docs/case/examples/`
на ревизии `e5af8d6a28ccb0fb686ec667c25cfdf9ae3e5174`: одну КФЗ, 22
подтверждающих файла и два представления README. Роль `supporting` обозначает
файл из предоставленного комплекта. Применимость к конкретной статье и
возможность включения в расчёт требуют отдельного подтверждения.

Пути в манифесте относительны к `docs/case/`. Для PDF `native` означает
наличие извлекаемого текста, `scan` — его отсутствие. Без текстового слоя
оказались КФЗ (`01`) и три акта (`04`, `08`, `15`). PNG имеет тип `image`.
Распознавание этих пяти файлов по содержанию не проводилось. DOCX, XLSX и TXT
отмечены как структурированные или текстовые файлы с типом `native`.

## Область и даты

Оба README пакета указывают целевую строку широкой таблицы КФЗ «3 этап,
2026 г.» и период с 01.01.2026 по 31.05.2026. [NRT-16](https://linear.app/andreiakimov/issue/NRT-16/inventar-dannyh-i-razbor-otchyota-kfz)
отдельно фиксирует расхождение 30/31 мая. В обоих README найдена только
граница 31 мая. Какая дата применяется для предметной приёмки, подтверждает
Андрей. Он также сверяет статьи, внутренние детализации и применимость
источников в разрешённом контуре. Формат промежуточной сводки и исключение
конкретной справки остаются открытыми. [Уточнения кейса](README.md)

## Проверка

Запустите из корня репозитория с Python 3.11 или новее. Команда сверяет
перечень отслеживаемых Git файлов, форматы по расширению и SHA-256 текущих байтов.

```sh
python -c "from pathlib import Path; import hashlib,json,subprocess; r=Path('docs/case'); actual=set(subprocess.check_output(['git','ls-files','-z','--','docs/case/examples']).decode().rstrip(chr(0)).split(chr(0))); fs=json.loads((r/'example-inventory.json').read_text(encoding='utf-8'))['files']; paths=[(r/f['path']).as_posix() for f in fs]; assert len(paths)==len(set(paths)) and set(paths)==actual, 'Unexpected file list'; bad=[p for p,f in zip(paths,fs) if Path(p).suffix[1:]!=f['format'] or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=f['sha256']]; assert not bad,bad; print(len(fs),'files verified')"
```
