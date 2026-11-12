"""Independent prefix-loss controls; no benchmark/model answers are inputs."""
import unittest

from test_identity_v3 import baseline, readings
from doccheck_ml.identity.identity_v3 import evaluate_arms


class PrefixSafetyTests(unittest.TestCase):
    def test_bare_ascii_n_prefix_cannot_be_erased_into_accepted_digits(self):
        for number in ("N123", "N 123", "No123"):
            base = baseline(number, number)
            row = readings(base, number)
            row["qwen_roi"]["prediction"]["verbatim_line"] = number
            for observation in row["tesseract"]:
                observation["text"] = number
            result = evaluate_arms(base, row)["combined"]["number"]
            self.assertEqual(result["value"], number)
            self.assertIsNone(result["usable_value"])
            self.assertTrue(result["manual_review_required"])

    def test_bare_n_with_date_preserves_prefix(self):
        base = baseline("N123", "N123")
        row = readings(base, "N123")
        row["qwen_roi"]["prediction"]["verbatim_line"] = "N123 от 31.03.2026"
        for observation in row["tesseract"]:
            observation["text"] = "N123 от 31.03.2026"
        result = evaluate_arms(base, row)["combined"]["number"]
        self.assertEqual(result["value"], "N123")
        self.assertIsNone(result["usable_value"])

    def test_explicit_number_sign_is_still_a_marker(self):
        base = baseline("ЛБ-0017", "0017")
        base["number"]["usable_value"] = None
        row = readings(base, "№ ЛБ-0017")
        row["qwen_roi"]["prediction"]["verbatim_line"] = "№ ЛБ-0017 от 31.03.2026"
        for observation in row["tesseract"]:
            observation["text"] = "№ ЛБ-0017 от 31.03.2026"
        self.assertEqual(evaluate_arms(base, row)["combined"]["number"]["usable_value"], "ЛБ-0017")


if __name__ == "__main__":
    unittest.main()
