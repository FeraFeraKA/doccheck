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


def test_duplicate_reading_of_exact_same_report_row_is_not_ambiguity(scanned_stage):
    from dataclasses import replace

    row = next(item for item in scanned_stage if item.raw_text == "7 этап, 2028 г.:")
    confirmed = replace(
        row,
        locator=row.locator.model_copy(update={"fragment_id": "same-cell-reread"}),
        repeated_read=True,
    )
    assert parse_scan_report((*scanned_stage, confirmed)) is not None


def test_repeated_page_read_rejects_conflicting_alternative_in_either_frame():
    from dataclasses import replace

    from doccheck_backend.local_ocr import _repeated_full_frame_read

    original = _box("Дата 10", 0.30, 0.10, 0.54)
    conflict = replace(original, raw_text="Дата 11")
    assert not _repeated_full_frame_read(original, (original, conflict), (original,))
    assert not _repeated_full_frame_read(original, (original,), (original, conflict))
    assert _repeated_full_frame_read(original, (original,), (original, original))


def test_conflict_on_row_page_survives_same_date_on_earlier_page(scanned_stage):
    from dataclasses import replace

    source = scanned_stage[4]
    alternative = replace(source, raw_text='"18" апреля 2028 г.', confidence=0.74)
    another_page = replace(
        alternative,
        locator=alternative.locator.model_copy(update={"page": 2}),
    )
    stage_label = scanned_stage[3]
    label_elsewhere = replace(
        stage_label,
        locator=stage_label.locator.model_copy(update={"page": 2}),
        confidence=0.73,
    )

    assert parse_scan_report((another_page, label_elsewhere, *scanned_stage, alternative)) is None


def test_low_score_contract_conflict_at_same_address_rejects_scope(scanned_stage):
    from dataclasses import replace

    selected = scanned_stage[0]
    competing = replace(selected, raw_text="Договор № SYN-R/99", confidence=0.73)

    assert parse_scan_report((*scanned_stage, competing)) is None


def test_broad_row_box_cannot_join_two_disjoint_narrow_boxes(scanned_stage):
    selected = scanned_stage[9]
    narrow_left = _box(selected.raw_text, 0.04, 0.53, 0.085)
    narrow_right = _box(selected.raw_text, 0.115, 0.53, 0.16)

    assert parse_scan_report((*scanned_stage, narrow_left, narrow_right)) is None


def test_contained_compact_alternative_is_not_lost_to_iou():
    from doccheck_backend.local_ocr import _repeated_full_frame_read

    broad = _box("Договор № SYN-R/11", 0.06, 0.09, 0.36)
    compact = _box("SYN-R/99", 0.29, 0.09, 0.34)

    assert not _repeated_full_frame_read(broad, (broad,), (broad, compact))


def test_crop_cannot_erase_conflict_from_verification_frame(scanned_stage, tmp_path, monkeypatch):
    from PIL import Image

    from doccheck_backend.local_ocr import _read_windows_page

    first, second = tmp_path / "first.png", tmp_path / "second.png"
    Image.new("RGB", (40, 40)).save(first)
    original = scanned_stage[0]
    alternate = _box("SYN-R/99", 0.23, 0.09, 0.30, confidence=0.74)
    monkeypatch.setattr(
        "doccheck_backend.local_ocr._windows_frame",
        lambda path, *_: scanned_stage if path == first else (*scanned_stage, alternate),
    )
    monkeypatch.setattr("doccheck_backend.local_ocr._context_windows_crops", lambda *_: (original,))
    merged = _read_windows_page(first, second, 1, None, None)

    assert any(item.raw_text == alternate.raw_text for item in merged)
    assert parse_scan_report(merged) is None


def test_date_parser_cannot_skip_intervening_low_quality_fragment(scanned_stage):
    fragment = _box("архивный", 0.147, 0.15, 0.172, confidence=0.54)

    assert parse_scan_report((*scanned_stage, fragment)) is None


def test_compact_numeric_alternative_inside_contract_value_rejects_scope(scanned_stage):
    _, *others = scanned_stage
    contract = _box("Договор № 741208 от 01.01.2027", 0.06, 0.09, 0.36)
    alternate = _box("741209", 0.166, 0.09, 0.216, confidence=0.73)

    assert parse_scan_report((contract, *others, alternate)) is None


