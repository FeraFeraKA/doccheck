import io
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from PIL import Image

from doccheck_backend import scanned_report
from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.database import create_database_engine
from doccheck_backend.grounded_amounts import _contracts, _money, _periods, format_rubles
from doccheck_backend.native_observations import NativeDocument, NativeIssue, Observation
from doccheck_backend.page_ocr import OcrLine
from doccheck_backend.run_worker import run_document_worker
from doccheck_backend.v32_processor import V32Processor


def test_v32_worker_preserves_number_when_document_prediction_fails(database_url, tmp_path):
    qwen = pytest.importorskip("doccheck_ml.qwen")
    pytest.importorskip("bench.e2e_v32_20261114")

    book = Workbook()
    sheet = book.active
    sheet.title = "КФЗ"
    sheet["A3"] = "Договор № TEST-26"
    sheet["A4"] = "Период: 2026-01-01 — 2026-01-31. Этап 1."
    sheet["B6"], sheet["C6"] = "Статья затрат", "Отчетная сумма, руб."
    sheet["B7"], sheet["C7"] = "Общепроизводственные расходы", 1250
    sheet["A8"], sheet["C8"] = "Всего по отчету", "=SUM(C7:C7)"
    report, image = io.BytesIO(), io.BytesIO()
    book.save(report)
    Image.new("RGB", (32, 32), "white").save(image, format="PNG")

    seen = []

    def read_number(path):
        seen.append(Path(path))
        assert path.is_file()
        return {
            "adapter_sha256": "a" * 64,
            "model_sha256": "b" * 64,
            "policy_sha256": "c" * 64,
            "prediction": {"doc_number": "007-26", "verbatim_line": "Акт № 007-26"},
        }

    def read_document(*args, **kwargs):
        raise qwen.QwenPredictionError("test detail must stay out of the result")

    processor = V32Processor(read_document, read_number)
    engine = create_database_engine(database_url)
    try:
        with TestClient(create_app(Settings(database_url, upload_root=tmp_path))) as client:
            submitted = client.post(
                "/api/v0/runs",
                headers={"Idempotency-Key": str(uuid4())},
                files=[
                    ("report", ("report.xlsx", report.getvalue())),
                    ("documents", ("act.png", image.getvalue())),
                    ("documents", ("duplicate.png", image.getvalue())),
                ],
            )
            assert submitted.status_code == 202
            run_id = submitted.json()["run_id"]
            assert run_document_worker(engine, tmp_path, processor, once=True)
            state = client.get(f"/api/v0/runs/{run_id}").json()
            assert state["status"] == "completed_with_issues"
            response = client.get(f"/api/v0/runs/{run_id}/findings")
            assert response.status_code == 200
            result = response.json()
    finally:
        engine.dispose()

    assert len(seen) == 1 and not seen[0].exists()
    assert "test detail" not in response.text
    assert result["versions"]["model_revision"] == f"{'b' * 64}+lora:{'a' * 64}"
    assert sum(document["duplicate_of"] is not None for document in result["documents"]) == 1
    assert any(
        item["method"] == "qwen_proposal" and item["normalized_value"] == "007-26"
        for item in result["evidence"]
    )
    assert result["rows"][0]["reported_value"] == "1250.00"
    assert result["rows"][0]["status"] == "unverified"


def test_rubles_tolerate_only_xlsx_representation_noise():
    assert format_rubles(Decimal("66936.92999999999"), xlsx=True) == "66936.93"
    assert format_rubles(Decimal("66936.92999999999")) is None
    assert format_rubles(Decimal("66936.929"), xlsx=True) is None


def test_ocr_contract_number_marker_is_not_the_contract_number():
    address = PageLocator(kind="page", page=1, bbox=(0.1, 0.1, 0.7, 0.2))
    observation = Observation("Договор Ne 74/891234/26-47", address)
    assert _contracts((observation,), template=False) == [("74/891234/26-47", observation)]


@pytest.mark.parametrize(("unit", "amount"), [("USD", None), ("руб.", Decimal("625.02"))])
def test_pdf_total_requires_a_ruble_column_or_currency_in_the_value(unit, amount):
    document = NativeDocument(
        (
            Observation(
                f"Сумма, {unit}", PageLocator(kind="page", page=1, bbox=(0.6, 0.2, 0.8, 0.3))
            ),
            Observation("Итого", PageLocator(kind="page", page=1, bbox=(0.1, 0.4, 0.3, 0.5))),
            Observation("625.02", PageLocator(kind="page", page=1, bbox=(0.6, 0.4, 0.8, 0.5))),
        )
    )
    value, _ = _money(document, template=False, format_="pdf")
    assert (value.amount if value is not None else None) == amount


