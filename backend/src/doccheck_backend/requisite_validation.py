"""Local validation for an explicitly observed Russian taxpayer number."""

import re
from dataclasses import dataclass
from typing import Literal

from .contracts.locators import Locator

type InnIssue = Literal["missing_inn", "invalid_inn_format", "invalid_inn_checksum"]

_INN_FORMAT = re.compile(r"[0-9]{10}(?:[0-9]{2})?")
_ORGANIZATION_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_PERSON_FIRST_WEIGHTS = (7, *_ORGANIZATION_WEIGHTS)
_PERSON_SECOND_WEIGHTS = (3, *_PERSON_FIRST_WEIGHTS)


@dataclass(frozen=True, slots=True)
class InnValidation:
    raw: str | None
    locator: Locator | None
    value: str | None
    issue: InnIssue | None


def _check_digit(prefix: str, weights: tuple[int, ...]) -> str:
    return str(
        sum(int(digit) * weight for digit, weight in zip(prefix, weights, strict=True)) % 11 % 10
    )


def validate_observed_inn(raw: str | None, *, locator: Locator | None = None) -> InnValidation:
    """Check format and control digits of an already selected INN token.

    Passing does not establish that an INN was assigned, identifies a named party
    or was read correctly. The supplied address is preserved for the caller.
    """
    value = raw.strip() if raw is not None else ""
    if not value:
        return InnValidation(raw, locator, None, "missing_inn")
    if not _INN_FORMAT.fullmatch(value):
        return InnValidation(raw, locator, None, "invalid_inn_format")

    if len(value) == 10:
        matches = _check_digit(value[:9], _ORGANIZATION_WEIGHTS) == value[9]
    else:
        matches = (
            _check_digit(value[:10], _PERSON_FIRST_WEIGHTS) == value[10]
            and _check_digit(value[:11], _PERSON_SECOND_WEIGHTS) == value[11]
        )
    if not matches:
        return InnValidation(raw, locator, None, "invalid_inn_checksum")
    return InnValidation(raw, locator, value, None)