def test_date_to_right_of_contract_value_does_not_compete(scanned_stage):
    _, *others = scanned_stage
    contract = _box("Договор № 741208 от 01.01.2027", 0.06, 0.09, 0.36)
    from dataclasses import replace

    number = _box("741208", 0.165, 0.09, 0.218)
    date_reading = _box("01.01.2027", 0.258, 0.09, 0.36, confidence=0.73)
    number_start = contract.raw_text.index(number.raw_text)
    date_start = contract.raw_text.index(date_reading.raw_text)
    contract = replace(
        contract,
        text_boxes=(
            (number_start, number_start + len(number.raw_text), number.locator),
            (date_start, date_start + len(date_reading.raw_text), date_reading.locator),
        ),
    )

    result = parse_scan_report((contract, *others, date_reading))

    assert result is not None
    assert result.contract == "741208"
    assert result.end.isoformat() == "2028-04-17"


def test_literal_date_in_precise_contract_box_remains_a_conflict(scanned_stage):
    from dataclasses import replace

    _, *others = scanned_stage
    source = _box("Договор № SYN-41 от 2027-01-01", 0.06, 0.09, 0.36)
    number = _box("SYN-41", 0.225, 0.09, 0.275)
    date = _box("2027-01-01", 0.299, 0.09, 0.36, confidence=0.72)
    source = replace(
        source,
        text_boxes=(
            (source.raw_text.index("SYN"), source.raw_text.index(" от"), number.locator),
            (source.raw_text.index("2027"), len(source.raw_text), date.locator),
        ),
    )
    disputed = replace(date, locator=number.locator)

    assert parse_scan_report((source, *others, date)) is not None
    assert parse_scan_report((source, *others, disputed)) is None


def test_repeated_context_lifts_exact_word_positions(tmp_path, monkeypatch):
    from dataclasses import replace

    from PIL import Image

    from doccheck_backend.local_ocr import _context_windows_crops

    original = _box("Договор № SYN-41", 0.06, 0.10, 0.19)
    local = _box("Договор № SYN-41", 0.05, 0.32, 0.52)
    local = replace(
        local,
        text_boxes=((10, 16, _box("SYN-41", 0.30, 0.32, 0.52).locator),),
    )
    monkeypatch.setattr("doccheck_backend.local_ocr._windows_frame", lambda *_: (local,))
    result = _context_windows_crops(
        Image.new("RGB", (1000, 700)), (original,), tmp_path / "area.png", 1, None, None
    )

    (box,) = result
    ((start, end, location),) = box.text_boxes
    assert box.raw_text[start:end] == "SYN-41"
    assert location.bbox[0] > box.locator.bbox[0]
    assert location.bbox[2] == box.locator.bbox[2]


def test_precise_contract_read_takes_priority_over_same_value_broad_copy(scanned_stage):
    from dataclasses import replace

    _, *others = scanned_stage
    broad = _box("Договор № SYN-41 от 2027-01-01", 0.06, 0.09, 0.36)
    number = _box("SYN-41", 0.225, 0.09, 0.275)
    date_reading = _box("2027-01-01", 0.299, 0.09, 0.36, confidence=0.72)
    precise = replace(
        broad,
        text_boxes=(
            (broad.raw_text.index("SYN"), broad.raw_text.index(" от"), number.locator),
            (broad.raw_text.index("2027"), len(broad.raw_text), date_reading.locator),
        ),
    )

    assert parse_scan_report((broad, precise, *others, date_reading)) is not None


def test_bare_alternative_date_in_same_exact_region_rejects_scope(scanned_stage):
    from dataclasses import replace

    broad = _box("Окончание 7 этапа 17 апреля 2028 г.", 0.06, 0.15, 0.28)
    date = _box("17 апреля 2028", 0.18, 0.15, 0.28)
    precise = replace(
        broad,
        text_boxes=((broad.raw_text.index("17"), broad.raw_text.index(" г."), date.locator),),
    )
    alternative = replace(date, raw_text="18 апреля 2028 г.", confidence=0.74)
    elsewhere = replace(
        alternative,
        locator=alternative.locator.model_copy(update={"bbox": (0.3, 0.15, 0.4, 0.168)}),
    )
    case = (*scanned_stage[:3], broad, precise, *scanned_stage[5:])

    assert parse_scan_report((*case, elsewhere)) is not None
    assert parse_scan_report((*case, alternative)) is None


