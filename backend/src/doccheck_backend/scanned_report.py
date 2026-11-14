"""Read an addressed row of a visible, ruled KФЗ table with local OCR."""

import re
from calendar import monthrange
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from statistics import median

import numpy as np
from PIL import Image

from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.normalization import normalize_document_date
from doccheck_backend.page_ocr import (
    OcrLine,
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
    r"\b(?:договор|контракт)(?:\s*:\s*(?:№\s*|N[eoо°º]\.?\s+)?|\s*(?:№\s*|N[eoо°º]\.?\s+)"
    r"|\s+(?=[\w/-]*[0-9/-]))(\w+(?:[-/]\w+)*)(?=$|[\s.,;:])",
    re.I,
)
_ROW = re.compile(r"^\s*(\d+)\s*этап\s*[,.:]?\s*(\d{4})\s*(?:г\.?|год)?[.:\s—–-]*$", re.I)
_ROW_LOCATOR = re.compile(r"kfz-stage-([1-9][0-9]*)-([0-9]{4})")
_MONEY = re.compile(r"-?(?:[0-9]+|[0-9]{1,4}(?: [0-9]{3})+)[,.][0-9]{2}")
_QUANTITY = re.compile(r"-?[0-9]+(?:[,.][0-9]+)?")
_RUBLE_UNIT = re.compile(r"(?<!\w)(?:руб(?:л(?:ей|я|ь|ях|и)?)?\.?|RUB|RUR|₽)(?!\w)", re.I)
_OTHER_CURRENCY = re.compile(
    r"(?<![A-Za-z0-9/-])(?:USD|EUR|CNY|GBP|JPY|KZT|BYN|CHF|TRY|AZN|AMD|UZS|UAH|CAD|INR)"
    r"(?![A-Za-z0-9/-])|(?<!\w)(?:доллар\w*|евро|юан\w*)(?!\w)|[$€£¥]",
    re.I,
)
_UNKNOWN_UNIT_CODE = re.compile(
    r"(?:[:=]|\()\s*(?:в\s+)?(?!(?:RUB|RUR)\b)[A-Za-z]{3}\b",
    re.I,
)
_UNKNOWN_UNIT_WORD = re.compile(
    r"[:=]\s*(?:в\s+)?(?!(?:руб(?:л(?:ей|я|ь|ях|и)?)?|RUB|RUR)(?!\w))"
    r"[^\W\d_]{2,}(?!\w)",
    re.I,
)
_UPPERCASE_UNIT_CODE = re.compile(r"(?<![A-Za-z0-9])(?!(?:RUB|RUR)\b)[A-Z]{3}(?![A-Za-z0-9])")
_OTHER_SCALE = re.compile(
    r"(?<!\w)(?:ты[сc](?:яч\w*)?|млн|миллион\w*|млрд|миллиард\w*|коп(?:еек|ейки|ейка)?)\.?(?!\w)",
    re.I,
)
_UNIT_MULTIPLIER = re.compile(r"(?<!\d)(?:1000|1[ \u00a0]000)(?![\d.,])")
_RUBLE_RATE = re.compile(r"(?:руб\.?|RUB|₽)\s*/\s*\w+", re.I)
_UNIT_CONTEXT = re.compile(
    r"\b(?:сумм\w*|затрат\w*|расход\w*|стоимост\w*|оплат\w*|взнос\w*|"
    r"единиц\w*|валют\w*|денежн\w*|итог\w*|показател\w*|ед\.?\s*изм\w*)\b",
    re.I,
)
_GLOBAL_RUBLE_DECLARATION = re.compile(
    r"^\s*(?:суммы|денежные\s+показатели|показатели|единица(?:\s+измерения)?|"
    r"ед\.?\s*изм\.?)\s+(?:таблицы|отч[её]та|КФЗ)\s*[:=,]?\s*(?:в\s+)?"
    r"(?:руб(?:л(?:ей|я|ь|ях|и)?)?\.?|RUB|RUR|₽)\s*\.?\s*$",
    re.I,
)
_LABOR_UNITS = {
    "чел.-мес.": re.compile(r"(?:человеко|чел\.?)[\s-]*мес"),
    "чел.-ч.": re.compile(r"(?:человеко|чел\.?)[\s-]*(?:час|ч\b)"),
    "чел.-дн.": re.compile(r"(?:человеко|чел\.?)[\s-]*(?:д(?:ень|н))"),
}
_PAY = re.compile(r"\bзаработн\w*\s+плат\w*")
_RESERVE = re.compile(r"\bрезерв\w*\s+отпуск\w*")
_DETAIL_LABELS = {
    "0200": {
        "subtotal": "Заработная плата — всего",
        "base": "Основная заработная плата",
        "additional": "Дополнительная заработная плата",
        "reserve": "Резерв отпусков",
    },
    "0300": {
        "subtotal": "Страховые взносы с зарплаты — всего",
        "base": "Страховые взносы с основной зарплаты",
        "additional": "Страховые взносы с дополнительной зарплаты",
        "reserve": "Страховые взносы по резерву отпусков",
    },
}


