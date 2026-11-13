"""QA checks of the generator; this file is never imported by the application."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from generate import generate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MONEY = re.compile(r"-?\d+\.\d{2}\Z")


class GenerateTest(unittest.TestCase):
    def test_variations_cover_every_catalog_id_and_change_inputs(self) -> None:
        original = generate(64, 4)
        changed = generate(271, 4)
        self.assertEqual(original, generate(64, 4))
        self.assertEqual(len({case["case_id"] for case in original}), len(original))
        catalog = (ROOT / "docs/research/error-catalog.md").read_text(encoding="utf-8")
        documented = set(
            re.findall(r"^\| ([OPCMF]\d{2}) ", catalog, flags=re.MULTILINE)
        )
        self.assertEqual(len(documented), 26)
        self.assertEqual(len(original), 4 * len(documented))
        by_id = {case["case_id"]: case for case in original}
        changed_by_id = {case["case_id"]: case for case in changed}
        self.assertEqual(set(by_id), set(changed_by_id))
        for scenario in documented:
            self.assertEqual(sum(case["case"] == scenario for case in original), 4)
        for case_id, left in by_id.items():
            right = changed_by_id[case_id]
            self.assertNotEqual(
                left["input"]["target_contract"], right["input"]["target_contract"]
            )
            self.assertEqual(left["expected"]["status"], right["expected"]["status"])
        self.assertNotEqual(
            by_id["F03-001"]["input"]["reported"],
            changed_by_id["F03-001"]["input"]["reported"],
        )
        self.assertNotEqual(
            [case["case_id"] for case in original],
            [case["case_id"] for case in changed],
        )
        self.assertTrue(
            any(
                [source["ref"] for source in case["input"]["sources"]]
                != [
                    source["ref"]
                    for source in changed_by_id[case["case_id"]]["input"]["sources"]
                ]
                for case in original
            )
        )

    def test_statuses_and_amounts_remain_consistent(self) -> None:
        cent = Decimal("0.01")
        for case in generate(99, 8):
            with self.subTest(case=case["case_id"]):
                self.assertIs(case["synthetic"], True)
                self.assertNotIn("expected", case["input"])
                reported = case["input"]["reported"]
                comparison = case["expected"]["comparison_amount"]
                status = case["expected"]["status"]
                for money in [
                    reported,
                    comparison,
                    *[s["amount"] for s in case["input"]["sources"]],
                ]:
                    if money is not None:
                        self.assertRegex(money, MONEY)
                        self.assertTrue(Decimal(money).is_finite())
                if status == "unverified":
                    self.assertIsNone(comparison)
                elif status == "verified":
                    self.assertEqual(Decimal(reported), Decimal(comparison))
                elif status == "discrepancy":
                    self.assertGreaterEqual(
                        abs(Decimal(reported) - Decimal(comparison)), cent
                    )
                else:
                    self.fail(f"unexpected status {status!r}")
                self.assertTrue(case["expected"]["reason"])

    def test_high_risk_pairs_have_independent_arithmetic_checks(self) -> None:
        cases = {case["case"]: case for case in generate(43, 1)}
        unknown, zero = cases["P03"], cases["P04"]
        self.assertIsNone(unknown["expected"]["comparison_amount"])
        self.assertEqual(zero["expected"]["comparison_amount"], "0.00")

        rounding = cases["C01"]
        data = rounding["input"]["sources"][0]
        bulk = (
            sum(Decimal(line) for line in data["net_lines"]) * Decimal(data["rate"])
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.assertEqual(
            Decimal(rounding["expected"]["comparison_amount"]) - bulk, Decimal("0.01")
        )

        for scenario, rate in [("C02", "0.22"), ("C03", "0.20")]:
            case = cases[scenario]
            document = case["input"]["sources"][0]
            taxable_base = Decimal(document["taxable_base"])
            self.assertEqual(document["rate"], "0.20")
            self.assertEqual(
                Decimal(document["amount"]), taxable_base * Decimal("0.20")
            )
            self.assertEqual(case["input"]["reported"], document["amount"])
            self.assertEqual(
                document["supply_date"][:4], "2026" if scenario == "C02" else "2025"
            )
            self.assertEqual(
                Decimal(case["expected"]["comparison_amount"]),
                taxable_base * Decimal(rate),
            )

    def test_ndfl_credits_withholding_even_when_it_differs_from_calculated_tax(
        self,
    ) -> None:
        withholding_cases = [case for case in generate(43, 4) if case["case"] == "C07"]
        coverage = set()
        threshold = Decimal(2400000)
        for case in withholding_cases:
            with self.subTest(case=case["case_id"]):
                payroll = case["input"]["sources"][0]
                prior_base = Decimal(payroll["prior_annual_base"])
                annual_base = prior_base + Decimal(payroll["increment"])
                withheld = Decimal(payroll["prior_withheld_tax"])
                self.assertLess(prior_base, threshold)
                self.assertGreater(annual_base, threshold)
                prior_calculated = (prior_base * Decimal("0.13")).quantize(
                    Decimal(1), rounding=ROUND_HALF_UP
                )
                cumulative = (
                    Decimal(312000) + (annual_base - threshold) * Decimal("0.15")
                ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
                self.assertEqual(
                    payroll["prior_tax_fully_withheld"], withheld == prior_calculated
                )
                self.assertEqual(
                    Decimal(case["expected"]["comparison_amount"]),
                    cumulative - withheld,
                )
                coverage.add(prior_calculated - withheld)
        self.assertEqual(coverage, {Decimal(0), Decimal(1)})

    def test_duplicate_requires_file_identity_and_keeps_equal_amount_operations(
        self,
    ) -> None:
        for case in (case for case in generate(43, 8) if case["case"] == "M01"):
            with self.subTest(case=case["case_id"]):
                first, second = case["input"]["sources"]
                self.assertNotEqual(first["ref"], second["ref"])
                self.assertEqual(first["content_key"], second["content_key"])
                self.assertEqual(first["operations"], second["operations"])
                self.assertEqual(len(first["operations"]), 2)
                self.assertEqual(len({row["cell"] for row in first["operations"]}), 2)
                amounts = [Decimal(row["amount"]) for row in first["operations"]]
                self.assertEqual(len(set(amounts)), 1)
                expected = Decimal(case["expected"]["comparison_amount"])
                self.assertEqual(sum(amounts), expected)
                self.assertNotEqual(sum(set(amounts)), expected)
                self.assertNotEqual(
                    sum(Decimal(s["amount"]) for s in (first, second)), expected
                )

    def test_matching_partial_total_has_a_missing_required_source(self) -> None:
        case = next(case for case in generate(43, 1) if case["case"] == "F01")
        data = case["input"]
        sources = {s["ref"]: s for s in data["sources"]}
        required = set(data["comparison_profile"]["required_source_refs"])
        self.assertEqual(
            required - {ref for ref, s in sources.items() if s["available"]},
            {"missing"},
        )
        self.assertIsNone(sources["missing"]["amount"])
        self.assertEqual(sources["present"]["amount"], data["observed_subtotal"])
        self.assertEqual(data["reported"], data["observed_subtotal"])
        self.assertEqual(case["expected"]["status"], "unverified")
        self.assertIsNone(case["expected"]["comparison_amount"])

    def test_cli_recreates_the_sample_and_writes_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new" / "sample.json"
            subprocess.run(
                [sys.executable, str(HERE / "generate.py"), "--output", str(output)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(output.read_bytes(), (HERE / "sample.json").read_bytes())
            raw = json.loads(
                output.read_text(encoding="utf-8"), parse_float=self.reject_float
            )
            self.assertTrue(raw["synthetic"])
            self.assertEqual(raw["variants_per_scenario"], 1)
            self.assertEqual(len(raw["cases"]), 26)
            rejected = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "generate.py"),
                    "--variants",
                    "0",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rejected.returncode, 0)

    @staticmethod
    def reject_float(value: str) -> None:
        raise AssertionError(f"floating-point JSON number: {value}")


if __name__ == "__main__":
    unittest.main()
