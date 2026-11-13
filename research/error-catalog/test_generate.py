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
        self.assertEqual(
            cases["F01"]["input"]["reported"],
            cases["F01"]["input"]["observed_subtotal"],
        )
        self.assertIsNone(cases["F01"]["expected"]["comparison_amount"])

        duplicate = cases["M01"]
        copies = duplicate["input"]["sources"]
        self.assertEqual(copies[0]["content_key"], copies[1]["content_key"])
        self.assertEqual(copies[0]["operations"], copies[1]["operations"])
        operations = [Decimal(amount) for amount in copies[0]["operations"]]
        self.assertEqual(len(operations), 2)
        self.assertEqual(
            sum(operations), Decimal(duplicate["expected"]["comparison_amount"])
        )

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
            taxable_base = Decimal(case["input"]["sources"][0]["taxable_base"])
            self.assertEqual(
                Decimal(case["expected"]["comparison_amount"]),
                taxable_base * Decimal(rate),
            )

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
