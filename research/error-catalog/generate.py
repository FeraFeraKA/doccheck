"""Generate public, fictional QA probes for NRT-64. No application imports or files."""

from __future__ import annotations

import argparse
import json
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from random import Random
from typing import Any, Literal

Status = Literal["verified", "discrepancy", "unverified"]
Case = dict[str, Any]
Source = dict[str, Any]

CENT = Decimal("0.01")
RUBLE = Decimal(1)
VAT_2025 = Decimal("0.20")
VAT_2026 = Decimal("0.22")
NDFL_LIMIT = Decimal(2400000)
CONTRIBUTION_LIMIT = Decimal(2979000)


def money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), "f")


def from_cents(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2)


def split_charge(
    prior: Decimal, current: Decimal, limit: Decimal, lower: Decimal, upper: Decimal
) -> Decimal:
    below = max(Decimal(0), min(current, limit - prior))
    return below * lower + (current - below) * upper


def make_case(
    code: str,
    scenario: str,
    reported: Decimal | None,
    expected: Decimal | None,
    status: Status,
    reason: str,
    sources: list[Source],
    *,
    basis: str = "qa_assumption",
    **extra: Any,
) -> Case:
    return {
        "case": code,
        "scenario": scenario,
        "basis": basis,
        "input": {"reported": money(reported), "sources": sources, **extra},
        "expected": {
            "status": status,
            "comparison_amount": money(expected),
            "reason": reason,
        },
    }


