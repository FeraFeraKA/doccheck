"""Read original OOXML numbers and a restricted local SUM without running Excel."""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal
from xml.etree.ElementTree import Element
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring

from doccheck_backend.contracts.locators import SheetLocator
from doccheck_backend.native_observations import NativeDocument, NativeIssue, Observation

_SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_OFFICE_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PART_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_COORDINATE = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})")
_SUM = re.compile(
    r"\s*SUM\s*\(\s*(\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})\s*:\s*"
    r"(\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})\s*\)\s*",
    re.IGNORECASE,
)
_EXCEL_DECIMAL = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?(?:[Ee][+-]?[0-9]+)?")
_EXTERNAL_FORMULA = re.compile(r"\[[^\[\]]+\][^\[\]!(),]*!|\|.+!")
_MAX_XML_PART = 64 * 1024**2
_MAX_SUM_CELLS = 100_000


@dataclass(frozen=True)
class _Cell:
    raw: str
    kind: str
    numeric: Decimal | None = None
    formula: bool = False
    has_cache: bool = False


def _part(archive: ZipFile, path: str) -> Element:
    with archive.open(path) as stream:
        data = stream.read(_MAX_XML_PART + 1)
    if len(data) > _MAX_XML_PART:
        raise ValueError("OOXML part exceeds the native reader limit")
    return fromstring(data, forbid_dtd=True)


def _position(value: str) -> tuple[int, int]:
    match = _COORDINATE.fullmatch(value)
    if match is None:
        raise ValueError("Invalid spreadsheet address")
    column = 0
    for letter in match[1]:
        column = 26 * column + ord(letter) - ord("A") + 1
    row = int(match[2])
    if column > 16_384 or row > 1_048_576:
        raise ValueError("Spreadsheet address is outside the workbook grid")
    return column, row


def _numeric(text: str) -> Decimal | None:
    if len(text) > 128 or not _EXCEL_DECIMAL.fullmatch(text):
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    # Bound scaling of source numbers to Excel's usable exponent domain.
    if not -324 <= amount.as_tuple().exponent <= 308 or amount.adjusted() > 308:
        return None
    return amount


def _text_runs(element: Element) -> str:
    chunks = []
    for child in element:
        if child.tag == _SHEET + "t":
            chunks.append(child.text or "")
        elif child.tag == _SHEET + "r":
            chunks.append(child.findtext(_SHEET + "t") or "")
    return "".join(chunks)


def _cells(root: Element, shared_strings: list[str]) -> dict[str, _Cell]:
    if root.tag != _SHEET + "worksheet":
        raise ValueError("Invalid worksheet")
    cells = {}
    for node in root.findall(f"{_SHEET}sheetData/{_SHEET}row/{_SHEET}c"):
        key = node.attrib["r"]
        _position(key)
        if key in cells:
            raise ValueError("Duplicate spreadsheet address")
        kind = node.get("t", "n")
        value = node.findtext(_SHEET + "v") or ""
        formula = node.find(_SHEET + "f")
        if formula is not None:
            content = formula.text or ""
            expression = content if content.startswith("=") else "=" + content
            cells[key] = _Cell(
                expression,
                kind,
                _numeric(value) if kind == "n" else None,
                formula=True,
                has_cache=bool(value),
            )
        elif kind == "s":
            index = int(value)
            if not 0 <= index < len(shared_strings):
                raise ValueError("Invalid shared string index")
            cells[key] = _Cell(shared_strings[index], kind)
        elif kind == "inlineStr":
            inline = node.find(_SHEET + "is")
            if inline is not None:
                cells[key] = _Cell(_text_runs(inline), kind)
        elif value:
            cells[key] = _Cell(value, kind, _numeric(value) if kind == "n" else None)
    return cells


def _normalized_title(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split())


def _matches_title(cells: dict[str, _Cell], expected: dict[str, str]) -> bool:
    return all(
        address in cells and _normalized_title(cells[address].raw) == title
        for address, title in expected.items()
    )


def _money_template(cells: dict[str, _Cell]) -> tuple[str, set[str]] | None:
    if _matches_title(
        cells,
        {
            "A1": "расчетная ведомость по оплате труда",
            "A5": "код статьи",
            "B5": "вид начисления",
            "C5": "сумма, руб.",
            "B8": "итого",
        },
    ):
        return "C8", {"C6", "C7"}
    if _matches_title(
        cells,
        {
            "A1": "расчет страховых взносов",
            "A5": "база начислений, руб.",
            "B5": "начислено взносов, руб.",
            "C5": "код статьи",
        },
    ):
        return "B6", set()
    return None


