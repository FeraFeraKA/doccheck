"""Normalize explicitly selected document fields without inferring their role."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Literal

from .contracts.result import Period

FieldIssue = Literal["missing", "invalid_contract_number", "invalid_date"]
PeriodIssue = Literal["missing", "invalid_bound", "reversed_bounds"]
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DOTTED_DATE = re.compile(r"([0-9]{2})\.([0-9]{2})\.([0-9]{4})")


@dataclass(frozen=True)
class NormalizedField:
    raw: str | None
    value: str | None
    issue: FieldIssue | None = None


@dataclass(frozen=True)
class NormalizedPeriod:
    start: NormalizedField
    end: NormalizedField
    value: Period | None
    issue: PeriodIssue | None = None


def normalize_contract_number(raw: str | None) -> NormalizedField:
    """Canonicalize Unicode encoding and outer whitespace, retaining the token."""
    if raw is None or not raw.strip():
        return NormalizedField(raw, None, "missing")
    value = unicodedata.normalize("NFC", raw.strip())
    # A replacement character means a character was lost during decoding.
    if "\ufffd" in value:
        return NormalizedField(raw, None, "invalid_contract_number")
    if not any(character.isalnum() for character in value) or any(
        unicodedata.category(character).startswith("C") for character in value
    ):
        return NormalizedField(raw, None, "invalid_contract_number")
    return NormalizedField(raw, value)


def normalize_document_date(raw: str | None) -> NormalizedField:
    """Normalize an explicit ISO or dotted day-month-year date."""
    if raw is None or not raw.strip():
        return NormalizedField(raw, None, "missing")
    value = raw.strip()
    dotted = _DOTTED_DATE.fullmatch(value)
    if dotted is not None:
        day, month, year = dotted.groups()
        value = f"{year}-{month}-{day}"
    elif not _ISO_DATE.fullmatch(value):
        return NormalizedField(raw, None, "invalid_date")

    try:
        normalized = date.fromisoformat(value)
    except ValueError:
        return NormalizedField(raw, None, "invalid_date")
    return NormalizedField(raw, normalized.isoformat())


def normalize_document_period(raw_start: str | None, raw_end: str | None) -> NormalizedPeriod:
    """Normalize observed bounds, keeping a genuinely missing bound open."""
    start = normalize_document_date(raw_start)
    end = normalize_document_date(raw_end)
    if start.issue == "invalid_date" or end.issue == "invalid_date":
        return NormalizedPeriod(start, end, None, "invalid_bound")
    if start.value is None and end.value is None:
        return NormalizedPeriod(start, end, None, "missing")
    if start.value is not None and end.value is not None and start.value > end.value:
        return NormalizedPeriod(start, end, None, "reversed_bounds")
    return NormalizedPeriod(start, end, Period(start=start.value, end=end.value))