def test_precise_contract_read_does_not_hide_conflict_at_other_occurrence(scanned_stage):
    from dataclasses import replace

    _, *others = scanned_stage
    broad = _box("Договор № SYN-41", 0.27, 0.09, 0.50)
    precise = _box("Договор № SYN-41", 0.52, 0.09, 0.74)
    number = _box("SYN-41", 0.64, 0.09, 0.74)
    precise = replace(precise, text_boxes=((10, 16, number.locator),))
    alternate = _box("SYN-42", 0.30, 0.09, 0.39, confidence=0.72)

    assert parse_scan_report((broad, precise, *others)) is not None
    assert parse_scan_report((broad, precise, *others, alternate)) is None


@pytest.mark.parametrize("alternate", ("2028-04-18", "18.04.2028", "18 апреля 2028 г."))
def test_bare_cutoff_alternative_survives_different_position_with_precise_read(
    scanned_stage, alternate
):
    from dataclasses import replace

    broad = _box("Окончание 7 этапа 17 апреля 2028 г.", 0.05, 0.16, 0.28)
    precise = _box(broad.raw_text, 0.48, 0.16, 0.74)
    date = _box("17 апреля 2028", 0.61, 0.16, 0.74)
    precise = replace(
        precise,
        text_boxes=((precise.raw_text.index("17"), precise.raw_text.index(" г."), date.locator),),
    )
    disputed = _box(alternate, 0.18, 0.16, 0.28, confidence=0.72)
    case = (*scanned_stage[:3], broad, precise, *scanned_stage[5:])

    assert parse_scan_report(case) is not None
    assert parse_scan_report((*case, disputed)) is None


def test_split_bare_cutoff_contradiction_requires_contiguous_date(scanned_stage):
    from dataclasses import replace

    broad = _box("Окончание 7 этапа 17 апреля 2028 г.", 0.06, 0.15, 0.36)
    date = _box("17 апреля 2028", 0.18, 0.15, 0.36)
    precise = replace(
        broad,
        text_boxes=((broad.raw_text.index("17"), broad.raw_text.index(" г."), date.locator),),
    )
    day = _box("18", 0.18, 0.15, 0.20, confidence=0.71)
    month = _box("апреля", 0.25, 0.15, 0.29, confidence=0.71)
    year = _box("2028 г.", 0.30, 0.15, 0.36, confidence=0.71)
    intervening = _box("архив", 0.21, 0.15, 0.24, confidence=0.50)
    case = (*scanned_stage[:3], precise, *scanned_stage[5:])

    assert parse_scan_report((*case, day, month, year)) is None
    assert parse_scan_report((*case, day, intervening, month, year)) is not None


def test_scanned_contract_drops_sentence_dot_without_changing_internal_dots(scanned_stage):
    contract = _box("Договор № E2E.31.", 0.06, 0.09, 0.36)
    other = _box("E2E.31", 0.27, 0.09, 0.34, confidence=0.72)

    scope = parse_scan_report((contract, *scanned_stage[1:], other))
    assert scope is not None
    assert scope.contract == "E2E.31"
    assert scope.contract_source.raw_text.endswith(".")


def test_scanned_scope_uses_same_value_metadata_on_selected_row_page(scanned_stage):
    from dataclasses import replace

    # The full report is on page 2, with identical metadata repeated on page 1.
    report = tuple(
        replace(item, locator=item.locator.model_copy(update={"page": 2})) for item in scanned_stage
    )
    cover = scanned_stage[:5]
    result = parse_scan_report((*cover, *report))

    assert result is not None
    assert result.row.page == result.contract_source.locator.page == 2
    assert result.cutoff_source.locator.page == 2
    assert parse_scan_report((*cover, *report[1:])) is None
    assert parse_scan_report((*cover, report[0], *report[5:])) is None

    conflicting_cover = replace(cover[0], raw_text="Договор № OTHER-19")
    assert parse_scan_report((conflicting_cover, *cover[1:], *report)) is None


@pytest.mark.parametrize(
    ("text", "confidence", "repeated"),
    [("7 этап, 2029 г.:", 0.60, False), ("8 этап, 2028 г.:", 0.99, True)],
)
def test_conflicting_stage_or_year_at_selected_row_location_rejects_scope(
    scanned_stage, text, confidence, repeated
):
    from dataclasses import replace

    row = next(item for item in scanned_stage if item.raw_text == "7 этап, 2028 г.:")
    alternative = replace(row, raw_text=text, confidence=confidence, repeated_read=repeated)

    assert parse_scan_report((*scanned_stage, alternative)) is None
