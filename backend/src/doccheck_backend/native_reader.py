"""Native observations with contract addresses for a single trusted local file."""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile
from zlib import error as DecompressionError

import pdfplumber
from defusedxml.common import DefusedXmlException
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from lxml.etree import XMLSyntaxError
from pdfminer.pdfexceptions import PDFException
from pdfminer.psexceptions import PSException
from pdfplumber.page import Page
from pdfplumber.utils import chars_to_textmap
from pdfplumber.utils.exceptions import PdfminerException

from doccheck_backend.contracts.locators import (
    Locator,
    PageLocator,
    ParagraphLocator,
    TableCellLocator,
)
from doccheck_backend.native_observations import NativeDocument, NativeIssue, Observation
from doccheck_backend.native_xlsx import read_workbook

_SPACE_CHARS = " \u00a0\u2009\u202f"
_SPACE = rf"[{_SPACE_CHARS}]"
_NUMBER = re.compile(
    rf"(?P<sign>[+−-]?){_SPACE}*"
    rf"(?P<integer>[0-9]{{1,3}}(?:{_SPACE}[0-9]{{3}})+|[0-9]+)"
    r"(?P<fraction>[.,][0-9]+)?"
)
_CURRENCY = r"(?:₽|руб(?:лей|ля|ль|\.)?|RUB|р\.)"
_KOPECKS = r"коп(?:еек|ейки|ейка|\.)?"
_RUB_TOKEN = re.compile(
    rf"{_CURRENCY}(?:{_SPACE}*([0-9]+){_SPACE}*{_KOPECKS}(?!\w)|(?!\w))",
    re.IGNORECASE,
)
_MONEY_HEADER = re.compile(r"^(?:сумма|стоимость)\s*[,\s(]+(?:руб\.?|₽|rub)\)?$", re.I)


@dataclass
class _Collected:
    observations: list[Observation] = field(default_factory=list)
    issues: list[NativeIssue] = field(default_factory=list)


def _rub_tokens(text: str) -> list[tuple[str, str]]:
    matches = []
    # Each reverse scan stops at the first non-numeric character. Runs between currency
    # markers cannot overlap, even when the document has a long invalid grouping.
    for currency in _RUB_TOKEN.finditer(text):
        end = currency.start()
        if not end or text[end - 1] not in "0123456789" + _SPACE_CHARS:
            continue
        start = end
        while start and text[start - 1] in "0123456789.," + _SPACE_CHARS:
            start -= 1
        if start and text[start - 1] in "+−-":
            start -= 1
        numeral = text[start:end].strip(_SPACE_CHARS)
        if not numeral or numeral[-1] not in "0123456789":
            continue
        if (
            start
            and text[start] not in _SPACE_CHARS
            and (text[start - 1].isalnum() or text[start - 1] in "_./,+−-")
        ):
            numeral = ""
        matches.append((numeral, currency[1] or ""))
    return matches


def _text_amount(text: str, *, rub_column: bool = False) -> tuple[Decimal | None, bool]:
    matches = _rub_tokens(text)
    if not matches and rub_column and re.search(r"\d", text):
        matches = [(text.strip(), "")]
    if len(matches) != 1:
        return None, bool(matches)
    numeral, kopecks = matches[0]
    number = _NUMBER.fullmatch(numeral)
    if number is None:
        return None, True
    sign, integer, fraction = number.groups()
    if kopecks:
        if fraction or len(kopecks) > 2:
            return None, True
        fraction = "." + kopecks.zfill(2)
    compact = ("-" if sign in ("-", "−") else "") + re.sub(_SPACE, "", integer)
    compact += (fraction or "").replace(",", ".")
    try:
        return Decimal(compact), False
    except InvalidOperation:
        return None, True


def _observe(
    collected: _Collected, text: str, locator: Locator, *, rub_column: bool = False
) -> None:
    if not text.strip():
        return
    amount, ambiguous = _text_amount(text, rub_column=rub_column)
    if ambiguous:
        collected.issues.append(NativeIssue("ambiguous_rub_amount", locator=locator))
    collected.observations.append(
        Observation(text, locator, amount, "candidate" if amount is not None else None)
    )


