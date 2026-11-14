"""Read an addressed row of a visible, ruled KФЗ table with local OCR."""

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

import numpy as np
from bench.e2e_v32_20261114.articles import (
    ARTICLE_CODE_TOKEN,
    ARTICLE_CODES,
    LEGACY_CODES,
    REPORT_CODES,
    REPORT_ROWS,
    report_category,
)
from PIL import Image

from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.normalization import normalize_document_date
from doccheck_backend.page_ocr import (
    PixelBox,
    page_locator,
    recognize_crop,
    recognize_lines,
)

_GROUP_HEADER = {
    "0100": re.compile(r"материальн\w*\s+(?:затрат|расход)\w*"),
    "0200": re.compile(r"оплат\w*\s+труд\w*"),
    "0300": re.compile(r"страхов\w*\s+взнос\w*"),
    "0400": re.compile(r"подготов\w*\s+и\s+освоен\w*\s+производств\w*"),
    "0500": re.compile(r"специальн\w*\s+технологическ\w*\s+оснастк\w*"),
    "0600": re.compile(r"специальн\w*\s+оборудован\w*\s+для\s+(?:научн|экспериментальн)\w*"),
    "0700": re.compile(r"специальн\w*\s+(?:затрат|расход)\w*"),
    "0800": re.compile(r"общепроизводствен\w*"),
    "0900": re.compile(r"общехозяйствен\w*"),
    "1200": re.compile(r"(?:работ\w*|услуг\w*)\b.*\bсторонн\w*\s+организац\w*"),
}
_AGGREGATES = {"0100", "0200", "0300", "0400"}
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


@dataclass(frozen=True)
class ReportReading:
    cells: list[ReportCell]
    complete: bool


def _peaks(values: np.ndarray, threshold: float) -> list[int]:
    indices = np.flatnonzero(values >= threshold)
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1)
    return [int(group[np.argmax(values[group])]) for group in groups if group.size]


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


def _money_spacing(text: str) -> str:
    # Tesseract can separate the decimal separator from the last two digits.
    return re.sub(r"(?<=\d)\s*([,.])\s*(?=\d{2}$)", r"\1", " ".join(text.split()))


def read_explicit_scope(image: Image.Image) -> tuple[str, str, str] | None:
    """Return the report's own explicit interval when one pair of bounds is visible."""
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
) -> ReportReading | None:
    if selected is not None:
        return None
    lines = recognize_lines(image, mode=6)
    contracts = {m[1] for line in lines for m in _CONTRACT.finditer(line.text)}
    if contracts != {contract_number}:
        return None
    bounds = {
        tuple(normalize_document_date(value).value for value in match.groups())
        for line in lines
        if (match := _EXPLICIT_PERIOD.fullmatch(line.text))
    }
    if bounds != {period}:
        return None
    amounts = {}
    conflicts = False
    for line in lines:
        parsed = _SIMPLE_LINE.fullmatch(_money_spacing(line.text))
        if parsed is None:
            continue
        category = report_category(parsed[1])
        if category is not None:
            code = REPORT_ROWS[category][0] or category
            amounts.setdefault(code, []).append((line, parsed[1], parsed[2]))
        elif ARTICLE_CODE_TOKEN.search(parsed[1]):
            conflicts = True
    if not amounts:
        return None
    result = []
    for code, candidates in amounts.items():
        if len(candidates) != 1:
            continue
        line, label, raw = candidates[0]
        checked = recognize_crop(image, line.box, mode=7)
        confirmed = _SIMPLE_LINE.fullmatch(_money_spacing(checked))
        amount = _parse_money(raw)
        if (
            confirmed is None
            or report_category(confirmed[1]) != report_category(label)
            or _parse_money(confirmed[2]) != amount
        ):
            raw, amount = None, None
        result.append(ReportCell(code, page_locator(page, image, line.box), raw, amount))
    return ReportReading(
        result,
        not conflicts
        and _complete_codes({cell.code for cell in result})
        and len(result) == len(amounts),
    )


def _complete_codes(codes: set[str]) -> bool:
    return "total" in codes and LEGACY_CODES <= codes


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


def _numeric_header_code(image: Image.Image, box: PixelBox, code: str) -> bool:
    left, top, right, bottom = box
    # OCR may read a zero as punctuation in a Cyrillic line. Re-read just the
    # numeric tail, keeping the original table boundary for wider characters.
    for line in recognize_lines(image.crop(box), mode=6):
        token = re.search(r"(?<!\d)([0-9][0-9()OoОо]{2,3})\)*$", line.text)
        if token is None or not token[1].startswith(code[:2]):
            continue
        x0, y0, x1, y1 = line.box
        height = y1 - y0
        end = min(x1 + 5, right - left + 5)
        for width in (2.4, 2.8):
            start = max(x0, x1 - round(height * width))
            code_box = (
                left + start,
                max(top, top + y0 - 5),
                left + end,
                min(bottom, top + y1 + 5),
            )
            if recognize_crop(image, code_box, mode=7, numeric=True).strip() == code:
                return True
    return False


