"""Address cells only when original raster grid and header roles agree."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby, pairwise
from typing import TYPE_CHECKING

from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.native_observations import Observation

if TYPE_CHECKING:
    from PIL.Image import Image

type PixelBox = tuple[int, int, int, int]
type ReadCell = Callable[[PixelBox, int], tuple[Observation, ...]]

_MONEY = re.compile(r"(?:\d+|\d{1,3}(?:[ \u00a0\u2009\u202f]\d{3})+)[,.]\d{2}")
_REPORT_CODES = {
    "production_overhead": ("0800", ("общепроизводственн", "затрат")),
    "general_admin": ("0900", ("общехозяйственн", "затрат")),
}
_AGGREGATES = {
    "payroll": ("0200", ("на оплату труда",), ("оплату", "труд", "всего")),
    "insurance": ("0300", ("страховые взносы",), ("взносы", "всего")),
}


@dataclass(frozen=True)
class TableGrid:
    x: tuple[int, ...]
    row: tuple[int, int]
    upper: tuple[int, ...]


def _groups(positions: list[int]) -> list[int]:
    result = []
    for _, group in groupby(enumerate(positions), lambda pair: pair[1] - pair[0]):
        values = [value for _, value in group]
        result.append((values[0] + values[-1]) // 2)
    return result


def _table_lines(image: Image, row: PageLocator, threshold: int) -> TableGrid | None:
    width, height = image.size
    if row.bbox is None or width < 300 or height < 100:
        return None
    row_box = tuple(
        round(value * size) for value, size in zip(row.bbox, (width, height, width, height))
    )
    left, top, _, bottom = row_box
    mask = image.point(lambda value: int(value <= threshold))
    pixels = mask.tobytes()
    lines = _groups(
        [
            y
            for y in range(bottom + min(height // 30, height - bottom))
            if sum(pixels[y * width : (y + 1) * width]) >= width * 0.62
        ]
    )
    before = [y for y in lines if y < top]
    after = [y for y in lines if y > bottom]
    if len(before) < 3 or not after:
        return None
    upper, lower = before[-1], after[0]
    if not 8 <= lower - upper <= height * 0.045 or min(top - upper, lower - bottom) < 1:
        return None
    stripe = pixels[(upper + 2) * width : (lower - 1) * width]
    vertical = _groups(
        [x for x in range(width) if sum(stripe[x::width]) >= (lower - upper - 3) * 0.90]
    )
    if not 5 <= len(vertical) <= 32 or any(right - edge < 16 for edge, right in pairwise(vertical)):
        return None
    if not vertical[0] < left < vertical[1] or row_box[2] >= vertical[1]:
        return None
    # Header proof requires top, at least one interior rule, and an upper body line.
    return TableGrid(tuple(vertical), (upper, lower), tuple(before[:-1]))


def detect_table_grid(image: Image, row: PageLocator) -> TableGrid | None:
    """Require matching boundaries on two luminance binarizations of the source."""
    gray = image.convert("L")
    main = _table_lines(gray, row, 160)
    other = _table_lines(gray, row, 200)
    if main is None or other is None or len(main.x) != len(other.x):
        return None
    if any(abs(a - b) > 2 for a, b in zip((*main.x, *main.row), (*other.x, *other.row))):
        return None
    if len(main.upper) != len(other.upper) or any(
        abs(left - right) > 2 for left, right in zip(main.upper, other.upper)
    ):
        return None
    return main


def _line_score(image: Image, x: int, top: int, bottom: int) -> float:
    radius = max(2, image.width // 1500)
    crop = image.crop((x - radius, top, x + radius + 1, bottom))
    rows = crop.tobytes()
    stride = crop.width
    return sum(min(rows[i : i + stride]) < 160 for i in range(0, len(rows), stride)) / crop.height


def _cell_box(grid: TableGrid, index: int, top: int, bottom: int) -> PixelBox:
    return grid.x[index] + 4, top + 3, grid.x[index + 1] - 4, bottom - 2


def _tokens(observations: tuple[Observation, ...]) -> str:
    return re.sub(r"\s+", " ", " ".join(item.raw_text for item in observations)).casefold().strip()


def _repeat_contains(read: ReadCell, box: PixelBox, required: tuple[str, ...]) -> bool:
    # Agreement on significant words is separate from numeric agreement.
    texts = [_tokens(read(box, scale)) for scale in (2, 3, 4)]
    return sum(all(term in text for term in required) for text in texts) >= 2


def _scoped_column_roles(
    image: Image,
    grid: TableGrid,
    page_observations: tuple[Observation, ...],
    read: ReadCell,
) -> dict[str, int]:
    # Locate labelled section boxes inside the top header band, then prove a
    # particular leaf column and its boundaries. The nearest text is never enough.
    header_top, header_bottom = grid.upper[0], grid.upper[1]
    if header_bottom - header_top < 16:
        return {}
    sections = {}
    labels_by_column = {}
    accepted = [
        item
        for item in page_observations
        if item.repeated_read or (item.confidence is not None and item.confidence >= 0.8)
    ]
    for item in accepted:
        location = item.locator
        if not isinstance(location, PageLocator) or location.bbox is None:
            continue
        x0, y0, x1, y1 = location.bbox
        if not header_top <= y0 * image.height < y1 * image.height <= header_bottom:
            continue
        text = _tokens((item,))
        for category, rule in {**_REPORT_CODES, **_AGGREGATES}.items():
            words = rule[1]
            key = words[0]
            if key not in text:
                continue
            covered = [
                index
                for index, (left, right) in enumerate(pairwise(grid.x))
                if min(right, x1 * image.width) - max(left, x0 * image.width)
                >= (right - left) * 0.3
            ]
            if covered:
                sections.setdefault(category, set()).add(tuple(covered))
                for index in covered:
                    labels_by_column.setdefault(index, set()).add(category)

    roles = {}
    for category, candidates in sections.items():
        if len(candidates) != 1:
            continue
        covered = next(iter(candidates))
        # Shared headings can cover several atomic columns. Its leftmost
        # candidate still needs a distinct, independently read aggregate label.
        index = covered[0]
        if labels_by_column.get(index) != {category}:
            continue
        if category in _REPORT_CODES:
            code, words = _REPORT_CODES[category]
            if len(covered) != 1 or not _repeat_contains(
                read, _cell_box(grid, index, header_top, header_bottom), (*words, code)
            ):
                continue
        else:
            code, words, leaf = _AGGREGATES[category]
            heading = (
                grid.x[covered[0]] + 3,
                header_top + 2,
                grid.x[covered[-1] + 1] - 3,
                header_bottom - 2,
            )
            if len(covered) < 2 or not _repeat_contains(read, heading, (*words, code)):
                continue
            leaf_top, leaf_bottom = header_bottom, grid.upper[2]
            if leaf_bottom - leaf_top < 36 or not _repeat_contains(
                read, _cell_box(grid, index, leaf_top, leaf_bottom), leaf
            ):
                continue
        if (
            min(
                _line_score(image, grid.x[index], header_bottom + 4, grid.row[0] - 3),
                _line_score(image, grid.x[index + 1], header_bottom + 4, grid.row[0] - 3),
            )
            < 0.60
        ):
            continue
        roles[category] = index
    if len(set(roles.values())) != len(roles):
        return {}
    return roles


def _money_read(items: tuple[Observation, ...]) -> Decimal | None:
    if len(items) != 1:
        return None
    text = items[0].raw_text.strip()
    if not _MONEY.fullmatch(text):
        return None
    return Decimal(re.sub(r"\s", "", text.replace(",", ".")))


def read_table_amounts(
    image: Image,
    row: PageLocator,
    page_observations: tuple[Observation, ...],
    read: ReadCell,
) -> dict[str, Observation]:
    grid = detect_table_grid(image, row)
    if grid is None:
        return {}
    gray = image.convert("L")
    roles = _scoped_column_roles(gray, grid, page_observations, read)
    amounts = {}
    for category, index in roles.items():
        box = _cell_box(grid, index, *grid.row)
        readings = [read(box, scale) for scale in (2, 3, 4)]
        values = [_money_read(items) for items in readings]
        confirmed = {value for value in values if value is not None}
        if len(confirmed) != 1:
            continue
        amount = next(iter(confirmed))
        if values.count(amount) < 2:
            continue
        (reading,) = readings[values.index(amount)]
        # Whole grid cell, rather than cropped subframe coordinates, anchors preview.
        x0, y0, x1, y1 = box
        amounts[category] = Observation(
            reading.raw_text,
            PageLocator(
                kind="page",
                page=row.page,
                bbox=(x0 / image.width, y0 / image.height, x1 / image.width, y1 / image.height),
                fragment_id=f"ocr-grid-{category}",
            ),
            amount=amount,
            repeated_read=True,
        )
    return amounts
