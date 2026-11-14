"""Read an addressed row of a visible, ruled KФЗ table with local OCR."""

import re
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

import numpy as np
from PIL import Image

from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.page_ocr import (
    PixelBox,
    page_locator,
    recognize_crop,
    recognize_lines,
)

_GROUP_HEADER = {
    "0200": re.compile(r"оплат\w*\s+труд\w*"),
    "0300": re.compile(r"страхов\w*\s+взнос\w*"),
    "0800": re.compile(r"общепроизводствен\w*"),
    "0900": re.compile(r"общехозяйствен\w*"),
}
_AGGREGATES = {"0200", "0300"}
_CONTRACT = re.compile(
    r"\b(?:договор|контракт)\s*(?:№|No)?\s*([\w]+(?:[-/][\w]+)+)(?=$|[\s.,;:])", re.I
)
_ROW = re.compile(r"^\s*(\d+)\s*этап\s*[,.:]?\s*(\d{4})\s*(?:г\.?|год)?[.:\s—–-]*$", re.I)
_ROW_LOCATOR = re.compile(r"kfz-stage-([1-9][0-9]*)-([0-9]{4})")
_MONEY = re.compile(r"-?(?:[0-9]+|[0-9]{1,4}(?: [0-9]{3})+)[,.][0-9]{2}")


@dataclass(frozen=True)
class ReportCell:
    code: str
    locator: PageLocator
    raw: str | None
    amount: Decimal | None


def _peaks(values: np.ndarray, threshold: float) -> list[int]:
    indices = np.flatnonzero(values >= threshold)
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
    return [int(group[np.argmax(values[group])]) for group in groups if group.size]


_SIMPLE_LABELS = {
    "оплата труда": "0200",
    "затраты на оплату труда": "0200",
    "страховые взносы": "0300",
    "общепроизводственные расходы": "0800",
    "общепроизводственные затраты": "0800",
    "общехозяйственные расходы": "0900",
    "общехозяйственные затраты": "0900",
    "прочие расходы": "other",
    "итого": "total",
}
_EXPLICIT_PERIOD = re.compile(
    r"^отч[её]тный период:\s*(\d{2}\.\d{2}\.\d{4})\s*[—–-]\s*"
    r"(\d{2}\.\d{2}\.\d{4})$",
    re.I,
)
_SIMPLE_LINE = re.compile(rf"(.*?)\s+({_MONEY.pattern})$")


def _parse_money(text: str) -> Decimal | None:
    if _MONEY.fullmatch(text):
        return Decimal(text.replace(" ", "").replace(",", "."))
    return None


def read_explicit_scope(image: Image.Image) -> tuple[str, str, str] | None:
    """Return the report's own explicit interval when one pair of bounds is visible."""
    from doccheck_backend.normalization import normalize_document_date

    lines = recognize_lines(image, mode=6)
    contracts = {m[1] for line in lines for m in _CONTRACT.finditer(line.text)}
    bounds = {
        tuple(normalize_document_date(value).value for value in match.groups())
        for line in lines
        if (match := _EXPLICIT_PERIOD.fullmatch(line.text))
    }
    if len(contracts) != 1 or len(bounds) != 1:
        return None
    start, end = next(iter(bounds))
    if not start or not end or start > end:
        return None
    return next(iter(contracts)), start, end


def _simple_table(
    image: Image.Image,
    page: int,
    selected: PageLocator | None,
    contract_number: str,
    period: tuple[str, str],
) -> list[ReportCell]:
    from doccheck_backend.normalization import normalize_document_date

    if selected is not None:
        return []
    lines = recognize_lines(image, mode=6)
    contracts = {m[1] for line in lines for m in _CONTRACT.finditer(line.text)}
    if contracts != {contract_number}:
        return []
    bounds = {
        tuple(normalize_document_date(value).value for value in match.groups())
        for line in lines
        if (match := _EXPLICIT_PERIOD.fullmatch(line.text))
    }
    if bounds != {period}:
        return []
    amounts = {}
    for line in lines:
        parsed = _SIMPLE_LINE.fullmatch(line.text)
        if parsed is None:
            continue
        code = _SIMPLE_LABELS.get(parsed[1].strip(".: ").casefold())
        if code is not None:
            amounts.setdefault(code, []).append(line)
    if not {"0200", "0300", "0800", "0900"} <= amounts.keys():
        return []
    result = []
    for code, candidates in amounts.items():
        if len(candidates) != 1:
            continue
        line = candidates[0]
        raw = _SIMPLE_LINE.fullmatch(line.text)[2]
        checked = recognize_crop(image, line.box, mode=7)
        confirmed = _SIMPLE_LINE.fullmatch(" ".join(checked.split()))
        amount = _parse_money(raw)
        if confirmed is None or _parse_money(confirmed[2]) != amount:
            raw, amount = None, None
        result.append(ReportCell(code, page_locator(page, image, line.box), raw, amount))
    return result