def _headers(image: Image.Image, ink: np.ndarray, xs: list[int], ys: list[int]) -> dict[str, int]:
    """Find article groups by title and code, then identify their total subcolumn."""
    content_top = ys[0]
    candidates = {}
    uncertain = set()
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
            raw = recognize_crop(image, box, mode=6).casefold()
            text = " ".join(re.sub(r"([-–—])\s*\n\s*(?=[а-яё])", r"\1", raw).split())
            category = report_category(text)
            code = (REPORT_ROWS[category][0] or category) if category else None
            matching_labels = {
                code for code, pattern in _GROUP_HEADER.items() if pattern.search(text)
            }
            visible_codes = set(ARTICLE_CODE_TOKEN.findall(text))
            # An exact detail label takes precedence over a phrase shared
            # with its parent article (for example, 0402 and 0400).
            if code in REPORT_CODES and code not in ARTICLE_CODES:
                if end == start + 1:
                    found.setdefault(code, set()).add(start)
                continue
            if (
                matching_labels
                and visible_codes - matching_labels
                and (code is None or not visible_codes <= {code})
            ):
                uncertain.update(matching_labels | visible_codes)
                continue
            if code and end == start + 1 and (code not in LEGACY_CODES or code in visible_codes):
                found.setdefault(code, set()).add(start)
            for code in matching_labels:
                pattern = _GROUP_HEADER[code]
                if code not in visible_codes:
                    if visible_codes or len(matching_labels) != 1:
                        continue
                    if code in LEGACY_CODES:
                        continue
                    if code != "0100" and not _numeric_header_code(image, box, code):
                        uncertain.add(code)
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
                        if re.search(r"\b(?:всего|итого)\b", label) and (
                            pattern.search(label) or code in {"0100", "0400"}
                        ):
                            found.setdefault(code, set()).add(start)
                            break
        for code, indices in found.items():
            candidates.setdefault(code, set()).update(indices)
    return {
        **dict.fromkeys(sorted(uncertain), -1),
        **{
            code: next(iter(indices)) if len(indices) == 1 else -1
            for code, indices in candidates.items()
        },
    }


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
        match = None
        for edge in (xs[1], xs[2]):
            label = recognize_crop(image, (xs[0] + 4, top + 3, edge - 4, bottom - 3))
            match = _ROW.fullmatch(" ".join(label.casefold().split()))
            if match:
                break
        if match and (selector is None or match.groups() == selector.groups()):
            candidates.append((top, bottom, match[2]))
    return candidates[0] if len(candidates) == 1 else None


def _read_amount(image: Image.Image, box: PixelBox) -> tuple[str | None, Decimal | None]:
    left, top, right, bottom = box
    readings = []
    # The center of a thick rule can be several pixels inside the table cell.
    pads = (6, 10) if min(right - left, bottom - top) >= 85 else (3, 5)
    for pad in pads:
        raw = _money_spacing(
            recognize_crop(image, (left + pad, top + pad, right - pad, bottom - pad), numeric=True)
        )
        if (amount := _parse_money(raw)) is not None:
            readings.append((raw, amount))
    if len(readings) == 2 and readings[0][1] == readings[1][1]:
        return readings[0]
    return None, None


def read_report_row(
    image: Image.Image,
    page: int,
    selected: PageLocator | None,
    contract_number: str,
    period: tuple[str, str] | None = None,
) -> ReportReading | None:
    """Return values only when the report contract, header and row can be located."""
    if selected is not None and selected.page != page:
        return None
    ink = np.asarray(image.convert("L")) < 190
    width, height = image.size
    ys = _peaks(ink[:, width // 8 : width * 7 // 8].sum(axis=1), width * 0.43)
    xs = _column_tracks(ink, ys) if 4 <= len(ys) <= 60 else []
    if len(xs) < 4 or xs[-1] - xs[0] < width * 0.55:
        return _simple_table(image, page, selected, contract_number, period) if period else None
    header = image.crop((0, 0, width, ys[0]))
    if period is None:
        return None
    lines = recognize_lines(header)
    contracts = {match[1] for line in lines for match in _CONTRACT.finditer(line.text)}
    if contracts != {contract_number}:
        return None
    bounds = {
        tuple(normalize_document_date(value).value for value in match.groups())
        for line in lines
        if (match := _EXPLICIT_PERIOD.fullmatch(line.text))
    }
    if (bounds and bounds != {period}) or (not bounds and selected is None):
        return None
    band = _row_band(image, selected, xs, ys)
    if band is None:
        return None
    top, bottom, year = band
    if period[0][:4] != year or period[1][:4] != year:
        return None
    cols = _headers(image, ink, xs, ys)
    used_columns = Counter(cols.values())
    cells = []
    for code, col in cols.items():
        if col < 0 or used_columns[col] != 1:
            continue
        box = (xs[col], top, xs[col + 1], bottom)
        raw, amount = _read_amount(image, box)
        cells.append(ReportCell(code, page_locator(page, image, box), raw, amount))
    return ReportReading(cells, len(cells) == len(cols) and _complete_codes(set(cols)))
