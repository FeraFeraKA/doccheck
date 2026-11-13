"""Render only invented public facts; no expected statuses reach input files."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import os
import textwrap

from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import pypdfium2 as pdfium
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from model import MARK, shown


def setup_font() -> None:
    candidates = [os.environ.get("SYNTHETIC_FONT", ""),
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                  "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
                  "/System/Library/Fonts/Supplemental/Arial.ttf",
                  "C:/Windows/Fonts/arial.ttf"]
    font = next((Path(x) for x in candidates if x and Path(x).is_file()), None)
    if font is None:
        raise RuntimeError("Set SYNTHETIC_FONT to a Cyrillic TrueType font (e.g. DejaVuSans.ttf)")
    pdfmetrics.registerFont(TTFont("Synthetic", str(font)))


def date_text(value):
    return datetime.fromisoformat(value).strftime("%d.%m.%Y")


def description(doc):
    return {
        "production_overhead": "Обслуживание испытательного оборудования производственного участка.",
        "general_admin": "Обеспечение работы административных подразделений и аппарата управления.",
    }[doc["category"]]


def partial_note(doc):
    return ("Приложение 1 из 2. Учтено только подразделение А. Приложение 2 по подразделению Б отсутствует."
            if doc["partial"] else "В документе приведен полный объем указанной операции.")


def lines(c, text, y, *, x=42, width=90, size=10):
    c.setFont("Synthetic", size)
    for line in textwrap.wrap(text, width=width):
        c.drawString(x, y, line)
        y -= size * 1.6
    return y - 8


def source_pdf(doc) -> bytes:
    target = BytesIO()
    c = canvas.Canvas(target, pagesize=(595.28, 841.89), invariant=1)
    c.setTitle(f"Синтетический {doc['kind']}")
    c.setAuthor("DocCheck synthetic generator")
    c.setFont("Synthetic", 8)
    c.drawString(42, 812, MARK.replace("—", "-"))
    y = lines(c, doc["kind"], 764, width=48, size=16)
    y = lines(c, f"№ {doc['number']} от {date_text(doc['date'])}", y - 12)
    y = lines(c, f"Договор № {doc['contract']}", y)
    y = lines(c, f"Заказчик: {doc['company']}", y)
    y = lines(c, f"Исполнитель: {doc['counterparty']}", y)
    y = lines(c, f"Учебный ИНН: {doc['tax_id']}", y)
    y = lines(c, f"Период: {date_text(doc['period_start'])} - {date_text(doc['period_end'])}", y)
    y = lines(c, description(doc), y - 5)
    c.line(42, y, 553, y)
    y -= 26
    c.drawString(48, y, "Наименование")
    c.drawRightString(548, y, "Сумма, руб.")
    y -= 34
    c.drawString(48, y, doc["items"][0]["label"])
    c.drawRightString(548, y, shown(doc["amount"]))
    y -= 20
    c.line(42, y, 553, y)
    y -= 28
    c.drawString(48, y, "Итого к учету")
    c.drawRightString(548, y, shown(doc["amount"]))
    y = lines(c, partial_note(doc), y - 40)
    y = lines(c, "Сумма указана в рублях. НДС отдельно не предъявляется в этой учебной операции.", y)
    y = lines(c, "Ответственный: Синтез У. У. __________________", y - 20)
    if y < 65:
        raise ValueError(f"PDF content overflow: {doc['id']}")
    c.setFont("Synthetic", 8)
    c.drawString(42, 32, "Все реквизиты вымышлены. Учебный образец. Страница 1 из 1.")
    c.save()
    return target.getvalue()


def raster(data: bytes):
    with pdfium.PdfDocument(data) as pdf:
        return pdf[0].render(scale=2).to_pil().convert("RGB")


def scan_pdf(image, path):
    c = canvas.Canvas(str(path), pagesize=(595.28, 841.89), invariant=1)
    c.setTitle("Синтетический скан")
    c.setAuthor("DocCheck synthetic generator")
    c.drawImage(ImageReader(image), 0, 0, width=595.28, height=841.89)
    c.save()


def write_pdf_or_image(doc, path):
    data = source_pdf(doc)
    if doc["acquisition"] == "native":
        path.write_bytes(data)
    elif doc["format"] == "png":
        raster(data).save(path)
    else:
        scan_pdf(raster(data), path)


def write_report(report, path):
    data = BytesIO()
    c = canvas.Canvas(data, pagesize=(595.28, 841.89), invariant=1)
    c.setTitle("Синтетическая карточка фактических затрат")
    c.setAuthor("DocCheck synthetic generator")
    c.setFont("Synthetic", 8)
    c.drawString(42, 812, MARK.replace("—", "-"))
    y = lines(c, "Карточка учета фактических затрат", 765, width=45, size=16)
    y = lines(c, f"Договор № {report['contract']}. Этап 7.", y - 12)
    y = lines(c, report["company"], y)
    y = lines(c, f"Отчетный период: {date_text(report['period_start'])} - {date_text(report['period_end'])}", y)
    y = lines(c, "Суммы фактических затрат за отчетный период, руб.", y - 12)
    c.line(42, y, 553, y)
    y -= 28
    c.drawString(48, y, "Статья затрат")
    c.drawRightString(548, y, "В отчете, руб.")
    for row in report["rows"]:
        y -= 46
        c.drawString(48, y, row["label"])
        c.drawRightString(548, y, shown(row["reported_amount"]))
    from decimal import Decimal
    total = sum(Decimal(r["reported_amount"]) for r in report["rows"])
    y -= 20
    c.line(42, y, 553, y)
    y -= 28
    c.drawString(48, y, "Итого")
    c.drawRightString(548, y, shown(format(total, ".2f")))
    lines(c, "Ответственный: Синтез У. У. __________________", y - 55)
    c.setFont("Synthetic", 8)
    c.drawString(42, 32, "Все реквизиты вымышлены. Учебный образец. Страница 1 из 1.")
    c.save()
    scan_pdf(raster(data.getvalue()), path)


def write_docx(doc, path):
    document = Document()
    for style in document.styles:
        for border in list(style.element.iter(qn("w:pBdr"))):
            border.getparent().remove(border)
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Cm(1.8)
    section.left_margin = section.right_margin = Cm(2)
    normal = document.styles["Normal"]
    normal.font.name, normal.font.size = "Arial", Pt(10)
    normal.paragraph_format.space_after = Pt(8)
    header = section.header.paragraphs[0]
    header.text = MARK
    header.runs[0].font.size = Pt(7)
    title = document.add_paragraph(doc["kind"], "Title")
    title.runs[0].font.color.rgb = RGBColor(0, 0, 0)
    for text in [f"№ {doc['number']} от {date_text(doc['date'])}", f"Договор № {doc['contract']}",
                 f"Заказчик: {doc['company']}", f"Исполнитель: {doc['counterparty']}",
                 f"Учебный ИНН: {doc['tax_id']}",
                 f"Период: {date_text(doc['period_start'])} - {date_text(doc['period_end'])}", description(doc)]:
        document.add_paragraph(text)
    table = document.add_table(rows=1, cols=2)
    table.autofit = False
    table.columns[0].width, table.columns[1].width = Cm(12), Cm(5)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Основание", "Сумма, руб."
    for label, amount in [(doc["items"][0]["label"], doc["amount"]), ("Итого к учету", doc["amount"])]:
        cells = table.add_row().cells
        cells[0].text, cells[1].text = label, shown(amount)
    for i, row in enumerate(table.rows):
        for cell in row.cells:
            props = cell._tc.get_or_add_tcPr()
            borders = OxmlElement("w:tcBorders")
            for edge in ("top", "left", "bottom", "right"):
                element = OxmlElement(f"w:{edge}")
                for key, value in (("val", "single"), ("sz", "4"), ("color", "D9D9D9")):
                    element.set(qn(f"w:{key}"), value)
                borders.append(element)
            props.append(borders)
            if i == 0:
                fill = OxmlElement("w:shd")
                fill.set(qn("w:fill"), "E8E8E8")
                props.append(fill)
    document.add_paragraph(partial_note(doc))
    document.add_paragraph("Ответственный: Синтез У. У. __________________")
    document.core_properties.author = "DocCheck synthetic generator"
    document.core_properties.created = document.core_properties.modified = datetime(2000, 1, 1, tzinfo=timezone.utc)
    document.save(path)