def _column_tracks(ink: np.ndarray, horizontals: list[int]) -> list[int]:
    """Infer recurring vertical rules from bands, including bands with merged cells."""
    bands = []
    for top, bottom in zip(horizontals, horizontals[1:]):
        height = bottom - top
        if height < 14:
            continue
        band = ink[top + 4 : bottom - 4, :]
        lines = _peaks(band.sum(axis=0), len(band) * 0.78)
        # Narrow groups of strokes around a glyph cannot describe a table.
        if 3 <= len(lines) <= 25 and min(np.diff(lines)) >= ink.shape[1] * 0.012:
            bands.append(lines)
    if not bands:
        return []
    template = max(bands, key=len)
    tolerance = max(5, ink.shape[1] // 440)
    return [
        round(median(matches))
        for x in template
        if len(
            matches := [
                nearest
                for band in bands
                if abs((nearest := min(band, key=lambda col: abs(col - x))) - x) <= tolerance
            ]
        )
        >= 2
    ]


def _headers(image: Image.Image, ink: np.ndarray, xs: list[int], ys: list[int]) -> dict[str, int]:
    """Find article groups by title and code, then identify their total subcolumn."""
    content_top = ys[0]
    candidates = {}
    # Use the vertical rules that continue through the first header band to
    # locate the merged titles. A single-level header uses the same logic.
    for edge in ys[1:3]:
        band = ink[content_top + 4 : edge - 4]
        if len(band) < 20:
            continue
        rules = _peaks(band.sum(axis=0), len(band) * 0.78)
        main = [
            i
            for i, x in enumerate(xs)
            if any(abs(x - rule) <= max(6, image.width // 280) for rule in rules)
        ]
        found = {}
        for start, end in zip(main, main[1:]):
            box = (xs[start] + 6, content_top + 5, xs[end] - 6, edge - 4)
            text = " ".join(recognize_crop(image, box, mode=6).casefold().split())
            if text.strip(" .:") == "итого":
                found.setdefault("total", set()).add(start)
            for code, pattern in _GROUP_HEADER.items():
                if not re.search(rf"(?<!\d){code}(?!\d)", text) or not pattern.search(text):
                    continue
                if end == start + 1:
                    found.setdefault(code, set()).add(start)
                elif code in _AGGREGATES:
                    for header_bottom in ys[2:5]:
                        if header_bottom - edge < 45:
                            continue
                        label_box = (xs[start] + 6, edge + 5, xs[start + 1] - 6, header_bottom - 5)
                        label = " ".join(
                            recognize_crop(image, label_box, mode=6).casefold().split()
                        )
                        if pattern.search(label) and re.search(r"\bвсего\b", label):
                            found.setdefault(code, set()).add(start)
                            break
        for code, indices in found.items():
            candidates.setdefault(code, set()).update(indices)
        if all(code in candidates for code in (*_GROUP_HEADER, "total")):
            break
    return {code: next(iter(indices)) for code, indices in candidates.items() if len(indices) == 1}


def _row_band(
    image: Image.Image, locator: PageLocator | None, xs: list[int], ys: list[int]
) -> tuple[int, int, str] | None:
    if locator is not None and locator.bbox is not None:
        left, top, right, bottom = locator.bbox
        matches = [
            (y0, y1)
            for y0, y1 in zip(ys, ys[1:])
            if y0 <= (top + bottom) * image.height / 2 < y1
            and left * image.width < xs[2]
            and right * image.width > xs[0]
        ]
        if len(matches) != 1:
            return None
        selected = matches[0]
    else:
        selected = None
    selector = _ROW_LOCATOR.fullmatch(locator.fragment_id or "") if locator else None
    if locator and locator.bbox is None and not selector:
        return None
    candidates = []
    for top, bottom in zip(ys, ys[1:]):
        if bottom - top < 13 or (selected and (top, bottom) != selected):
            continue
        label = recognize_crop(image, (xs[0] + 4, top + 3, xs[2] - 4, bottom - 3))
        match = _ROW.fullmatch(" ".join(label.casefold().split()))
        if match and (selector is None or match.groups() == selector.groups()):
            candidates.append((top, bottom, label))
    return candidates[0] if len(candidates) == 1 else None


def _read_amount(image: Image.Image, box: PixelBox) -> tuple[str | None, Decimal | None]:
    left, top, right, bottom = box
    readings = []
    for pad in (3, 5):
        raw = " ".join(
            recognize_crop(
                image, (left + pad, top + pad, right - pad, bottom - pad), numeric=True
            ).split()
        )
        if _MONEY.fullmatch(raw):
            readings.append((raw, Decimal(raw.replace(" ", "").replace(",", "."))))
    if len(readings) == 2 and readings[0][1] == readings[1][1]:
        return readings[0]
    return None, None


def read_report_row(
    image: Image.Image,
    page: int,
    selected: PageLocator | None,
    contract_number: str,
    period: tuple[str, str] | None = None,
) -> list[ReportCell]:
    """Return values only when the report contract, header and row can be located."""
    if selected is not None and selected.page != page:
        return []
    ink = np.asarray(image.convert("L")) < 190
    width, height = image.size
    ys = _peaks(ink[:, width // 8 : width * 7 // 8].sum(axis=1), width * 0.43)
    xs = _column_tracks(ink, ys) if 4 <= len(ys) <= 60 else []
    if len(xs) < 6 or xs[-1] - xs[0] < width * 0.55:
        return _simple_table(image, page, selected, contract_number, period) if period else []
    header = image.crop((0, 0, width, ys[0]))
    contracts = {
        match[1] for line in recognize_lines(header) for match in _CONTRACT.finditer(line.text)
    }
    if contracts != {contract_number}:
        return []
    band = _row_band(image, selected, xs, ys)
    if band is None:
        return []
    top, bottom, _ = band
    cols = _headers(image, ink, xs, ys)
    cells = []
    for code, col in cols.items():
        box = (xs[col], top, xs[col + 1], bottom)
        raw, amount = _read_amount(image, box)
        cells.append(ReportCell(code, page_locator(page, image, box), raw, amount))
    return cells
