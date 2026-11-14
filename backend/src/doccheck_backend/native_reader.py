"""Native Office observations with contract addresses for a trusted local file."""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from unicodedata import category
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile
from zlib import error as DecompressionError

from defusedxml.common import DefusedXmlException
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.exceptions import InvalidXmlError
from docx.oxml.ns import qn
from lxml.etree import XMLSyntaxError

from doccheck_backend.contracts.locators import (
    Locator,
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
) -> None:
    if not text.strip():
        return
    amount, ambiguous = _text_amount(text, rub_column=rub_column)
    if ambiguous:
        collected.issues.append(NativeIssue("ambiguous_rub_amount", locator=locator))
    collected.observations.append(
        Observation(text, locator, amount, "candidate" if amount is not None else None)
    )


def _read_docx(path: Path, collected: _Collected) -> None:
    with ZipFile(path) as archive:
        if sum(part.file_size for part in archive.infolist()) > 128 * 1024**2:
            raise ValueError("DOCX archive exceeds the native reader limit")
    document = Document(path)
    # Check the actual main part selected by package relationships before python-docx
    # traverses its body. DOCX parts are not required to use word/document.xml.
    root = document.element
    if root.tag != qn("w:document") or len(root.findall(qn("w:body"))) != 1:
        raise ValueError("Invalid Word document structure")
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
        InvalidXmlError,
        XMLSyntaxError,
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
