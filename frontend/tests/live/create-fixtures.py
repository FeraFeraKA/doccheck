"""Generate independent synthetic inputs for the real browser reconciliation."""

from pathlib import Path

from docx import Document
from openpyxl import Workbook


def make_report(destination: Path, contract: str) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "КФЗ"
    sheet["A3"] = f"Договор № {contract}"
    sheet["A4"] = "Период: 2026-01-01 — 2026-05-31. Этап 3."
    sheet["B6"] = "Статья затрат"
    sheet["C6"] = "Отчетная сумма, руб."
    sheet["B7"] = "Общехозяйственные расходы"
    sheet["C7"] = 10000
    sheet["A8"] = "Всего по отчету"
    sheet["C8"] = "=SUM(C7:C7)"
    book.save(destination)


def make_act(destination: Path, contract: str, number: str, amount: str) -> None:
    act = Document()
    act.add_paragraph(f"Акт оказанных услуг № {number} от 31.01.2026")
    act.add_paragraph(f"Договор № {contract}.")
    act.add_paragraph("Период оказания услуг: с 01.01.2026 по 31.01.2026.")
    act.add_paragraph("Обслуживание административного аппарата заказчика.")
    act.add_paragraph("Расходы отнесены к общехозяйственным расходам.")
    act.add_paragraph(f"Итого стоимость услуг: {amount} руб. Без НДС.")
    act.save(destination)


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[3] / "data" / "nrt-43-live"
    target.mkdir(parents=True, exist_ok=True)
    for name, contract, number, amount in (
        ("first", "TEST-5", "SYN-01", "9 000,00"),
        ("changed", "TEST-6", "SYN-02", "8 112,50"),
    ):
        package = target / name
        package.mkdir(exist_ok=True)
        make_report(package / "report.xlsx", contract)
        make_act(package / "act.docx", contract, number, amount)
