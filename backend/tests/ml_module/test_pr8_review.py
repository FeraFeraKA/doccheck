"""PR #8 regressions exercised through the public API on synthetic sources."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from doccheck_ml import DocumentInput, process_documents


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "synthetic.txt"

    def process(self, lines, prediction=None):
        self.source.write_text("\n".join(line["text"] for line in lines), encoding="utf-8")
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        return process_documents([
            DocumentInput("synthetic", self.source, digest, "native", lines,
                          prediction or {}),
        ], synthetic=True)

    def assert_number_needs_review(self, result):
        number = result["records"][0]["number"]
        self.assertIsNone(number["usable_value"])
        self.assertTrue(number["manual_review_required"])
        self.assertEqual(result["review_queue"]["number_review_document_ids"], ["synthetic"])

    def test_split_number_requires_a_shared_location(self):
        cases = [
            [{"text": "Документ №", "sheet": "A", "cell": "A1"},
             {"text": "123", "sheet": "B", "cell": "A2"}],
            [{"text": "Документ №", "page": 1, "line": 1},
             {"text": "123", "page": 2, "line": 2}],
            [{"text": "Документ №"}, {"text": "123"}],
            [{"text": "Документ №", "sheet": " "}, {"text": "123", "sheet": " "}],
            [{"text": "Документ №", "page": 1}, {"text": "123"}],
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                self.assert_number_needs_review(self.process(lines))

    def test_split_number_rejects_gaps_and_reversed_addresses(self):
        cases = [
            [{"text": "Документ №", "page": 1, "line": 1},
             {"text": "123", "page": 1, "line": 9}],
            [{"text": "Документ №", "page": 1, "line": 9},
             {"text": "123", "page": 1, "line": 1}],
            [{"text": "Документ №", "sheet": "A", "cell": "A1"},
             {"text": "123", "sheet": "A", "cell": "Z99"}],
            [{"text": "Документ №", "sheet": "A", "cell": "A9"},
             {"text": "123", "sheet": "A", "cell": "A1"}],
            [{"text": "Документ №", "page": 1, "line": 1},
             {"text": "123", "page": 1}],
            [{"text": "Документ №", "page": 1},
             {"text": "123", "page": 1, "line": 2}],
            [{"text": "Документ №", "sheet": "A", "cell": "A1"},
             {"text": "123", "sheet": "A"}],
            [{"text": "Документ №", "sheet": "A"},
             {"text": "123", "sheet": "A", "cell": "A2"}],
            [{"text": "Документ №", "sheet": "A", "cell": "A0"},
             {"text": "123", "sheet": "A", "cell": "A1"}],
            [{"text": "Документ №", "sheet": "A", "cell": "A1:B2"},
             {"text": "123", "sheet": "A", "cell": "C2"}],
            [{"text": "Документ №", "sheet": "A", "cell": "A1"},
             {"text": "123", "sheet": "A", "cell": "B2"}],
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                self.assert_number_needs_review(self.process(lines))

    def test_title_context_cannot_cross_sheets_or_unlocated_lines(self):
        cases = [
            [{"text": "Акт", "sheet": "A", "cell": "A1"},
             {"text": "№ 123", "sheet": "B", "cell": "A2"}],
            [{"text": "Акт"}, {"text": "№ 123"}],
            [{"text": "Акт", "page": 1, "line": 1},
             {"text": "№ 123", "page": 1, "line": 10}],
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                self.assert_number_needs_review(self.process(lines))

    def test_split_number_preserves_contiguous_page_evidence(self):
        lines = [{"text": "Документ №", "page": 3, "line": 4},
                 {"text": "SYN-017", "page": 3, "line": 5}]
        result = self.process(lines)
        number = result["records"][0]["number"]
        self.assertEqual(number["usable_value"], "SYN-017")
        self.assertEqual(number["evidence"], lines)
        self.assertEqual(result["review_queue"]["number_review_document_ids"], [])

    def test_split_number_preserves_adjacent_cells_on_one_sheet(self):
        for next_cell in ("A2", "B1"):
            lines = [{"text": "Документ №", "sheet": "A", "cell": "A1"},
                     {"text": "SYN-017", "sheet": "A", "cell": next_cell}]
            with self.subTest(next_cell=next_cell):
                number = self.process(lines)["records"][0]["number"]
                self.assertEqual(number["usable_value"], "SYN-017")
                self.assertEqual(number["evidence"], lines)

    def test_title_and_number_on_contiguous_page_lines_remain_valid(self):
        lines = [{"text": "Акт выполненных работ", "page": 1, "line": 4},
                 {"text": "№ SYN-017", "page": 1, "line": 5}]
        number = self.process(lines)["records"][0]["number"]
        self.assertEqual(number["usable_value"], "SYN-017")

    def test_same_line_number_does_not_require_cross_line_metadata(self):
        for text in ("Акт № SYN-017", "Документ № SYN-017"):
            with self.subTest(text=text):
                number = self.process([{"text": text}])["records"][0]["number"]
                self.assertEqual(number["usable_value"], "SYN-017")

    def test_explicit_zero_overrides_conflicting_model_amount(self):
        line = {"text": "Итого: 0", "page": 1, "line": 1}
        record = self.process([line], {"amount": "987.65"})["records"][0]
        self.assertEqual(record["source_facts"]["amount"], "0")
        self.assertEqual(record["facts"]["amount"], "0")
        self.assertEqual(record["fact_evidence"]["amount"], [line])

    def test_all_single_digit_integer_totals_are_source_facts(self):
        for amount in range(1, 10):
            line = {"text": f"Итого: {amount}", "page": 1, "line": 1}
            with self.subTest(amount=amount):
                record = self.process([line], {"amount": "987.65"})["records"][0]
                self.assertEqual(record["source_facts"]["amount"], str(amount))
                self.assertEqual(record["facts"]["amount"], str(amount))
                self.assertEqual(record["fact_evidence"]["amount"], [line])

    def test_split_zero_amount_is_kept_with_both_source_lines(self):
        lines = [{"text": "Итого", "page": 1, "line": 1},
                 {"text": "0", "page": 1, "line": 2}]
        record = self.process(lines, {"amount": "987.65"})["records"][0]
        self.assertEqual(record["facts"]["amount"], "0")
        self.assertEqual(record["fact_evidence"]["amount"], lines)

    def test_absent_amount_stays_distinct_from_zero(self):
        record = self.process([{"text": "Итого: не указано", "page": 1, "line": 1}])["records"][0]
        self.assertIsNone(record["facts"]["amount"])
        self.assertNotIn("amount", record["source_facts"])
        self.assertNotIn("amount", record["fact_evidence"])

    def test_existing_integer_and_decimal_amounts_keep_precision(self):
        for text, expected in (("17", "17"), ("0,00", "0.00"),
                               ("7,25", "7.25"), ("1 234,56", "1234.56")):
            with self.subTest(text=text):
                line = {"text": f"Итого: {text}", "page": 1, "line": 1}
                record = self.process([line])["records"][0]
                self.assertEqual(record["source_facts"]["amount"], expected)

    def test_contract_only_header_is_not_a_document_number(self):
        for noun in ("договору", "контракту"):
            line = {"text": f"Акт выполненных работ по {noun} № CN-2047",
                    "page": 1, "line": 1}
            with self.subTest(noun=noun):
                self.assert_number_needs_review(self.process([line]))

    def test_contract_proposal_from_model_does_not_become_usable(self):
        line = {"text": "Акт выполненных работ по договору № CN-2047",
                "page": 1, "line": 1}
        result = self.process([line], {"doc_number": "CN-2047"})
        self.assert_number_needs_review(result)

    def test_explicit_document_number_survives_separate_contract_reference(self):
        for texts in (
            ["Акт № SYN-017", "Договор № CN-2047"],
            ["Договор № CN-2047", "Акт № SYN-017"],
            ["Акт выполненных работ по договору № CN-2047", "Номер акта: SYN-017"],
        ):
            lines = [{"text": text, "page": 1, "line": i}
                     for i, text in enumerate(texts, 1)]
            with self.subTest(texts=texts):
                number = self.process(lines)["records"][0]["number"]
                self.assertEqual(number["usable_value"], "SYN-017")
                self.assertFalse(number["manual_review_required"])

    def test_same_line_document_number_precedes_contract_reference(self):
        for text in ("Акт № SYN-017 от 12.11.2026 по договору № CN-2047",
                     "Акт № SYN-017 по договору № CN-2047"):
            with self.subTest(text=text):
                line = {"text": text, "page": 1, "line": 1}
                number = self.process([line])["records"][0]["number"]
                self.assertEqual(number["usable_value"], "SYN-017")

    def test_same_line_explicit_act_number_follows_contract_reference(self):
        line = {"text": "Акт по договору № CN-2047; номер акта № SYN-017",
                "page": 1, "line": 1}
        number = self.process([line])["records"][0]["number"]
        self.assertEqual(number["usable_value"], "SYN-017")

    def test_equal_document_and_contract_numbers_need_explicit_document_anchor(self):
        lines = [{"text": "Акт № CN-2047", "page": 1, "line": 1},
                 {"text": "Договор № CN-2047", "page": 1, "line": 2}]
        number = self.process(lines)["records"][0]["number"]
        self.assertEqual(number["usable_value"], "CN-2047")
        self.assertFalse(number["manual_review_required"])


if __name__ == "__main__":
    unittest.main()
