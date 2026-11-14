"""Compare values already admitted by the reconciliation rules."""

from decimal import Context, Decimal

from doccheck_backend.contracts.result import Completeness, Reason, RowStatus


def _decimal_difference(reported: str, expected: str) -> Decimal:
    reported_whole, _, reported_fraction = reported.lstrip("-").partition(".")
    expected_whole, _, expected_fraction = expected.lstrip("-").partition(".")
    places = max(len(reported_fraction), len(expected_fraction))
    # Reserve an extra integer digit for subtraction of opposite-signed values.
    precision = max(len(reported_whole), len(expected_whole)) + places + 1
    return Context(prec=precision).subtract(Decimal(reported), Decimal(expected))


def compare_observed_rubles(
    reported: str | None, observed: str | None, evidence_refs: list[str]
) -> Reason | None:
    """Compare a reported value with available sources without asserting completeness."""
    if reported is None or observed is None:
        return None
    difference = _decimal_difference(reported, observed)
    if difference == 0:
        return Reason(
            code="observed_match",
            message="КФЗ совпадает с суммой по доступной первичке.",
            evidence_refs=evidence_refs,
        )
    relation = "больше" if difference > 0 else "меньше"
    return Reason(
        code="observed_difference",
        message=(
            f"Сумма в КФЗ на {difference.copy_abs():.2f} ₽ {relation} суммы по доступной первичке."
        ),
        evidence_refs=evidence_refs,
    )


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

    delta = _decimal_difference(reported_value, expected_value)
    if not delta:
        return "verified", format(delta.copy_abs(), "f")
    return "discrepancy", format(delta, "f")
