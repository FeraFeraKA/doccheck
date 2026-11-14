from decimal import Decimal

import pytest
from PIL import Image, ImageDraw

from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.native_observations import Observation
from doccheck_backend.ocr_table import detect_table_grid, read_table_amounts

_COORDINATES = (30, 160, 240, 380, 525, 670, 770)
_ROW = (365, 387)


def _source(text, x0, y0, x1, y1):
    return Observation(
        text,
        PageLocator(kind="page", page=1, bbox=(x0 / 800, y0 / 550, x1 / 800, y1 / 550)),
        repeated_read=True,
    )


@pytest.fixture
def table():
    image = Image.new("L", (800, 550), 255)
    draw = ImageDraw.Draw(image)
    for y in (90, 145, 270, 315, *_ROW):
        draw.line((_COORDINATES[0], y, _COORDINATES[-1], y), width=2, fill=0)
    for x in _COORDINATES:
        draw.line((x, 90, x, _ROW[-1]), width=2, fill=0)
    row = _source("9 этап, 2040 г.", 46, 370, 135, 381).locator
    headings = (
        _source("Затраты на оплату труда - всего (0200)", 242, 105, 516, 125),
        _source("Общепроизводственные затраты (0800)", 526, 103, 670, 127),
    )
    return image, row, headings


def test_cell_binding_uses_closed_grid_not_adjacent_subtotal(table):
    image, row, headings = table
    requested = []

    def read(box, scale):
        requested.append(box)
        left, top, _, _ = box
        if top < 145 and left < 380:
            text = "Затраты на оплату труда 0200"
        elif top < 145:
            text = "Общепроизводственные затраты 0800"
        elif top < 270:
            text = "Оплату труда, всего"
        elif left < 380:
            text = "0,00"
        else:
            text = "1234,67"
        return (_source(text, 10, 10, 36, 36),)

    report = read_table_amounts(image, row, headings, read)

    assert report["payroll"].amount == Decimal("0.00")
    assert report["production_overhead"].amount == Decimal("1234.67")
    assert report["payroll"].locator.bbox[2] < 380 / 800
    assert not any(380 < box[0] < 525 and box[1] > 365 for box in requested)


def test_broken_grid_has_no_amount_to_bind(table):
    image, row, headings = table
    ImageDraw.Draw(image).rectangle((378, 367, 384, 385), fill=255)

    # The missing separator makes the covered heading compete for one wider cell.
    def read(box, scale):
        left, top, right, _ = box
        if left < 380 and right > 500 and top > 145:
            return (_source("отдельная статья", 11, 11, 40, 40),)
        return (_source("0,00", 11, 11, 40, 40),)

    assert "payroll" not in read_table_amounts(image, row, headings, read)


def test_disagreement_and_letters_in_value_stay_unknown(table):
    image, row, headings = table

    def read(box, scale):
        left, top, _, _ = box
        if top < 145:
            text = (
                "Затраты на оплату труда 0200"
                if left < 380
                else "Общепроизводственные затраты 0800"
            )
        elif top < 270:
            text = "Оплату труда, всего"
        elif left < 380:
            text = "0,00" if scale == 2 else "0,01"
        else:
            text = "З 215,40"
        return (_source(text, 11, 11, 40, 40),)

    assert detect_table_grid(image, row) is not None
    assert read_table_amounts(image, row, headings, read) == {}


def _default_cell_read(box, _scale):
    left, top, _, _ = box
    if top < 145:
        text = "Затраты на оплату труда 0200" if left < 380 else "Общепроизводственные затраты 0800"
    elif top < 270:
        text = "Оплату труда, всего"
    else:
        text = "1234,67"
    return (_source(text, 10, 10, 36, 36),)


def test_payroll_without_leaf_header_band_does_not_raise(table):
    image, row, headings = table
    draw = ImageDraw.Draw(image)
    for y in (270, 315):
        draw.rectangle((30, y, 770, y + 1), fill=255)
    for x in _COORDINATES:
        draw.line((x, 90, x, _ROW[-1]), width=2, fill=0)

    assert "payroll" not in read_table_amounts(image, row, headings, _default_cell_read)


@pytest.mark.parametrize(
    ("left", "right", "affected"),
    [(30, 240, {"payroll", "production_overhead"}), (240, 525, {"payroll"})],
    ids=["label-only-divider", "money-column-divider"],
)
def test_local_row_rule_blocks_cell_even_if_too_short_for_global_grid(table, left, right, affected):
    image, row, headings = table
    ImageDraw.Draw(image).line((left, 384, right, 384), fill=0, width=2)

    result = read_table_amounts(image, row, headings, _default_cell_read)

    assert result.keys().isdisjoint(affected)
    if "production_overhead" not in affected:
        assert result["production_overhead"].amount == Decimal("1234.67")


def test_long_gap_in_selected_column_boundary_does_not_block_other_column(table):
    image, row, headings = table
    ImageDraw.Draw(image).rectangle((239, 285, 243, 344), fill=255)

    result = read_table_amounts(image, row, headings, _default_cell_read)

    assert "payroll" not in result
    assert result["production_overhead"].amount == Decimal("1234.67")


@pytest.mark.parametrize(
    "header",
    [
        ("Общепроизводственные затраты 10800",) * 3,
        (
            "Общепроизводственные затраты 0800",
            "Общепроизводственные затраты 0800",
            "Общепроизводственные затраты 0900",
        ),
    ],
    ids=["longer-number-contains-code", "third-read-disagrees"],
)
def test_header_must_confirm_standalone_code_without_contradiction(table, header):
    image, row, headings = table

    def read(box, scale):
        if box[1] < 145 and box[0] > 525:
            return (_source(header[scale - 2], 10, 10, 36, 36),)
        return _default_cell_read(box, scale)

    result = read_table_amounts(image, row, headings, read)

    assert "production_overhead" not in result
    assert result["payroll"].amount == Decimal("1234.67")


def test_subsidy_only_payroll_leaf_is_not_the_complete_aggregate(table):
    image, row, headings = table

    def read(box, scale):
        if 145 < box[1] < 270:
            return (_source("Оплату труда, всего за счёт субсидии", 10, 10, 36, 36),)
        return _default_cell_read(box, scale)

    result = read_table_amounts(image, row, headings, read)

    assert "payroll" not in result
    assert result["production_overhead"].amount == Decimal("1234.67")


@pytest.mark.parametrize("signed", ["−1234,67", "(1234,67)", "separate"])
def test_third_read_with_negation_blocks_positive_consensus(table, signed):
    image, row, headings = table

    def read(box, scale):
        if box[1] > _ROW[0] and box[0] > 525 and scale == 4:
            if signed == "separate":
                return (_source("−", 3, 10, 12, 35), _source("1234,67", 14, 10, 45, 35))
            return (_source(signed, 10, 10, 36, 36),)
        return _default_cell_read(box, scale)

    result = read_table_amounts(image, row, headings, read)

    assert "production_overhead" not in result
    assert result["payroll"].amount == Decimal("1234.67")
