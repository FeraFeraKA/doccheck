"""Read the card's own number from an explicit report heading."""

import re
from collections.abc import Iterable

_NUMBER = re.compile(
    r"^(?:КФЗ|Карточка\s+уч[её]та\s+фактических\s+затрат)"
    r"\s*(?:№\s*|N[oо°º]\.?\s+)([A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9-]*(?:[./][A-ZА-ЯЁ0-9][A-ZА-ЯЁ0-9-]*)*)"
    r"(?:\s*[·—]\s*[^\r\n]+)?\.?$",
    re.IGNORECASE,
)


def report_number(headings: Iterable[str]) -> str | None:
    numbers = {match[1] for text in headings if (match := _NUMBER.fullmatch(text.strip()))}
    return next(iter(numbers)) if len(numbers) == 1 else None
