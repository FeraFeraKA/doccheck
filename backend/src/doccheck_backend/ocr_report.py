"""Recognize a uniquely addressed yearly stage row from local OCR observations."""

import re
from dataclasses import dataclass
from datetime import date
from itertools import combinations

from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.native_observations import Observation

_CONTRACT = re.compile(r"\b(?:контракт|договор)\s*(?:№\s*)?([\w./-]*\d[\w./-]*)", re.IGNORECASE)
_CONTRACT_TOKEN = re.compile(r"^(?=[\w./-]*\d)[\w./-]+$")
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


def _same_region(left: Observation, right: Observation) -> bool:
    if _page(left) != _page(right):
        return False
    ax, ay, bx, by = _box(left)
    cx, cy, dx, dy = _box(right)
    intersection = max(0, min(bx, dx) - max(ax, cx)) * max(0, min(by, dy) - max(ay, cy))
    return intersection >= 0.55 * min((bx - ax) * (by - ay), (dx - cx) * (dy - cy))


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
    text_boxes = []
    offset = 0
    for part in parts:
        text_boxes.extend(
            (offset + start, offset + end, locator)
            for start, end, locator in (part.text_boxes or ((0, len(part.raw_text), part.locator),))
        )
        offset += len(part.raw_text) + 1
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
        text_boxes=tuple(text_boxes),
    )


def _value_source(source: Observation, start: int, end: int, family: str) -> Observation | None:
    parts = []
    covered: set[int] = set()
    for lower, upper, locator in source.text_boxes:
        if lower >= end or upper <= start:
            continue
        # A whole-fragment fallback may cover a value and its label. Such an
        # address is not exact enough to disambiguate two neighboring values.
        if any(
            character.isalnum()
            for character in source.raw_text[lower:start] + source.raw_text[end:upper]
        ):
            return None
        covered.update(range(max(lower, start), min(upper, end)))
        parts.append(Observation(source.raw_text[max(lower, start) : min(upper, end)], locator))
    if not parts or any(
        index not in covered and source.raw_text[index].isalnum() for index in range(start, end)
    ):
        return None
    return _reading_source(parts, family)


def _contract_value_source(match: re.Match[str], source: Observation) -> Observation | None:
    return _value_source(source, *match.span(1), "contract-number")


def _has_intervening_text(
    left: Observation, right: Observation, intervening: list[Observation]
) -> bool:
    left_end = _box(left)[2]
    right_start = _box(right)[0]
    return any(
        left_end <= _center(item, 0) <= right_start
        and not (_same_region(left, item) or _same_region(right, item))
        for item in intervening
    )


def _row_readings(
    positioned: tuple[Observation, ...],
    pattern: re.Pattern[str],
    family: str,
    *,
    context: tuple[Observation, ...] | None = None,
):
    """Yield a match and truthful location, preferring the uncombined fragment."""
    for item in positioned:
        text = item.raw_text.casefold() if family == "stage" else item.raw_text
        for match in pattern.finditer(text):
            yield match, item
    for item in positioned:
        pieces = _row_neighbors(item, positioned)
        if len(pieces) < 2:
            continue
        # Read every contiguous non-overlapping sequence. An alternative
        # fragment at the same position should not hide a valid second claim.
        for start in range(len(pieces) - 1):
            sequences = [[pieces[start]]]
            for part in pieces[start + 1 :]:
                for seq in tuple(sequences):
                    if len(seq) >= 5 or _box(part)[0] < _box(seq[-1])[2] - 0.002:
                        continue
                    if _box(part)[0] - _box(seq[-1])[2] > 0.18:
                        continue
                    if _has_intervening_text(
                        seq[-1],
                        part,
                        _row_neighbors(seq[-1], context) if context is not None else pieces,
                    ):
                        continue
                    next_seq = [*seq, part]
                    sequences.append(next_seq)
                    if len(sequences) > 48:
                        break
                    raw = " ".join(chunk.raw_text for chunk in next_seq)
                    text = raw.casefold() if family == "stage" else raw
                    for match in pattern.finditer(text):
                        offset = 0
                        relevant = []
                        for chunk in next_seq:
                            end = offset + len(chunk.raw_text)
                            if offset < match.end() and match.start() < end:
                                relevant.append(chunk)
                            offset = end + 1
                        yield match, _reading_source(relevant, family)
                if len(sequences) > 48:
                    break


def _date_readings(items: tuple[Observation, ...], context: tuple[Observation, ...] | None = None):
    for reading, source in _row_readings(items, _STAGE_DATE, "stage", context=context):
        label, stage, day, month, year = reading.groups()
        if month not in _MONTHS:
            continue
        try:
            value = date(int(year), _MONTHS.index(month) + 1, int(day))
        except ValueError:
            continue
        location = _value_source(source, reading.start(3), reading.end(5), "stage-date")
        yield int(stage.replace("з", "3")), label, value, source, location


