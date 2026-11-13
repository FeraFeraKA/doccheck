from dataclasses import replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

import pytest

from doccheck_backend.contracts.locators import (
    PageLocator,
    ParagraphLocator,
    SheetLocator,
    TableCellLocator,
)
from doccheck_backend.contracts.result import Period
from doccheck_backend.evidence_binding import (
    EvidenceBindingError,
    ManifestDocument,
    ObservationAssertion,
    bind_observations,
)

RUN = UUID(int=1)
OTHER_RUN = UUID(int=2)
HASH = sha256(b"synthetic document").hexdigest()
REPORT = ManifestDocument("report", HASH, "pdf", "report")
PRIMARY = ManifestDocument("primary", HASH, "xlsx", "supporting")
TABLE = SheetLocator(kind="sheet", sheet="Synthetic", range="C6")
ADDRESS = PageLocator(kind="page", page=1, line=2, bbox=(0.1, 0.2, 0.3, 0.4))
ASSERTION = ObservationAssertion(
    RUN,
    "primary",
    HASH,
    "xlsx",
    "amount",
    "0,00",
    "0.00",
    "RUB",
    "native",
    TABLE,
)


def test_binds_only_explicit_assertions_and_keeps_exact_zero():
    anchor = ObservationAssertion(
        RUN,
        "report",
        HASH,
        "pdf",
        "reported_value",
        "12,34",
        "12.34",
        "RUB",
        "ocr",
        ADDRESS,
    )
    period = replace(
        ASSERTION,
        kind="period",
        raw_value="Март 2026",
        unit=None,
        normalized_value=Period(start="2026-03-01", end="2026-03-31"),
    )
    bound = bind_observations(RUN, [REPORT, PRIMARY], [anchor, ASSERTION, period])
    assert bound.errors == ()
    report_value, amount, period_value = bound.evidence
    assert report_value.document_id == "report" and report_value.method == "ocr"
    assert report_value.locator == ADDRESS and report_value.raw_value == "12,34"
    assert amount.normalized_value == "0.00" and amount.raw_value == "0,00"
    assert amount.locator == TABLE and amount.document_id == "primary"
    assert period_value.normalized_value == period.normalized_value
    assert len({item.id for item in bound.evidence}) == 3


def test_stable_ids_distinguish_runs_document_instances_and_evidence_fields():
    clone = replace(PRIMARY, id="byte-copy")
    different_instance = replace(ASSERTION, document_id=clone.id)
    different_address = replace(ASSERTION, locator=TABLE.model_copy(update={"range": "C7"}))
    first = bind_observations(
        RUN, [PRIMARY, clone], [ASSERTION, different_instance, different_address, ASSERTION]
    )
    reordered = bind_observations(
        RUN, [clone, PRIMARY], [different_address, different_instance, ASSERTION]
    )
    second_run = bind_observations(OTHER_RUN, [PRIMARY], [replace(ASSERTION, run_id=OTHER_RUN)])
    assert len(first.evidence) == 3
    assert {item.id for item in first.evidence} == {item.id for item in reordered.evidence}
    assert second_run.evidence[0].id not in {item.id for item in first.evidence}


def test_missing_and_changed_readings_keep_local_context_without_inventing_numbers():
    stale = replace(ASSERTION, opened_sha256="a" * 64, raw_value="локальный источник")
    missing = replace(ASSERTION, normalized_value=None, raw_value="пустая ячейка")
    unreadable = replace(ASSERTION, unreadable=True, raw_value="закрытый OCR")
    result = bind_observations(RUN, [PRIMARY], [ASSERTION, stale, missing, unreadable])
    assert [item.normalized_value for item in result.evidence] == ["0.00"]
    assert [item.error.code for item in result.errors] == [
        "source_changed",
        "missing_reading",
        "unreadable_source",
    ]
    assert [item.raw_value for item in result.errors] == [
        stale.raw_value,
        missing.raw_value,
        unreadable.raw_value,
    ]
    for item in result.errors:
        assert item.document_id == PRIMARY.id and item.locator == TABLE
        assert item.raw_value not in item.error.model_dump_json()


@pytest.mark.parametrize(
    ("file_format", "locator"),
    [
        ("pdf", ADDRESS),
        ("png", ADDRESS),
        ("xlsx", TABLE),
        ("docx", ParagraphLocator(kind="paragraph", paragraph=2)),
        ("docx", TableCellLocator(kind="table_cell", table=2, row=1, cell=2)),
    ],
)
def test_binds_all_existing_address_variants(file_format, locator):
    document = replace(PRIMARY, format=file_format)
    assertion = replace(ASSERTION, source_format=file_format, locator=locator)
    bound = bind_observations(RUN, [document], [assertion])
    assert bound.errors == ()
    assert bound.evidence[0].locator == locator


