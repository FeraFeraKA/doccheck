"""Behavioural regression tests for false joins and source-number repair."""
import unittest

from doccheck_ml.identity.identity_v2 import compare_documents, extract_number_candidates, group_documents, resolve_document



def record(number="АК-0017", model=None, acquisition="native", extra=(), ident="a"):
    lines = [{"text": text, "line": i + 1, "page": 1} for i, text in enumerate([
        "Акт оказанных услуг", f"№ {number} от 31.03.2026",
        "Исполнитель: ООО Проверка", "Договор № 24/03/15-01", "Итого: 100,00", *extra])]
    return resolve_document(ident, ident, acquisition, lines, {"doc_number": model})


class NumberTests(unittest.TestCase):
    def test_recover_literal_prefix_without_losing_zeros(self):
        r = record("ЛБ-0017", "0017", "scan")
        self.assertEqual(r["number"]["value"], "ЛБ-0017")
        self.assertEqual(r["number"]["status"], "prefix_recovered_from_source")

    def test_shared_letter_digit_error_is_not_verified(self):
        r = record("3П-0017", "3П-0017", "scan")
        self.assertEqual(r["number"]["value"], "3П-0017")
        self.assertIsNone(r["number"]["usable_value"])

    def test_source_conflict_keeps_both_observations(self):
        r = record("Л5-0017", "ЛБ-0017", "scan")
        self.assertEqual(r["number"]["value"], "ЛБ-0017")
        self.assertEqual(r["number"]["candidates"][0]["value"], "Л5-0017")
        self.assertIsNone(r["number"]["usable_value"])

    def test_empty_number_does_not_capture_contract_or_date(self):
        for text in ["Дата: 31.03.2026", "Договор № 24/03/15-01", "ИНН исполнителя: 7701234507"]:
            self.assertEqual(extract_number_candidates([{"text": "Документ №"}, {"text": text}]), [])

    def test_table_and_footer_are_not_competing_document_numbers(self):
        lines = [{"text": text} for text in ["Акт оказанных услуг", "№ ЛБ-0017 от 31.03.2026",
                 "Договор № 24/03/15-01", "Сумма, руб.", "N2", "ner1", "Nwet 1"]]
        self.assertEqual([x["value"] for x in extract_number_candidates(lines)], ["ЛБ-0017"])

    def test_bare_marker_requires_title_or_date_context(self):
        self.assertEqual(extract_number_candidates([{"text": "№ 17"}]), [])
        self.assertEqual(extract_number_candidates([{"text": "Акт"}, {"text": "N17"}])[0]["value"], "17")

    def test_split_number_label_cannot_cross_pages(self):
        self.assertEqual(extract_number_candidates([{"text": "Документ №", "page": 1},
                         {"text": "17", "page": 2}]), [])

    def test_missing_marker_and_customer_do_not_supply_issuer(self):
        r = resolve_document("a", "a", "native", [{"text": "Исполнитель: не указан"},
                             {"text": "Заказчик: ООО Покупатель"}], {})
        self.assertIsNone(r["issuer"]["value"])

    def test_native_unicode_alphabets_remain_distinct(self):
        a, b = record("CB-0017"), record("СВ-0017", ident="b")
        self.assertNotIn(compare_documents(a, b)["status"], {"duplicate", "candidate"})

    def test_native_leading_zero_and_prefix_are_significant(self):
        a = record()
        for n in ["АК-017", "0017"]:
            b = record(n, ident="b")
            self.assertNotIn(compare_documents(a, b)["status"], {"duplicate", "candidate"})

    def test_optional_model_period_does_not_override_issue_date(self):
        a, b = record(ident="a"), record(ident="b")
        b["facts"].update(period_start="2026-03-01", period_end="2026-03-31")
        self.assertEqual(compare_documents(a, b)["status"], "candidate")

    def test_same_name_different_role_tax_id_never_duplicate(self):
        a = record(extra=["ИНН исполнителя: 7701234507"])
        b = record(extra=["ИНН исполнителя: 7701234518"], ident="b")
        self.assertIn("issuer_tax_id", compare_documents(a, b)["reasons"][0])
        self.assertFalse(compare_documents(a, b)["auto_merge"])

    def test_same_identity_changed_amount_is_conflict(self):
        a, b = record(), record(ident="b")
        b["facts"]["amount"] = "101.00"
        self.assertEqual(compare_documents(a, b)["status"], "conflict")

    def test_candidate_edges_cannot_bridge_groups(self):
        a, b, c = record(ident="a"), record(ident="b"), record(ident="c")
        b["source_sha256"] = a["source_sha256"]
        groups = group_documents([a, b, c])
        self.assertEqual(sorted(map(sorted, groups["groups"])), [["a", "b"], ["c"]])
        self.assertFalse(groups["files_deleted"])
