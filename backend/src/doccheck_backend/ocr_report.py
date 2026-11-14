"""Recognize a uniquely addressed yearly stage row from local OCR observations."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

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
_AMOUNT = re.compile(r"^(?:\d+|\d{1,3}(?:[ \u00a0\u2009\u202f]\d{3})+)[.,]\d{2}$")
_HEADERS = {
    "production_overhead": re.compile(r"общепроизводственн\w*\s+(?:затрат|расход)\w*"),
    "general_admin": re.compile(r"общехозяйственн\w*\s+(?:затрат|расход)\w*"),
}
_MONEY_HEADER = {
    "payroll": re.compile(r"(?:затрат\w*\s+на\s+оплату\s+труда|оплата\s+труда)[, :]+всего"),
    "insurance": re.compile(r"страховые\s+взносы(?:\s+на\s+обязательное[^:]*?)?[, :]+всего"),
}
_MIN_SCORE = 0.8
# OCR returns text boxes, not cell boundaries. Reject column snaps with implausible offset.
_MAX_X_DRIFT = 0.016


@dataclass(frozen=True)
class ScanScope:
    contract: str
    start: date
    end: date
    row: PageLocator
    amounts: dict[str, Observation]


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


def _above(item: Observation, row: Observation) -> bool:
    return _page(item) == _page(row) and _box(item)[3] < _box(row)[1]


def _anchors(ordered: tuple[Observation, ...], row: Observation) -> dict[str, Observation]:
    anchors = {}
    above = [item for item in ordered if _above(item, row)]
    for category, pattern in {**_HEADERS, **_MONEY_HEADER}.items():
        # A broad section title does not identify one monetary column.
        # Without a verified numbered/grid boundary keep this table cell unknown.
        matches = []
        for item in above:
            normalized = " ".join(item.raw_text.casefold().split())
            if not pattern.fullmatch(normalized):
                continue
            if category in _MONEY_HEADER and "всего" not in normalized:
                continue
            matches.append(item)
        if len(matches) == 1:
            anchors[category] = matches[0]
    return anchors


def _dated_stages(
    items: tuple[Observation, ...],
) -> dict[int, dict[str, set[date]]]:
    stages: dict[int, dict[str, set[date]]] = {}
    for item in items:
        # Label and date can be separate adjacent recognition boxes.
        neighbor_text = " ".join(other.raw_text for other in _row_neighbors(item, items))
        readings = _STAGE_DATE.findall(item.raw_text.casefold())
        readings.extend(_STAGE_DATE.findall(neighbor_text.casefold()))
        for label, stage, day, month, year in readings:
            if month not in _MONTHS:
                continue
            try:
                value = date(int(year), _MONTHS.index(month) + 1, int(day))
            except ValueError:
                continue
            stages.setdefault(int(stage.replace("з", "3")), {}).setdefault(label, set()).add(value)
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
    contracts = {
        value
        for item in visible
        for value in _CONTRACT.findall(
            " ".join(other.raw_text for other in _row_neighbors(item, visible))
        )
    }
    if len(contracts) != 1:
        return None
    stages = _dated_stages(visible)
    if len(stages) != 1:
        return None
    stage, dates = next(iter(stages.items()))
    starts, ends = dates.get("начало", set()), dates.get("окончание", set())
    if len(starts) != 1 or len(ends) != 1:
        return None
    first, last = next(iter(starts)), next(iter(ends))
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
    row_items = _row_neighbors(row, positioned)
    candidates = [
        item
        for item in row_items
        if _box(item)[0] > _box(row)[2] and _AMOUNT.fullmatch(item.raw_text.strip())
    ]
    amounts = {}
    claimed = set()
    for category, anchor in _anchors(visible, row).items():
        x = _center(anchor, 0)
        eligible = [
            item
            for item in candidates
            if _box(item)[0] - _MAX_X_DRIFT <= x <= _box(item)[2] + _MAX_X_DRIFT
        ]
        if len(eligible) != 1 or eligible[0] not in visible:
            continue
        if eligible[0].locator.bbox in claimed:
            return None
        item = eligible[0]
        value = Decimal(re.sub(r"\s", "", item.raw_text.strip()).replace(",", "."))
        amounts[category] = Observation(item.raw_text, item.locator, amount=value)
        claimed.add(item.locator.bbox)
    assert isinstance(row.locator, PageLocator)
    return ScanScope(next(iter(contracts)), start, last, row.locator, amounts)
