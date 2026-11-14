"""Address cells only when original raster grid and header roles agree."""

from __future__ import annotations

import re
from collections import defaultdict
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

_MONEY = re.compile(r"[+−–-]?(?:\d+|\d{1,3}(?:[ \u00a0\u2009\u202f]\d{3})+)[,.]\d{2}")
_ACCOUNTING = re.compile(r"\(\s*(.+?)\s*\)")
_CODE = re.compile(r"(?<!\d)\d{4}(?!\d)")
_REPORT_CODES = {
    "production_overhead": ("0800", ("общепроизводственн", "затрат")),
    "general_admin": ("0900", ("общехозяйственн", "затрат")),
}
_AGGREGATES = {
    "payroll": ("0200", ("на оплату труда",)),
    "insurance": ("0300", ("страховые взносы",)),
}
_WORD = r"[^\W\d_]+"
_SECTION_HEADER = {
    "0200": re.compile(r"(?:затраты\s+)?на\s+оплату\s+труда(?:[\s,−–—-]+всего)?"),
    "0300": re.compile(r"страховые\s+взносы(?:\s+на\s+обязательное\s+социальное\s+страхование)?"),
    "0800": re.compile(r"общепроизводственные\s+(?:затраты|расходы)"),
    "0900": re.compile(r"общехозяйственные\s+(?:затраты|расходы)"),
}
_ARTICLE = r"статья\s+калькуляци[ия]"
# A broken read of the isolated printed suffix may abstain. Only the
# canonical words and the alternate inflection above count as confirmation.
_UNREADABLE_ARTICLE = r"статья\s+калькуля[а-яё]{2,4}"
_HEADER_QUALIFIER = re.compile(
    r"\b(?:в\s+том\s+числе|за\s+сч[её]т|из\s+средств|по\s+видам|"
    r"без\s+уч[её]та|только|часть|подытог|субсид\w*|со[-\s]?финансирован\w*|"
    r"подразделени\w*)\b"
)
_SUBARTICLE_CODE = re.compile(r"(?<!\d)\d{4}[.\-/]\d+(?!\d)")
# Accept only finite known leaf vocabulary (including narrow OCR spelling
# variants), never an arbitrary qualifier. Parent section code is separate proof.
_PAYROLL_LEAD = r"(?:(?:затраты|ззтрзты)\s+(?:(?:на|ва)\s+)?)?"
_PAYROLL_LEAF = re.compile(rf"{_PAYROLL_LEAD}оплату\s+труд(?:а|;з)?[\s.,:]+всего[.:]?")
_INSURANCE_LEAF = re.compile(
    r"(?:(?:страховые|стрффв\.ые|стдод\.ые)\s+)?(?:взносы|взяоеы)\s*"
    r"(?:(?:на|ва|зга)\s+)?"
    r"(?:обязательное|обязатељное|обюатељное)\s+"
    r"(?:социальное|еоциа\.тное|соцвсљное|соцна-льное)\s+"
    r"(?:страхование|страхованне|страхезанне)[\s.,:]+всего[.:]?"
)
# The source layout prints an arithmetic reference on a separate line.
# Restrict it to reference-like tokens, digits and plus; if OCR is unclear
# the optional suffix is noise only when enclosed and geometrically isolated.
_FORMULA_SUFFIX = re.compile(
    r"\(\s*(?:гр|тр|ф|rp)[.\-\s]*[\dлitх]+\s*\+\s*"
    r"(?:гр|тр|rp|т;х)[.\-\s]*[\dлitх-]+\s*\)",
    re.IGNORECASE,
)


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
    if bottom <= top:
        return 0.0
    radius = max(2, image.width // 1500)
    crop = image.crop((x - radius, top, x + radius + 1, bottom))
    rows = crop.tobytes()
    stride = crop.width
    return sum(min(rows[i : i + stride]) < 160 for i in range(0, len(rows), stride)) / crop.height


def _has_long_line_gap(image: Image, x: int, top: int, bottom: int) -> bool:
    radius = max(2, image.width // 1500)
    crop = image.crop((x - radius, top, x + radius + 1, bottom))
    pixels = crop.tobytes()
    gap = 0
    for cursor in range(0, len(pixels), crop.width):
        gap = gap + 1 if min(pixels[cursor : cursor + crop.width]) >= 200 else 0
        if gap > max(crop.height * 0.14, image.height * 0.018):
            return True
    return False


def _cell_box(grid: TableGrid, index: int, top: int, bottom: int) -> PixelBox:
    return grid.x[index] + 4, top + 3, grid.x[index + 1] - 4, bottom - 2


def _tokens(observations: tuple[Observation, ...]) -> str:
    return re.sub(r"\s+", " ", " ".join(item.raw_text for item in observations)).casefold().strip()


def _repeat_contains(
    read: ReadCell, box: PixelBox, required: tuple[str, ...], *, code: str
) -> bool:
    texts = [_tokens(read(box, scale)) for scale in (2, 3, 4)]
    section = _SECTION_HEADER[code]
    article = rf"{section.pattern}\s*\(?\s*{{}}{code}\s*\)?\s*[.:]?"
    hits = 0
    for text in texts:
        other_roles = [
            rule[1][0]
            for rule in (*_REPORT_CODES.values(), *_AGGREGATES.values())
            if rule[0] != code
        ]
        if any(role in text for role in other_roles):
            return False
        if _HEADER_QUALIFIER.search(text):
            return False
        codes = set(_CODE.findall(text))
        if codes - {code}:
            return False
        # The complete parent role is independent of the leaves. Only the
        # printed article reference and code may follow the section title.
        if re.fullmatch(article.format(rf"(?:{_ARTICLE}\s+)?"), text):
            hits += 1
        elif not re.fullmatch(article.format(rf"{_UNREADABLE_ARTICLE}\s+"), text) and (
            required[0] in text or code in codes
        ):
            if codes or section.fullmatch(text) is None:
                return False
    return hits >= 2


def _leaf_header(items: tuple[Observation, ...], category: str) -> str | None:
    content = []
    prefix = _PAYROLL_LEAF if category == "payroll" else _INSURANCE_LEAF
    for index, item in enumerate(items):
        text = _tokens((item,))
        if text.startswith("("):
            if index != len(items) - 1 or not _FORMULA_SUFFIX.fullmatch(text):
                return None
            previous = items[index - 1].locator if index else None
            current = item.locator
            if (
                not isinstance(previous, PageLocator)
                or not isinstance(current, PageLocator)
                or previous.bbox is None
                or current.bbox is None
                or current.bbox[1] <= previous.bbox[3]
            ):
                return None
        else:
            content.append(text)
    candidate = " ".join(content)
    return candidate if prefix.fullmatch(candidate) else None


def _repeat_leaf(read: ReadCell, box: PixelBox, category: str) -> bool:
    hits = 0
    for scale in (2, 3, 4):
        items = read(box, scale)
        if _leaf_header(items, category) is not None:
            hits += 1
        elif "всего" in (content := _tokens(items)) or _HEADER_QUALIFIER.search(content):
            # A rejected read that names an aggregate may describe part of it.
            # It may only be ignored if its words form an OCR variant handled
            # above, never because another scale omitted a printed qualifier.
            return False
    return hits >= 2


def _restricted_subcolumn(text: str, code: str) -> bool:
    return bool(
        _HEADER_QUALIFIER.search(text)
        or _SUBARTICLE_CODE.search(text)
        or (re.search(_WORD, text) and set(_CODE.findall(text)) - {code})
    )


def _has_restricted_overhead_leaf(
    image: Image,
    grid: TableGrid,
    index: int,
    code: str,
    page_observations: tuple[Observation, ...],
    read: ReadCell,
) -> bool:
    left, right = grid.x[index], grid.x[index + 1]
    top = grid.upper[1]
    bottom = grid.row[0]
    for item in page_observations:
        if not isinstance(item.locator, PageLocator) or item.locator.bbox is None:
            continue
        x0, y0, x1, y1 = item.locator.bbox
        if (
            top <= (y0 + y1) * image.height / 2 < bottom
            and min(x1 * image.width, right) - max(x0 * image.width, left)
            >= (x1 - x0) * image.width * 0.55
            and _restricted_subcolumn(_tokens((item,)), code)
        ):
            return True
    for y0, y1 in pairwise((*grid.upper[1:], bottom)):
        if y1 - y0 >= 8:
            crop = _cell_box(grid, index, y0, y1)
            if any(_restricted_subcolumn(_tokens(read(crop, scale)), code) for scale in (2, 3, 4)):
                return True
    return False


def _safe_row_cell(image: Image, grid: TableGrid, index: int) -> bool:
    top, bottom = grid.row
    for left, right in ((grid.x[0], grid.x[1]), (grid.x[index], grid.x[index + 1])):
        span = right - left - 10
        if span <= 0:
            return False
        tolerance = max(2, min(4, (bottom - top) // 7))
        # The global projected line can differ by a few pixels from the local
        # cell edge on a slanted scan. Exempt only the contiguous edge cluster;
        # a separate rule just inside it is still an ambiguous row boundary.
        local_edges = []
        for y in (top, bottom):
            edge_y = max(0, y - tolerance)
            edge = image.crop((left + 5, edge_y, right - 5, y + tolerance + 1))
            pixels = edge.tobytes()
            lines = [
                edge_y + i // span
                for i in range(0, len(pixels), span)
                if sum(pixel <= 200 for pixel in pixels[i : i + span]) >= span * 0.72
            ]
            if not lines or lines[-1] - lines[0] + 1 != len(lines):
                return False
            local_edges.append(lines)
        region = image.crop((left + 5, local_edges[0][-1] + 1, right - 5, local_edges[1][0]))
        stripe = region.tobytes()
        if any(
            sum(pixel <= 200 for pixel in stripe[i : i + span]) >= span * 0.68
            for i in range(0, len(stripe), span)
        ):
            return False
    return (
        min(
            _line_score(image, grid.x[column], top + 3, bottom - 2)
            for column in (0, 1, index, index + 1)
        )
        >= 0.8
    )


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
            if len(covered) != 1:
                continue
            # The text may be narrow even if its actual parent cell is
            # merged. Prove both sides of this section in the header band.
            left, right = grid.x[index], grid.x[index + 1]
            top, bottom = header_top + 3, header_bottom - 2
            if any(
                _line_score(image, edge, top, bottom) < 0.8
                or _has_long_line_gap(image, edge, top, bottom)
                for edge in (left, right)
            ) or not _repeat_contains(
                read, _cell_box(grid, index, header_top, header_bottom), words, code=code
            ):
                continue
            if _has_restricted_overhead_leaf(image, grid, index, code, page_observations, read):
                continue
        else:
            code, words = _AGGREGATES[category]
            heading = (
                grid.x[covered[0]] + 3,
                header_top + 2,
                grid.x[covered[-1] + 1] - 3,
                header_bottom - 2,
            )
            if (
                len(grid.upper) < 3
                or len(covered) < 2
                or not _repeat_contains(read, heading, words, code=code)
            ):
                continue
            leaf_top, leaf_bottom = header_bottom, grid.upper[2]
            if leaf_bottom - leaf_top < 36 or not _repeat_leaf(
                read, _cell_box(grid, index, leaf_top, leaf_bottom), category
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
        if any(
            _has_long_line_gap(image, grid.x[column], header_bottom + 4, grid.row[0] - 3)
            for column in (index, index + 1)
        ):
            continue
        roles[category] = index
    if len(set(roles.values())) != len(roles):
        return {}
    return roles


def _money_read(
    items: tuple[Observation, ...], *, frame_size: tuple[int, int] | None = None
) -> Decimal | None:
    if len(items) > 1:
        regions = [item.locator.bbox for item in items if isinstance(item.locator, PageLocator)]
        if len(regions) != len(items) or any(region is None for region in regions):
            return None
        if max(region[1] for region in regions) >= min(region[3] for region in regions):
            return None
        width, height = frame_size or items[0].frame_size or (1, 1)
        for previous, following in pairwise(regions):
            previous_height = previous[3] - previous[1]
            following_height = following[3] - following[1]
            if (following[0] - previous[2]) * width > min(
                previous_height, following_height
            ) * height * 1.2:
                return None
    text = " ".join(item.raw_text.strip() for item in items)
    text = re.sub(r"^([+−–-])\s+", r"\1", text)
    if match := _ACCOUNTING.fullmatch(text):
        text = "-" + match[1].strip()
    text = text.replace("−", "-").replace("–", "-")
    if not _MONEY.fullmatch(text):
        return None
    return Decimal(re.sub(r"\s", "", text.replace(",", ".")))


def _page_amount_candidates(
    observations: list[Observation], frame_size: tuple[int, int]
) -> set[Decimal]:
    frames = defaultdict(list)
    for item in observations:
        frames[item.frame_id].append(item)
    return {
        value for frame in frames.values() for value in _frame_amount_candidates(frame, frame_size)
    }


def _frame_amount_candidates(
    observations: list[Observation], frame_size: tuple[int, int]
) -> set[Decimal]:
    observations = sorted(observations, key=lambda item: item.locator.bbox[0])
    chains = []
    for start, item in enumerate(observations):
        chain = [item]
        for following in observations[start + 1 : start + 6]:
            previous = chain[-1].locator.bbox
            box = following.locator.bbox
            if (
                box[0] < previous[2]
                or max(previous[1], box[1]) >= min(previous[3], box[3])
                or (box[0] - previous[2]) * frame_size[0]
                > min(previous[3] - previous[1], box[3] - box[1]) * frame_size[1] * 1.2
            ):
                break
            chain.append(following)
            chains.append(tuple(chain))
    used = set()
    candidates = set()
    for chain in sorted(chains, key=len, reverse=True):
        ids = tuple(id(item) for item in chain)
        if ids in used:
            continue
        value = _money_read(chain, frame_size=frame_size)
        if value is None:
            continue
        candidates.add(value)
        # A parseable suffix is part of this same amount, not another reading.
        used.update(
            ids[start:end] for start in range(len(ids)) for end in range(start + 1, len(ids) + 1)
        )
    candidates.update(
        value
        for item in observations
        if (id(item),) not in used and (value := _money_read((item,))) is not None
    )
    return candidates


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
        if not _safe_row_cell(gray, grid, index):
            continue
        box = _cell_box(grid, index, *grid.row)
        readings = [read(box, scale) for scale in (2, 3, 4)]
        values = [_money_read(items) for items in readings]
        confirmed = {value for value in values if value is not None}
        if len(confirmed) != 1:
            continue
        amount = next(iter(confirmed))
        if values.count(amount) < 2:
            continue
        # A crop may contain a line artefact next to a readable dissenting
        # number. It cannot confirm a value, but it must be able to contradict.
        fallback_size = (box[2] - box[0], box[3] - box[1])
        if any(
            _frame_amount_candidates(
                [
                    item
                    for item in items
                    if isinstance(item.locator, PageLocator) and item.locator.bbox is not None
                ],
                next((item.frame_size for item in items if item.frame_size), fallback_size),
            )
            - {amount}
            for items, value in zip(readings, values)
            if value is None
        ):
            continue
        # The full-frame reader can return a conflicting, legible number
        # without repeat confidence. Check the full cell, including margins.
        x0, x1 = grid.x[index], grid.x[index + 1]
        y0, y1 = grid.row
        inside = []
        for item in page_observations:
            location = item.locator
            if not isinstance(location, PageLocator) or location.bbox is None:
                continue
            if location.page != row.page:
                continue
            left, top, right, bottom = location.bbox
            if (
                x0 <= left * image.width < right * image.width <= x1
                and y0 <= top * image.height < bottom * image.height <= y1
            ):
                inside.append(item)

        if _page_amount_candidates(inside, image.size) - {amount}:
            continue
        reading = " ".join(item.raw_text for item in readings[values.index(amount)])
        # The inner crop stays within the original atomic cell.
        x0, y0, x1, y1 = box
        amounts[category] = Observation(
            reading,
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
