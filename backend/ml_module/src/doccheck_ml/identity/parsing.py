"""Exact amount/date parsers preserved from the existing identity module."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
import unicodedata


def parse_amount(value: object) -> Decimal | None:
    """Normalize explicit decimal notation; never guess a missing digit/decimal."""
    if value is None or isinstance(value, bool):
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"(?:руб\.?|рублей|rub|₽)$", "", text, flags=re.IGNORECASE)
    if "," in text and "." in text:
        # Accept unambiguous grouped numbers such as 1,234.56 or 1.234,56.
        decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
        group_separator = "." if decimal_separator == "," else ","
        integer, fraction = text.rsplit(decimal_separator, 1)
        if not re.fullmatch(r"[+-]?\d{1,3}(?:" + re.escape(group_separator) + r"\d{3})+", integer):
            return None
        if not re.fullmatch(r"\d{1,2}", fraction):
            return None
        text = integer.replace(group_separator, "") + "." + fraction
    elif "," in text:
        text = text.replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def parse_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None
