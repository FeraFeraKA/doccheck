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
    assert result.contract_source.locator.bbox[:2] == (0.06, 0.09)
    assert result.cutoff_source.locator.bbox[:2] == (0.06, 0.15)


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


def test_ocr_normalizes_pixel_boxes_in_original_png_frame(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    from PIL import Image

    from doccheck_backend.local_ocr import read_paddle

    pixels = SimpleNamespace(__getitem__=lambda *_: None)

    class ImageArray:
        def __getitem__(self, index):
            assert index == (slice(None), slice(None), slice(None, None, -1))
            return pixels

    monkeypatch.setitem(
        sys.modules,
        "numpy",
        SimpleNamespace(asarray=lambda image: ImageArray(), ascontiguousarray=lambda frame: frame),
    )

    def predict(frame):
        assert frame is pixels
        return [
            {
                "rec_texts": ["Исходный текст"],
                "rec_boxes": [[20, 30, 80, 45]],
                "rec_scores": [0.93],
            }
        ]

    monkeypatch.setattr(
        "doccheck_backend.local_ocr._paddle", lambda: SimpleNamespace(predict=predict)
    )
    source = tmp_path / "source.png"
    Image.new("RGB", (200, 100)).save(source)
    document = read_paddle(source, "png")

    assert not document.issues
    (item,) = document.observations
    assert item.locator.page == 1
    assert item.locator.bbox == (0.1, 0.3, 0.4, 0.45)
    assert item.confidence == 0.93


def test_cannot_join_report_scope_across_pages(scanned_stage):
    from dataclasses import replace

    contract, *others = scanned_stage
    wrong_page = replace(contract, locator=contract.locator.model_copy(update={"page": 2}))

    assert parse_scan_report((wrong_page, *others)) is None


def test_conflicting_contract_in_single_observation_is_ambiguous(scanned_stage):
    from dataclasses import replace

    contract, *others = scanned_stage
    conflicting = replace(contract, raw_text=contract.raw_text + "; договор № E2E-99")
    assert parse_scan_report((conflicting, *others)) is None


def test_repeated_date_must_use_same_source_geometry(tmp_path, monkeypatch):
    from PIL import Image

    from doccheck_backend.local_ocr import _date_windows_crop
    from doccheck_backend.native_observations import Observation

    trigger = Observation(
        "Окончание 3 этапа",
        PageLocator(kind="page", page=1, bbox=(0.1, 0.2, 0.3, 0.24)),
    )
    x_values = iter([0.15, 0.55, 0.20, 0.60])

    def nonoverlapping(*_):
        x = next(x_values)
        return (
            Observation(
                "30 мая 2026 г.",
                PageLocator(kind="page", page=1, bbox=(x, 0.2, x + 0.06, 0.6)),
            ),
        )

    monkeypatch.setattr("doccheck_backend.local_ocr._windows_frame", nonoverlapping)
    result = _date_windows_crop(
        Image.new("RGB", (1000, 800)),
        trigger,
        tmp_path / "crop.png",
        1,
        None,
        None,
    )
    assert result is None