def make_variant(rng: Random, variant: int) -> list[Case]:
    amount = from_cents(rng.randrange(123_457, 797_777))
    second = from_cents(rng.randrange(8_231, 54_789))
    gap = from_cents(rng.randrange(1, 97))
    contract = f"QA-C-{rng.randrange(100000, 999999)}"
    vendor = f"QA-V-{rng.randrange(100000, 999999)}"
    other_contract = contract + "-OTHER"
    period = f"2026-{rng.randrange(2, 7):02}"

    def source(ref: str, value: Decimal | None, **extra: Any) -> Source:
        return {
            "ref": ref,
            "contract": contract,
            "party": vendor,
            "period": period,
            "amount": money(value),
            **extra,
        }

    cent_base = Decimal(1000) + Decimal(rng.randrange(1, 4000))
    old_tax = cent_base * VAT_2025
    new_tax = cent_base * VAT_2026
    # These fictional net amounts round differently per line and in aggregate.
    first_line = Decimal(rng.randrange(5, 30)) + Decimal("0.03")
    second_line = Decimal(rng.randrange(5, 30)) + Decimal("0.03")
    rounding_rate = Decimal("0.20")
    round_per_line = sum(
        (
            (line * rounding_rate).quantize(CENT, rounding=ROUND_HALF_UP)
            for line in (first_line, second_line)
        ),
        Decimal(0),
    )
    ytd = NDFL_LIMIT - Decimal(rng.randrange(500, 4000))
    taxable = Decimal(rng.randrange(6000, 25000))
    prior_calculated_tax = (ytd * Decimal("0.13")).quantize(
        RUBLE, rounding=ROUND_HALF_UP
    )
    # The public sample uses full prior withholding. Even variants leave one ruble due.
    prior_fully_withheld = variant % 2 == 1
    prior_withheld_tax = prior_calculated_tax - (
        Decimal(0) if prior_fully_withheld else RUBLE
    )
    after_tax = (
        ytd * Decimal("0.13")
        + split_charge(ytd, taxable, NDFL_LIMIT, Decimal("0.13"), Decimal("0.15"))
    ).quantize(RUBLE, rounding=ROUND_HALF_UP)
    ndfl = after_tax - prior_withheld_tax
    duplicate_operations = [
        {"cell": "F7", "amount": money(amount)},
        {"cell": "F8", "amount": money(amount)},
    ]
    duplicate_total = amount + amount
    contribution_ytd = CONTRIBUTION_LIMIT - Decimal(rng.randrange(500, 4000))
    contribution_base = Decimal(rng.randrange(5000, 20000))
    contribution = split_charge(
        contribution_ytd,
        contribution_base,
        CONTRIBUTION_LIMIT,
        Decimal("0.30"),
        Decimal("0.151"),
    ).quantize(CENT, rounding=ROUND_HALF_UP)

    cases = [
        make_case(
            "O01",
            "ocr_digit_conflict",
            amount,
            None,
            "unverified",
            "digit_unconfirmed",
            [source("scan", None, ocr_candidate=money(amount + Decimal(1000)))],
            basis="evidence_rule",
        ),
        make_case(
            "O02",
            "ocr_missing_separator",
            amount,
            None,
            "unverified",
            "decimal_separator_unconfirmed",
            [source("scan", None, ocr_candidate=money(amount).replace(".", ""))],
            basis="evidence_rule",
        ),
        make_case(
            "O03",
            "ocr_joined_rows",
            amount,
            None,
            "unverified",
            "row_scope_ambiguous",
            [
                source(
                    "scan",
                    None,
                    ocr_candidate=money(amount) + money(second),
                    fragment="overlapping_rows",
                )
            ],
            basis="evidence_rule",
        ),
        make_case(
            "P01",
            "reordered_columns",
            amount,
            amount,
            "verified",
            "headers_identify_amount",
            [
                source(
                    "sheet",
                    None,
                    columns=[
                        {"header": "base", "text": money(amount + second)},
                        {"header": "amount", "text": money(amount)},
                    ],
                )
            ],
            basis="evidence_rule",
        ),
        make_case(
            "P02",
            "unsupported_template",
            amount,
            None,
            "unverified",
            "unknown_header",
            [
                source(
                    "sheet",
                    None,
                    columns=[{"header": "QA unknown", "text": money(amount)}],
                )
            ],
            basis="evidence_rule",
        ),
        make_case(
            "P03",
            "blank_is_unknown",
            Decimal(0),
            None,
            "unverified",
            "missing_amount",
            [source("sheet", None, cell_text="")],
            basis="evidence_rule",
        ),
        make_case(
            "P04",
            "explicit_zero",
            Decimal(0),
            Decimal(0),
            "verified",
            "zero_confirmed",
            [source("sheet", Decimal(0), cell_text="0.00")],
            basis="evidence_rule",
        ),
        make_case(
            "P05",
            "merged_cells_and_uncached_total",
            amount + second,
            amount + second,
            "verified",
            "complete_detail_supports_sum",
            [
                source("row-1", amount, fragment="D5"),
                source("row-2", second, fragment="D6"),
                source(
                    "total",
                    None,
                    fragment="D7",
                    formula="SUM(D5:D6)",
                    cache_present=False,
                ),
            ],
            basis="evidence_rule",
            merged_header="A1:D1",
        ),
        make_case(
            "C01",
            "rounding_at_wrong_level",
            round_per_line,
            round_per_line,
            "verified",
            "synthetic_rule_rounds_each_line",
            [
                source(
                    "invoice",
                    round_per_line,
                    net_lines=[money(first_line), money(second_line)],
                    rounding_policy="per_line_half_up",
                    rate="0.20",
                )
            ],
        ),
        make_case(
            "C02",
            "vat_2026_wrong_rate",
            old_tax,
            new_tax,
            "discrepancy",
            "vat_rate_mismatch",
            [
                source(
                    "upd",
                    old_tax,
                    taxable_base=money(cent_base),
                    supply_date=period + "-04",
                    standard_vat=True,
                    rate="0.20",
                )
            ],
            basis="vat_standard",
        ),
        make_case(
            "C03",
            "vat_correction_old_supply",
            old_tax,
            old_tax,
            "verified",
            "original_vat_rate",
            [
                source(
                    "correction",
                    old_tax,
                    taxable_base=money(cent_base),
                    supply_date="2025-12-23",
                    issued_date=period + "-04",
                    same_original_supply=True,
                    standard_vat=True,
                    rate="0.20",
                )
            ],
            basis="vat_standard",
        ),
        make_case(
            "C04",
            "act_signed_after_period",
            amount,
            amount,
            "verified",
            "synthetic_use_event_date",
            [
                source(
                    "act",
                    amount,
                    service_date=period + "-26",
                    signed_date=period[:5] + f"{int(period[-2:]) + 1:02}-03",
                )
            ],
            comparison_policy="fictional_accrual_event_date",
        ),
        make_case(
            "C05",
            "partial_payment_is_not_full_cost",
            amount,
            None,
            "unverified",
            "partial_payment_without_accrual",
            [source("payment", second, settlement="partial", expense_document=None)],
            basis="evidence_rule",
        ),
        make_case(
            "C06",
            "advance_without_delivery",
            amount,
            None,
            "unverified",
            "delivery_unconfirmed",
            [source("advance", amount, settlement="advance", expense_document=None)],
            basis="evidence_rule",
            comparison_policy="fictional_accrual",
        ),
        make_case(
            "C07",
            "ndfl_crossing_first_threshold",
            ndfl,
            ndfl,
            "verified",
            "split_tax_brackets",
            [
                source(
                    "payroll",
                    ndfl,
                    prior_annual_base=money(ytd),
                    increment=money(taxable),
                    prior_withheld_tax=money(prior_withheld_tax),
                    prior_tax_fully_withheld=prior_fully_withheld,
                    main_resident_base=True,
                    one_tax_agent=True,
                )
            ],
            basis="ndfl_main_base",
        ),
        make_case(
            "C08",
            "contribution_threshold",
            contribution,
            contribution,
            "verified",
            "split_contribution_brackets",
            [
                source(
                    "contributions",
                    contribution,
                    prior_annual_base=money(contribution_ytd),
                    increment=money(contribution_base),
                    general_tariff=True,
                    year=2026,
                )
            ],
            basis="contribution_general_2026",
        ),
        make_case(
            "C09",
            "gross_and_net_are_distinct",
            amount + second,
            amount + second,
            "verified",
            "fictional_report_uses_gross",
            [
                source(
                    "payroll",
                    amount + second,
                    gross=money(amount + second),
                    net_payment=money(amount),
                    withholding=money(second),
                    employer_contribution=money(gap),
                )
            ],
            comparison_policy="fictional_gross",
        ),
        make_case(
            "M01",
            "byte_duplicate_multi_operation",
            duplicate_total,
            duplicate_total,
            "verified",
            "one_copy_all_distinct_operations",
            [
                source(
                    "original",
                    duplicate_total,
                    content_key=contract + "-BYTES",
                    operations=duplicate_operations,
                ),
                source(
                    "copy",
                    duplicate_total,
                    content_key=contract + "-BYTES",
                    operations=duplicate_operations,
                ),
            ],
            basis="evidence_rule",
        ),
        make_case(
            "M02",
            "one_payment_multiple_articles",
            amount,
            None,
            "unverified",
            "no_confirmed_allocation",
            [
                source(
                    "payment",
                    amount + second,
                    possible_articles=["QA-A", "QA-B"],
                    allocation=None,
                )
            ],
            basis="evidence_rule",
        ),
        make_case(
            "M03",
            "other_period_or_contract",
            amount,
            None,
            "unverified",
            "no_matching_source",
            [
                source("old-period", amount, period="2025-12"),
                source("other-contract", amount, contract=other_contract),
            ],
            basis="evidence_rule",
        ),
        make_case(
            "M04",
            "replacement_chain",
            amount,
            amount,
            "verified",
            "one_confirmed_replacement",
            [
                source("old", amount + second, version_state="superseded"),
                source("replacement", amount, replaces="old"),
            ],
        ),
        make_case(
            "M05",
            "near_duplicate_is_ambiguous",
            amount,
            None,
            "unverified",
            "identity_conflict",
            [
                source("candidate-a", amount, content_key="qa-distinct-1"),
                source("candidate-b", amount, content_key="qa-distinct-2"),
            ],
            basis="evidence_rule",
        ),
        make_case(
            "F01",
            "partial_sum_equals_report",
            amount,
            None,
            "unverified",
            "mandatory_source_missing",
            [
                source("present", amount, available=True),
                source("missing", None, available=False),
            ],
            basis="evidence_rule",
            comparison_profile={"required_source_refs": ["present", "missing"]},
            observed_subtotal=money(amount),
        ),
        make_case(
            "F02",
            "total_is_not_an_extra_operation",
            amount + second,
            amount + second,
            "verified",
            "use_detail_or_total_once",
            [
                source("line-a", amount, row_type="detail"),
                source("line-b", second, row_type="detail"),
                source("total", amount + second, row_type="summary"),
            ],
            basis="evidence_rule",
        ),
        make_case(
            "F03",
            "complete_small_difference",
            amount + gap,
            amount,
            "discrepancy",
            "complete_comparable_values_differ",
            [source("act", amount)],
            basis="evidence_rule",
        ),
        make_case(
            "F04",
            "payment_date_is_not_service_period",
            amount,
            None,
            "unverified",
            "no_service_period_evidence",
            [
                source(
                    "payment", amount, payment_date=period + "-01", service_period=None
                )
            ],
            basis="evidence_rule",
            comparison_policy="fictional_accrual",
        ),
    ]
    for case in cases:
        case.update(
            synthetic=True, variant=variant, case_id=f"{case['case']}-{variant:03}"
        )
        case["input"].update(target_contract=contract, target_period=period)
        rng.shuffle(case["input"]["sources"])
        for item in case["input"]["sources"]:
            if "columns" in item:
                rng.shuffle(item["columns"])
    return cases


def generate(seed: int, variants: int) -> list[Case]:
    if not 1 <= variants <= 100:
        raise ValueError("variants must be between 1 and 100")
    rng = Random(seed)
    with localcontext() as context:
        context.prec = 34
        cases = [
            case
            for variant in range(1, variants + 1)
            for case in make_variant(rng, variant)
        ]
    rng.shuffle(cases)
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=64)
    parser.add_argument("--variants", type=int, default=1)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).resolve().with_name("sample.json")
    )
    args = parser.parse_args()
    try:
        cases = generate(args.seed, args.variants)
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dataset = {
        "format": "nrt64-qa-fixtures/1",
        "synthetic": True,
        "seed": args.seed,
        "variants_per_scenario": args.variants,
        "cases": cases,
    }
    args.output.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Generated {len(cases)} synthetic cases: {args.output}")


if __name__ == "__main__":
    main()