@dataclass(frozen=True)
class ReportCell:
    code: str
    locator: PageLocator
    raw: str | None
    amount: Decimal | None
    unit_unverified: bool = field(default=False, kw_only=True)
    unverified_amount: Decimal | None = field(default=None, kw_only=True)


@dataclass(frozen=True)
class ReportDetailCell(ReportCell):
    label: str
    unit: str
    parent_code: str | None


@dataclass(frozen=True)
class ReportReading:
    cells: list[ReportCell]
    complete: bool
    details: tuple[ReportDetailCell, ...] = ()
    stage: str | None = None


@dataclass(frozen=True)
class HeaderGroup:
    start: int
    end: int
    bottom: int


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
_MONTHS = (
    "январь февраль март апрель май июнь июль август сентябрь октябрь ноябрь декабрь"
).split()
_MONTH_GENITIVES = (
    "января февраля марта апреля мая июня июля августа сентября октября ноября декабря"
).split()
_MONTH_NUMBERS = dict(zip(_MONTHS, range(1, 13))) | dict(zip(_MONTH_GENITIVES, range(1, 13)))
_MONTH_YEAR = rf"({'|'.join(_MONTHS)})\s+([0-9]{{4}})\s*(?:г\.?|года?)?"
_MONTH_RANGE = re.compile(
    rf"^(?:отч[её]тный период:\s*)?{_MONTH_YEAR}\s*[—–-]\s*{_MONTH_YEAR}$",
    re.I,
)
_ROW_DATE = (
    rf"(?:[0-9]{{1,2}}[./][0-9]{{1,2}}[./][0-9]{{4}}|[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}"
    rf"|[0-9]{{1,2}}\s+(?:{'|'.join(_MONTH_GENITIVES)})\s+[0-9]{{4}})"
)
_ROW_PERIOD = re.compile(
    rf"(?:с\s+)?({_ROW_DATE})(?:\s+г\.?)?\s*(?:[—–-]|по)\s*({_ROW_DATE})(?:\s+г\.?)?"
)
_PERIOD_MARKER = re.compile(rf"[0-9]|\b(?:{'|'.join(_MONTH_NUMBERS)})\b", re.I)
type ReportPeriod = tuple[str, str]


@dataclass(frozen=True)
class ScanRow:
    locator: PageLocator
    year: str
    period: ReportPeriod | None


@dataclass(frozen=True)
class ScanPage:
    contract: str | None
    rows: tuple[ScanRow, ...]


_SIMPLE_LINE = re.compile(rf"(.*?)\s+({_MONEY.pattern})$")


def _parse_money(text: str) -> Decimal | None:
    if _MONEY.fullmatch(text):
        return Decimal(text.replace(" ", "").replace(",", "."))
    return None


