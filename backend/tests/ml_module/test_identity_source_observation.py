"""Synthetic tests for the portable, in-memory OCR evidence boundary."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from doccheck_ml.identity import identity_v3, identity_v4
from doccheck_ml.identity.identity_v4_source import source_corrections
from test_identity_v2 import record


def inputs(amount="123.45"):
    baseline = record("ABCD-17", "ABCD-17", acquisition="scan")
    baseline["facts"]["amount"] = "1.00"
    joined = {
        "id": baseline["id"],
        "source_sha256": baseline["source_sha256"],
        "baseline": {"prediction": {"amount": amount}},
    }
    observation = {
        "id": baseline["id"],
        "source_sha256": baseline["source_sha256"],
        "lines": [{"text": "Итого: 123,45", "page": 1}],
    }
    return baseline, joined, observation


class SourceObservationTests(TestCase):
    def test_explicit_source_and_fullpage_agreement_correct_amount(self):
        baseline, joined, observation = inputs()
        correction = source_corrections(baseline, joined, observation)["amount"]
        self.assertTrue(correction["applied"])
        self.assertEqual(correction["new"], "123.45")
        self.assertEqual(correction["candidates"][0]["evidence"], observation["lines"])
        self.assertEqual(len(correction["source_observation_sha256"]), 64)
        self.assertEqual(baseline["facts"]["amount"], "1.00")

    def test_old_cache_metadata_does_not_open_a_file_or_supply_amount(self):
        baseline, joined, _ = inputs()
        joined["baseline"]["paddle_provenance"] = {
            "cache": "/synthetic/nonexistent/cache.json",
            "cache_sha256": "0" * 64,
        }
        with patch("builtins.open", side_effect=AssertionError("unexpected I/O")):
            correction = source_corrections(baseline, joined)
        self.assertFalse(correction["amount"]["applied"])

    def test_source_identity_mismatch_rejected(self):
        baseline, joined, observation = inputs()
        for key in ("id", "source_sha256"):
            wrong = deepcopy(observation)
            wrong[key] = "another-source"
            with self.assertRaises(ValueError):
                source_corrections(baseline, joined, wrong)

    def test_model_disagreement_does_not_correct(self):
        baseline, joined, observation = inputs("234.56")
        self.assertFalse(source_corrections(baseline, joined, observation)["amount"]["applied"])

    def test_several_distinct_totals_do_not_correct(self):
        baseline, joined, observation = inputs()
        observation["lines"].append({"text": "Итого: 234,56", "page": 2})
        self.assertFalse(source_corrections(baseline, joined, observation)["amount"]["applied"])

    def test_explicit_zero_is_preserved_and_missing_model_is_not_zero(self):
        baseline, joined, observation = inputs("0.00")
        observation["lines"][0]["text"] = "Итого: 0,00"
        self.assertEqual(source_corrections(baseline, joined, observation)["amount"]["new"], "0.00")
        joined["baseline"]["prediction"]["amount"] = None
        self.assertFalse(source_corrections(baseline, joined, observation)["amount"]["applied"])

    def test_corrected_evidence_is_a_snapshot(self):
        baseline, joined, observation = inputs()
        correction = source_corrections(baseline, joined, observation)
        observation["lines"][0]["text"] = "Итого: 999,99"
        self.assertEqual(correction["amount"]["candidates"][0]["evidence"][0]["text"], "Итого: 123,45")

    def test_v4_forwards_explicit_source_observation(self):
        baseline, joined, observation = inputs()
        previous = identity_v3.evaluate_arms(baseline)["combined"]
        result = identity_v4.evaluate_arms(previous, joined, source_observation=observation)["A2"]
        self.assertEqual(result["facts"]["amount"], "123.45")
        self.assertEqual(result["source_facts"]["amount"], "123.45")
        self.assertIn("source_observation_sha256", result["source_corrections"]["amount"])
        self.assertNotIn("paddle_cache", result["source_corrections"]["amount"])
