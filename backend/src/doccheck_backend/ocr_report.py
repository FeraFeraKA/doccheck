"""Recognize a uniquely addressed yearly stage row from local OCR observations."""

import re
from dataclasses import dataclass
from datetime import date

from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.native_observations import Observation

_CONTRACT = re.compile(r"\b(?:контракт|договор)\s*(?:№\s*)?([\w./-]*\d[\w./-]*)", re.IGNORECASE)
_STAGE_DATE = re.compile(
    r'\b(начало|окончание)\s+([\dз]+)\s+этапа\s*:?\s*[«"“”]?\s*'
    r'(\d{1,2})\s*[»"”“]?\s+([а-яё]+)\s+(\d{4})\s*г?[.,]?',
    re.IGNORECASE,
)
_ROW = re.compile(r"^\s*([\dз]+)\s+этап\s*[,.:]?\s*(\d{4})\s*(?:г\.?\s*)?[:.]?\s*$", re.I)
_MONTHS = tuple(
    "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()
)
_MIN_SCORE = 0.8


@dataclass(frozen=True)
class ScanScope:
    contract: str
    start: date
    end: date
    row: PageLocator
    contract_source: Observation
    cutoff_source: Observation


def _box(item: Observation) -> tuple[float, float, float, float]:
    locator = item.locator
    assert isinstance(locator, PageLocator) and locator.bbox is not None
    return locator.bbox


def _center(item: Observation, axis: int) -> float:
    box = _box(item)
    return (box[axis] + box[axis + 2]) / 2


def _page(item: Observation) -> int:
    locator = item.locator
    assert isinstance(locator, PageLocator)
    return locator.page


def _row_neighbors(item: Observation, observations: tuple[Observation, ...]) -> list[Observation]:
    _, top, _, bottom = _box(item)
    center = (top + bottom) / 2
    return sorted(
        (
            other
            for other in observations
            if _page(other) == _page(item) and abs(_center(other, 1) - center) < (bottom - top) / 2
        ),
        key=lambda other: _box(other)[0],
    )


def _reading_source(parts: list[Observation], family: str) -> Observation:
    """Preserve raw recognized words and cover the union of their source boxes."""
    if len(parts) == 1:
        return parts[0]
    boxes = [_box(part) for part in parts]
    return Observation(
        " ".join(part.raw_text for part in parts),
        PageLocator(
            kind="page",
            page=_page(parts[0]),
            bbox=(
                min(box[0] for box in boxes),
                min(box[1] for box in boxes),
                max(box[2] for box in boxes),
                max(box[3] for box in boxes),
            ),
            fragment_id=f"ocr-{family}",
        ),
    )


def _row_readings(positioned: tuple[Observation, ...], pattern: re.Pattern[str], family: str):
    """Yield a match and truthful location, preferring the uncombined fragment."""
    for item in positioned:
        if match := pattern.search(
            item.raw_text.casefold() if family == "stage" else item.raw_text
        ):
            yield match, item
    for item in positioned:
        pieces = _row_neighbors(item, positioned)
        if len(pieces) < 2:
            continue
        previous = 0
        for index, part in enumerate(pieces):
            if index and _box(part)[0] < previous - 0.002:
                # Context rereads can overlap their component boxes. Do not
                # combine overlapping raw readings as if they were extra words.
                break
            previous = _box(part)[2]
        else:
            raw = " ".join(part.raw_text for part in pieces)
            text = raw.casefold() if family == "stage" else raw
            if match := pattern.search(text):
                offset = 0
                relevant = []
                for part in pieces:
                    end = offset + len(part.raw_text)
                    if offset < match.end() and match.start() < end:
                        relevant.append(part)
                    offset = end + 1
                yield match, _reading_source(relevant, family)


def _dated_stages(
    items: tuple[Observation, ...],
) -> dict[int, dict[str, dict[date, Observation]]]:
    stages: dict[int, dict[str, dict[date, Observation]]] = {}
    for reading, source in _row_readings(items, _STAGE_DATE, "stage"):
        label, stage, day, month, year = reading.groups()
        if month not in _MONTHS:
            continue
        try:
            value = date(int(year), _MONTHS.index(month) + 1, int(day))
        except ValueError:
            continue
        labels = stages.setdefault(int(stage.replace("з", "3")), {})
        labels.setdefault(label, {}).setdefault(value, source)
    return stages


def parse_scan_report(observations: tuple[Observation, ...]) -> ScanScope | None:
    positioned = tuple(
        item
        for item in observations
        if isinstance(item.locator, PageLocator) and item.locator.bbox is not None
    )
    visible = tuple(
        item
        for item in positioned
        if item.repeated_read or (item.confidence is not None and item.confidence >= _MIN_SCORE)
    )
    contracts = {}
    for reading, source in _row_readings(visible, _CONTRACT, "contract"):
        contracts.setdefault(reading[1], source)
    if len(contracts) != 1:
        return None
    contract, contract_source = next(iter(contracts.items()))
    stages = _dated_stages(visible)
    if len(stages) != 1:
        return None
    stage, dates = next(iter(stages.items()))
    starts, ends = dates.get("начало", {}), dates.get("окончание", {})
    if len(starts) != 1 or len(ends) != 1:
        return None
    first = next(iter(starts))
    last, cutoff_source = next(iter(ends.items()))
    start = max(first, date(last.year, 1, 1))
    if start > last:
        return None
    matches = []
    for item in positioned:
        label = _ROW.fullmatch(item.raw_text.casefold())
        if label and (int(label[1].replace("з", "3")), int(label[2])) == (stage, last.year):
            matches.append(item)
    confirmed_rows = [item for item in matches if item in visible]
    if len(confirmed_rows) != 1:
        return None
    row = confirmed_rows[0]
    if any(
        _page(other) != _page(row) or abs(_center(other, 1) - _center(row, 1)) > 0.004
        for other in matches
    ):
        return None
    if _page(contract_source) != _page(row) or _page(cutoff_source) != _page(row):
        return None
    start_source = starts[first]
    if _page(start_source) != _page(row):
        return None
    assert isinstance(row.locator, PageLocator)
    return ScanScope(contract, start, last, row.locator, contract_source, cutoff_source)