def _dated_stages(
    items: tuple[Observation, ...], context: tuple[Observation, ...]
) -> dict[int, dict[str, dict[date, list[tuple[Observation, Observation | None]]]]]:
    stages: dict[int, dict[str, dict[date, list[tuple[Observation, Observation | None]]]]] = {}
    for stage, label, value, source, location in _date_readings(items, context):
        labels = stages.setdefault(stage, {})
        labels.setdefault(label, {}).setdefault(value, []).append((source, location))
    return stages


def _preferred_value_locations(
    readings: list[tuple[Observation, Observation | None]],
) -> list[Observation]:
    precise = [location for _, location in readings if location is not None]
    return precise or [source for source, _ in readings]


_BARE_STAGE_DATE = re.compile(
    r'\s*[«"“”]?\s*(\d{1,2})\s*[»"”“]?\s+([а-яё]+)\s+(\d{4})\s*г?[.,]?\s*',
    re.I,
)
_DOTTED_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})[.,]?")


def _bare_date(text: str) -> date | None:
    text = text.strip()
    try:
        if match := _BARE_STAGE_DATE.fullmatch(text):
            day, month, year = match.groups()
            if month.casefold() in _MONTHS:
                return date(int(year), _MONTHS.index(month.casefold()) + 1, int(day))
        elif match := _DOTTED_DATE.fullmatch(text):
            day, month, year = map(int, match.groups())
            return date(year, month, day)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text)
    except ValueError:
        pass
    return None


def select_scan_contract(
    positioned: tuple[Observation, ...],
    visible: tuple[Observation, ...] | None = None,
) -> tuple[str, Observation] | None:
    """Return the single addressed contract when its observed readings agree."""
    if visible is None:
        positioned = tuple(
            item
            for item in positioned
            if isinstance(item.locator, PageLocator) and item.locator.bbox is not None
        )
        visible = tuple(
            item
            for item in positioned
            if item.repeated_read or (item.confidence is not None and item.confidence >= _MIN_SCORE)
        )
    contracts: dict[str, list[tuple[Observation, Observation | None]]] = {}
    for reading, source in _row_readings(visible, _CONTRACT, "contract", context=positioned):
        contracts.setdefault(reading[1], []).append(
            (source, _contract_value_source(reading, source))
        )
    if len(contracts) != 1:
        return None
    contract, sources = next(iter(contracts.items()))
    for reading, location in _row_readings(positioned, _CONTRACT, "contract"):
        if reading[1] != contract and any(_same_region(source, location) for source, _ in sources):
            return None
    locations = _preferred_value_locations(sources)
    for item in positioned:
        value = item.raw_text.strip()
        if value == contract or not _CONTRACT_TOKEN.fullmatch(value):
            continue
        if any(_same_region(location, item) for location in locations):
            return None
    return contract, sources[0][0]


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
    selection = select_scan_contract(positioned, visible)
    if selection is None:
        return None
    contract, contract_source = selection
    stages = _dated_stages(visible, positioned)
    if len(stages) != 1:
        return None
    stage, dates = next(iter(stages.items()))
    starts, ends = dates.get("начало", {}), dates.get("окончание", {})
    if len(starts) != 1 or len(ends) != 1:
        return None
    first = next(iter(starts))
    last, cutoff_readings = next(iter(ends.items()))
    cutoff_source, _ = cutoff_readings[0]
    start = max(first, date(last.year, 1, 1))
    if start > last:
        return None
    matches = []
    for item in positioned:
        label = _ROW.fullmatch(item.raw_text.casefold())
        if label and (int(label[1].replace("з", "3")), int(label[2])) == (stage, last.year):
            matches.append(item)
    confirmed_rows = [item for item in matches if item in visible]
    if not confirmed_rows:
        return None
    row = confirmed_rows[0]
    if any(not _same_region(left, right) for left, right in combinations(confirmed_rows, 2)):
        return None
    if any(
        _page(other) != _page(row) or abs(_center(other, 1) - _center(row, 1)) > 0.004
        for other in matches
    ):
        return None
    if _page(contract_source) != _page(row) or _page(cutoff_source) != _page(row):
        return None
    start_readings = starts[first]
    start_source, _ = start_readings[0]
    if _page(start_source) != _page(row):
        return None
    # Confidence is a promotion gate, not a reason to discard a competing
    # well-formed date in the same source region.
    adjudicated = {
        "начало": (first, _preferred_value_locations(start_readings)),
        "окончание": (last, _preferred_value_locations(cutoff_readings)),
    }
    for read_stage, name, alternative, source, exact in _date_readings(positioned):
        selected, locations = adjudicated[name]
        if (read_stage != stage or alternative != selected) and any(
            _same_region(location, exact or source) for location in locations
        ):
            return None
    for item in positioned:
        alternative = _bare_date(item.raw_text)
        if alternative is not None and any(
            alternative != selected and _same_region(location, item)
            for selected, locations in adjudicated.values()
            for location in locations
        ):
            return None
    assert isinstance(row.locator, PageLocator)
    return ScanScope(contract, start, last, row.locator, contract_source, cutoff_source)
