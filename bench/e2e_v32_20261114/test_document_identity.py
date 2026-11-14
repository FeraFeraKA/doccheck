import copy
import unittest

from bench.e2e_v32_20261114.document_identity import apply_document_number_checks, validate_number_evidence, resolve_own_number
from bench.e2e_v32_20261114.decision_rules import reconcile
from bench.e2e_v32_20261114.test_quality import COMPLETE, document


def native(identifier="first", own="ОС-3817", raw="3817", amount="100.00", category="general_admin", text=None):
    record = document(identifier, category, amount)
    record["prediction"]["doc_number"] = raw
    record["input_kind"] = "native"
    source = text if text is not None else f"Акт оказанных услуг\nДокумент № {own}\nДоговор: EX-72"
    return apply_document_number_checks(record, source)


def compare(records, reported="100.00"):
    return reconcile(records, [{"category": "general_admin", "reported_amount": reported},
                               {"category": "production_overhead", "reported_amount": "100.00"}],
                     "EX-72", "2026-01-01", "2026-05-31", COMPLETE)


class OwnNumberTests(unittest.TestCase):
    def test_explicit_own_number_corrects_every_wrong_raw_without_tail_inference(self):
        for raw in ("3817", "999999", "ПР-3817", "ОC-3817", None):
            for category in ("general_admin", "production_overhead", "payroll", "insurance"):
                checked = native(raw=raw, category=category)
                self.assertEqual(checked["prediction"]["doc_number"], "ОС-3817")
                self.assertEqual(checked["number_evidence"]["decision"], "corrected")
                self.assertTrue(validate_number_evidence(checked)["identity_usable"])
                self.assertEqual(checked["raw_prediction"]["doc_number"], raw)
                self.assertEqual(checked["prediction"]["category"], category)

    def test_format_specific_native_structures_keep_full_literal_number(self):
        for source in (
            "Лист: Акт\nA1: Акт оказанных услуг\nA3: Номер документа | C3: ОС-3817\nA6: Код статьи | B6: Сумма",
            "Акт оказанных услуг\nНомер документа | ОС-3817\nДата | 31.03.2026",
            "Страница 1\nАкт оказанных услуг\n№ ОС-3817 от 31.03.2026\nДоговор № EX-72",
            "УПД ОС-3817\nОснование\nДоговор № EX-72",
        ):
            checked = native(text=source)
            self.assertEqual(checked["prediction"]["doc_number"], "ОС-3817", source)
            for candidate in checked["number_evidence"]["candidates"]:
                self.assertEqual(source[candidate["start"]:candidate["end"]], candidate["value"])
                self.assertEqual(source[candidate["context_start"]:candidate["context_end"]], candidate["context"])

    def test_same_number_is_confirmed_and_repeat_application_is_idempotent(self):
        first = native(raw="ОС-3817")
        self.assertEqual(first["number_evidence"]["decision"], "confirmed")
        self.assertEqual(apply_document_number_checks(first, first["source_native_text"]), first)
        corrected = native(raw="wrong")
        twice = apply_document_number_checks(corrected, corrected["source_native_text"])
        self.assertEqual(twice, corrected)
        self.assertEqual(twice["number_evidence"]["decision"], "corrected")

    def test_nonnumber_fields_and_raw_are_unchanged(self):
        record = document()
        record["prediction"].update(doc_number="3817", description="keep", evidence_quote="keep", counterparty="keep")
        before = copy.deepcopy(record)
        checked = apply_document_number_checks(record, "Документ № ОС-3817")
        self.assertEqual(record, before)
        self.assertEqual(checked["raw_prediction"], before["prediction"])
        self.assertEqual({k:v for k,v in checked["prediction"].items() if k != "doc_number"},
                         {k:v for k,v in before["prediction"].items() if k != "doc_number"})

    def test_contract_date_reference_and_account_are_not_own_numbers(self):
        for source in ("Договор № ОС-3817", "Дата: 31.03.2026", "Основание: Акт № ОС-3817",
                       "Согласно акту № ОС-3817", "Приложение к акту № ОС-3817",
                       "Расчетный счет № 40702810000000000001", "Счет организации: 40702810000000000001",
                       "Акт выполненных работ по заявке № З-3817", "Акт к отчёту № ОТ-3817"):
            checked = native(raw="raw-19", text=source)
            self.assertEqual(checked["prediction"]["doc_number"], "raw-19", source)
            self.assertFalse(validate_number_evidence(checked)["identity_usable"], source)

    def test_row_numbers_and_documents_in_body_table_are_not_own(self):
        checked = native(text="Акт оказанных услуг\nНаименование | Сумма\nДокумент № ЧУЖ-3817 | 100\n№ строки: 4")
        self.assertEqual(checked["prediction"]["doc_number"], "3817")
        self.assertFalse(checked["number_evidence"]["identity_usable"])

    def test_generic_document_name_and_partial_labels_are_not_number_fields(self):
        for source in ("Документ: Инвентаризация-2026", "Номер документации2026", "Документальный № 27"):
            checked = native(raw="raw-19", text=source)
            self.assertEqual(checked["prediction"]["doc_number"], "raw-19")
            self.assertFalse(validate_number_evidence(checked)["identity_usable"])

    def test_unknown_title_descriptor_is_not_proven_foreign_number(self):
        checked = native(raw="А-43", text="Акт обслуживания банка № А-43")
        proof = validate_number_evidence(checked)
        self.assertFalse(proof["identity_usable"])
        self.assertEqual(proof["non_own_candidates"], [])

    def test_distinct_own_ids_are_ambiguous_and_not_used_to_correct(self):
        for source in ("Документ № А-3817\nДокумент № Б-3817",
                       "Акт № А-3817; Акт № Б-3817"):
            checked = native(text=source)
            self.assertEqual(checked["prediction"]["doc_number"], "3817")
            self.assertEqual(checked["number_evidence"]["status"], "ambiguous")
            self.assertFalse(validate_number_evidence(checked)["identity_usable"])

    def test_repeated_same_own_id_is_not_ambiguity(self):
        checked = native(text="Акт № ОС-3817\nНомер документа: ОС-3817")
        self.assertTrue(validate_number_evidence(checked)["identity_usable"])
        self.assertEqual(checked["prediction"]["doc_number"], "ОС-3817")

    def test_blank_and_unassigned_number_never_become_shared_identity(self):
        for value in ("б/н", "без номера", "не присвоен", "—", ""):
            checked = native(raw=None, text="Документ № " + value)
            self.assertIsNone(checked["prediction"]["doc_number"])
            self.assertFalse(validate_number_evidence(checked)["identity_usable"])

    def test_date_shaped_values_in_explicit_own_fields_are_literal_ids(self):
        for value in ("31.03.2026", "31 . 03 . 2026", "2026-03-31", "2026 - 03 - 31"):
            checked = native(raw=None, text="Номер документа: " + value)
            self.assertEqual(checked["prediction"]["doc_number"], value)
            self.assertTrue(validate_number_evidence(checked)["identity_usable"])

    def test_scripts_zeros_case_dashes_and_leading_zeros_are_preserved(self):
        for value in ("OC-0017", "ОС-0017", "0C-0017", "ОC-0017", "ос-0017", "ОС–0017", "ОС - 0017"):
            checked = native(own=value, raw="17")
            self.assertEqual(checked["prediction"]["doc_number"], value)
            self.assertTrue(validate_number_evidence(checked)["identity_usable"])

    def test_model_only_scan_never_repairs_prefix_or_claims_source_identity(self):
        record = document()
        record["prediction"]["doc_number"] = "3817"
        record["prediction"]["evidence_quote"] = "Документ № ОС-3817"
        checked = apply_document_number_checks(record)
        self.assertEqual(checked["prediction"]["doc_number"], "3817")
        self.assertEqual(checked["number_evidence"]["decision"], "model_only")
        self.assertFalse(checked["number_evidence"]["source_verified"])
        self.assertFalse(validate_number_evidence(checked)["identity_usable"])

    def test_tampering_never_grants_identity_authority(self):
        original = native()
        for mutation in ("source_hash", "text", "native_hash", "effective", "decision", "state", "permission", "span", "candidate", "raw"):
            checked = copy.deepcopy(original)
            if mutation == "source_hash": checked["source_hash"] = "changed"
            elif mutation == "text": checked["source_native_text"] += " altered"
            elif mutation == "native_hash": checked["number_evidence"]["native_text_sha256"] = "0" * 64
            elif mutation == "effective": checked["prediction"]["doc_number"] = "OTHER-1"
            elif mutation == "decision": checked["number_evidence"]["decision"] = "confirmed"
            elif mutation == "state": checked["number_evidence"]["status"] = "missing"
            elif mutation == "permission": checked["number_evidence"]["identity_usable"] = None
            elif mutation == "span": checked["number_evidence"]["candidates"][0]["start"] += 1
            elif mutation == "candidate": checked["number_evidence"]["candidates"][0]["value"] = "OTHER-1"
            else: checked["raw_prediction"]["doc_number"] = "changed"
            self.assertFalse(validate_number_evidence(checked)["identity_usable"], mutation)