def _unit_declaration(line: OcrLine) -> bool:
    """Identify unit declarations rather than arbitrary currency mentions."""
    text = line.text.strip()
    if not any(
        pattern.search(text)
        for pattern in (
            _RUBLE_UNIT,
            _OTHER_CURRENCY,
            _UNKNOWN_UNIT_CODE,
            _UNKNOWN_UNIT_WORD,
            _UPPERCASE_UNIT_CODE,
            _OTHER_SCALE,
            _UNIT_MULTIPLIER,
        )
    ):
        return False
    remainder = text
    for pattern in (_RUBLE_UNIT, _OTHER_CURRENCY, _OTHER_SCALE):
        remainder = pattern.sub("", remainder)
    standalone = not any(character.isalnum() for character in remainder)
    return (
        standalone
        or bool(_UNKNOWN_UNIT_CODE.search(text))
        or bool(_UNIT_CONTEXT.search(text))
        or bool(_RUBLE_UNIT.search(text) and _UNIT_MULTIPLIER.search(text))
    )


def _confirmed_rubles(header: Sequence[OcrLine], table_header: Sequence[OcrLine] = ()) -> bool:
    """Require an explicit unit for report values and veto conflicting markers."""
    declarations = [line for line in (*header, *table_header) if _unit_declaration(line)]
    if any(
        _OTHER_CURRENCY.search(line.text)
        or _UNKNOWN_UNIT_CODE.search(line.text)
        or (_UNIT_CONTEXT.search(line.text) and _UNKNOWN_UNIT_WORD.search(line.text))
        or (_UNIT_CONTEXT.search(line.text) and _UPPERCASE_UNIT_CODE.search(line.text))
        or _OTHER_SCALE.search(line.text)
        or _UNIT_MULTIPLIER.search(line.text)
        or _RUBLE_RATE.search(line.text)
        for line in declarations
    ):
        return False
    return any(
        line.confidence >= 50 and _GLOBAL_RUBLE_DECLARATION.fullmatch(line.text) for line in header
    )


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
    for line in lines:
        parsed = _SIMPLE_LINE.fullmatch(line.text)
        if parsed is None:
            continue
        code = _SIMPLE_LABELS.get(parsed[1].strip(".: ").casefold())
        if code is not None:
            amounts.setdefault(code, []).append(line)
    if not amounts:
        return None
    first_row = min(line.box[1] for candidates in amounts.values() for line in candidates)
    rubles = _confirmed_rubles([line for line in lines if line.box[3] <= first_row])
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
        result.append(
            ReportCell(
                code,
                page_locator(page, image, line.box),
                raw,
                amount if rubles else None,
                unit_unverified=not rubles,
                unverified_amount=amount if not rubles else None,
            )
        )
    return ReportReading(
        result,
        rubles
        and {code for code in _SIMPLE_LABELS.values() if code != "other"}
        <= {cell.code for cell in result},
    )


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


