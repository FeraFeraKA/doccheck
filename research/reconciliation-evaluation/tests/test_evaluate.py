import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evaluate import InputError, evaluate


def expectation(case, status, *, group="test-origin", split="holdout"):
    return {
        "case_id": case,
        "indicator_id": "example-indicator",
        "origin_group": group,
        "split": split,
        "expected_status": status,
    }


def observation(case, status, evidence=True):
    return {
        "case_id": case,
        "indicator_id": "example-indicator",
        "status": status,
        "has_evidence": evidence,
    }


class EvaluationTests(unittest.TestCase):
    def test_metrics_use_the_predeclared_rows_and_do_not_emit_identifiers(self):
        expected = [
            expectation("case-a", "discrepancy"),
            expectation("case-b", "discrepancy"),
            expectation("case-c", "discrepancy"),
            expectation("case-d", "verified"),
            expectation("case-e", "verified"),
            expectation("case-f", "unverified", group="another-origin"),
            expectation("case-g", "unverified", group="another-origin"),
            expectation("case-h", "verified", group="dev-origin", split="development"),
        ]
        observed = [
            observation("case-a", "discrepancy"),
            observation("case-b", "verified", False),
            observation("case-d", "discrepancy"),
            observation("case-e", "unverified"),
            observation("case-f", "verified"),
            observation("case-g", "discrepancy"),
        ]
        result = evaluate(expected, observed, split="holdout")
        self.assertEqual(result["target_rows"], 7)
        self.assertEqual(result["origin_groups"], 2)
        self.assertEqual(result["true_discrepancies"], 3)
        self.assertEqual(result["missing_rows"], 1)
        self.assertEqual(result["actual_discrepancies_on_expected_unverified"], 1)
        self.assertEqual(
            result["status_matrix"]["discrepancy"],
            {"verified": 1, "discrepancy": 1, "unverified": 0, "missing": 1},
        )
        ratios = {
            "discrepancy_precision": (1, 2, 0.5),
            "discrepancy_recall": (1, 3, 1 / 3),
            "false_confirmation_rate": (2, 2, 1.0),
            "false_alarm_rate": (1, 2, 0.5),
            "unverified_rate": (1, 7, 1 / 7),
            "response_coverage": (6, 7, 6 / 7),
            "definitive_coverage": (5, 7, 5 / 7),
            "definitive_evidence_rate": (4, 5, 0.8),
        }
        for metric, (numerator, denominator, value) in ratios.items():
            self.assertEqual(
                result["metrics"][metric],
                {"numerator": numerator, "denominator": denominator, "value": value},
            )
        encoded = json.dumps(result)
        for identifier in ("case-a", "example-indicator", "test-origin"):
            self.assertNotIn(identifier, encoded)

    def test_empty_and_entirely_abstaining_samples(self):
        empty = evaluate([], [], split="holdout")
        self.assertEqual(empty["target_rows"], 0)
        for ratio in empty["metrics"].values():
            self.assertEqual(ratio, {"numerator": 0, "denominator": 0, "value": None})
        abstention = evaluate(
            [expectation("abstention", "discrepancy")],
            [observation("abstention", "unverified", False)],
            split="holdout",
        )["metrics"]
        self.assertIsNone(abstention["discrepancy_precision"]["value"])
        self.assertEqual(abstention["discrepancy_recall"]["value"], 0)
        self.assertEqual(abstention["response_coverage"]["value"], 1)
        self.assertEqual(abstention["definitive_coverage"]["value"], 0)

    def test_invalid_joins_and_group_leaks_are_rejected(self):
        item = expectation("case-a", "verified")
        prediction = observation("case-a", "verified")
        cases = (
            ([item, item], [], "Duplicate key"),
            ([item], [prediction, prediction], "duplicate or absent"),
            ([item], [observation("other", "verified")], "duplicate or absent"),
            ([item], [{**prediction, "has_evidence": 1}], "must be a boolean"),
            (
                [item],
                [{**prediction, "source_text": "unwanted text"}],
                "documented fields",
            ),
            (
                [item, expectation("case-b", "verified", split="development")],
                [],
                "crosses",
            ),
            (
                [
                    item,
                    {**item, "indicator_id": "another", "origin_group": "different"},
                ],
                [],
                "multiple",
            ),
        )
        for expected, observed, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(InputError, message),
            ):
                evaluate(expected, observed, split="holdout")

    def test_cli_rejects_bad_json_without_echoing_identifiers_or_paths(self):
        script = Path(__file__).resolve().parents[1] / "evaluate.py"
        with tempfile.TemporaryDirectory() as folder:
            expectation_path = Path(folder) / "synthetic-private-filename.json"
            observation_path = Path(folder) / "observations.json"
            expectation_path.write_text(
                '[{"case_id":"synthetic-id","case_id":"another-id"}]', encoding="utf-8"
            )
            observation_path.write_text("[]", encoding="utf-8")
            command = [
                sys.executable,
                str(script),
                "--expectations",
                str(expectation_path),
                "--observations",
                str(observation_path),
                "--split",
                "holdout",
            ]
            failed = subprocess.run(
                command, capture_output=True, text=True, check=False
            )
            self.assertEqual(failed.returncode, 2)
            self.assertEqual(failed.stdout, "")
            self.assertIn("Unable to read an input as UTF-8 JSON", failed.stderr)
            self.assertNotIn("synthetic-id", failed.stderr)
            self.assertNotIn("synthetic-private-filename", failed.stderr)
            expectation_path.write_text("[]", encoding="utf-8")
            passed = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(passed.stdout)["target_rows"], 0)

    def test_cli_argument_errors_do_not_echo_paths_or_identifiers(self):
        script = Path(__file__).resolve().parents[1] / "evaluate.py"
        expected = "directory/synthetic-expected-metadata.json"
        observed = "directory/synthetic-observed-metadata.json"
        arguments = ["--expectations", expected, "--observations", observed]
        inputs = {
            "extra": [
                *arguments,
                "--split",
                "holdout",
                "directory/synthetic-extra.json",
            ],
            "missing": arguments,
            "invalid split": [*arguments, "--split", "synthetic-origin-id"],
        }
        for case, argv in inputs.items():
            with self.subTest(case=case):
                failed = subprocess.run(
                    [sys.executable, str(script), *argv],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(failed.returncode, 2)
                self.assertEqual(failed.stdout, "")
                self.assertEqual(
                    failed.stderr, "Invalid command-line arguments. Use --help.\n"
                )