@pytest.mark.parametrize(
    ("file_format", "locator", "error"),
    [
        ("png", PageLocator(kind="page", page=2, line=1), "invalid_locator"),
        ("xlsx", ADDRESS, "invalid_locator"),
        ("docx", None, "invalid_locator"),
        (None, TABLE, "unsupported_format"),
        ("pdf", ADDRESS.model_copy(update={"bbox": (0.0, 0.0, 1.5, 0.2)}), "invalid_locator"),
    ],
)
def test_echoes_no_evidence_for_invalid_source_address(file_format, locator, error):
    document = replace(PRIMARY, format=file_format)
    assertion = replace(ASSERTION, source_format=file_format, locator=locator)
    result = bind_observations(RUN, [document], [assertion])
    assert result.evidence == ()
    assert [item.error.code for item in result.errors] == [error]


def test_format_and_monetary_role_must_correspond_to_manifest():
    wrong_format = replace(ASSERTION, source_format="pdf")
    wrong_role = replace(ASSERTION, kind="reported_value")
    result = bind_observations(RUN, [PRIMARY], [wrong_format, wrong_role])
    assert result.evidence == ()
    assert [item.error.code for item in result.errors] == ["format_mismatch", "invalid_reading"]


@pytest.mark.parametrize(
    ("manifest", "assertion"),
    [
        ([PRIMARY, PRIMARY], ASSERTION),
        ([replace(PRIMARY, sha256="broken")], ASSERTION),
        ([PRIMARY], replace(ASSERTION, document_id="not-in-run")),
        ([PRIMARY], replace(ASSERTION, run_id=OTHER_RUN)),
        ([PRIMARY], replace(ASSERTION, opened_sha256="broken")),
    ],
)
def test_invalid_boundary_input_cannot_cross_runs_or_versions(manifest, assertion):
    with pytest.raises(EvidenceBindingError):
        bind_observations(RUN, manifest, [assertion])


def test_invalid_number_or_ocr_text_stays_local():
    invalid_number = replace(ASSERTION, normalized_value="0.000")
    invalid_text = replace(ASSERTION, raw_value="synthetic\x00value")
    result = bind_observations(RUN, [PRIMARY], [invalid_number, invalid_text])
    assert not result.evidence
    assert [item.error.code for item in result.errors] == ["invalid_reading", "invalid_reading"]
    assert result.errors[-1].raw_value == invalid_text.raw_value


def test_distinct_invalid_sheet_ranges_keep_stable_local_diagnostics():
    malformed = [
        replace(ASSERTION, locator=TABLE.model_copy(update={"range": cell}))
        for cell in ("A0", "B0")
    ]
    first = bind_observations(RUN, [PRIMARY], [ASSERTION, *malformed])
    second = bind_observations(RUN, [PRIMARY], [*reversed(malformed), ASSERTION])

    assert first.evidence == second.evidence and len(first.evidence) == 1
    first_ids = {
        item.locator.range: item.error.id
        for item in first.errors
        if isinstance(item.locator, SheetLocator)
    }
    second_ids = {
        item.locator.range: item.error.id
        for item in second.errors
        if isinstance(item.locator, SheetLocator)
    }
    assert len(first.errors) == len(second.errors) == 2
    assert first_ids == second_ids and set(first_ids) == {"A0", "B0"}
    assert len(set(first_ids.values())) == 2
    for item in first.errors:
        assert item.error.code == "invalid_locator"
        assert item.error.message == "Адрес наблюдения не соответствует формату источника."
        assert "A0" not in item.error.model_dump_json()
        assert "B0" not in item.error.model_dump_json()


@pytest.mark.parametrize(
    "invalid_page",
    [date(2026, 11, 14), Decimal("2.5"), object()],
    ids=["date", "decimal", "opaque"],
)
def test_malformed_typed_locator_cannot_drop_other_observations(invalid_page):
    report = ObservationAssertion(
        RUN,
        REPORT.id,
        HASH,
        "pdf",
        "reported_value",
        "12,34",
        "12.34",
        "RUB",
        "ocr",
        ADDRESS,
    )
    malformed_address = ADDRESS.model_copy(update={"page": invalid_page})
    malformed = replace(report, locator=malformed_address, raw_value="исходный фрагмент")
    first = bind_observations(RUN, [REPORT], [malformed, report])
    second = bind_observations(RUN, [REPORT], [report, malformed])

    assert first.evidence == second.evidence
    assert len(first.evidence) == 1 and first.evidence[0].normalized_value == "12.34"
    (diagnostic,) = first.errors
    assert diagnostic.error.code == "invalid_locator"
    assert diagnostic.error.id == second.errors[0].error.id
    assert diagnostic.raw_value == malformed.raw_value
    assert diagnostic.locator is malformed_address
    assert diagnostic.raw_value not in diagnostic.error.model_dump_json()
