"""Regression guards for fixture content and isolation, not application tests."""
from decimal import Decimal
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import make_package, public_document, public_report
from verify import verify

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "docs/synthetic/nrt-89"


class PackageTests(unittest.TestCase):
    def test_shipped_package(self):
        result = verify(PACKAGE)
        self.assertEqual(result["rows"], {"verified": 2, "discrepancy": 1, "unverified": 2})

    def test_repeat_seed_and_alternate_seed(self):
        first = make_package(890041)
        self.assertEqual(first, make_package(890041))
        other = make_package(890042)
        self.assertNotEqual(first["contract"], other["contract"])
        self.assertNotEqual(first["period_start"], other["period_start"])
        self.assertNotEqual(first["documents"][0]["amount"], other["documents"][0]["amount"])
        self.assertEqual([d["file"] for d in first["documents"]], [d["file"] for d in other["documents"]])
        self.assertEqual([r["expected_status"] for r in first["rows"]], [r["expected_status"] for r in other["rows"]])

    def test_equal_partial_sum_remains_unknown(self):
        for seed in (0, 1, 890041, 890042, 99999999):
            rows = {r["id"]: r for r in make_package(seed)["rows"]}
            partial = rows["general_admin"]
            self.assertEqual(partial["reported_amount"], partial["available_subtotal"])
            self.assertEqual(partial["expected_status"], "unverified")
            self.assertIsNone(partial["expected_amount"])
            self.assertIsNone(partial["delta"])
            self.assertIsNone(rows["other"]["available_subtotal"])
            self.assertNotEqual(rows["other"]["reported_amount"], "0.00")

    def test_public_projection_drops_added_secrets(self):
        data = make_package()
        data["expected_secret"] = "SHOULD_NOT_REACH_INPUTS"
        data["rows"][0]["expected_secret"] = "SHOULD_NOT_REACH_INPUTS"
        data["documents"][0]["expected_secret"] = "SHOULD_NOT_REACH_INPUTS"
        for value in (public_report(data), public_document(data["documents"][0])):
            encoded = json.dumps(value)
            self.assertNotIn("SHOULD_NOT_REACH_INPUTS", encoded)
            self.assertNotIn("expected_", encoded)
            self.assertNotIn("duplicate_of", encoded)

    def test_wrong_scope_and_duplicates_are_excluded(self):
        data = make_package()
        row = next(r for r in data["rows"] if r["id"] == "general_admin")
        self.assertEqual(set(row["excluded_documents"]), {"10_admin_copy", "13_transfer", "14_admin_act"})
        docs = {d["id"]: d for d in data["documents"]}
        subtotal = sum(Decimal(docs[key]["amount"]) for key in row["included_documents"])
        naive = sum(Decimal(d["amount"]) for d in docs.values() if d["category"] == "general_admin")
        self.assertEqual(subtotal, Decimal(row["available_subtotal"]))
        self.assertGreater(naive, subtotal)

    def test_tampered_files_and_extra_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "kit"
            shutil.copytree(PACKAGE, target)
            extra = target / "inputs/answers.json"
            extra.write_text('{"expected_status":"verified"}')
            with self.assertRaises(AssertionError):
                verify(target)
            extra.unlink()
            path = target / "inputs/04_act.pdf"
            path.write_bytes(path.read_bytes() + b"tampered")
            with self.assertRaisesRegex(AssertionError, "Hash mismatch"):
                verify(target)

    def test_wrong_expectation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "kit"
            shutil.copytree(PACKAGE, target)
            path = target / "expectations/manifest.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["rows"][0]["expected_amount"] = "0.00"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(AssertionError):
                verify(target)


if __name__ == "__main__":
    unittest.main()