def test_scanned_table_requires_matching_year_and_identifies_missing_columns(monkeypatch):
    image = Image.new("L", (1000, 600), "white")
    row = PageLocator(kind="page", page=1, fragment_id="kfz-stage-3-2026")
    monkeypatch.setattr(scanned_report, "_peaks", lambda *_: [150, 220, 290, 360])
    monkeypatch.setattr(scanned_report, "_column_tracks", lambda *_: [90, 240, 390, 540, 690, 840])
    monkeypatch.setattr(
        scanned_report,
        "recognize_lines",
        lambda *_: [
            OcrLine("Договор № EX-26", (10, 10, 200, 50), 99),
            OcrLine("Отчетный период: 01.01.2026 — 31.05.2026", (10, 60, 600, 85), 99),
            OcrLine("руб.", (700, 100, 800, 130), 99),
        ],
    )
    monkeypatch.setattr(
        scanned_report,
        "_stage_bands",
        lambda *_: iter([(290, 360, "3", "2026"), (220, 290, "4", "2026")]),
    )
    monkeypatch.setattr(scanned_report, "recognize_crop", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        scanned_report, "_headers", lambda *_: {"0200": scanned_report.HeaderGroup(2, 3, 220)}
    )
    monkeypatch.setattr(scanned_report, "_read_amount", lambda *_: ("625.02", Decimal("625.02")))

    assert (
        scanned_report.read_report_row(image, 1, row, "EX-26", ("2025-01-01", "2025-05-31")) is None
    )
    assert (
        scanned_report.read_report_row(image, 1, None, "EX-26", ("2026-01-01", "2026-05-31"))
        is None
    )
    reading = scanned_report.read_report_row(image, 1, row, "EX-26", ("2026-01-01", "2026-05-31"))
    assert reading is not None and not reading.complete
    assert reading.cells[0].amount == Decimal("625.02")
    assert reading.cells[0].locator.bbox == (0.39, 290 / 600, 0.54, 0.6)


def test_skipped_page_blocks_totals_from_visible_fragment(monkeypatch, tmp_path):
    from doccheck_backend import grounded_amounts

    address = PageLocator(kind="page", page=1, bbox=(0.1, 0.2, 0.8, 0.3))
    document = NativeDocument(
        (Observation("Сумма: 625.02 руб.", address),),
        (NativeIssue("native_read_error", page=2),),
    )
    monkeypatch.setattr(grounded_amounts, "_read_observations", lambda *_: (document, "native", ()))
    result = grounded_amounts.ground_document(
        uuid4(), "a" * 32, tmp_path / "act.pdf", "pdf", "b" * 64
    )
    assert result.issues == document.issues
    assert result.amount is None
    assert not any(item.kind == "amount" for item in result.assertions)


def test_final_ruble_total_has_priority_over_intermediate_amount():
    document = NativeDocument(
        (
            Observation(
                "Сумма: 100,00 руб.", PageLocator(kind="page", page=1, bbox=(0.1, 0.3, 0.7, 0.4))
            ),
            Observation(
                "Итого к оплате 120,00 руб.",
                PageLocator(kind="page", page=1, bbox=(0.1, 0.5, 0.7, 0.6)),
            ),
        )
    )
    total, _ = _money(document, template=False, format_="pdf")
    assert total.amount == Decimal("120.00")
    assert total.locator == document.observations[1].locator


@pytest.mark.parametrize(
    ("printed", "bounds"),
    [
        ("Период: Январь 2031 — Февраль 2031", ("2031-01-01", "2031-02-28")),
        ("Период: Январь 2031 г — Февраль 2031 г", ("2031-01-01", "2031-02-28")),
        ("Период: с декабря 2030 г. по январь 2031 г.", ("2030-12-01", "2031-01-31")),
        ("Период: Январь 2031", ("2031-01-01", "2031-01-31")),
        ("Период: Январь 2031 — Февраль", None),
        ("Период: Январь 2031 — Декабрь 2030", None),
    ],
)
def test_primary_period_does_not_shorten_a_month_range(printed, bounds):
    first = PageLocator(kind="page", page=1, bbox=(0.1, 0.2, 0.8, 0.3))
    second = PageLocator(kind="page", page=1, bbox=(0.1, 0.4, 0.8, 0.5))
    reading = _periods((Observation(printed, first), Observation("Дата: 31.01.2031", second)))
    if bounds is None:
        assert reading == []
    else:
        ((period, source),) = reading
        assert (period.start, period.end) == bounds
        assert source.locator == first


