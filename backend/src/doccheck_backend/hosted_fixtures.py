"""Materialize the one compiled synthetic package allowed on the hosted Preview."""

import json
from hashlib import sha256
from pathlib import Path

from docx import Document
from openpyxl import Workbook


def materialize(directory: Path) -> tuple[Path, str]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest = directory / "manifest.json"
    if not manifest.exists():
        report, act_path = directory / "report.xlsx", directory / "act.docx"
        book = Workbook()
        sheet = book.active
        sheet.title = "КФЗ"
        sheet["A3"] = "Договор № PREVIEW-001"
        sheet["A4"] = "Период: 2026-01-01 — 2026-05-31. Этап 3."
        sheet["B6"] = "Статья затрат"
        sheet["C6"] = "Отчетная сумма, руб."
        sheet["B7"] = "Общехозяйственные расходы"
        sheet["C7"] = 10000
        sheet["A8"] = "Всего по отчету"
        sheet["C8"] = "=SUM(C7:C7)"
        book.save(report)
        act = Document()
        for paragraph in (
            "Акт оказанных услуг № PREVIEW-01 от 31.01.2026",
            "Договор № PREVIEW-001.",
            "Период оказания услуг: с 01.01.2026 по 31.01.2026.",
            "Обслуживание административного аппарата заказчика.",
            "Расходы отнесены к общехозяйственным расходам.",
            "Итого стоимость услуг: 9 000,00 руб. Без НДС.",
        ):
            act.add_paragraph(paragraph)
        act.save(act_path)
        writing = manifest.with_suffix(".tmp")
        writing.write_text(
            json.dumps(
                {
                    "synthetic": True,
                    "report": _entry(report),
                    "documents": [_entry(act_path)],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        writing.replace(manifest)
    return manifest, sha256(manifest.read_bytes()).hexdigest()


def _entry(path: Path) -> dict[str, str]:
    return {"name": path.name, "sha256": sha256(path.read_bytes()).hexdigest()}
