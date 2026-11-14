"""Bounded, read-only representations for the document pane."""

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from io import BytesIO
from threading import Lock
from zipfile import BadZipFile, ZipFile

import pypdfium2 as pdfium
from defusedxml.common import DefusedXmlException
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.table import _Rows
from docx.text.paragraph import Paragraph
from lxml.etree import XMLSyntaxError
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel

MAX_PREVIEW_BYTES = 16 * 1024**2
_MAX_UNPACKED_BYTES = 48 * 1024**2
_MAX_WORD_BLOCKS = 1500
_MAX_WORD_CELLS = 12_000
_MAX_RESPONSE_TEXT = 500_000
SHEET_ROWS = 60
SHEET_COLUMNS = 20
_PDFIUM_LOCK = Lock()


class SheetPreview(BaseModel):
    sheets: list[str]
    sheet: str
    row: int
    column: int
    last_row: int
    last_column: int
    rows: list[list[str]]


class WordCell(BaseModel):
    column: int
    span: int
    text: str


class WordParagraph(BaseModel):
    paragraph: int
    text: str
    heading: bool = False


class WordTable(BaseModel):
    table: int
    rows: list[list[WordCell]]


class WordPreview(BaseModel):
    blocks: list[WordParagraph | WordTable]
    truncated: bool


def _check_office_package(data: bytes) -> None:
    with ZipFile(BytesIO(data)) as archive:
        if sum(part.file_size for part in archive.infolist()) > _MAX_UNPACKED_BYTES:
            raise ValueError("Office package exceeds the preview limit")


def _display_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (date, time, datetime)):
        return value.isoformat()
    if isinstance(value, (str, int, float, timedelta)):
        return str(value)
    # Array formulas expose their source expression without executing it.
    formula = getattr(value, "text", None)
    return formula if isinstance(formula, str) else ""


def sheet_preview(data: bytes, name: str | None, row: int, column: int) -> SheetPreview:
    _check_office_package(data)
    with BytesIO(data) as stream:
        book = load_workbook(stream, read_only=True, data_only=False, keep_links=False)
        try:
            sheets = [sheet.title for sheet in book.worksheets]
            if not sheets:
                raise ValueError("Workbook has no sheets")
            name = name or sheets[0]
            if name not in sheets:
                raise KeyError(name)
            sheet = book[name]
            bottom = min(row + SHEET_ROWS - 1, max(row, sheet.max_row or row))
            right = min(column + SHEET_COLUMNS - 1, max(column, sheet.max_column or column))
            columns = right - column + 1
            rows = [
                [_display_cell(value)[:400] for value in values]
                for values in sheet.iter_rows(
                    min_row=row, max_row=bottom, min_col=column, max_col=right, values_only=True
                )
            ]
            rows.extend([[""] * columns for _ in range(bottom - row + 1 - len(rows))])
            return SheetPreview(
                sheets=sheets,
                sheet=name,
                row=row,
                column=column,
                last_row=max(bottom, sheet.max_row or 1),
                last_column=max(right, sheet.max_column or 1),
                rows=rows,
            )
        finally:
            book.close()


def word_preview(data: bytes) -> WordPreview:
    _check_office_package(data)
    document = Document(BytesIO(data))
    if document.element.tag != qn("w:document") or len(document.element.findall(qn("w:body"))) != 1:
        raise ValueError("Invalid Word document")
    blocks: list[WordParagraph | WordTable] = []
    paragraph_id = table_id = text_size = cell_count = 0
    for block in document.iter_inner_content():
        if len(blocks) >= _MAX_WORD_BLOCKS or text_size >= _MAX_RESPONSE_TEXT:
            return WordPreview(blocks=blocks, truncated=True)
        if isinstance(block, Paragraph):
            paragraph_id += 1
            text = block.text
            if text_size + len(text) > _MAX_RESPONSE_TEXT:
                return WordPreview(blocks=blocks, truncated=True)
            text_size += len(text)
            style = block.style.name if block.style is not None else ""
            blocks.append(
                WordParagraph(
                    paragraph=paragraph_id,
                    heading=style.startswith(("Heading", "Title")),
                    text=text,
                )
            )
            continue

        table_id += 1
        rows = []
        for cells in _word_rows(block.rows):
            cell_count += len(cells)
            text_size += sum(len(cell.text) for cell in cells)
            if cell_count > _MAX_WORD_CELLS or text_size > _MAX_RESPONSE_TEXT:
                if rows:
                    blocks.append(WordTable(table=table_id, rows=rows))
                return WordPreview(blocks=blocks, truncated=True)
            rows.append(cells)
        blocks.append(WordTable(table=table_id, rows=rows))
    return WordPreview(blocks=blocks, truncated=False)


def _word_rows(rows: _Rows) -> Iterator[list[WordCell]]:
    for row in rows:
        cells: list[WordCell] = []
        if row.grid_cols_before:
            cells.append(WordCell(column=1, span=row.grid_cols_before, text=""))
        previous = None
        for column, cell in enumerate(row.cells, row.grid_cols_before + 1):
            if previous is not None and previous == cell._tc:
                cells[-1].span += 1
                continue
            cells.append(WordCell(column=column, span=1, text=cell.text))
            previous = cell._tc
        yield cells


def pdf_page_preview(data: bytes, page: int) -> tuple[bytes, int]:
    # PDFium accepts bytes and does not need to resolve the stored path a second time.
    with _PDFIUM_LOCK, pdfium.PdfDocument(data) as pdf:
        if not 1 <= page <= len(pdf):
            raise IndexError
        source = pdf[page - 1]
        try:
            width, height = source.get_size()
            if width <= 0 or height <= 0:
                raise ValueError("Invalid PDF page size")
            # Keep the displayed page and normalized coordinates in the same frame.
            bitmap = source.render(scale=min(2, 1600 / max(width, height)), may_draw_forms=False)
            try:
                output = BytesIO()
                bitmap.to_pil().save(output, format="PNG")
                return output.getvalue(), len(pdf)
            finally:
                bitmap.close()
        finally:
            source.close()


PREVIEW_ERRORS = (
    BadZipFile,
    DefusedXmlException,
    InvalidFileException,
    PackageNotFoundError,
    XMLSyntaxError,
    OverflowError,
    OSError,
    UnicodeError,
    ValueError,
    NotImplementedError,
    pdfium.PdfiumError,
)
