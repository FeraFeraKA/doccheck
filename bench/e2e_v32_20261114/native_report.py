"""Read the generated KФЗ XLSX report template without oracle data or inference.

This deliberately bounded OOXML reader preserves decimal values and evaluates
only same-sheet SUM/ROUND formulas. Unsupported formulas fail visibly; their
cached values are never silently trusted. It is not a general Excel engine.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import hashlib
from pathlib import Path
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format, is_timedelta_format

try:
    from .articles import EXPENSE_ARTICLES, report_category
    from .decision_rules import parse_amount, parse_date
except ImportError:
    from articles import EXPENSE_ARTICLES, report_category
    from decision_rules import parse_amount, parse_date

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def evaluate_cell(cells, address, stack=()):
    address = address.replace("$", "").upper()
    if address in stack:
        raise ValueError(f"Circular formula at {address}")
    cell = cells.get(address)
    if not cell:
        raise ValueError(f"Missing numeric cell {address}")
    if cell.get("type") in {"b", "e", "d"} or cell.get("temporal_format"):
        raise ValueError(f"Nonmonetary value in monetary cell {address}")
    expression = cell.get("formula")
    if not expression:
        value = parse_amount(cell.get("value"))
        if value is None:
            raise ValueError(f"Invalid amount at {address}: {cell.get('value')!r}")
        return value
    expression = expression.strip().lstrip("=").replace("$", "").upper()

    def evaluate(expression):
        rounded = re.fullmatch(r"ROUND\((.+),\s*(-?\d+)\)", expression)
        if rounded:
            digits = int(rounded.group(2))
            if abs(digits) > 8:
                raise ValueError("Unsupported rounding precision")
            return evaluate(rounded.group(1)).quantize(Decimal(10) ** -digits, rounding=ROUND_HALF_UP)
        summed = re.fullmatch(r"SUM\(([A-Z]+)(\d+):\1(\d+)\)", expression)
        if summed:
            column, first, last = summed.group(1), int(summed.group(2)), int(summed.group(3))
            if not (0 < first <= last < first + 10000):
                raise ValueError("Invalid or excessive SUM range")
            return sum((evaluate_cell(cells, f"{column}{row}", (*stack, address)) for row in range(first, last + 1)), Decimal("0"))
        if re.fullmatch(r"[A-Z]+\d+", expression):
            return evaluate_cell(cells, expression, (*stack, address))
        raise ValueError(f"Unsupported formula at {address}: {expression}")

    return evaluate(expression)


def temporal_styles(archive):
    if "xl/styles.xml" not in archive.namelist():
        return [False]
    styles = ET.fromstring(archive.read("xl/styles.xml"))
    formats = dict(BUILTIN_FORMATS)
    formats.update({
        int(item.attrib["numFmtId"]): item.attrib["formatCode"]
        for item in styles.findall("x:numFmts/x:numFmt", NS)
    })
    return [
        is_date_format(code) or is_timedelta_format(code)
        for style in styles.findall("x:cellXfs/x:xf", NS)
        for code in [formats.get(int(style.get("numFmtId", "0")))]
    ] or [False]


def read_native_report(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    with ZipFile(path) as archive:
        date_styles = temporal_styles(archive)
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(node.itertext()) for node in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("x:si", NS)]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook.findall("x:sheets/x:sheet", NS)
        sheet = next((sheet for sheet in sheets if sheet.get("name") == "КФЗ"), None)
        if sheet is None:
            raise ValueError("Expected worksheet КФЗ is absent")
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relationship = next((item for item in relationships if item.get("Id") == sheet.get("{" + REL + "}id")), None)
        if relationship is None or relationship.get("TargetMode") == "External":
            raise ValueError("Missing or external worksheet relationship")
        target = relationship.get("Target", "")
        worksheet_path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target))
        if not worksheet_path.startswith("xl/"):
            raise ValueError("Worksheet path escapes workbook")
        xml = ET.fromstring(archive.read(worksheet_path))
    cells = {}
    for cell in xml.findall("x:sheetData/x:row/x:c", NS):
        cell_type = cell.get("t")
        value = cell.findtext("x:v", namespaces=NS)
        if cell_type == "s" and value is not None:
            value = shared[int(value)]
        elif cell_type == "inlineStr":
            value = "".join(cell.find("x:is", NS).itertext())
        style = int(cell.get("s", "0"))
        if not 0 <= style < len(date_styles):
            raise ValueError("Unrecognized worksheet cell style")
        cells[cell.get("r")] = {
            "type": cell_type, "value": value, "formula": cell.findtext("x:f", namespaces=NS),
            "temporal_format": date_styles[style],
        }
    text = lambda address: str(cells.get(address, {}).get("value") or "").strip()
    if text("B6") != "Статья затрат" or text("C6") != "Отчетная сумма, руб.":
        raise ValueError("Unsupported report table headers")
    contract = re.fullmatch(r"Договор\s*№\s*(\S+)", text("A3"))
    period = re.fullmatch(r"Период:\s*(\d{4}-\d{2}-\d{2})\s*[—–-]\s*(\d{4}-\d{2}-\d{2})\.\s*Этап\s+\d+\.", text("A4"))
    if not contract or not period or not all(parse_date(value) for value in period.groups()):
        raise ValueError("Report contract or period is missing/malformed")
    if parse_date(period.group(1)) > parse_date(period.group(2)):
        raise ValueError("Reversed report period")
    rows, total, seen = [], None, set()
    for row in range(7, 100):
        if text(f"A{row}") == "Всего по отчету":
            total = {"amount": str(evaluate_cell(cells, f"C{row}")), "cell": f"КФЗ!C{row}", "formula": cells[f"C{row}"].get("formula")}
            break
        label = text(f"B{row}")
        code = text(f"A{row}")
        if not label and not code:
            raise ValueError(f"Missing expense category at B{row}")
        category = report_category(label, code)
        if category in {None, "total"} or category in seen:
            raise ValueError(f"Unknown or duplicate category at B{row}: {label}")
        seen.add(category)
        rows.append({"category": category, "reported_amount": str(evaluate_cell(cells, f"C{row}")),
                     "source_cells": {"category": f"КФЗ!{'B' if label else 'A'}{row}",
                                      "reported_amount": f"КФЗ!C{row}"}})
    if not rows or total is None:
        raise ValueError("Missing report rows or total")
    row_sum = sum(
        (parse_amount(row["reported_amount"]) for row in rows if row["category"] in EXPENSE_ARTICLES),
        Decimal("0"),
    )
    return {"contract_number": contract.group(1), "period_start": period.group(1), "period_end": period.group(2),
            "rows": rows, "total": total, "total_agrees_with_rows": row_sum == parse_amount(total["amount"]),
            "source": {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "sheet": "КФЗ",
                       "contract_cell": "КФЗ!A3", "period_cell": "КФЗ!A4"},
            "reader": "bounded_native_xlsx_decimal_v1"}
