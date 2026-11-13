"""Generate an isolated synthetic package without reading any organizer data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from model import DEFAULT_SEED, make_package, public_document, public_report
from render import setup_font, write_docx, write_pdf_or_image, write_report

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def canonical_zip(path):
    """Discard ZIP container timestamps without changing Office content."""
    with zipfile.ZipFile(path) as archive:
        entries = [(name, archive.read(name)) for name in sorted(archive.namelist())]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def generate(output: Path, seed: int, node: str, previews: Path | None = None):
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output is not empty; choose a new directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "inputs").mkdir()
    (output / "expectations").mkdir()
    setup_font()
    package = make_package(seed)
    report = {"id": "01_kfz", "file": "inputs/01_kfz.pdf", "role": "report", "format": "pdf", "acquisition": "scan"}
    write_report(public_report(package), output / report["file"])
    for doc in package["documents"]:
        path = output / doc["file"]
        if doc.get("duplicate_of"):
            source = next(d for d in package["documents"] if d["id"] == doc["duplicate_of"])
            shutil.copyfile(output / source["file"], path)
        elif doc["format"] == "docx":
            write_docx(public_document(doc), path)
            canonical_zip(path)
        elif doc["format"] != "xlsx":
            write_pdf_or_image(public_document(doc), path)
    with tempfile.TemporaryDirectory(prefix="doccheck-synthetic-") as temp:
        source = Path(temp) / "public-sheets.json"
        write_json(source, [public_document(d) for d in package["documents"] if d["format"] == "xlsx"])
        command = [node, str(HERE / "xlsx.mjs"), str(source), str(output.resolve())]
        if previews:
            command.append(str(previews.resolve()))
        subprocess.run(command, check=True)
    inputs = [report]
    for doc in package["documents"]:
        if doc["format"] == "xlsx":
            canonical_zip(output / doc["file"])
        inputs.append({"id": doc["id"], "file": doc["file"], "role": "supporting", "format": doc["format"], "acquisition": doc["acquisition"]})
    for item in inputs:
        item["sha256"] = hashlib.sha256((output / item["file"]).read_bytes()).hexdigest()
    write_json(output / "inputs.json", {"synthetic": True, "files": inputs})
    package["report"] = report
    package["coverage"] = ["verified", "discrepancy", "unverified", "duplicate", "other_period", "other_contract", "partial_sum"]
    package["provenance"] = {
        "source": "All fixture values are generated from the seed without source data or an answer book",
        "layout": "Payroll and insurance worksheets match the source cell addresses; other formats await structural review",
        "acceptance": "Andrei checks the remaining layouts and absence of coinciding substantive values locally",
        "purpose": "Public regression fixture, not independent holdout or application output",
    }
    write_json(output / "expectations/manifest.json", package)
    (output / "README.md").write_text(f"""# Синтетический комплект КФЗ

Все документы и реквизиты вымышлены. Seed: `{seed}`. Это входные примеры для разработки, а не результат работы системы и не независимый holdout.

В `inputs/` находятся 23 файла: скан КФЗ, пять расчетных ведомостей, пять ведомостей взносов, акты, счет-акт, УПД, служебная записка и справка. Форматы: текстовые PDF, PDF-сканы, PNG, XLSX и DOCX. Все файлы имеют видимую пометку «СИНТЕТИЧЕСКИЙ ДОКУМЕНТ»; копия документа помечена тем же образом.

Для обработки передавайте **только файлы из `inputs.json`**. Этот список содержит идентификатор, путь, формат, роль, способ получения и SHA-256. Пути относительны к этой папке. README, `expectations/`, исходники генератора и превью не являются входными документами. Не загружайте всю папку рекурсивно.

`expectations/manifest.json` предназначен только для тестов и человека: содержание каждого файла, включение в расчет, исключенные документы, доступные суммы и ожидаемые статусы всех пяти показателей. Статусы не записываются в документы. У непроверяемых показателей ожидаемая полная сумма и дельта равны `null`.

Для XLSX сверены адреса полей на всех десяти исходных ведомостях. В зарплате суммы стоят в `C6:C7`, итог в `C8`. Во взносах база и сумма стоят в `A6:B6`, код статьи и комментарий в `C6:D6`. Значения сгенерированы из seed. Андрей локально проверяет расположение полей в остальных форматах и отсутствие совпадающих существенных реквизитов и сумм. Учебные ИНН имеют префикс `SYN-INN`.

Генератор, зависимости и команды проверки: [research/synthetic-package](../../../research/synthetic-package/README.md).
""", encoding="utf-8")
    return package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/synthetic/nrt-89")
    parser.add_argument("--node", default="node", help="Node.js executable with @oai/artifact-tool available")
    parser.add_argument("--previews", type=Path, help="Optional XLSX previews outside the input package")
    args = parser.parse_args()
    if not 0 <= args.seed <= 99999999:
        parser.error("seed must be between 0 and 99999999")
    output = args.output.resolve()
    if args.previews and (args.previews.resolve() == output or output in args.previews.resolve().parents):
        parser.error("previews must be outside the package")
    generate(output, args.seed, args.node, args.previews)
    print(f"Created 23 synthetic inputs: {output}")


if __name__ == "__main__":
    main()
