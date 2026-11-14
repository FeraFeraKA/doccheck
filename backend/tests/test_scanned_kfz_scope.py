from hashlib import sha256
from uuid import uuid4

import pytest
from PIL import Image
from scanned_kfz_fixture import (
    DISTRACTOR_AMOUNTS,
    SYNTHETIC_AMOUNTS,
    SYNTHETIC_CONTRACT,
    ScanRow,
    require_raster_ocr,
    write_scanned_kfz,
    write_support,
)

from doccheck_backend import scanned_report
from doccheck_backend.contracts.locators import PageLocator
from doccheck_backend.grounded_amounts import ground_document
from doccheck_backend.page_ocr import render_pages
from doccheck_backend.scanned_report import read_report_row, read_scan_page
from doccheck_backend.v32_processor import _select_scan_scope

REPORT_ID = "f" * 32
TARGET = ("2034-01-01", "2034-02-28")
JANUARY = ("2034-01-01", "2034-01-31")
FEBRUARY = ("2034-02-01", "2034-02-28")
DISTRACTOR = ("2033-11-01", "2033-12-31")
WRONG_CONTRACT = "74/963211/26-47"
TARGET_ROW = ScanRow(3, 2034, SYNTHETIC_AMOUNTS)


@pytest.fixture(scope="module", autouse=True)
def raster_ocr_available():
    require_raster_ocr()


def _read_scan(path):
    return [
        scan
        for page, image in enumerate(render_pages(path), start=1)
        if (scan := read_scan_page(image, page)) is not None
    ]


def _ground_support(tmp_path, periods, *, contract=SYNTHETIC_CONTRACT):
    documents = []
    run_id = uuid4()
    for index, period in enumerate(periods, 1):
        number = f"SYN-{contract.split('/')[1]}-{index}"
        path = write_support(tmp_path / f"{number}.docx", period, contract=contract, number=number)
        grounded = ground_document(
            run_id, uuid4().hex, path, "docx", sha256(path.read_bytes()).hexdigest()
        )
        assert grounded.contract == contract
        assert grounded.period is not None
        assert (grounded.period.start, grounded.period.end) == period
        assert grounded.identity == number and not grounded.issues
        documents.append(grounded)
    return documents


def _assert_scope(scope, *, page, stage, period=TARGET):
    assert scope is not None
    assert scope.contract_number == SYNTHETIC_CONTRACT
    assert (scope.period_start, scope.period_end) == period
    locator = scope.report_row_locator
    assert isinstance(locator, PageLocator)
    assert locator.page == page
    assert locator.fragment_id == f"kfz-stage-{stage}-{period[0][:4]}"
    return locator


def test_selects_the_only_ruled_row_from_explicit_report_period(tmp_path):
    path = write_scanned_kfz(tmp_path / "report.png", ((TARGET_ROW,),), period=TARGET)
    pages = _read_scan(path)
    scope = _select_scan_scope(REPORT_ID, pages, [])
    locator = _assert_scope(scope, page=1, stage=3)
    reading = read_report_row(
        next(render_pages(path)),
        1,
        locator,
        SYNTHETIC_CONTRACT,
        TARGET,
    )

    assert reading is not None and reading.complete
    assert not reading.details
    assert {cell.code: str(cell.amount) for cell in reading.cells} == {
        "0200": "1350.00",
        "0300": "315.00",
        "0800": "240.00",
        "0900": "180.00",
        "total": "2085.00",
    }


def test_locates_target_page_from_visible_year_band_and_matching_primary_docs(tmp_path):
    distractor = ScanRow(3, 2033, DISTRACTOR_AMOUNTS)
    path = write_scanned_kfz(
        tmp_path / "report.pdf",
        ((distractor,), (TARGET_ROW,)),
        period="Ноябрь 2033 г. — Февраль 2034 г.",
        cover=True,
    )
    support = _ground_support(tmp_path, (JANUARY, FEBRUARY))
    unrelated = _ground_support(tmp_path, (DISTRACTOR,), contract=WRONG_CONTRACT)
    pages = _read_scan(path)
    locator = _assert_scope(
        _select_scan_scope(REPORT_ID, pages, [*unrelated, *support]),
        page=3,
        stage=3,
    )
    target_image = list(render_pages(path))[2]
    reading = read_report_row(
        target_image,
        3,
        locator,
        SYNTHETIC_CONTRACT,
        TARGET,
    )

    assert reading is not None and reading.complete
    totals = [cell for cell in reading.cells if cell.code == "total"]
    assert len(totals) == 1 and str(totals[0].amount) == "2085.00"
    assert totals[0].locator.page == 3


