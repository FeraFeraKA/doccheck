"""Internal parsed observations, independent of financial result decisions."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from doccheck_backend.contracts.locators import Locator


@dataclass(frozen=True)
class Observation:
    raw_text: str
    locator: Locator
    amount: Decimal | None = None
    amount_role: Literal["candidate", "component", "total", "basis"] | None = None
    cached_value: Decimal | None = None
    component_locators: tuple[Locator, ...] = ()
    column_span: int = 1


@dataclass(frozen=True)
class NativeIssue:
    code: str
    locator: Locator | None = None
    page: int | None = None


@dataclass(frozen=True)
class NativeDocument:
    observations: tuple[Observation, ...] = ()
    issues: tuple[NativeIssue, ...] = ()
    has_raster_content: bool = False
