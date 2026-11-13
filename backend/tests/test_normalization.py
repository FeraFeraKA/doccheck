import pytest

from doccheck_backend.normalization import (
    normalize_contract_number,
    normalize_document_date,
    normalize_document_period,
)


def test_contract_number_keeps_distinguishing_characters_and_raw_value():
    raw = " \u00a0AB / 001-Ж_7\u202f "
    reading = normalize_contract_number(raw)
    assert reading.raw == raw
    assert reading.value == "AB / 001-Ж_7"
    assert reading.issue is None

    distinct = ["A/001", "А/001", "A/01", "A-001", "A—001", "A /001", "a/001"]
    assert [normalize_contract_number(item).value for item in distinct] == distinct
    assert normalize_contract_number("A\u0301/001").value == "Á/001"


@pytest.mark.parametrize(
    ("raw", "issue"),
    [
        (None, "missing"),
        ("\u00a0", "missing"),
        ("—", "invalid_contract_number"),
        ("AB\0-01", "invalid_contract_number"),
        ("\ufffd014", "invalid_contract_number"),
    ],
)
def test_contract_number_preserves_unusable_reading(raw: str | None, issue: str):
    reading = normalize_contract_number(raw)
    assert (reading.raw, reading.value, reading.issue) == (raw, None, issue)


@pytest.mark.parametrize(
    ("raw", "value"), [(" 29.02.2024 ", "2024-02-29"), ("2025-12-31", "2025-12-31")]
)
def test_normalizes_only_observed_document_date(raw: str, value: str):
    reading = normalize_document_date(raw)
    assert (reading.raw, reading.value, reading.issue) == (raw, value, None)


@pytest.mark.parametrize("raw", ["29.02.2025", "01/02/2026", "2026-02", "02.13.2026"])
def test_invalid_or_unresolved_date_stays_unavailable(raw: str):
    reading = normalize_document_date(raw)
    assert (reading.raw, reading.value, reading.issue) == (raw, None, "invalid_date")


def test_period_accepts_explicit_bounds_and_does_not_use_document_date():
    document_date = normalize_document_date("04.03.2026")
    period = normalize_document_period("01.02.2026", "28.02.2026")
    assert document_date.value == "2026-03-04"
    assert period.value is not None
    assert period.value.model_dump() == {"start": "2026-02-01", "end": "2026-02-28"}
    assert period.start.raw == "01.02.2026"
    assert period.end.raw == "28.02.2026"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (None, "2026-02-28", {"start": None, "end": "2026-02-28"}),
        ("2026-02-01", None, {"start": "2026-02-01", "end": None}),
    ],
)
def test_period_does_not_invent_missing_bound(start: str | None, end: str | None, expected: dict):
    period = normalize_document_period(start, end)
    assert period.value is not None
    assert period.value.model_dump() == expected
    assert period.issue is None


@pytest.mark.parametrize(
    ("start", "end", "issue"),
    [
        (None, None, "missing"),
        ("2026-02-31", "2026-03-01", "invalid_bound"),
        ("2026-03-01", "2026-02-28", "reversed_bounds"),
    ],
)
def test_period_rejects_unknown_invalid_or_reversed_bounds(
    start: str | None, end: str | None, issue: str
):
    period = normalize_document_period(start, end)
    assert period.value is None
    assert period.issue == issue
    assert (period.start.raw, period.end.raw) == (start, end)
