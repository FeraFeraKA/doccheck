"""A scan's monetary unit must be established before its values become RUB."""

from decimal import Decimal
from uuid import uuid4

import pytest
from PIL import Image

from doccheck_backend import scanned_report
from doccheck_backend.contracts.result import FileDecision, Scope, SourceDocument
from doccheck_backend.page_ocr import OcrLine
from doccheck_backend.v32_processor import _rows


def _line(text: str, top: int, confidence: float = 99) -> OcrLine:
    return OcrLine(text, (10, top, 500, top + 20), confidence)


@pytest.mark.parametrize(
    ("unit_lines", "expected"),
    [
        ([_line("Суммы: руб.", 70)], "12.34"),
        ([_line("руб.", 70)], "12.34"),
        ([_line("Суммы: RUB", 70)], "12.34"),
        ([_line("Суммы: тыс. руб.", 70)], None),
        ([_line("Суммы: млн руб.", 70)], None),
        ([_line("Суммы: USD", 70)], None),
        ([], None),
        ([_line("Суммы: руб.", 70, confidence=20)], None),
        ([_line("Суммы: руб.", 70), _line("Суммы: EUR", 95)], None),
        ([_line("Стоимость договора: 12,34 руб.", 70)], None),
        ([_line("тыс.", 70), _line("руб.", 95)], None),
        ([_line("Суммы: 1000 руб.", 70)], None),
        ([_line("Суммы: руб./час", 70)], None),
        ([_line("руб.", 70), _line("Суммы по договору: тыс. руб.", 95)], None),
        ([_line("руб.", 70), _line("Суммы: USD", 95, confidence=20)], None),
    ],
)
def test_simple_scan_exposes_only_unambiguous_ruble_amounts(monkeypatch, unit_lines, expected):
    line = "Оплата труда 12,34"
    lines = [
        _line("Договор № SYN-01", 10),
        _line("Отчетный период: 01.01.2026 — 31.01.2026", 40),
        *unit_lines,
        _line(line, 140),
    ]
    monkeypatch.setattr(scanned_report, "recognize_lines", lambda *_args, **_kwargs: lines)
    monkeypatch.setattr(scanned_report, "recognize_crop", lambda *_args, **_kwargs: line)

    reading = scanned_report._simple_table(
        Image.new("RGB", (600, 400), "white"),
        1,
        None,
        "SYN-01",
        ("2026-01-01", "2026-01-31"),
    )
    assert reading is not None
    assert len(reading.cells) == 1
    assert reading.cells[0].amount == (Decimal(expected) if expected is not None else None)

    run_id, document_id = uuid4(), uuid4().hex
    report = SourceDocument(
        id=document_id,
        name="synthetic.png",
        sha256="a" * 64,
        format="png",
        role="report",
        parse_status="parsed",
        decision=FileDecision(
            state="include", reason_code="test", message="test", evidence_refs=[]
        ),
        errors=[],
    )
    scope = Scope(
        report_document_id=document_id,
        contract_number="SYN-01",
        period_start="2026-01-01",
        period_end="2026-01-31",
        report_row_locator=None,
    )
    rows, evidence, _ = _rows(run_id, scope, report, None, reading, [report], {})
    assert rows[0].reported_value == expected
    if expected is None:
        assert rows[0].status == "unverified"
        assert not any(item.kind == "reported_value" for item in evidence)
    else:
        assert [(item.normalized_value, item.unit) for item in evidence] == [(expected, "RUB")]


@pytest.mark.parametrize(
    ("global_units", "table_units", "expected"),
    [
        ([_line("руб.", 70)], [], True),
        ([_line("Суммы: руб.", 70)], [], True),
        ([_line("руб.", 70)], [_line("Код 1000", 10)], True),
        ([_line("Суммы: тыс. руб.", 70)], [], False),
        ([_line("Суммы: USD", 70)], [], False),
        ([], [], False),
        ([_line("руб.", 70)], [_line("Оплата труда: тыс. руб.", 10)], False),
        ([_line("руб.", 70)], [_line("Страховые взносы: USD", 10)], False),
        ([_line("руб.", 70)], [_line("Страховые взносы: коп.", 10)], False),
        ([_line("руб.", 70)], [_line("Страховые взносы: 1000", 10)], False),
    ],
)
def test_multilevel_scan_checks_units_without_losing_labor_quantity(
    monkeypatch, global_units, table_units, expected
):
    image = Image.new("RGB", (1000, 600), "white")
    xs = list(range(0, 1001, 100))
    ys = [100, 200, 300, 400]
    monkeypatch.setattr(scanned_report, "_table_rules", lambda *_: (None, xs, ys))
    monkeypatch.setattr(scanned_report, "_row_band", lambda *_: (300, 400))
    groups = {
        "0200": scanned_report.HeaderGroup(2, 4, 200),
        "0300": scanned_report.HeaderGroup(4, 5, 200),
        "0800": scanned_report.HeaderGroup(5, 6, 200),
        "0900": scanned_report.HeaderGroup(6, 7, 200),
        "total": scanned_report.HeaderGroup(7, 8, 200),
    }
    monkeypatch.setattr(scanned_report, "_headers", lambda *_: groups)
    monkeypatch.setattr(scanned_report, "_labor_column", lambda *_: (8, "чел.-ч."))
    monkeypatch.setattr(scanned_report, "_pay_breakdown", lambda *_: {"base": 3})
    monkeypatch.setattr(scanned_report, "_read_amount", lambda *_: ("12.34", Decimal("12.34")))

    def recognize(part, **_kwargs):
        if part.height == ys[0]:
            return [_line("Договор № SYN-01", 10), *global_units]
        return table_units

    monkeypatch.setattr(scanned_report, "recognize_lines", recognize)
    reading = scanned_report.read_report_row(image, 1, None, "SYN-01", ("2026-01-01", "2026-01-31"))
    assert reading is not None
    assert reading.complete is expected
    assert all((cell.amount == Decimal("12.34")) is expected for cell in reading.cells)
    labor = next(cell for cell in reading.details if cell.code == "labor_intensity")
    assert labor.unit == "чел.-ч." and labor.amount == Decimal("12.34")
    monetary = next(cell for cell in reading.details if cell.code == "0200-base")
    assert (monetary.amount == Decimal("12.34")) is expected