def test_same_year_stages_remain_ambiguous_when_only_header_has_period(tmp_path):
    other_stage = ScanRow(4, 2034, DISTRACTOR_AMOUNTS)
    path = write_scanned_kfz(
        tmp_path / "report.png",
        ((TARGET_ROW, other_stage),),
        period=TARGET,
    )
    support = _ground_support(tmp_path, (JANUARY, FEBRUARY))

    assert _select_scan_scope(REPORT_ID, _read_scan(path), support) is None


@pytest.mark.parametrize("header", [TARGET, "Январь 2034 г. — Февраль 2034 г.", None])
def test_manual_stage_requires_the_printed_row_period(tmp_path, header):
    january = ScanRow(3, 2034, SYNTHETIC_AMOUNTS, JANUARY)
    february = ScanRow(4, 2034, DISTRACTOR_AMOUNTS, FEBRUARY)
    path = write_scanned_kfz(tmp_path / "report.png", ((january, february),), period=header)
    image = next(render_pages(path))
    locator = PageLocator(kind="page", page=1, fragment_id="kfz-stage-3-2034")

    assert read_report_row(image, 1, locator, SYNTHETIC_CONTRACT, FEBRUARY) is None
    assert read_report_row(image, 1, locator, SYNTHETIC_CONTRACT, TARGET) is None
    reading = read_report_row(image, 1, locator, SYNTHETIC_CONTRACT, JANUARY)
    assert reading is not None and reading.complete
    assert str(next(cell.amount for cell in reading.cells if cell.code == "total")) == "2085.00"


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("01. 01. 2034 — 31. 01. 2034", JANUARY),
        ("Январь 2034 г.", JANUARY),
        ("1 января 2034 — 31 января 2034", JANUARY),
        ("с 01.01.2034 по 31.01.2034", JANUARY),
        ("01.01.2034 — 3?.01.2034", None),
    ],
)
def test_printed_row_period_does_not_fall_back_to_the_broader_header(
    monkeypatch, printed, expected
):
    monkeypatch.setattr(scanned_report, "recognize_crop", lambda *_: printed)
    image = Image.new("L", (300, 300), "white")
    assert (
        scanned_report._visible_row_period(image, [10, 40, 175], 100, 160, "2034", {TARGET})
        == expected
    )


def test_manual_period_disambiguates_rows_of_the_same_stage_and_year(tmp_path):
    january = ScanRow(3, 2034, SYNTHETIC_AMOUNTS, JANUARY)
    february = ScanRow(3, 2034, DISTRACTOR_AMOUNTS, FEBRUARY)
    path = write_scanned_kfz(tmp_path / "report.png", ((january, february),), period=TARGET)
    image = next(render_pages(path))
    locator = PageLocator(kind="page", page=1, fragment_id="kfz-stage-3-2034")
    reading = read_report_row(image, 1, locator, SYNTHETIC_CONTRACT, FEBRUARY)
    assert reading is not None and reading.complete
    assert str(next(cell.amount for cell in reading.cells if cell.code == "total")) == "4180.00"


def test_two_distinct_row_periods_are_selected_only_with_unique_support(tmp_path):
    target = ScanRow(3, 2034, SYNTHETIC_AMOUNTS, JANUARY)
    other = ScanRow(4, 2034, DISTRACTOR_AMOUNTS, FEBRUARY)
    path = write_scanned_kfz(
        tmp_path / "report.png",
        ((target, other),),
        period=TARGET,
    )
    first, second, third = _ground_support(tmp_path, (JANUARY, FEBRUARY, FEBRUARY))
    pages = _read_scan(path)

    assert _select_scan_scope(REPORT_ID, pages, []) is None
    assert _select_scan_scope(REPORT_ID, pages, [second, second]) is None
    assert _select_scan_scope(REPORT_ID, pages, [first, second, third]) is None
    locator = _assert_scope(
        _select_scan_scope(REPORT_ID, pages, [second, third]),
        page=1,
        stage=4,
        period=FEBRUARY,
    )

    image = next(render_pages(path))
    reading = read_report_row(
        image,
        1,
        locator,
        SYNTHETIC_CONTRACT,
        FEBRUARY,
    )
    assert reading is not None and reading.complete
    assert str(next(cell.amount for cell in reading.cells if cell.code == "total")) == "4180.00"


def test_missing_second_row_period_cannot_be_replaced_by_dates_from_primary_docs(tmp_path):
    target = ScanRow(3, 2034, SYNTHETIC_AMOUNTS, JANUARY)
    unknown = ScanRow(4, 2034, DISTRACTOR_AMOUNTS)
    path = write_scanned_kfz(tmp_path / "report.png", ((target, unknown),))
    support = _ground_support(tmp_path, (JANUARY, JANUARY))

    assert _select_scan_scope(REPORT_ID, _read_scan(path), support) is None
