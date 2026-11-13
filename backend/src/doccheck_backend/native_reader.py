"""Native observations with contract addresses for a single trusted local file."""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from unicodedata import category
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

_GROUP_SPACES = " \u00a0\u2009\u202f"
_SPACE_CHARS = "\t \u00a0\u1680" + "".join(map(chr, range(0x2000, 0x200B))) + "\u202f\u205f\u3000"
_SPACE = rf"[{_SPACE_CHARS}]"
_GROUP_SPACE = rf"[{_GROUP_SPACES}]"
_SIGNS = "+−-"
_LINE_BREAKS = "\r\n\v\f\u0085\u2028\u2029"
_DIGITS = "0123456789"
_NUMBER_CHARACTERS = _DIGITS + ".,"
_NUMBER = re.compile(
    rf"(?P<sign>[+−-]?){_SPACE}*"
    rf"(?P<integer>[0-9]{{1,3}}(?:{_GROUP_SPACE}[0-9]{{3}})+|[0-9]+)"
    r"(?P<fraction>[.,][0-9]+)?"
)
_RUB_UNITS = ("рублей", "рубля", "рубль", "руб.", "руб", "rub", "р.", "₽")
_KOPECK_UNITS = ("копеек", "копейки", "копейка", "коп.", "коп")
_RUB_START = re.compile(r"[рr₽]", re.IGNORECASE)
_NON_AMOUNT_LABEL = re.compile(
    r"^\s*(?:код\s+статьи|договор|контракт|номер\s+документа|ИНН|КПП|дата|contract)\b",
    re.IGNORECASE,
)
_MONEY_HEADER = re.compile(r"^(?:сумма|стоимость)\s*[,\s(]+(?:руб\.?|₽|rub)\)?$", re.I)


@dataclass
class _Collected:
    observations: list[Observation] = field(default_factory=list)
    issues: list[NativeIssue] = field(default_factory=list)


def _preceding_symbol(text: str, start: int) -> int:
    if not start:
        return start
    symbol = text[start - 1]
    if symbol in _SIGNS:
        return start - 1
    if category(symbol) != "Pd":
        return start
    # An en or em dash separates a written label only when spaced on both sides.
    if symbol in "–—" and text[start] in _SPACE_CHARS:
        before = start - 1
        while before and text[before - 1] in _SPACE_CHARS:
            before -= 1
        if 0 < before < start - 1 and text[before - 1].isalpha():
            return start
    # Retain ambiguous sign-like punctuation so number validation rejects the token.
    return start - 1


def _token_space(char: str) -> bool:
    return char in _SPACE_CHARS + _LINE_BREAKS or category(char) == "Cf"


def _numeric_run_character(char: str) -> bool:
    return char in _NUMBER_CHARACTERS or _token_space(char)


def _match_unit(text: str, start: int, units: tuple[str, ...]) -> tuple[int, bool] | None:
    # Fixed-size vocabulary. Spaces or formatting within a recognized unit
    # preserve the candidate boundary but make it unsafe to normalize.
    for unit in units:
        index = start
        interrupted = False
        for offset, letter in enumerate(unit):
            if offset:
                while index < len(text) and _token_space(text[index]):
                    interrupted = True
                    index += 1
            if index == len(text) or text[index].casefold() != letter:
                break
            index += 1
        else:
            if index == len(text) or not (text[index].isalnum() or text[index] == "_"):
                return index, interrupted
            if index < len(text) and text[index] in _DIGITS and unit.endswith("."):
                return index, interrupted
    return None


def _possible_kopecks(text: str, start: int) -> tuple[str, bool]:
    index = start
    while index < len(text) and _token_space(text[index]):
        index += 1
    token_start = index
    if index == len(text) or text[index] not in _NUMBER_CHARACTERS + _SIGNS:
        return "", False
    if text[index] in _SIGNS:
        index += 1
    token_end = index
    while index < len(text) and _numeric_run_character(text[index]):
        if text[index] in _NUMBER_CHARACTERS:
            token_end = index + 1
        index += 1
    suffix = _match_unit(text, index, _KOPECK_UNITS)
    if suffix is None:
        return "", False
    # Validate the whole run, so a split or malformed kopeck group cannot disappear.
    digits = text[token_start:token_end]
    gap = text[start:token_start] + text[token_end:index]
    return digits, suffix[1] or not re.fullmatch(r"[0-9]{1,2}", digits) or any(
        char not in _SPACE_CHARS for char in gap
    )


