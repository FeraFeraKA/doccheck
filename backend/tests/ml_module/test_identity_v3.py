"""Policy regressions, independent of new OCR/inference evaluation results."""
from copy import deepcopy
import unittest

from test_identity_v2 import record
from doccheck_ml.identity.identity_v3 import evaluate_arms, compare_documents, group_documents, review_queue


def baseline(number="3П-0017", model="3П-0017", ident="a"):
    return record(number, model, "scan", ident=ident)


def readings(base, number="ЗП-0017", confidence=95):
    line = f"№ {number} от 31.03.2026"
    return {"id": base["id"], "source_sha256": base["source_sha256"], "selected": True,
            "crop": {"mode": "single_line"},
            "qwen_roi": {"prediction": {"doc_number": number, "verbatim_line": line}, "error": None},
            "tesseract": [{"variant": variant, "text": line, "mean_confidence": confidence,
                           "error": None} for variant in ("original", "gray2x")]}


class RereadingTests(unittest.TestCase):
    def test_two_engines_and_stable_preprocessing_can_corroborate(self):
        base = baseline()
        result = evaluate_arms(base, readings(base))["combined"]
        self.assertEqual(result["number"]["value"], "ЗП-0017")
        self.assertEqual(result["number"]["usable_value"], "ЗП-0017")
        self.assertFalse(result["number"]["manual_review_required"])
        self.assertIsNone(base["number"]["usable_value"])

    def test_no_global_letter_digit_rewrite(self):
        base = baseline()
        result = evaluate_arms(base, readings(base, "3П-0017"))["combined"]
        self.assertEqual(result["number"]["value"], "3П-0017")
        self.assertIsNone(result["number"]["usable_value"])

    def test_date_suffix_is_parsed_without_changing_number(self):
        base = baseline()
        read = readings(base)
        read["qwen_roi"]["prediction"]["doc_number"] += " от 31.03.2026"
        self.assertEqual(evaluate_arms(base, read)["combined"]["number"]["usable_value"], "ЗП-0017")

    def test_wrong_quote_cannot_corroborate_a_hallucination(self):
        base = baseline()
        read = readings(base)
        read["qwen_roi"]["prediction"]["verbatim_line"] = "№ ЗП-0018 от 31.03.2026"
        result = evaluate_arms(base, read)["combined"]
        self.assertIsNone(result["number"]["usable_value"])
        self.assertIn("no_quote_supported_qwen_number", result["number"]["issues"])

    def test_independent_engine_disagreement_requires_review(self):
        base = baseline()
        read = readings(base)
        for r in read["tesseract"]:
            r["text"] = "№ ЗП-0018 от 31.03.2026"
        self.assertIsNone(evaluate_arms(base, read)["combined"]["number"]["usable_value"])

    def test_preprocessing_variants_are_not_majority_votes(self):
        base = baseline()
        read = readings(base)
        read["tesseract"][1]["text"] = "№ 3П-0017 от 31.03.2026"
        self.assertIsNone(evaluate_arms(base, read)["combined"]["number"]["usable_value"])

    def test_confidence_is_a_gate_not_a_probability(self):
        base = baseline()
        for confidence in [79.9, float("nan"), float("inf"), 101, None]:
            self.assertIsNone(evaluate_arms(base, readings(base, confidence=confidence))["combined"]["number"]["usable_value"])

    def test_fallback_header_requires_explicit_document_number_anchors(self):
        base = baseline()
        base["number"]["candidates"] = []
        read = readings(base)
        read["crop"]["mode"] = "header"
        read["qwen_roi"]["prediction"]["verbatim_line"] = "ЗП-0017"
        for r in read["tesseract"]:
            r["text"] = "ЗП-0017"
        self.assertIsNone(evaluate_arms(base, read)["combined"]["number"]["usable_value"])

    def test_partial_and_missing_readings_cannot_be_accepted(self):
        base = baseline()
        for number in ["ЗП-00?7", "?", "не указан"]:
            self.assertIsNone(evaluate_arms(base, readings(base, number))["combined"]["number"]["usable_value"])

    def test_confusable_alphabet_stays_explicitly_uncertain(self):
        base = baseline("СВ-0017", "CB-0017")
        result = evaluate_arms(base, readings(base, "СВ-0017"))["combined"]
        self.assertEqual(result["number"]["value"], "СВ-0017")
        self.assertIsNone(result["number"]["usable_value"])

    def test_existing_usable_number_and_native_source_are_not_overwritten(self):
        for base in [record("ЛБ-0017", "ЛБ-0017", "scan"), record("ЛБ-0017", None, "native")]:
            result = evaluate_arms(base, readings(base))["combined"]
            self.assertEqual(result["number"]["usable_value"], "ЛБ-0017")

    def test_wrong_source_hash_or_id_is_rejected(self):
        base = baseline()
        for key in ["id", "source_sha256"]:
            read = readings(base)
            read[key] = "another-source"
            with self.assertRaises(ValueError):
                evaluate_arms(base, read)

    def test_reader_failures_preserve_baseline_and_review(self):
        base = baseline()
        read = readings(base)
        read["qwen_roi"] = {"prediction": None, "error": "timeout"}
        read["tesseract"] = []
        result = evaluate_arms(base, read)["combined"]
        self.assertEqual(result["number"]["value"], base["number"]["value"])
        self.assertTrue(result["number"]["manual_review_required"])


class MergeSafetyTests(unittest.TestCase):
    def test_number_change_cannot_create_new_auto_edge(self):
        old_a, old_b = record("ЛБ-0017", ident="a"), record("ЛБ-0018", ident="b")
        a = evaluate_arms(old_a)["combined"]
        b = evaluate_arms(old_b)["combined"]
        for r in [a, b]:
            r.update(content_complete=True, content_fingerprint="same", package_fingerprint="same")
            r["number"].update(value="ЛБ-0017", usable_value="ЛБ-0017")
        self.assertFalse(compare_documents(a, b)["auto_merge"])
        self.assertIn("rereading_cannot_authorize_a_new_merge", compare_documents(a, b)["reasons"])

    def test_identical_file_proof_survives(self):
        a, b = baseline(ident="a"), baseline(ident="b")
        b["source_sha256"] = a["source_sha256"]
        self.assertTrue(compare_documents(evaluate_arms(a)["combined"], evaluate_arms(b)["combined"])["auto_merge"])

    def test_candidate_cards_do_not_form_duplicate_groups(self):
        results = [evaluate_arms(baseline(ident=k))["combined"] for k in ["a", "b", "c"]]
        queue = review_queue(results)
        self.assertEqual(queue["number_review_documents"], 3)
        self.assertEqual(queue["number_review_cards"], 1)
        self.assertFalse(queue["number_cards"][0]["correction_propagates"])
        self.assertEqual(len(group_documents(results)["groups"]), 3)


if __name__ == "__main__":
    unittest.main()
