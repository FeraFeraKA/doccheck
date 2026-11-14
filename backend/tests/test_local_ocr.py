from decimal import Decimal

import pytest

from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.native_observations import NativeDocument, Observation
from doccheck_backend.ocr_report import parse_scan_report


def _box(text, left, top, right, *, confidence=0.99):
    return Observation(
        text,
        PageLocator(
            kind="page",
            page=1,
            bbox=(left, top, right, top + 0.018),
            fragment_id=f"ocr-{left}-{top}",
        ),
        confidence=confidence,
    )


@pytest.fixture
def scanned_stage():
    return (
        _box("Договор № SYN-R/11 от 01.01.2027", 0.06, 0.09, 0.36),
        _box("Начало 7 этапа", 0.06, 0.12, 0.14),
        _box('"22" октября 2027 г.', 0.18, 0.12, 0.28),
        _box("Окончание 7 этапа", 0.06, 0.15, 0.15),
        _box('"17" апреля 2028 г.', 0.18, 0.15, 0.28),
        _box("Оплата труда", 0.35, 0.24, 0.53),
        _box("Затраты на оплату труда, всего", 0.34, 0.29, 0.37),
        _box("Общехозяйственные затраты", 0.73, 0.24, 0.81),
        _box("7 этап, 2027 г.:", 0.04, 0.50, 0.16),
        _box("7 этап, 2028 г.:", 0.04, 0.53, 0.16),
        _box("701,50", 0.34, 0.53, 0.37),
        _box("502,12", 0.75, 0.53, 0.79),
        _box("ВСЕГО 7 этап:", 0.04, 0.57, 0.16),
    )


def test_select_stage_period_and_original_boxes(scanned_stage):
    result = parse_scan_report(scanned_stage)
    assert result is not None
    assert result.contract == "SYN-R/11"
    assert result.start.isoformat() == "2028-01-01"
    assert result.end.isoformat() == "2028-04-17"
    assert result.row.bbox[:2] == (0.04, 0.53)
    assert result.amounts["payroll"].amount == Decimal("701.50")
    assert result.amounts["general_admin"].locator.bbox[:2] == (0.75, 0.53)


def test_ambiguous_report_rows_are_rejected(scanned_stage):
    duplicate_row = _box("7 этап, 2028 г.:", 0.04, 0.62, 0.16)
    assert parse_scan_report((*scanned_stage, duplicate_row)) is None


def test_provider_rejects_a_box_in_wrong_frame(tmp_path, monkeypatch):
    from doccheck_backend.local_ocr import read_scan

    invalid = Observation("проверка", PageLocator(kind="page", page=2, line=4))
    monkeypatch.setenv("DOCCHECK_OCR_PROVIDER", "test_local_ocr:_mock_reader")
    monkeypatch.setattr(
        "test_local_ocr._mock_reader", lambda *_: NativeDocument((invalid,)), raising=False
    )
    result = read_scan(tmp_path / "input.png", "png")
    assert not result.observations
    assert result.issues[0].code == "ocr_read_error"