def _rub_tokens(text: str) -> list[tuple[str, str]]:
    matches = []
    # Each reverse scan stops at the first non-numeric character. Runs between currency
    # markers cannot overlap, even when the document has a long invalid grouping.
    currency_end = 0
    for marker in _RUB_START.finditer(text):
        end = marker.start()
        if end < currency_end:
            continue
        currency = _match_unit(text, end, _RUB_UNITS)
        if currency is None:
            continue
        currency_end, interrupted_currency = currency
        last = end
        while last and _token_space(text[last - 1]):
            last -= 1
        if not last or text[last - 1] not in _DIGITS:
            continue
        start = last
        while start and _numeric_run_character(text[start - 1]):
            start -= 1
        start = _preceding_symbol(text, start)
        # A line break before the entire token is harmless. A break inside the
        # numeric run or between its sign and digits is rejected by _NUMBER.
        numeral = text[start:last].lstrip(_SPACE_CHARS + _LINE_BREAKS)
        # Punctuation attached to a label ends the prose, not the numeral.
        # A separator after a digit or before a fractional digit stays in the token.
        if (
            start > 0
            and text[start - 1].isalpha()
            and text[start] in ".,"
            and text[start + 1] in _SPACE_CHARS
        ):
            start += 1
            numeral = text[start:last].lstrip(_SPACE_CHARS)
        if (
            start
            and text[start] not in _SPACE_CHARS + _LINE_BREAKS
            and (
                text[start - 1].isalnum()
                or text[start - 1] in "_./," + _SIGNS
                or category(text[start - 1]) in ("Pd", "Cf")
            )
        ):
            numeral = ""
        kopecks, interrupted = _possible_kopecks(text, currency_end)
        if (
            interrupted_currency
            or interrupted
            or any(char not in _SPACE_CHARS for char in text[last:end])
        ):
            numeral = ""
        matches.append((numeral, kopecks))
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
    collected: _Collected,
    text: str,
    locator: Locator,
    *,
    rub_column: bool = False,
    interrupted: bool = False,
) -> None:
    if not text.strip():
        return
    amount, ambiguous = (None, True) if interrupted else _text_amount(text, rub_column=rub_column)
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
        line["reading_box"] = (line["x0"], line["top"], line["x1"], line["bottom"])
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


def _adjacent_pdf_lines(
    previous: dict, current: dict, *, alignment: Literal["left", "right", "either"]
) -> bool:
    if current.get("clipped") or previous.get("clipped"):
        return False
    px0, py0, px1, py1 = previous["reading_box"]
    cx0, cy0, cx1, cy1 = current["reading_box"]
    height = max(py1 - py0, cy1 - cy0)
    overlap = min(px1, cx1) - max(px0, cx0)
    left = abs(cx0 - px0) <= 1.5 * height
    right = abs(cx1 - px1) <= height / 2
    aligned = (alignment != "right" and left) or (alignment != "left" and right)
    return 0 < cy0 - py0 <= 1.8 * height and overlap >= 0.5 * min(px1 - px0, cx1 - cx0) and aligned


def _pdf_dividers(page: Page) -> list[tuple[float, float, float]]:
    dividers = []
    for edge in page.edges:
        if page.rotation in (90, 270):
            if edge["orientation"] != "v":
                continue
            x = edge["x0"]
            top, bottom = edge["top"], edge["bottom"]
            dividers.append((top, bottom, -x) if page.rotation == 90 else (-bottom, -top, x))
        elif edge["orientation"] == "h":
            left, right, y = edge["x0"], edge["x1"], edge["top"]
            dividers.append((-right, -left, -y) if page.rotation == 180 else (left, right, y))
    return dividers


