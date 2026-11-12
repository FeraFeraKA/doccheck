"""Generic safety controls for preserving unresolved existing relationships."""
import unittest

from test_identity_v3 import baseline
from doccheck_ml.identity.identity_v3 import evaluate_arms, compare_documents


def pair(issuer=True):
    a, b = baseline(ident="a"), baseline(ident="b")
    b["facts"]["amount"] = "101.00"
    if not issuer:
        a["issuer"]["value"] = b["issuer"]["value"] = None
    return evaluate_arms(a)["combined"], evaluate_arms(b)["combined"]


class MatchingSafetyTests(unittest.TestCase):
    def test_unverified_reread_cannot_clear_amount_conflict(self):
        a, b = pair()
        self.assertEqual(compare_documents(a, b)["status"], "conflict")
        a["number"]["value"] = "ЗП-0017"
        result = compare_documents(a, b)
        self.assertEqual(result["status"], "conflict")
        self.assertFalse(result["auto_merge"])
        self.assertIn("unverified_reread_cannot_clear_existing_review", result["reasons"])

    def test_unverified_reread_cannot_clear_existing_candidate(self):
        a, b = pair(issuer=False)
        self.assertEqual(compare_documents(a, b)["status"], "candidate")
        a["number"]["value"] = "ЗП-0017"
        self.assertEqual(compare_documents(a, b)["status"], "candidate")

    def test_corroborated_distinct_numbers_are_not_forced_equal(self):
        a, b = pair()
        a["number"].update(value="ЛБ-0017", usable_value="ЛБ-0017")
        b["number"].update(value="ЛБ-0018", usable_value="ЛБ-0018")
        self.assertEqual(compare_documents(a, b)["status"], "distinct")

    def test_new_conflict_discovery_remains_possible(self):
        a, b = pair()
        a["baseline_identity"]["number"]["value"] = "ЗП-0017"
        self.assertEqual(compare_documents(a["baseline_identity"], b["baseline_identity"])["status"], "distinct")
        a["number"]["value"] = b["number"]["value"] = "ЗП-0017"
        self.assertEqual(compare_documents(a, b)["status"], "conflict")


if __name__ == "__main__":
    unittest.main()