def _sum_candidate(
    address: str, formula: str, cells: dict[str, _Cell]
) -> tuple[Decimal | None, tuple[str, ...], str | None]:
    if _EXTERNAL_FORMULA.search(formula):
        return None, (), "external_formula_reference"
    match = _SUM.fullmatch(formula[1:])
    if match is None:
        return None, (), "unsupported_formula"
    start, end = (part.replace("$", "").upper() for part in match.groups())
    try:
        x1, y1 = _position(start)
        x2, y2 = _position(end)
    except ValueError:
        return None, (), "invalid_sum_range"
    if not x1 <= x2 or not y1 <= y2 or (x2 - x1 + 1) * (y2 - y1 + 1) > _MAX_SUM_CELLS:
        return None, (), "invalid_sum_range"
    components = []
    columns = [_column_name(column) for column in range(x1, x2 + 1)]
    for row in range(y1, y2 + 1):
        for column in columns:
            key = f"{column}{row}"
            current = cells.get(key)
            if current is None:
                continue
            if key == address or current.formula or current.kind == "e":
                return None, (), "unsupported_sum_input"
            if current.kind == "n":
                if current.numeric is None:
                    return None, (), "invalid_numeric_cell"
                components.append((key, current.numeric))
    if not components:
        return None, (), "missing_sum_input"

    # More than the full supported exponent range and the largest range count.
    with localcontext() as context:
        context.prec = 650
        result = sum((value for _, value in components), Decimal(0))
    return result, tuple(key for key, _ in components), None


def _column_name(number: int) -> str:
    column = ""
    while number:
        number, index = divmod(number - 1, 26)
        column = chr(ord("A") + index) + column
    return column


def _read_sheet(
    title: str, cells: dict[str, _Cell], observations: list[Observation], issues: list[NativeIssue]
) -> None:
    template = _money_template(cells)
    total, components = template if template is not None else (None, set())
    sheet_observations = {}
    for address, cell in cells.items():
        locator = SheetLocator(kind="sheet", sheet=title, range=address)
        if cell.formula:
            amount, inputs, issue = _sum_candidate(address, cell.raw, cells)
            if (
                template is not None
                and total == address
                and components
                and set(inputs) != components
            ):
                amount, inputs = None, ()
                issue = issue or "unexpected_total_components"
            if issue is not None:
                issues.append(NativeIssue(issue, locator=locator))
            if cell.has_cache and cell.numeric is None:
                issues.append(NativeIssue("invalid_formula_cache", locator=locator))
            elif amount is not None and cell.numeric is not None and amount != cell.numeric:
                issues.append(NativeIssue("formula_cache_mismatch", locator=locator))
            observation = Observation(
                cell.raw,
                locator,
                amount=amount,
                amount_role=_amount_role(address, amount, total, components, formula=True),
                cached_value=cell.numeric,
                component_locators=tuple(
                    SheetLocator(kind="sheet", sheet=title, range=key) for key in inputs
                ),
            )
        else:
            if cell.kind == "e" or (cell.kind == "n" and cell.numeric is None):
                issues.append(NativeIssue("invalid_numeric_cell", locator=locator))
            observation = Observation(
                cell.raw,
                locator,
                cell.numeric,
                _amount_role(address, cell.numeric, total, components),
            )
        sheet_observations[address] = observation

    if total is not None and (
        total not in sheet_observations or sheet_observations[total].amount_role != "total"
    ):
        issues.append(
            NativeIssue(
                "missing_template_total",
                locator=SheetLocator(kind="sheet", sheet=title, range=total),
            )
        )
    observations.extend(sheet_observations.values())


def _amount_role(
    address: str,
    amount: Decimal | None,
    total: str | None,
    components: set[str],
    *,
    formula: bool = False,
) -> Literal["candidate", "component", "total", "basis"] | None:
    if amount is None:
        return None
    if address == total and (formula or not components):
        return "total"
    if total == "B6" and address == "A6":
        return "basis"
    if address in components:
        return "component"
    return "candidate"


def read_workbook(path: Path | BinaryIO) -> NativeDocument:
    observations: list[Observation] = []
    issues: list[NativeIssue] = []
    with ZipFile(path) as archive:
        workbook = _part(archive, "xl/workbook.xml")
        if workbook.tag != _SHEET + "workbook":
            raise ValueError("Invalid workbook")
        rels = _part(archive, "xl/_rels/workbook.xml.rels")
        relations = {
            rel.attrib["Id"]: rel.attrib for rel in rels.findall(_PART_REL + "Relationship")
        }
        if workbook.find(_SHEET + "externalReferences") is not None or any(
            relation["Type"].endswith("/externalLink") for relation in relations.values()
        ):
            issues.append(NativeIssue("external_workbook_reference"))
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = [
                _text_runs(item)
                for item in _part(archive, "xl/sharedStrings.xml").findall(_SHEET + "si")
            ]
        sheets = workbook.findall(f"{_SHEET}sheets/{_SHEET}sheet")
        if not sheets:
            raise ValueError("Empty workbook sheet list")
        for sheet in sheets:
            relation = relations[sheet.attrib[_OFFICE_REL + "id"]]
            target = PurePosixPath(relation["Target"])
            member = (
                target.relative_to("/") if target.is_absolute() else PurePosixPath("xl") / target
            )
            if (
                relation.get("TargetMode") == "External"
                or not relation["Type"].endswith("/worksheet")
                or not member.is_relative_to("xl/worksheets")
                or ".." in member.parts
            ):
                issues.append(NativeIssue("unsupported_sheet_reference"))
                continue
            _read_sheet(
                sheet.attrib["name"],
                _cells(_part(archive, str(member)), shared),
                observations,
                issues,
            )
    if not observations and not issues:
        issues.append(NativeIssue("no_native_text"))
    return NativeDocument(tuple(observations), tuple(issues))
