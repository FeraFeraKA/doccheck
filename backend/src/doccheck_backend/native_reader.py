"""Native observations with contract addresses for a single trusted local file."""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

import pdfplumber
from defusedxml.common import DefusedXmlException
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from lxml.etree import XMLSyntaxError
from pdfminer.pdfexceptions import PDFException
from pdfminer.psexceptions import PSException
from pdfplumber.utils.exceptions import PdfminerException

from doccheck_backend.contracts.locators import (
    Locator,
    PageLocator,
    ParagraphLocator,
    TableCellLocator,
)
from doccheck_backend.native_observations import NativeDocument, NativeIssue, Observation
from doccheck_backend.native_xlsx import read_workbook

_NUMBER = r"-?(?:[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3})+|[0-9]+)(?:[.,][0-9]+)?"
_CURRENCY = r"(?:₽|руб(?:лей|ля|\.)?|RUB|р\.)"
_EXPLICIT_RUB = re.compile(
    rf"(?<![\w./,+-])({_NUMBER})[ \u00a0\u202f]*{_CURRENCY}(?!\w)", re.IGNORECASE
)
_MONEY_HEADER = re.compile(r"^(?:сумма|стоимость)\s*[,\s(]+(?:руб\.?|₽|rub)\)?$", re.I)


@dataclass
class _Collected:
    observations: list[Observation] = field(default_factory=list)
    issues: list[NativeIssue] = field(default_factory=list)


def _text_amount(text: str, *, rub_column: bool = False) -> Decimal | None:
    matches = _EXPLICIT_RUB.findall(text)
    if not matches and rub_column and re.fullmatch(_NUMBER, text.strip()):
        matches = [text.strip()]
    if len(matches) != 1:
        return None
    compact = re.sub(r"[ \u00a0\u202f]", "", matches[0]).replace(",", ".")
    try:
        return Decimal(compact)
    except InvalidOperation:
        return None


def _observe(
    collected: _Collected, text: str, locator: Locator, *, rub_column: bool = False
) -> None:
    if not text.strip():
        return
    amount = _text_amount(text, rub_column=rub_column)
    collected.observations.append(
        Observation(text, locator, amount, "candidate" if amount is not None else None)
    )


def _read_pdf(path: Path, collected: _Collected) -> None:
    with pdfplumber.open(path) as document:
        for page in document.pages:
            lines = page.extract_text_lines(return_chars=False)
            if not lines:
                collected.issues.append(NativeIssue("no_native_text", page=page.page_number))
                continue
            x0, top, _, _ = page.bbox
            for number, line in enumerate(lines, 1):
                box = (
                    max(0.0, (line["x0"] - x0) / page.width),
                    max(0.0, (line["top"] - top) / page.height),
                    min(1.0, (line["x1"] - x0) / page.width),
                    min(1.0, (line["bottom"] - top) / page.height),
                )
                locator = PageLocator(
                    kind="page",
                    page=page.page_number,
                    line=number,
                    bbox=box if box[0] < box[2] and box[1] < box[3] else None,
                )
                _observe(collected, line["text"], locator)
            page.close()


def _read_docx(path: Path, collected: _Collected) -> None:
    with ZipFile(path) as archive:
        if sum(part.file_size for part in archive.infolist()) > 128 * 1024**2:
            raise ValueError("DOCX archive exceeds the native reader limit")
    document = Document(path)
    for number, paragraph in enumerate(document.paragraphs, 1):
        _observe(collected, paragraph.text, ParagraphLocator(kind="paragraph", paragraph=number))
    for table_index, table in enumerate(document.tables, 1):
        if not table.rows:
            continue
        heading = table.rows[0]
        rub_columns = {
            index
            for index, cell in enumerate(heading.cells, heading.grid_cols_before + 1)
            if _MONEY_HEADER.fullmatch(" ".join(cell.text.split()))
        }
        observed_cells = set()
        for row_index, row in enumerate(table.rows, 1):
            for cell_index, cell in enumerate(row.cells, row.grid_cols_before + 1):
                if cell._tc in observed_cells:
                    continue
                observed_cells.add(cell._tc)
                locator = TableCellLocator(
                    kind="table_cell", table=table_index, row=row_index, cell=cell_index
                )
                _observe(collected, cell.text, locator, rub_column=cell_index in rub_columns)


def read_native_document(path: Path, file_format: str) -> NativeDocument:
    """Extract candidates, formulas and diagnostics without making business decisions."""
    collected = _Collected()
    try:
        match file_format:
            case "pdf":
                _read_pdf(path, collected)
            case "docx":
                _read_docx(path, collected)
            case "xlsx":
                return read_workbook(path)
            case _:
                return NativeDocument(issues=(NativeIssue("unsupported_native_format"),))
    except (
        OSError,
        BadZipFile,
        PackageNotFoundError,
        XMLSyntaxError,
        PDFException,
        PSException,
        PdfminerException,
        ParseError,
        DefusedXmlException,
        UnicodeError,
        ValueError,
        KeyError,
        OverflowError,
        NotImplementedError,
    ):
        collected.issues.append(NativeIssue("native_read_error"))
    if not collected.observations and not collected.issues:
        collected.issues.append(NativeIssue("no_native_text"))
    return NativeDocument(tuple(collected.observations), tuple(collected.issues))