def _header_tracks(ink: np.ndarray, xs: list[int], top: int, bottom: int) -> list[int]:
    band = ink[top + 4 : bottom - 4]
    if len(band) < 20:
        return []
    rules = _peaks(band.sum(axis=0), len(band) * 0.78)
    tolerance = max(6, ink.shape[1] // 280)
    return [i for i, x in enumerate(xs) if any(abs(x - rule) <= tolerance for rule in rules)]


def _header_label(
    image: Image.Image, xs: list[int], start: int, end: int, top: int, bottom: int
) -> str:
    box = (xs[start] + 6, top + 5, xs[end] - 6, bottom - 4)
    return " ".join(recognize_crop(image, box, mode=6).casefold().split())


def _headers(
    image: Image.Image, ink: np.ndarray, xs: list[int], ys: list[int]
) -> dict[str, HeaderGroup]:
    """Find article groups by title and code, then identify their total subcolumn."""
    content_top = ys[0]
    candidates: dict[str, dict[int, HeaderGroup]] = {}
    # Use the vertical rules that continue through the first header band to
    # locate the merged titles. A single-level header uses the same logic.
    for edge in ys[1:3]:
        main = _header_tracks(ink, xs, content_top, edge)
        for start, end in zip(main, main[1:]):
            group = HeaderGroup(start, end, edge)
            text = _header_label(image, xs, start, end, content_top, edge)
            if text.strip(" .:") == "итого":
                candidates.setdefault("total", {}).setdefault(start, group)
            for code, pattern in _GROUP_HEADER.items():
                if not re.search(rf"(?<!\d){code}(?!\d)", text) or not pattern.search(text):
                    continue
                if end == start + 1:
                    candidates.setdefault(code, {}).setdefault(start, group)
                elif code in _AGGREGATES:
                    for header_bottom in ys[2:5]:
                        if header_bottom - edge < 45:
                            continue
                        label = _header_label(image, xs, start, start + 1, edge, header_bottom)
                        if pattern.search(label) and re.search(r"\bвсего\b", label):
                            candidates.setdefault(code, {}).setdefault(start, group)
                            break
        if all(code in candidates for code in (*_GROUP_HEADER, "total")):
            break
    return {
        code: next(iter(groups.values())) for code, groups in candidates.items() if len(groups) == 1
    }


def _labor_column(
    image: Image.Image,
    ink: np.ndarray,
    xs: list[int],
    ys: list[int],
    groups: dict[str, HeaderGroup],
) -> tuple[int, str] | None:
    top, bottom = ys[0], ys[min(3, len(ys) - 1)]
    tracks = _header_tracks(ink, xs, top, bottom)
    occupied = {col for group in groups.values() for col in range(group.start, group.end)}
    candidates = []
    for col, end in zip(tracks, tracks[1:]):
        if col < 2 or end != col + 1 or col in occupied:
            continue
        label = _header_label(image, xs, col, end, top, bottom)
        if re.search(r"\bтрудо[её]мкост\w*", label):
            candidates.extend(
                (col, unit) for unit, pattern in _LABOR_UNITS.items() if pattern.search(label)
            )
    return candidates[0] if len(candidates) == 1 else None


def _pay_leaf(label: str) -> str | None:
    if label.strip(" .:") in {"всего", "итого"}:
        return "subtotal"
    if _PAY.search(label):
        words = set(re.findall(r"\b(?:основн|дополн)\w*", label))
        if len(words) == 1:
            return "base" if next(iter(words)).startswith("основн") else "additional"
    return None


def _pay_breakdown(
    image: Image.Image, ink: np.ndarray, xs: list[int], ys: list[int], group: HeaderGroup
) -> dict[str, int]:
    edges = [y for y in ys if y >= group.bottom][:4]
    for band, (top, bottom) in enumerate(zip(edges, edges[1:])):
        # The first subcolumn is the already identified article total.
        tracks = [i for i in _header_tracks(ink, xs, top, bottom) if group.start < i <= group.end]
        found: dict[str, list[int]] = {}
        for col, end in zip(tracks, tracks[1:]):
            label = _header_label(image, xs, col, end, top, bottom)
            if end == col + 1:
                kind = "reserve" if _RESERVE.search(label) else _pay_leaf(label)
                if kind and kind != "subtotal":
                    found.setdefault(kind, []).append(col)
                continue
            if not _PAY.search(label) or band + 2 >= len(edges):
                continue
            leaf_bottom = edges[band + 2]
            leaf_tracks = set(_header_tracks(ink, xs, bottom, leaf_bottom))
            for leaf in range(col, end):
                if leaf not in leaf_tracks or leaf + 1 not in leaf_tracks:
                    continue
                text = _header_label(image, xs, leaf, leaf + 1, bottom, leaf_bottom)
                if not text:
                    # Sparse layout handles short labels missed by block OCR.
                    text = recognize_crop(
                        image, (xs[leaf], bottom, xs[leaf + 1], leaf_bottom), mode=11
                    ).casefold()
                if kind := _pay_leaf(text):
                    found.setdefault(kind, []).append(leaf)
        if found:
            return {kind: cols[0] for kind, cols in found.items() if len(cols) == 1}
    return {}


def _table_rules(image: Image.Image) -> tuple[np.ndarray, list[int], list[int]]:
    ink = np.asarray(image.convert("L")) < 190
    width = image.width
    ys = _peaks(ink[:, width // 8 : width * 7 // 8].sum(axis=1), width * 0.43)
    xs = _column_tracks(ink, ys) if 4 <= len(ys) <= 60 else []
    return ink, xs, ys


def _header_month_period(text: str) -> ReportPeriod | None:
    match = _MONTH_RANGE.fullmatch(" ".join(text.casefold().split()))
    if not match:
        return None
    first, start_year, last, end_year = match.groups()
    start_month, end_month = _MONTHS.index(first) + 1, _MONTHS.index(last) + 1
    if not int(start_year) or not int(end_year):
        return None
    start = date(int(start_year), start_month, 1)
    end = date(int(end_year), end_month, monthrange(int(end_year), end_month)[1])
    return (start.isoformat(), end.isoformat()) if start <= end else None


def _stage_bands(
    image: Image.Image, xs: list[int], ys: list[int], selected: tuple[int, int] | None = None
) -> Iterator[tuple[int, int, str, str]]:
    for top, bottom in zip(ys, ys[1:]):
        if bottom - top < 13 or (selected and (top, bottom) != selected):
            continue
        label = recognize_crop(image, (xs[0] + 4, top + 3, xs[2] - 4, bottom - 3))
        match = _ROW.fullmatch(" ".join(label.casefold().split()))
        if match is None:
            label = recognize_crop(image, (xs[0] + 4, top + 3, xs[1] - 4, bottom - 3))
            match = _ROW.fullmatch(" ".join(label.casefold().split()))
        if match and int(match[2]) and int(match[1]):
            yield top, bottom, str(int(match[1])), match[2]


def _header_periods(lines: list[OcrLine]) -> set[ReportPeriod]:
    return {
        period
        for line in lines
        if (
            period := _dates(_EXPLICIT_PERIOD.fullmatch(line.text))
            or _header_month_period(line.text)
        )
        is not None
    }


def _row_date(text: str) -> date:
    if " " in text:
        day, month, year = text.split()
        return date(int(year), _MONTH_NUMBERS[month], int(day))
    if "." in text or "/" in text:
        day, month, year = map(int, re.split(r"[./]", text))
        return date(year, month, day)
    return date.fromisoformat(text)


def _period_in_row(raw: str) -> ReportPeriod | None:
    text = " ".join(raw.casefold().split())
    text = re.sub(r"(?<=[0-9])\s*([./])\s*(?=[0-9])", r"\1", text)
    try:
        if bounds := _ROW_PERIOD.fullmatch(text):
            start, end = map(_row_date, bounds.groups())
        elif month := re.fullmatch(_MONTH_YEAR, text):
            year, number = int(month[2]), _MONTH_NUMBERS[month[1]]
            start, end = date(year, number, 1), date(year, number, monthrange(year, number)[1])
        else:
            return _header_month_period(text)
    except ValueError:
        return None
    return (start.isoformat(), end.isoformat()) if start <= end else None


def _visible_row_period(
    image: Image.Image,
    xs: list[int],
    top: int,
    bottom: int,
    year: str,
    header_periods: set[ReportPeriod],
) -> ReportPeriod | None:
    if len(header_periods) > 1:
        return None
    raw = recognize_crop(image, (xs[1] + 4, top + 3, xs[2] - 4, bottom - 3))
    row = _period_in_row(raw)
    if row is None and _PERIOD_MARKER.search(raw):
        return None
    first, last = f"{year}-01-01", f"{year}-12-31"
    if not header_periods:
        return row if row and first <= row[0] <= row[1] <= last else None
    start, end = next(iter(header_periods))
    start, end = max(start, first), min(end, last)
    if start > end or (row and not start <= row[0] <= row[1] <= end):
        return None
    return row or (start, end)


def read_scan_page(image: Image.Image, page: int) -> ScanPage | None:
    """Return OCR-addressed row candidates and periods printed by the report."""
    ink, xs, ys = _table_rules(image)
    if len(xs) < 6 or xs[-1] - xs[0] < image.width * 0.55:
        return None
    lines = recognize_lines(image.crop((0, 0, image.width, ys[0])))
    contracts = {match[1] for line in lines for match in _CONTRACT.finditer(line.text)}
    contract = next(iter(contracts)) if len(contracts) == 1 else None
    periods = _header_periods(lines)
    rows = []
    for top, bottom, stage, year in _stage_bands(image, xs, ys):
        period = _visible_row_period(image, xs, top, bottom, year, periods)
        locator = page_locator(page, image, (xs[0], top, xs[2], bottom)).model_copy(
            update={"fragment_id": f"kfz-stage-{stage}-{year}"}
        )
        rows.append(ScanRow(locator, year, period))
    if rows or (contract and _headers(image, ink, xs, ys)):
        return ScanPage(contract, tuple(rows))
    return None


def _dates(match: re.Match[str] | None) -> ReportPeriod | None:
    if match:
        start, end = (normalize_document_date(value).value for value in match.groups())
        if start and end and start <= end:
            return start, end
    return None


def _row_band(
    image: Image.Image,
    locator: PageLocator | None,
    xs: list[int],
    ys: list[int],
    header_periods: set[ReportPeriod],
    period: ReportPeriod,
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
    candidates = [
        (top, bottom, stage)
        for top, bottom, stage, year in _stage_bands(image, xs, ys, selected)
        if (selector is None or (stage, year) == selector.groups())
        and _visible_row_period(image, xs, top, bottom, year, header_periods) == period
    ]
    return candidates[0] if len(candidates) == 1 else None


def _read_amount(
    image: Image.Image, box: PixelBox, pattern: re.Pattern[str] = _MONEY
) -> tuple[str | None, Decimal | None]:
    left, top, right, bottom = box
    readings = []
    for pad in (3, 5):
        raw = " ".join(
            recognize_crop(
                image, (left + pad, top + pad, right - pad, bottom - pad), numeric=True
            ).split()
        )
        if pattern.fullmatch(raw):
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
) -> ReportReading | None:
    """Return values only when the report contract, header and row can be located."""
    if selected is not None and selected.page != page:
        return None
    ink, xs, ys = _table_rules(image)
    width = image.width
    if len(xs) < 6 or xs[-1] - xs[0] < width * 0.55:
        return _simple_table(image, page, selected, contract_number, period) if period else None
    header = image.crop((0, 0, width, ys[0]))
    if period is None:
        return None
    lines = recognize_lines(header)
    contracts = {match[1] for line in lines for match in _CONTRACT.finditer(line.text)}
    if contracts != {contract_number}:
        return None
    bounds = _header_periods(lines)
    band = _row_band(image, selected, xs, ys, bounds, period)
    if band is None:
        return None
    top, bottom, stage = band
    header_edges = [y for y in ys if y <= top]
    groups = _headers(image, ink, xs, header_edges)
    table_header = image.crop((0, ys[0], width, top))
    rubles = _confirmed_rubles(lines, recognize_lines(table_header))
    cells = []
    for code, group in groups.items():
        box = (xs[group.start], top, xs[group.start + 1], bottom)
        raw, amount = _read_amount(image, box)
        cells.append(
            ReportCell(
                code,
                page_locator(page, image, box),
                raw,
                amount if rubles else None,
                unit_unverified=not rubles,
                unverified_amount=amount if not rubles else None,
            )
        )
    details = []
    if labor := _labor_column(image, ink, xs, header_edges, groups):
        col, unit = labor
        box = (xs[col], top, xs[col + 1], bottom)
        raw, amount = _read_amount(image, box, _QUANTITY)
        details.append(
            ReportDetailCell(
                "labor_intensity",
                page_locator(page, image, box),
                raw,
                amount,
                "Трудоёмкость",
                unit,
                None,
            )
        )
    for code, labels in _DETAIL_LABELS.items():
        if (group := groups.get(code)) is None or group.end == group.start + 1:
            continue
        breakdown = _pay_breakdown(image, ink, xs, header_edges, group)
        for kind, col in sorted(breakdown.items(), key=lambda item: item[1]):
            box = (xs[col], top, xs[col + 1], bottom)
            raw, amount = _read_amount(image, box)
            details.append(
                ReportDetailCell(
                    f"{code}-{kind}",
                    page_locator(page, image, box),
                    raw,
                    amount if rubles else None,
                    labels[kind],
                    "RUB",
                    code,
                    unit_unverified=not rubles,
                    unverified_amount=amount if not rubles else None,
                )
            )
    return ReportReading(
        cells, rubles and {*_GROUP_HEADER, "total"} <= groups.keys(), tuple(details), stage
    )
