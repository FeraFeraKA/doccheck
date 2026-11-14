"""Checks of benchmark boundary behavior, not model accuracy tests."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bench.e2e_v32_20261114 import run


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.package = {"completeness": {"basis": "user_manifest", "status": "complete"}, "scope": {"contract_number": "TEST-5", "period_start": "2026-01-01", "period_end": "2026-05-31", "stage": 3, "year": 2026}}
        self.report = {"id": "r", "error": None, "input_kind": "bounded_native_report", "prediction": {
            "contract_number": "TEST-5", "period_start": "2026-01-01", "period_end": "2026-05-31", "stage": "3",
            "rows": [{"category": "payroll", "reported_amount": "100.00"}], "total": {"amount": "100.00"}}}
        self.doc = {"id": "d", "source_hash": "abc", "error": None, "prediction": {
            "contract_number": "TEST-5", "doc_number": "TEST-1", "period_start": "2026-01-01", "period_end": "2026-01-31", "amount": "90.00", "category": "payroll"}}

    def test_wrong_report_stage_cannot_confirm_financial_rows(self):
        self.report["prediction"]["stage"] = "2"
        result = run.compare(self.package, self.report, [self.doc])
        self.assertEqual(result["rows"][0]["status"], "unverified")
        self.assertIsNone(result["total"]["expected_amount"])
        self.assertIn("report_stage_not_verified", result["report_identity_issues"])

    def test_conflict_is_uncertainty_not_successful_detection(self):
        other = copy.deepcopy(self.doc)
        other.update(id="d2", source_hash="def")
        other["prediction"]["amount"] = "85.00"
        result = run.compare(self.package, self.report, [self.doc, other])
        review = run.manual_review(self.report, [self.doc, other], result)
        self.assertEqual(result["rows"][0]["status"], "unverified")
        self.assertTrue(review["uncertainty_package_required"])
        self.assertEqual(set(review["uncertainty_document_ids"]), {"r", "d", "d2"})

    def test_detected_discrepancy_is_attention_not_reading_uncertainty(self):
        result = run.compare(self.package, self.report, [self.doc])
        review = run.manual_review(self.report, [self.doc], result)
        self.assertEqual(result["rows"][0]["delta"], "10.00")
        self.assertEqual(result["total"]["delta"], "10.00")
        self.assertTrue(review["package_required"])
        self.assertFalse(review["uncertainty_package_required"])

    def test_declared_missing_source_blocks_total_even_when_partial_matches(self):
        self.package['completeness']={'basis':'user_manifest','status':'incomplete','missing_categories':['payroll']}
        self.doc['prediction']['amount']='100.00'
        result=run.compare(self.package,self.report,[self.doc])
        self.assertEqual(result['rows'][0]['partial_amount'],'100.00')
        self.assertEqual(result['rows'][0]['status'],'unverified')
        self.assertIsNone(result['rows'][0]['delta'])
        self.assertEqual(result['total']['status'],'unverified')
        self.assertIsNone(result['total']['expected_amount'])

    def test_detail_and_subtotal_do_not_count_again_or_block_expense_total(self):
        self.report["prediction"]["rows"].extend([
            {"category": "0201", "reported_amount": "80.00"},
            {"category": "production_cost", "reported_amount": "100.00"},
        ])
        result = run.compare(self.package, self.report, [self.doc])
        self.assertEqual(result["total"]["expected_amount"], "90.00")
        self.assertEqual(result["total"]["delta"], "10.00")
        for row in result["rows"][1:]:
            self.assertEqual(row["status"], "unverified")
            self.assertEqual(row["source_ids"], [])

    def test_byte_duplicate_skips_model_and_gets_fresh_wall_time(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "input.png"
            p.write_bytes(b"same bytes")
            previous = {run.sha(p): {"id": "first", "prediction": {"amount": "1.00"}, "input_kind": "scan", "error": None}}
            with patch.object(run.runtime, "infer", side_effect=AssertionError("unexpected inference")):
                result = run.extract_primary({"id": "copy", "path": str(p)}, previous)
            self.assertTrue(result["byte_duplicate_reuse"])
            self.assertEqual(result["duplicate_of"], "first")
            self.assertLess(result["elapsed_s"], 1)
            self.assertNotIn("latency_s", result)


if __name__ == "__main__":
    unittest.main()
