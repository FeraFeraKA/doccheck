"""Source-role regressions through the public API on generated local input."""

from copy import deepcopy
from decimal import Decimal
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from doccheck_ml import DocumentInput, process_documents
from doccheck_ml.identity import identity_v2, identity_v3, identity_v4_source


class SourceRoleRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "synthetic.txt"

    def process_result(self, lines, prediction=None, acquisition="native"):
        self.source.write_text("\n".join(line["text"] for line in lines), encoding="utf-8")
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        result = process_documents([
            DocumentInput("synthetic", self.source, digest, acquisition, lines,
                          prediction or {}),
        ], synthetic=True)
        return result

    def process(self, lines, prediction=None, acquisition="native"):
        return self.process_result(lines, prediction, acquisition)["records"][0]

    @staticmethod
    def lines(*texts):
        return [{"text": text, "page": 1, "line": i}
                for i, text in enumerate(texts, 1)]

    def test_document_total_wins_over_generic_amount_in_either_order(self):
        for texts in (("Сумма: 100,00", "Итого: 200,00"),
                      ("Итого: 200,00", "Сумма: 100,00")):
            with self.subTest(texts=texts):
                lines = self.lines(*texts)
                record = self.process(lines, {"amount": "100.00"})
                self.assertEqual(record["facts"]["amount"], "200.00")
                self.assertEqual(record["source_facts"]["amount"], "200.00")
                self.assertEqual(record["fact_evidence"]["amount"],
                                 [line for line in lines if line["text"].startswith("Итого")])

    def test_explicit_document_total_labels_take_priority(self):
        for label in ("Итоговая сумма", "К оплате по документу", "Сумма по акту"):
            with self.subTest(label=label):
                record = self.process(self.lines("Стоимость: 100,00", f"{label}: 200,00"))
                self.assertEqual(record["facts"]["amount"], "200.00")

    def test_section_totals_and_tax_amounts_do_not_override_the_document_total(self):
        for texts in (("Итого по разделу: 100,00", "Сумма НДС: 40,00", "Итого: 200,00"),
                      ("Итого: 200,00", "Сумма НДС: 40,00", "Итого по разделу: 100,00")):
            with self.subTest(texts=texts):
                lines = self.lines(*texts)
                record = self.process(lines)
                self.assertEqual(record["facts"]["amount"], "200.00")
                self.assertNotIn("amount", record["fact_conflicts"])
                self.assertEqual(record["fact_evidence"]["amount"],
                                 [line for line in lines if line["text"] == "Итого: 200,00"])

    def test_qualified_document_totals_take_priority_in_either_order(self):
        for label in ("Итого (с НДС)", "Итого (без НДС)", "Итого по документу",
                      "Итого к оплате по документу"):
            for texts in (("Сумма: 100,00", f"{label}: 200,00"),
                          (f"{label}: 200,00", "Сумма: 100,00")):
                with self.subTest(label=label, texts=texts):
                    lines = self.lines(*texts)
                    record = self.process(lines, {"amount": "100.00"})
                    self.assertEqual(record["facts"]["amount"], "200.00")
                    self.assertEqual(record["source_facts"]["amount"], "200.00")
                    self.assertEqual(record["fact_evidence"]["amount"],
                                     [line for line in lines if line["text"].startswith(label)])

    def test_qualified_document_totals_preserve_conflicts_in_either_order(self):
        for label in ("Итого (с НДС)", "Итого (без НДС)", "Итого по документу",
                      "Итого к оплате по документу"):
            for texts in (("Итого: 200,00", f"{label}: 300,00"),
                          (f"{label}: 300,00", "Итого: 200,00")):
                with self.subTest(label=label, texts=texts):
                    lines = self.lines(*texts)
                    record = self.process(lines, {"amount": "200.00"})
                    self.assertIsNone(record["facts"]["amount"])
                    self.assertIsNone(record["source_facts"]["amount"])
                    conflict = record["fact_conflicts"]["amount"]
                    self.assertEqual(conflict["reason"], "conflicting_source_totals")
                    self.assertEqual({candidate["value"] for candidate in conflict["candidates"]},
                                     {"200.00", "300.00"})
                    self.assertEqual(record["fact_evidence"]["amount"], lines)

    def test_unknown_total_qualifier_does_not_promote_a_generic_amount(self):
        for texts in (("Сумма: 100,00", "Итого окончательно: 200,00"),
                      ("Итого окончательно: 200,00", "Сумма: 100,00")):
            with self.subTest(texts=texts):
                record = self.process(self.lines(*texts), {"amount": "77.00"})
                self.assertNotIn("amount", record["source_facts"])
                self.assertEqual(record["facts"]["amount"], "77.00")

    def test_valid_and_unknown_qualified_totals_remain_ambiguous(self):
        for texts in (("Итого: 200,00", "Итого окончательно: 300,00"),
                      ("Итого окончательно: 300,00", "Итого: 200,00")):
            with self.subTest(texts=texts):
                lines = self.lines(*texts)
                record = self.process(lines, {"amount": "200.00"})
                self.assertIsNone(record["facts"]["amount"])
                self.assertIsNone(record["source_facts"]["amount"])
                conflict = record["fact_conflicts"]["amount"]
                self.assertEqual(conflict["reason"], "incomplete_source_totals")
                self.assertEqual({candidate["value"] for candidate in conflict["candidates"]},
                                 {"200.00", None})
                self.assertEqual(record["fact_evidence"]["amount"], lines)

    def test_conflicting_totals_do_not_choose_by_order_or_model(self):
        for texts in (("Итого: 200,00", "Итого: 300,00"),
                      ("Итого: 300,00", "Итого: 200,00")):
            for model in ("200.00", "300.00", None):
                with self.subTest(texts=texts, model=model):
                    lines = self.lines(*texts)
                    record = self.process(lines, {"amount": model})
                    self.assertIsNone(record["facts"]["amount"])
                    self.assertIsNone(record["source_facts"]["amount"])
                    conflict = record["fact_conflicts"]["amount"]
                    self.assertEqual(conflict["reason"], "conflicting_source_totals")
                    self.assertEqual({candidate["value"] for candidate in conflict["candidates"]},
                                     {"200.00", "300.00"})
                    self.assertEqual({candidate["role"] for candidate in conflict["candidates"]},
                                     {"document_total"})
                    self.assertEqual([candidate["evidence"] for candidate in conflict["candidates"]],
                                     [[line] for line in lines])
                    self.assertEqual(record["fact_evidence"]["amount"], lines)

    def test_conflicting_generic_amounts_are_explicitly_ambiguous(self):
        lines = self.lines("Сумма: 37,25", "Стоимость: 83,10")
        record = self.process(lines, {"amount": "37.25"})
        self.assertIsNone(record["facts"]["amount"])
        self.assertIsNone(record["source_facts"]["amount"])
        conflict = record["fact_conflicts"]["amount"]
        self.assertEqual(conflict["reason"], "conflicting_source_amounts")
        self.assertEqual({candidate["value"] for candidate in conflict["candidates"]},
                         {"37.25", "83.10"})
        self.assertEqual({candidate["role"] for candidate in conflict["candidates"]}, {"amount"})
        self.assertEqual(record["fact_evidence"]["amount"], lines)

    def test_standalone_amount_conflict_is_visible_without_number_review(self):
        result = self.process_result(self.lines("Акт № SYN-017", "Итого: 200,00", "Итого: 300,00"))
        self.assertEqual(result["review_queue"]["number_review_document_ids"], [])
        self.assertEqual(result["review_queue"]["fact_review_document_ids"], ["synthetic"])
        self.assertEqual(len(result["review_queue"]["fact_cards"]), 1)

    def test_v3_standalone_amount_conflict_is_visible_without_number_review(self):
        record = self.process(self.lines("Акт № SYN-017", "Итого: 200,00", "Итого: 300,00"))
        queue = identity_v3.review_queue([record])
        self.assertEqual(queue["number_review_document_ids"], [])
        self.assertEqual(queue["fact_review_document_ids"], ["synthetic"])
        self.assertEqual(len(queue["fact_cards"]), 1)

    def test_valid_and_unreadable_totals_cannot_silently_select_the_valid_one(self):
        lines = self.lines("Итого: 200,00", "Итого: 0?")
        record = self.process(lines, {"amount": "200.00"})
        self.assertIsNone(record["facts"]["amount"])
        self.assertIsNone(record["source_facts"]["amount"])
        conflict = record["fact_conflicts"]["amount"]
        self.assertEqual(conflict["reason"], "incomplete_source_totals")
        self.assertEqual({candidate["value"] for candidate in conflict["candidates"]}, {"200.00", None})
        self.assertEqual(record["fact_evidence"]["amount"], lines)

    def test_unreadable_total_does_not_promote_an_intermediate_source_amount(self):
        record = self.process(self.lines("Сумма: 100,00", "Итого: 0?"), {"amount": "77.00"})
        self.assertNotIn("amount", record["source_facts"])
        self.assertEqual(record["facts"]["amount"], "77.00")

    def test_blank_or_unreadable_total_does_not_promote_an_intermediate_source_amount(self):
        for texts in (("Сумма:100,00", "Итого", "Дата:12.11.2026"),
                      ("Сумма:100,00", "Итого: неразборчиво")):
            with self.subTest(texts=texts):
                record = self.process(self.lines(*texts), {"amount": "77.00"})
                self.assertNotIn("amount", record["source_facts"])
                self.assertEqual(record["facts"]["amount"], "77.00")

    def test_valid_and_blank_totals_cannot_use_an_unrelated_adjacent_field(self):
        lines = self.lines("Итого: 200,00", "Итого", "Дата:12.11.2026")
        record = self.process(lines, {"amount": "200.00"})
        self.assertIsNone(record["facts"]["amount"])
        self.assertIsNone(record["source_facts"]["amount"])
        conflict = record["fact_conflicts"]["amount"]
        self.assertEqual(conflict["reason"], "incomplete_source_totals")
        self.assertEqual({candidate["value"] for candidate in conflict["candidates"]},
                         {"200.00", None})
        self.assertEqual(record["fact_evidence"]["amount"], lines[:2])

    def test_amount_conflict_cannot_authorize_native_package_merging(self):
        lines = self.lines("Акт № SYN-017 от 12.11.2026", "Договор № SYN-CN-2070",
                           "Исполнитель: ООО Синтетика", "Итого: 200,00", "Итого: 300,00")
        first = self.process(lines)
        second = deepcopy(first)
        second.update(id="other", source_sha256=hashlib.sha256(b"another-synthetic-source").hexdigest())
        for record in (first, second):
            record.update(content_complete=True, content_fingerprint="synthetic-content",
                          package_fingerprint="synthetic-native-package")
        self.assertFalse(identity_v2.compare_documents(first, second)["auto_merge"])

    def test_partial_ocr_observation_cannot_clear_an_existing_amount_conflict(self):
        lines = self.lines("Итого: 200,00", "Итого: 300,00")
        record = self.process(lines, acquisition="scan")
        joined = {"id": record["id"], "source_sha256": record["source_sha256"],
                  "baseline": {"prediction": {"amount": "200.00"}}}
        observation = {"id": record["id"], "source_sha256": record["source_sha256"],
                       "lines": [lines[0]]}
        corrections = identity_v4_source.source_corrections(record, joined, observation)
        self.assertFalse(corrections["amount"]["applied"])
        after = identity_v4_source.apply_corrections(deepcopy(record), corrections)
        self.assertIsNone(after["facts"]["amount"])
        self.assertEqual(after["fact_conflicts"], record["fact_conflicts"])

    def test_equal_totals_with_different_decimal_scales_do_not_conflict(self):
        record = self.process(self.lines("Итого: 200,00", "Итоговая сумма: 200"))
        self.assertEqual(Decimal(record["facts"]["amount"]), Decimal("200"))
        self.assertEqual(Decimal(record["source_facts"]["amount"]), Decimal("200"))
        self.assertNotIn("amount", record["fact_conflicts"])

    def test_zero_total_wins_over_nonzero_intermediate_amount(self):
        record = self.process(self.lines("Сумма: 100,00", "Итого: 0"), {"amount": "100.00"})
        self.assertEqual(record["facts"]["amount"], "0")
        self.assertEqual(record["source_facts"]["amount"], "0")

    def test_split_total_preserves_its_actual_value_evidence(self):
        lines = self.lines("Сумма: 100,00", "Итого", "200,00")
        record = self.process(lines)
        self.assertEqual(record["facts"]["amount"], "200.00")
        self.assertEqual(record["fact_evidence"]["amount"], lines[1:])

    def test_a_unique_generic_amount_still_works(self):
        record = self.process(self.lines("Сумма: 37,25"))
        self.assertEqual(record["facts"]["amount"], "37.25")

    def test_issuer_value_cannot_cross_source_boundaries(self):
        cases = [
            [{"text": "Исполнитель:", "page": 1, "line": 1},
             {"text": "ООО Синтетика", "page": 2, "line": 2}],
            [{"text": "Исполнитель:", "sheet": "A", "cell": "A1"},
             {"text": "ООО Синтетика", "sheet": "B", "cell": "A2"}],
            [{"text": "Исполнитель:"}, {"text": "ООО Синтетика"}],
            [{"text": "Исполнитель:", "page": 1, "line": 1},
             {"text": "ООО Синтетика", "page": 1, "line": 9}],
            [{"text": "Исполнитель:", "sheet": "A", "cell": "A1"},
             {"text": "ООО Синтетика", "sheet": "A", "cell": "Z99"}],
            [{"text": "Исполнитель:", "page": 1, "line": 1},
             {"text": "ООО Синтетика", "page": 1}],
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                issuer = self.process(lines)["issuer"]
                self.assertIsNone(issuer["value"])
                self.assertNotEqual(issuer["status"], "explicit_source_role")

    def test_adjacent_issuer_lines_preserve_both_addresses(self):
        lines = self.lines("Исполнитель:", "ООО Синтетика")
        issuer = self.process(lines)["issuer"]
        self.assertEqual(issuer["value"], "ООО Синтетика")
        self.assertEqual(issuer["status"], "explicit_source_role")
        self.assertEqual(issuer["evidence"], lines)

    def test_adjacent_issuer_cells_are_supported(self):
        for next_cell in ("A2", "B1"):
            lines = [{"text": "Исполнитель:", "sheet": "A", "cell": "A1"},
                     {"text": "ООО Синтетика", "sheet": "A", "cell": next_cell}]
            with self.subTest(next_cell=next_cell):
                issuer = self.process(lines)["issuer"]
                self.assertEqual(issuer["value"], "ООО Синтетика")
                self.assertEqual(issuer["evidence"], lines)

    def test_inline_issuer_does_not_require_cross_line_metadata(self):
        line = {"text": "Исполнитель: ООО Синтетика"}
        issuer = self.process([line])["issuer"]
        self.assertEqual(issuer["value"], "ООО Синтетика")
        self.assertEqual(issuer["evidence"], [line])

    def test_empty_issuer_label_does_not_capture_another_role(self):
        issuer = self.process(self.lines("Исполнитель:", "Заказчик: ООО Синтетика"))["issuer"]
        self.assertIsNone(issuer["value"])

    def test_explicit_number_labels_allow_optional_number_sign(self):
        for text in ("Номер документа: № SYN-017", "Номер акта № SYN-017",
                     "Документ: № SYN-017", "Номер акта: № SYN-017"):
            with self.subTest(text=text):
                line = {"text": text, "page": 1, "line": 1}
                number = self.process([line])["number"]
                self.assertEqual(number["usable_value"], "SYN-017")
                self.assertFalse(number["manual_review_required"])
                self.assertEqual(number["evidence"], [line])

    def test_number_sign_does_not_consume_the_literal_ascii_prefix(self):
        for number_text in ("N123", "No123"):
            for marker in ("", "№ "):
                with self.subTest(number_text=number_text, marker=marker):
                    line = {"text": f"Номер документа: {marker}{number_text}"}
                    number = self.process([line])["number"]
                    self.assertEqual(number["usable_value"], number_text)

    def test_split_explicit_label_accepts_marker_with_valid_source_link(self):
        for label in ("Номер документа:", "Номер акта", "Документ:"):
            lines = self.lines(label, "№ SYN-017")
            with self.subTest(label=label):
                number = self.process(lines)["number"]
                self.assertEqual(number["usable_value"], "SYN-017")
                self.assertEqual(number["evidence"], lines)

    def test_split_explicit_label_with_trailing_marker_accepts_adjacent_value(self):
        for label in ("Номер документа: №", "Номер акта №"):
            lines = self.lines(label, "SYN-017")
            with self.subTest(label=label):
                number = self.process(lines)["number"]
                self.assertEqual(number["usable_value"], "SYN-017")
                self.assertFalse(number["manual_review_required"])
                self.assertEqual(number["evidence"], lines)

    def test_split_trailing_number_sign_cannot_bypass_source_boundary(self):
        for label in ("Номер документа: №", "Номер акта №"):
            for lines in (
                [{"text": label}, {"text": "SYN-017"}],
                [{"text": label, "page": 1, "line": 1},
                 {"text": "SYN-017", "page": 2, "line": 2}],
                [{"text": label, "sheet": "A", "cell": "A1"},
                 {"text": "SYN-017", "sheet": "B", "cell": "A2"}],
            ):
                with self.subTest(label=label, lines=lines):
                    number = self.process(lines)["number"]
                    self.assertIsNone(number["usable_value"])
                    self.assertTrue(number["manual_review_required"])

    def test_split_number_sign_cannot_bypass_source_boundary(self):
        for lines in (
            [{"text": "Номер документа:"}, {"text": "№ SYN-017"}],
            [{"text": "Номер документа:", "page": 1, "line": 1},
             {"text": "№ SYN-017", "page": 2, "line": 1}],
        ):
            with self.subTest(lines=lines):
                number = self.process(lines)["number"]
                self.assertIsNone(number["usable_value"])
                self.assertTrue(number["manual_review_required"])

    def test_number_sign_does_not_turn_missing_or_contract_fields_into_number(self):
        for text in ("Номер документа: №", "Номер документа: № не указан",
                     "Номер договора: № SYN-017"):
            with self.subTest(text=text):
                number = self.process([{"text": text}])["number"]
                self.assertIsNone(number["usable_value"])


if __name__ == "__main__":
    unittest.main()
