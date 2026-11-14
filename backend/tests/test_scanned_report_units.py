"""A scan's monetary unit must be established before its values become RUB."""

from decimal import Decimal
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw, ImageFont
from scanned_kfz_fixture import ScanRow, require_raster_ocr, write_kfz_with_breakdown

from doccheck_backend import scanned_report
from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.contracts.result import CheckResult, FileDecision, Scope, SourceDocument
from doccheck_backend.page_ocr import OcrLine
from doccheck_backend.v32_processor import _rows


def _line(text: str, top: int, confidence: float = 99) -> OcrLine:
    return OcrLine(text, (10, top, 500, top + 20), confidence)


@pytest.mark.parametrize(
    ("unit_lines", "expected"),
    [
        ([_line("Суммы КФЗ: руб.", 70)], "12.34"),
        ([_line("руб.", 70)], None),
        ([_line("Суммы: руб.", 70)], None),
        ([_line("Суммы КФЗ: RUB", 70)], "12.34"),
        ([_line("Суммы: тыс. руб.", 70)], None),
        ([_line("Суммы: млн руб.", 70)], None),
        ([_line("Суммы: USD", 70)], None),
        ([_line("Суммы: XYZ", 70)], None),
        ([], None),
        ([_line("Суммы КФЗ: руб.", 70, confidence=20)], None),
        ([_line("Суммы КФЗ: руб.", 70), _line("Суммы: EUR", 95)], None),
        ([_line("Стоимость договора: 12,34 руб.", 70)], None),
        ([_line("Сметная стоимость работ: 12,34 руб.", 70)], None),
        ([_line("тыс.", 70), _line("руб.", 95)], None),
        ([_line("Суммы: 1000 руб.", 70)], None),
        ([_line("Суммы КФЗ: руб./час", 70)], None),
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
        assert rows[0].reported_value is None
        observed = next(item for item in evidence if item.id in rows[0].reported_evidence_refs)
        assert observed.kind == "reported_value" and observed.unit is None
        assert observed.raw_value == "12,34" and observed.normalized_value == "12.34"
        assert observed.locator == reading.cells[0].locator
        reason = next(
            reason for reason in rows[0].reasons if reason.code == "report_unit_unverified"
        )
        assert reason.evidence_refs == [observed.id]
    else:
        assert [(item.normalized_value, item.unit) for item in evidence] == [(expected, "RUB")]


@pytest.mark.parametrize(
    ("global_units", "table_units", "expected"),
    [
        ([_line("руб.", 70)], [], False),
        ([_line("Суммы КФЗ: руб.", 70)], [], True),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Код 1000", 10)], True),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Период 01 / 02", 10)], True),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда AcT", 10)], True),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда", 10), _line("RUB", 40)], True),
        ([_line("Суммы: тыс. руб.", 70)], [], False),
        ([_line("Суммы: USD", 70)], [], False),
        ([], [], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: тыс. руб.", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: тыc. руб.", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Страховые взносы: USD", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: CAD", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Страховые взносы: INR", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда", 10), _line("AUD", 40)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Взносы", 10), _line("SGD", 40)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда", 10), _line("XYZ", 40)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда", 10), _line("xYz", 40)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда", 10), _line("AUD", 40, 15)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда", 10), _line("код AUD", 40)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда USD/hour", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда CAD/hr", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: руб./час", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: руб.／час", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: USD∕hour", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: RUB/hour", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: долл./час", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: $ / час", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда U?D/hour", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда U S D / hour", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда $ /", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда АUD/час", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: USD/?", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: XYZ", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Оплата труда: фунты", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Страховые взносы: коп.", 10)], False),
        ([_line("Суммы КФЗ: руб.", 70)], [_line("Страховые взносы: 1000", 10)], False),
    ],
)
def test_multilevel_scan_checks_units_without_losing_labor_quantity(
    monkeypatch, global_units, table_units, expected
):
    image = Image.new("RGB", (1000, 600), "white")
    xs = list(range(0, 1001, 100))
    ys = [100, 200, 300, 400]
    monkeypatch.setattr(scanned_report, "_table_rules", lambda *_: (None, xs, ys))
    monkeypatch.setattr(scanned_report, "_row_band", lambda *_: (300, 400, "1"))
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

    if not expected:
        run_id, document_id = uuid4(), uuid4().hex
        report = SourceDocument(
            id=document_id,
            name="synthetic.png",
            sha256="c" * 64,
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
        monetary_rows = [row for row in rows if row.unit == "RUB"]
        assert monetary_rows and all(
            row.status == "unverified"
            and row.reported_value is None
            and any(reason.code == "report_unit_unverified" for reason in row.reasons)
            for row in monetary_rows
        )
        sources = {item.id: item for item in evidence}
        for row in monetary_rows:
            assert row.reported_evidence_refs
            assert all(sources[ref].unit is None for ref in row.reported_evidence_refs)


def test_unconfirmed_unit_keeps_source_address_without_asserting_rubles():
    run_id, document_id = uuid4(), uuid4().hex
    report = SourceDocument(
        id=document_id,
        name="synthetic.png",
        sha256="b" * 64,
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
        contract_number="SYN-02",
        period_start="2026-01-01",
        period_end="2026-01-31",
        report_row_locator=None,
    )
    first = PageLocator(kind="page", page=1, bbox=(0.2, 0.3, 0.4, 0.4))
    second = PageLocator(kind="page", page=1, bbox=(0.4, 0.3, 0.6, 0.4))
    scan = scanned_report.ReportReading(
        cells=[
            scanned_report.ReportCell(
                "0200",
                first,
                "12,34",
                None,
                unit_unverified=True,
                unverified_amount=Decimal("12.34"),
            )
        ],
        complete=False,
        details=(
            scanned_report.ReportDetailCell(
                "0200-base",
                second,
                "2,00",
                None,
                "Зарплата",
                "RUB",
                "0200",
                unit_unverified=True,
                unverified_amount=Decimal("2.00"),
            ),
        ),
    )
    rows, evidence, issues = _rows(run_id, scope, report, None, scan, [report], {})
    result = CheckResult.model_validate(
        {
            "schema_version": "doccheck-check-result/1",
            "run_id": str(run_id),
            "synthetic": True,
            "scope": scope,
            "versions": {
                "code_revision": "test",
                "rules_version": "test",
                "ml_module_version": None,
                "ml_policy_version": None,
                "model_revision": None,
            },
            "documents": [report],
            "evidence": evidence,
            "rows": rows,
            "summary": {
                "counts": {"verified": 0, "discrepancy": 0, "unverified": 2},
                "primary_issues": issues,
                "conclusion": "Тестовое значение требует проверки.",
            },
        }
    )
    assert [(item.locator, item.unit) for item in result.evidence] == [
        (first, None),
        (second, None),
    ]
    for row in result.rows:
        assert row.status == "unverified" and row.reported_value is None and row.delta is None
        reason = next(reason for reason in row.reasons if reason.code == "report_unit_unverified")
        assert reason.evidence_refs == row.reported_evidence_refs and len(reason.evidence_refs) == 1


@pytest.mark.parametrize(
    ("label", "offset", "confirmed"),
    [
        ("Суммы КФЗ: руб.", (30, 30), True),
        ("Суммы КФЗ: тыс. руб.", (110, 60), False),
        ("Суммы КФЗ: CAD", (200, 90), False),
    ],
)
def test_real_ocr_does_not_treat_other_units_as_rubles(label, offset, confirmed):
    require_raster_ocr()
    image = Image.new("RGB", (1000, 180), "white")
    ImageDraw.Draw(image).text(
        offset, label, fill="black", font=ImageFont.truetype("DejaVuSans.ttf", 36)
    )
    lines = scanned_report.recognize_lines(image)
    assert scanned_report._confirmed_rubles(lines) is confirmed


@pytest.mark.parametrize("currency", ["AUD", "SGD", "XYZ"])
def test_real_ocr_detects_code_on_separate_header_line(currency):
    require_raster_ocr()
    image = Image.new("RGB", (800, 200), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("DejaVuSans.ttf", 36)
    draw.text((30, 30), "Оплата труда", fill="black", font=font)
    draw.text((30, 100), currency, fill="black", font=font)
    lines = scanned_report.recognize_lines(image, mode=6)
    assert any(line.text.strip().upper() == currency for line in lines)
    assert not scanned_report._confirmed_rubles([_line("Суммы КФЗ: руб.", 5)], lines)


@pytest.mark.parametrize("rate", ["USD/hour", "CAD/hr", "руб./час"])
def test_real_ocr_detects_rate_with_slash(rate):
    require_raster_ocr()
    image = Image.new("RGB", (800, 200), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("DejaVuSans.ttf", 36)
    draw.text((30, 30), "Оплата труда", fill="black", font=font)
    draw.text((30, 100), rate, fill="black", font=font)
    lines = scanned_report.recognize_lines(image, mode=6)
    assert any(scanned_report._UNIT_RATE.search(line.text) for line in lines)
    assert not scanned_report._confirmed_rubles([_line("Суммы КФЗ: руб.", 5)], lines)


def test_real_ocr_reads_an_explicit_ruble_multilevel_report(tmp_path):
    require_raster_ocr()
    period = ("2031-01-01", "2031-03-31")
    contract = "SYN-10"
    path = write_kfz_with_breakdown(
        tmp_path / "report.png",
        contract,
        period,
        ScanRow(5, 2031, ("1070,45", "351,29", "789,05", "399,12", "2609,91")),
    )
    with Image.open(path) as image:
        reading = scanned_report.read_report_row(
            image,
            1,
            PageLocator(kind="page", page=1, fragment_id="kfz-stage-5-2031"),
            contract,
            period,
        )
    assert reading is not None and reading.complete
    assert {cell.code: str(cell.amount) for cell in reading.cells} == {
        "0200": "1070.45",
        "0300": "351.29",
        "0800": "789.05",
        "0900": "399.12",
        "total": "2609.91",
    }


@pytest.mark.parametrize(
    ("label", "position"),
    [("AUD", (100, 420)), ("USD/hour", (620, 289))],
    ids=["split-code", "rate-in-0200"],
)
def test_real_ocr_conflicting_header_remains_unverified_in_result(tmp_path, label, position):
    require_raster_ocr()
    period = ("2031-01-01", "2031-03-31")
    contract = "SYN-10"
    path = write_kfz_with_breakdown(
        tmp_path / "report.png",
        contract,
        period,
        ScanRow(5, 2031, ("1070,45", "351,29", "789,05", "399,12", "2609,91")),
    )
    with Image.open(path) as original:
        image = original.copy()
    ImageDraw.Draw(image).text(
        position, label, fill="black", font=ImageFont.truetype("DejaVuSans.ttf", 30)
    )
    _, _, ys = scanned_report._table_rules(image)
    header_lines = scanned_report.recognize_lines(image.crop((0, ys[0], image.width, ys[-2])))
    assert any(label.upper() in line.text.upper().replace(" ", "") for line in header_lines)
    reading = scanned_report.read_report_row(
        image,
        1,
        PageLocator(kind="page", page=1, fragment_id="kfz-stage-5-2031"),
        contract,
        period,
    )
    assert reading is not None and not reading.complete
    assert reading.cells and all(
        cell.amount is None and cell.unit_unverified for cell in reading.cells
    )

    run_id, document_id = uuid4(), uuid4().hex
    report = SourceDocument(
        id=document_id,
        name="synthetic.png",
        sha256="d" * 64,
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
        contract_number=contract,
        period_start=period[0],
        period_end=period[1],
        report_row_locator=None,
    )
    rows, evidence, _ = _rows(run_id, scope, report, None, reading, [report], {})
    assert all(
        row.status == "unverified" and row.reported_value is None
        for row in rows
        if row.unit == "RUB"
    )
    assert not any(item.kind == "reported_value" and item.unit == "RUB" for item in evidence)