def _split_by_divider(previous: dict, current: dict, dividers: list) -> bool:
    px0, _, px1, py1 = previous["reading_box"]
    cx0, cy0, cx1, _ = current["reading_box"]
    left, right = max(px0, cx0), min(px1, cx1)
    return any(x0 <= left and right <= x1 and py1 <= y <= cy0 for x0, x1, y in dividers)


def _wrapped_pdf_lines(lines: list[dict], dividers: list) -> set[int]:
    """Mark plausibly interrupted values in reading coordinates, without joining their text."""
    interrupted = set()
    for index, (previous, current) in enumerate(zip(lines, lines[1:])):
        if current.get("clipped") or previous.get("clipped"):
            continue
        tail = current["text"].lstrip(_SPACE_CHARS)
        if not tail:
            continue
        before = previous["text"].rstrip(_SPACE_CHARS)
        if not before:
            continue
        if index + 2 < len(lines) and re.fullmatch(r"[0-9]{1,2}", tail):
            final = lines[index + 2]
            suffix = final["text"].strip(_SPACE_CHARS)
            unit = _match_unit(suffix, 0, _KOPECK_UNITS)
            if (
                unit is not None
                and unit[0] == len(suffix)
                and any(
                    _adjacent_pdf_lines(previous, current, alignment=side)
                    and _adjacent_pdf_lines(current, final, alignment=side)
                    for side in ("left", "right")
                )
                and not _split_by_divider(previous, current, dividers)
                and not _split_by_divider(current, final, dividers)
                and any(
                    not numeral and cents
                    for numeral, cents in _rub_tokens(before + "\n" + tail + "\n" + suffix)
                )
            ):
                interrupted.add(index)
                continue
        decimals = tail[0] in _DIGITS and before[-1] in _NUMBER_CHARACTERS + _SIGNS
        # Inspect the two lines only for a boundary split. Keep their own source
        # addresses and never promote a value from their concatenated text.
        kopecks = bool(_possible_kopecks(tail, 0)[0] and _rub_tokens(before))
        if not kopecks and not decimals:
            # The amount may have its ruble unit on the first line while only
            # the kopeck suffix (or a part of it) wraps onto the second line.
            joined = before + "\n" + tail
            kopecks = bool(
                _rub_tokens(before)
                and any(not numeral and cents for numeral, cents in _rub_tokens(joined))
            )
        tail_amounts = _rub_tokens(tail) if decimals and not kopecks else []
        if not (kopecks or tail_amounts):
            continue
        alignment: Literal["left", "either"] = "either" if kopecks else "left"
        if tail_amounts:
            if _NON_AMOUNT_LABEL.match(before):
                continue
            # Numeric suffixes of identifiers (e.g. 31-001) are not amounts.
            end = len(before)
            start = end
            while start and _numeric_run_character(before[start - 1]):
                start -= 1
            start = _preceding_symbol(before, min(start, end - 1))
            if start and (before[start - 1].isalnum() or before[start - 1] in "_./," + _SIGNS):
                continue
            if not any(char in _DIGITS + _SIGNS for char in before[start:]):
                continue
            if len(tail_amounts) == 1:
                numeral, _ = tail_amounts[0]
                prefix = before[start:].lstrip(_SPACE_CHARS)
                # A shared right edge alone does not connect table rows. Require the
                # line to start with a continuation of a decimal, grouped integer or sign.
                if numeral and tail.startswith(numeral):
                    gap = "" if prefix.endswith(tuple(".," + _SIGNS)) else " "
                    if _NUMBER.fullmatch(prefix + gap + numeral):
                        alignment = "either"
        if not _adjacent_pdf_lines(previous, current, alignment=alignment):
            continue
        if _split_by_divider(previous, current, dividers):
            continue
        interrupted.add(index + (0 if kopecks else 1))
    return interrupted


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
            interrupted = _wrapped_pdf_lines(lines, _pdf_dividers(page))
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
                    _observe(
                        collected, line["text"], locator, interrupted=number - 1 in interrupted
                    )
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