class IdentityMergeTests(unittest.TestCase):
    def test_explicit_kind_conflict_prevents_same_id_merge(self):
        other_kind = native("second", text="УПД № ОС-3817")
        result = compare([native("first"), other_kind], "200.00")
        self.assertEqual(result["duplicates"], [])
        self.assertEqual(result["rows"][0]["status"], "correct")
        self.assertEqual(result["rows"][0]["source_ids"], ["first", "second"])
        self.assertTrue(any(w["reason"] == "explicit_identity_context_conflict" for w in result["identity_warnings"]))

    def test_explicit_issuer_conflict_prevents_same_id_merge(self):
        first = native("first", text='Акт № ОС-3817\nИсполнитель: ООО «Альфа»')
        second = native("second", text='Акт № ОС-3817\nИсполнитель: ООО «Бета»')
        result = compare([first, second], "200.00")
        self.assertEqual(result["duplicates"], [])
        self.assertEqual(result["rows"][0]["status"], "correct")
        self.assertEqual(result["rows"][0]["source_ids"], ["first", "second"])

    def test_absent_kind_or_issuer_does_not_become_a_new_veto(self):
        first = native("first", text='Акт № ОС-3817\nИсполнитель: ООО «Альфа»')
        second = native("second", text='Документ № ОС-3817')
        result = compare([first, second])
        self.assertEqual(result["rows"][0]["status"], "unverified")
        self.assertEqual(result["duplicates"], [])
        self.assertTrue(any(x["reason"] == "unresolved_document_identity_collision" for x in result["identity_warnings"]))

    def test_kind_and_issuer_fields_require_authentic_source_proof(self):
        checked = native()
        checked["number_evidence"]["document_kind"] = "forged"
        self.assertFalse(validate_number_evidence(checked)["identity_usable"])
        checked = native()
        checked["number_evidence"]["issuer_key"] = "invented organisation"
        self.assertFalse(validate_number_evidence(checked)["identity_usable"])
    def test_two_verified_full_own_ids_with_different_hashes_require_review(self):
        first = native("first")
        second = native("second", raw="unrelated", text="Страница 1\nАкт оказанных услуг\n№ ОС-3817 от 31.03.2026")
        result = compare([first, second])
        self.assertEqual(result["rows"][0]["status"], "unverified")
        self.assertIsNone(result["rows"][0]["expected_amount"])
        self.assertEqual(result["rows"][0]["source_ids"], [])
        self.assertEqual(result["duplicates"], [])

    def test_same_number_with_changed_amount_or_category_requires_review(self):
        for second in (native("second", amount="101.00"), native("second", category="production_overhead")):
            result = compare([native("first"), second])
            self.assertEqual(result["rows"][0]["status"], "unverified")
            self.assertTrue(any(reason["reason"] == "unresolved_document_identity_collision" for reason in result["rows"][0]["reasons"]))
            self.assertEqual(result["duplicates"], [])

    def test_two_confirmed_different_prefix_or_script_ids_never_collide(self):
        for left, right in (("А-17", "Б-17"), ("A-17", "А-17"), ("ОС-17", "0C-17"), ("ОС-17", "ос-17")):
            result = compare([native("first", own=left, raw="17"), native("second", own=right, raw="17")], "200.00")
            self.assertEqual(result["rows"][0]["status"], "correct", (left, right))
            self.assertEqual(result["duplicates"], [])
            self.assertEqual(result["identity_warnings"], [])

    def test_unresolved_identity_alone_warns_without_blocking_known_amount(self):
        for source in ("Акт оказанных услуг без собственного номера", "Документ № А-1\nДокумент № Б-2"):
            item = native(text=source, raw="raw-19")
            result = compare([item])
            self.assertEqual(result["rows"][0]["status"], "correct")
            self.assertTrue(result["identity_warnings"])

    def test_full_id_collision_with_unchecked_side_requires_review_not_merge(self):
        for amount in ("100.00", "101.00"):
            checked = native("first")
            uncertain = native("second", raw="ОС-3817", amount=amount, text="Акт оказанных услуг")
            result = compare([checked, uncertain], "200.00")
            self.assertEqual(result["duplicates"], [])
            self.assertEqual(result["rows"][0]["status"], "unverified")
            self.assertTrue(any(x["reason"] == "unresolved_document_identity_collision" for x in result["identity_warnings"]))

    def test_standalone_raw_number_marker_only_enables_suspected_review(self):
        for raw in ("№ ОС-3817", "номер: ОС-3817", "номер ОС-3817"):
            item = native("second", raw=raw, text="Сумма: 100")
            result = compare([native("first"), item], "200.00")
            self.assertEqual(item["prediction"]["doc_number"], raw)
            self.assertEqual(result["duplicates"], [])
            self.assertEqual(result["rows"][0]["status"], "unverified")

    def test_raw_alias_cleanup_does_not_strip_word_prefix_or_internal_format(self):
        for raw in ("номерОС-3817", "ОС - 3817", "OC-3817"):
            item = native("second", raw=raw, text="Сумма: 100")
            result = compare([native("first"), item], "200.00")
            self.assertEqual(item["prediction"]["doc_number"], raw)
            self.assertEqual(result["duplicates"], [])
            self.assertEqual(result["rows"][0]["status"], "correct")

    def test_bare_tail_suspicion_requires_same_amount_and_category(self):
        for amount, category, expected in (("100.00", "general_admin", True), ("101.00", "general_admin", False), ("100.00", "production_overhead", False)):
            uncertain = native("second", raw="3817", amount=amount, category=category, text="Акт оказанных услуг")
            result = compare([native("first"), uncertain], "201.00")
            suspected = any(x["reason"] == "suspected_bare_tail_identity" for x in result["identity_warnings"])
            self.assertEqual(suspected, expected)
            self.assertEqual(result["duplicates"], [])
            self.assertEqual(uncertain["prediction"]["doc_number"], "3817")

    def test_two_unchecked_same_full_raw_ids_never_auto_merge(self):
        result = compare([native("first", raw="NO-77", text="Сумма: 100"), native("second", raw="NO-77", text="Сумма: 100")], "200.00")
        self.assertEqual(result["duplicates"], [])
        self.assertEqual(result["rows"][0]["status"], "unverified")

    def test_collisions_require_matching_contract_period_and_counterparty(self):
        for field, value in (("contract_number", "OTHER-71"), ("period_start", "2026-04-01"), ("counterparty", "Another company")):
            uncertain = native("second", raw="ОС-3817", text="Сумма: 100")
            uncertain["prediction"][field] = value
            if field == "period_start": uncertain["prediction"]["period_end"] = "2026-04-30"
            result = compare([native("first"), uncertain], "200.00")
            self.assertFalse(any(x["reason"].endswith("collision") or x["reason"] == "suspected_bare_tail_identity" for x in result["identity_warnings"]))

    def test_foreign_reference_raw_is_not_an_alias_of_current_operation(self):
        for amount in ("100.00", "101.00"):
            foreign = native("second", raw="ОС-3817", amount=amount, text="Акт оказанных услуг\nОснование: Акт № ОС-3817")
            for records in ([native("first"), foreign], [foreign, native("first")]):
                result = compare(records, str(100 + int(float(amount))))
                self.assertEqual(result["duplicates"], [])
                self.assertEqual(result["rows"][0]["status"], "correct")
                self.assertFalse(any(x["reason"] == "unresolved_document_identity_collision" for x in result["identity_warnings"]))

    def test_own_candidate_has_priority_over_same_token_in_reference(self):
        ambiguous = native("second", raw="ОС-3817", text="Документ № ОС-3817\nДокумент № Б-92\nОснование: Акт № ОС-3817")
        result = compare([native("first"), ambiguous], "200.00")
        self.assertEqual(result["rows"][0]["status"], "unverified")
        self.assertEqual(result["duplicates"], [])

    def test_invalid_foreign_evidence_cannot_suppress_raw_collision(self):
        foreign = native("second", raw="ОС-3817", text="Основание: Акт № ОС-3817")
        foreign["number_evidence"]["native_text_sha256"] = "0" * 64
        result = compare([native("first"), foreign], "200.00")
        self.assertEqual(result["rows"][0]["status"], "unverified")
        self.assertEqual(result["duplicates"], [])

    def test_exact_byte_duplicate_still_precedes_identity_uncertainty(self):
        uncertain = native(text="Сумма: 100", raw="raw-9")
        duplicate = copy.deepcopy(uncertain); duplicate["id"] = "byte-copy"
        result = compare([uncertain, duplicate])
        self.assertEqual(result["rows"][0]["status"], "correct")
        self.assertEqual(result["duplicates"][0]["basis"], "hash")


if __name__ == "__main__":
    unittest.main()
