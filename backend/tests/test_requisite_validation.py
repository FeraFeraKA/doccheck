import pytest

from doccheck_backend.contracts.locators import ParagraphLocator, SheetLocator
from doccheck_backend.requisite_validation import validate_observed_inn


@pytest.mark.parametrize("digits", ["0135792463", "0101010020", "014234567800", "012345678943"])
def test_valid_format_and_control_digits_preserve_leading_zero(digits: str):
    address = SheetLocator(kind="sheet", sheet="Синтетика", range="B6")
    raw = f"  {digits}\u00a0"
    result = validate_observed_inn(raw, locator=address)
    assert result.raw == raw
    assert result.locator == address
    assert result.value == digits
    assert result.issue is None


@pytest.mark.parametrize("raw", ["0135792464", "012345678953", "012345678944", "012345678954"])
def test_checksum_failure_preserves_source_and_discards_value(raw: str):
    address = ParagraphLocator(kind="paragraph", paragraph=3)
    result = validate_observed_inn(raw, locator=address)
    assert result.raw == raw
    assert result.locator == address
    assert result.value is None
    assert result.issue == "invalid_inn_checksum"


@pytest.mark.parametrize(
    "raw",
    [
        "013579246",
        "01357924630",
        "0135792463000",
        "0135 792463",
        "013579246З",
        "０135792463",
        "ИНН: 0135792463",
        "SYN-INN-0135792463",
    ],
)
def test_invalid_token_remains_available_for_diagnosis(raw: str):
    result = validate_observed_inn(raw)
    assert result.raw == raw
    assert result.locator is None
    assert result.value is None
    assert result.issue == "invalid_inn_format"


@pytest.mark.parametrize("raw", [None, "", " \u00a0"])
def test_missing_token_is_never_substituted(raw: str | None):
    address = SheetLocator(kind="sheet", sheet="Синтетика", range="A2")
    result = validate_observed_inn(raw, locator=address)
    assert result.raw == raw
    assert result.locator == address
    assert result.value is None
    assert result.issue == "missing_inn"