def _visible_pdf_box(page: Page) -> tuple[float, float, float, float]:
    left, top, right, bottom = page.mediabox
    x0, y0, x1, y1 = page.cropbox
    if page.rotation in (90, 180):
        y0, y1 = top + bottom - y1, top + bottom - y0
    if page.rotation in (180, 270):
        x0, x1 = left + right - x1, left + right - x0
    return max(left, x0), max(top, y0), min(right, x1), min(bottom, y1)


def _pdf_text_lines(page: Page, visible_box: tuple[float, float, float, float]) -> list[dict]:
    left, top, right, bottom = visible_box
    chars = []
    positions = {}
    for char in page.chars:
        x0, y0, x1, y1 = char["x0"], char["top"], char["x1"], char["bottom"]
        if page.rotation == 90:
            position = (y0, -x1, y1, -x0)
        elif page.rotation == 180:
            position = (-x1, -y1, -x0, -y0)
        elif page.rotation == 270:
            position = (-y1, x0, -y0, x1)
        else:
            position = (x0, y0, x1, y1)
        ux0, uy0, ux1, uy1 = position
        visible = x1 > left and x0 < right and y1 > top and y0 < bottom
        clipped = x0 < left or x1 > right or y0 < top or y1 > bottom
        item = {
            **char,
            "x0": ux0,
            "top": uy0,
            "x1": ux1,
            "bottom": uy1,
            "doctop": uy0,
            "upright": char["upright"] if page.rotation in (0, 180) else not char["upright"],
        }
        visible_position = (
            max(left, x0),
            max(top, y0),
            min(right, x1),
            min(bottom, y1),
            clipped,
        )
        positions[id(item)] = visible_position if visible else None
        chars.append(item)

    if not any(char["text"].strip() for char in chars):
        return []
    lines = chars_to_textmap(chars).extract_text_lines()
    visible_lines = []
    for line in lines:
        glyphs = [positions[id(char)] for char in line["chars"]]
        visible_glyphs = [box for box in glyphs if box is not None]
        if not visible_glyphs:
            continue
        if len(visible_glyphs) != len(glyphs) or any(box[4] for box in visible_glyphs):
            # Do not expose hidden text or reparse a visible tail as a complete amount.
            line["text"] = "".join(
                char["text"] if box is not None and not box[4] else "�"
                for char, box in zip(line["chars"], glyphs, strict=True)
            )
            line["clipped"] = True
        glyphs = visible_glyphs
        line["x0"] = min(box[0] for box in glyphs)
        line["top"] = min(box[1] for box in glyphs)
        line["x1"] = max(box[2] for box in glyphs)
        line["bottom"] = max(box[3] for box in glyphs)
        visible_lines.append(line)
    return visible_lines


def _read_pdf(path: Path, collected: _Collected) -> None:
    with pdfplumber.open(path) as document:
        for page in document.pages:
            visible_box = _visible_pdf_box(page)
            if visible_box[0] >= visible_box[2] or visible_box[1] >= visible_box[3]:
                collected.issues.append(NativeIssue("invalid_pdf_cropbox", page=page.page_number))
                page.close()
                continue
            lines = _pdf_text_lines(page, visible_box)
            if not lines:
                collected.issues.append(NativeIssue("no_native_text", page=page.page_number))
                page.close()
                continue
            x0, top, x1, bottom = visible_box
            width, height = x1 - x0, bottom - top
            for number, line in enumerate(lines, 1):
                box = (
                    max(0.0, (line["x0"] - x0) / width),
                    max(0.0, (line["top"] - top) / height),
                    min(1.0, (line["x1"] - x0) / width),
                    min(1.0, (line["bottom"] - top) / height),
                )
                locator = PageLocator(
                    kind="page",
                    page=page.page_number,
                    line=number,
                    bbox=box if box[0] < box[2] and box[1] < box[3] else None,
                )
                if line.get("clipped"):
                    collected.issues.append(NativeIssue("clipped_pdf_text", locator=locator))
                    collected.observations.append(Observation(line["text"], locator))
                else:
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
        DecompressionError,
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