def test_wrapped_month_range_withholds_a_partial_period():
    first = PageLocator(kind="page", page=1, bbox=(0.1, 0.2, 0.8, 0.24))
    second = PageLocator(kind="page", page=1, bbox=(0.1, 0.26, 0.8, 0.3))
    dated = PageLocator(kind="page", page=1, bbox=(0.1, 0.4, 0.8, 0.5))
    assert (
        _periods(
            (
                Observation("Период: Январь 2031 г.", first),
                Observation("— Февраль 2031 г.", second),
                Observation("Дата: 31.01.2031", dated),
            )
        )
        == []
    )


def test_unbound_final_label_blocks_the_intermediate_total():
    lines = ("Итого: 100,00 руб.", "Итого к оплате:", "120,00 руб.")
    document = NativeDocument(
        tuple(
            Observation(text, PageLocator(kind="page", page=1, bbox=(0.1, y, 0.6, y + 0.04)))
            for text, y in zip(lines, (0.2, 0.4, 0.5), strict=True)
        )
    )
    assert _money(document, template=False, format_="pdf") == (None, [])


def test_faint_ocr_period_cannot_be_replaced_by_document_date(monkeypatch, tmp_path):
    from doccheck_backend import grounded_amounts

    image = Image.new("RGB", (300, 200), "white")
    path = tmp_path / "synthetic.png"
    image.save(path)
    monkeypatch.setattr(
        grounded_amounts,
        "recognize_lines",
        lambda _: [
            OcrLine("Акт № TEST-43 от 01.03.2031", (5, 10, 200, 20), 95),
            OcrLine("Период: с 01.02.2031 по 28.02.2031", (5, 30, 240, 40), 45),
            OcrLine("Итого: 120,00 руб.", (5, 70, 200, 80), 95),
        ],
    )
    source = grounded_amounts.ground_document(uuid4(), "e" * 32, path, "png", "b" * 64)
    assert source.period is None
    assert source.amount == "120.00"
    assert not any(item.kind == "period" for item in source.assertions)


@pytest.mark.parametrize(
    ("last_line", "confidence", "expected", "unreadable"),
    [
        ("Итого к оплате: 120,00 руб.", 42, None, True),
        ("Итого к оплате: 120,00 руб.", 90, "120.00", False),
        ("Итого к оплате — 120,00 руб.", 90, "120.00", False),
        ("Итого к оплате - 120,00 руб.", 90, "120.00", False),
        ("Итого к оплате: -120,00 руб.", 90, "-120.00", False),
        ("Всего к оплате: 120,00 руб.", 90, "120.00", False),
        ("Итoго к оплате: 120,00 руб.", 42, None, True),
        ("Итoго к оплате: 120,00 руб.", 90, None, True),
        ("Итого к оплате: неразборчиво", 90, None, False),
        ("Итого к оплате: ?20,00 руб.", 90, None, False),
        ("Итого к оплате: сто двадцать рублей", 90, None, False),
        ("Примечание к акту", 42, "100.00", False),
    ],
)
def test_faint_total_prevents_using_intermediate_ocr_amount(
    monkeypatch, tmp_path, last_line, confidence, expected, unreadable
):
    from doccheck_backend import grounded_amounts

    image = Image.new("RGB", (300, 200), "white")
    monkeypatch.setattr(grounded_amounts, "render_pages", lambda *_: iter([image]))
    monkeypatch.setattr(
        grounded_amounts,
        "recognize_lines",
        lambda *_: [
            OcrLine("Сумма: 100,00 руб.", (10, 20, 200, 35), 99),
            OcrLine(last_line, (10, 60, 200, 75), confidence),
        ],
    )
    path = tmp_path / "synthetic.png"
    image.save(path)
    result = grounded_amounts.ground_document(uuid4(), "a" * 32, path, "png", "b" * 64)
    assert result.amount == expected
    assert [item.normalized_value for item in result.assertions if item.kind == "amount"] == (
        [] if expected is None else [expected]
    )
    assert [issue.code for issue in result.issues] == (
        ["unreadable_amount_line"] if unreadable else []
    )


def test_own_document_number_points_to_own_header(monkeypatch, tmp_path):
    from doccheck_backend import grounded_amounts

    document = NativeDocument(
        (
            Observation(
                "Договор № SYN-008", PageLocator(kind="page", page=1, bbox=(0.1, 0.2, 0.8, 0.3))
            ),
            Observation(
                "Акт № SYN-008", PageLocator(kind="page", page=1, bbox=(0.1, 0.4, 0.8, 0.5))
            ),
        )
    )
    monkeypatch.setattr(grounded_amounts, "_read_observations", lambda *_: (document, "native", ()))
    result = grounded_amounts.ground_document(
        uuid4(), "a" * 32, tmp_path / "act.pdf", "pdf", "b" * 64
    )
    assert result.identity == "SYN-008"
    assert result.identity_locator == document.observations[1].locator
