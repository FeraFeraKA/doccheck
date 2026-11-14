"""Compare values already admitted by the reconciliation rules."""

from decimal import Context, Decimal

from doccheck_backend.contracts.result import Completeness, RowStatus


def compare_admitted_values(
    reported_value: str | None,
    expected_value: str | None,
    completeness: Completeness,
    *,
    comparable: bool,
) -> tuple[RowStatus, str | None]:
    """Return status and exact delta for normalized values of the same indicator.

    Inputs are validated decimal strings at the scale of their unit. The caller supplies
    confirmed evidence, completeness and comparability, and passes the full expected value.
    The result model still validates the completed row and its evidence references.
    """
    if (
        not comparable
        or completeness.state != "complete"
        or reported_value is None
        or expected_value is None
    ):
        return "unverified", None

    reported = Decimal(reported_value)
    expected = Decimal(expected_value)
    reported_whole, _, reported_fraction = reported_value.lstrip("-").partition(".")
    expected_whole, _, expected_fraction = expected_value.lstrip("-").partition(".")
    places = max(len(reported_fraction), len(expected_fraction))
    # Reserve an extra integer digit for subtraction of opposite-signed values.
    precision = max(len(reported_whole), len(expected_whole)) + places + 1
    delta = Context(prec=precision).subtract(reported, expected)

    if not delta:
        return "verified", format(Decimal(0), f".{places}f")
    return "discrepancy", format(delta, f".{places}f")
