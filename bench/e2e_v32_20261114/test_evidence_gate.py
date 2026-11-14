"""Causal source-gate tests: vary model answers independently of the source."""
import copy
import unittest

from bench.e2e_v32_20261114.classification import apply_source_checks
from bench.e2e_v32_20261114.decision_rules import reconcile
from bench.e2e_v32_20261114.test_quality import COMPLETE, document


RAW_CATEGORIES = ("general_admin", "production_overhead", None)


def reconcile_with_payroll(item, completeness=COMPLETE):
    return reconcile([item, document("pay", "payroll", "60.00")],
        [{"category": "general_admin", "reported_amount": "100.00"},
         {"category": "production_overhead", "reported_amount": "100.00"},
         {"category": "payroll", "reported_amount": "60.00"}],
        "EX-72", "2026-01-01", "2026-05-31", completeness)


class EvidenceGateTests(unittest.TestCase):
    def test_positive_evidence_corrects_wrong_raw_and_confirms_right_raw(self):
        for text, expected in (
            ("Обслуживание аппарата управления.", "general_admin"),
            ("Ремонт оборудования производственной лаборатории.", "production_overhead"),
        ):
            for raw in RAW_CATEGORIES:
                with self.subTest(text=text, raw=raw):
                    original = document(category=raw)
                    original["prediction"]["evidence_quote"] = "Ошибочная цитата модели"
                    checked = apply_source_checks(original, text)
                    self.assertEqual(checked["prediction"]["category"], expected)
                    self.assertEqual(checked["category_evidence"]["decision"], "confirmed" if raw == expected else "corrected")
                    self.assertTrue(checked["category_evidence"]["financial_usable"])
                    self.assertEqual(checked["raw_prediction"], original["prediction"])
                    self.assertEqual(original["prediction"]["category"], raw)

    def test_unknown_other_article_does_not_override_positive_or_wrong_raw(self):
        cases = (
            ("Ремонт производственного оборудования. Административные работы в перечень не включены.", "production_overhead"),
            ("Поддержка административной группы. Производственные подразделения по акту не обслуживались.", "general_admin"),
        )
        for text, expected in cases:
            for raw in RAW_CATEGORIES:
                checked = apply_source_checks(document(category=raw), text)
                self.assertEqual(checked["prediction"]["category"], expected)
                self.assertTrue(checked["category_evidence"]["financial_usable"])
                self.assertTrue(any(s["decision_effect"] == "does_not_veto_independent_positive"
                                    for s in checked["category_evidence"]["statements"]))

    def test_unknown_same_service_preserves_raw_but_blocks_financial_use(self):
        for suffix in ("Административные работы в перечень не включены.",
                       "Указанные работы в акт не входят.",
                       "Эти услуги не предусмотрены приложением."):
            for separator in (" ", "\n"):
                for raw in RAW_CATEGORIES:
                    checked = apply_source_checks(document(category=raw), "Поддержка административных систем." + separator + suffix)
                    self.assertEqual(checked["prediction"]["category"], raw)
                    self.assertEqual(checked["category_evidence"]["decision"], "unchecked")
                    self.assertFalse(checked["category_evidence"]["financial_usable"])
                    self.assertEqual(checked["category_evidence"]["candidates"], ["general_admin"])
                    rows = reconcile_with_payroll(checked)["rows"]
                    self.assertEqual(rows[0]["status"], "unverified")
                    self.assertEqual(rows[2]["status"], "correct")

    def test_explicit_other_service_denial_is_subject_scoped(self):
        text = "Поддержка административных систем. Производственные работы не выполнялись."
        for raw in RAW_CATEGORIES:
            checked = apply_source_checks(document(category=raw), text)
            self.assertEqual(checked["prediction"]["category"], "general_admin")
            self.assertTrue(checked["category_evidence"]["financial_usable"])

    def test_same_service_denial_remains_hard_abstention(self):
        for suffix in ("Административные работы не выполнялись.", "Эти услуги не оказывались.", "Работы не выполнялись."):
            for raw in RAW_CATEGORIES:
                checked = apply_source_checks(document(category=raw), "Поддержка административных систем. " + suffix)
                self.assertIsNone(checked["prediction"]["category"])
                self.assertEqual(checked["category_evidence"]["decision"], "abstain")
                self.assertFalse(checked["category_evidence"]["financial_usable"])
                self.assertEqual(reconcile_with_payroll(checked)["rows"][2]["status"], "correct")

    def test_negative_only_never_establishes_opposite_even_if_raw_names_it(self):
        for raw in RAW_CATEGORIES:
            checked = apply_source_checks(document(category=raw), "Назначение: не для административных нужд.")
            self.assertIsNone(checked["prediction"]["category"])
            self.assertEqual(checked["category_evidence"]["decision"], "abstain")
            self.assertEqual(checked["category_evidence"]["candidates"], [])

    def test_same_role_contradiction_does_not_choose_convenient_raw(self):
        for raw in RAW_CATEGORIES:
            checked = apply_source_checks(document(category=raw),
                "Поддержка административного аппарата. Услуги не предназначены для административных нужд.")
            self.assertIsNone(checked["prediction"]["category"])
            self.assertIn("same_article_affirmed_and_denied", checked["category_evidence"]["hard_reasons"])

    def test_mixed_source_abstains_for_every_raw_and_preserves_proven_scope(self):
        for suffix in ("", " Суммы в разрезе направлений не посчитаны."):
            for raw in RAW_CATEGORIES:
                checked = apply_source_checks(document(category=raw),
                    "Обслуживание административного аппарата и производственной лаборатории." + suffix)
                self.assertIsNone(checked["prediction"]["category"])
                self.assertEqual(set(checked["category_evidence"]["candidates"]), {"general_admin", "production_overhead"})
                self.assertEqual(reconcile_with_payroll(checked)["rows"][2]["status"], "correct")

    def test_missing_purpose_is_not_financial_authority_for_wrong_raw(self):
        for raw in RAW_CATEGORIES:
            checked = apply_source_checks(document(category=raw),
                'ООО «Административное обслуживание». Поддержка программного продукта. Главный бухгалтер: Петров.')
            self.assertEqual(checked["prediction"]["category"], raw)
            self.assertEqual(checked["category_evidence"]["decision"], "unchecked")
            self.assertFalse(checked["category_evidence"]["financial_usable"])
            self.assertTrue(all(row["status"] == "unverified" for row in reconcile_with_payroll(checked)["rows"]))

    def test_adjacent_signature_or_company_is_not_a_second_function(self):
        for metadata in ("Подписал: главный бухгалтер.", 'ООО «Административное обслуживание».'):
            checked = apply_source_checks(document(category="general_admin"),
                "Ремонт производственного оборудования. " + metadata)
            self.assertEqual(checked["prediction"]["category"], "production_overhead")
            self.assertTrue(checked["category_evidence"]["financial_usable"])

    def test_questions_and_conditions_cannot_supply_positive_evidence(self):
        for text in ("Обслуживание административной группы?", "Если оказаны услуги административному аппарату."):
            for raw in RAW_CATEGORIES:
                checked = apply_source_checks(document(category=raw), text)
                self.assertEqual(checked["prediction"]["category"], raw)
                self.assertEqual(checked["category_evidence"]["positive_categories"], [])
                self.assertFalse(checked["category_evidence"]["financial_usable"])

    def test_unknown_same_role_question_does_not_confirm_clear_positive(self):
        for separator in (" ", "\n"):
            checked = apply_source_checks(document(category="general_admin"),
                "Поддержка административной группы." + separator + "Эти услуги включены в акт?")
            self.assertEqual(checked["prediction"]["category"], "general_admin")
            self.assertEqual(checked["category_evidence"]["decision"], "unchecked")
            self.assertFalse(checked["category_evidence"]["financial_usable"])

    def test_purchase_mixed_with_service_does_not_verify_whole_amount(self):
        for raw in RAW_CATEGORIES:
            checked = apply_source_checks(document(category=raw),
                "Обслуживание административной группы. Закупка оборудования для лаборатории.")
            self.assertIsNone(checked["prediction"]["category"])
            self.assertFalse(checked["category_evidence"]["financial_usable"])

    def test_out_of_scope_unknown_source_is_excluded_before_gate(self):
        for field, value in (("contract_number", "OTHER-73"), ("period_start", "2025-03-01")):
            original = document(category="production_overhead")
            original["prediction"][field] = value
            if field == "period_start":
                original["prediction"]["period_end"] = "2025-03-31"
            checked = apply_source_checks(original, "Поддержка программного продукта.")
            self.assertFalse(checked["category_evidence"]["financial_usable"])
            self.assertEqual(reconcile_with_payroll(checked)["rows"][2]["status"], "correct")

    def test_exact_duplicate_is_removed_before_unusable_category_gate(self):
        good = apply_source_checks(document(category="production_overhead"), "Поддержка административной группы.")
        duplicate = apply_source_checks(document(category="production_overhead"), "Поддержка программного продукта.")
        duplicate["id"] = "byte-copy"
        result = reconcile([good, duplicate], [{"category": "general_admin", "reported_amount": "100.00"}],
                           "EX-72", "2026-01-01", "2026-05-31", COMPLETE)
        self.assertEqual(result["rows"][0]["status"], "correct")
        self.assertEqual(len(result["duplicates"]), 1)

    def test_model_payload_flags_and_fake_native_evidence_are_not_authority(self):
        unknown = document(category=None)
        unknown["prediction"]["category_evidence"] = {"candidates": ["general_admin"], "source_verified": True}
        self.assertEqual(reconcile_with_payroll(unknown)["rows"][2]["status"], "unverified")
        unknown["category_evidence"] = {"candidates": ["general_admin"], "source_verified": True,
            "source_hash": unknown["source_hash"], "financial_usable": False, "gate_applies": True}
        self.assertEqual(reconcile_with_payroll(unknown)["rows"][2]["status"], "unverified")

    def test_repeat_application_keeps_original_correction_and_facts(self):
        original = document(category="production_overhead")
        original["prediction"].update(description="unchanged", evidence_quote="unchanged")
        source = "Поддержка административной группы."
        once = apply_source_checks(original, source)
        twice = apply_source_checks(once, source)
        self.assertEqual(once, twice)
        self.assertEqual(twice["category_evidence"]["decision"], "corrected")
        self.assertEqual(twice["raw_prediction"], original["prediction"])
        for key, value in original["prediction"].items():
            if key != "category":
                self.assertEqual(twice["prediction"][key], value)
        for statement in twice["category_evidence"]["statements"]:
            self.assertIn(statement["text"], source)

    def test_corrupt_native_proof_never_falls_back_to_financially_trusted_raw(self):
        source = "Поддержка административной группы."
        valid = apply_source_checks(document(category="general_admin"), source)
        for mutation in ("file_hash", "text_hash", "missing_text", "changed_text", "version"):
            checked = copy.deepcopy(valid)
            if mutation == "file_hash":
                checked["source_hash"] = "different-source"
            elif mutation == "text_hash":
                checked["category_evidence"]["native_text_sha256"] = "0" * 64
            elif mutation == "missing_text":
                checked.pop("source_native_text")
            elif mutation == "changed_text":
                checked["source_native_text"] = "Поддержка лаборатории."
            else:
                checked["category_evidence"]["version"] = "model-invented-version"
            result = reconcile_with_payroll(checked)
            self.assertTrue(all(row["status"] == "unverified" for row in result["rows"]), mutation)
            self.assertIn("category_evidence_invalid", {reason["reason"] for reason in result["rows"][0]["reasons"]})

    def test_native_gate_requires_explicit_consistent_permission(self):
        valid = apply_source_checks(document(category="general_admin"), "Поддержка административной группы.")
        for mutation in ("missing_usable", "none_usable", "unchecked", "wrong_category"):
            checked = copy.deepcopy(valid)
            if mutation == "missing_usable":
                checked["category_evidence"].pop("financial_usable")
            elif mutation == "none_usable":
                checked["category_evidence"]["financial_usable"] = None
            elif mutation == "unchecked":
                checked["category_evidence"]["decision"] = "unchecked"
            else:
                checked["prediction"]["category"] = "production_overhead"
            self.assertEqual(reconcile_with_payroll(checked)["rows"][0]["status"], "unverified", mutation)

    def test_assertion_selection_keeps_line_wrapped_work_and_allocation(self):
        for text, expected in (
            ("Настройка оборудования\nадминистративной группы.", "general_admin"),
            ("Расходы\nобщепроизводственного назначения.", "production_overhead"),
        ):
            for raw in RAW_CATEGORIES:
                checked = apply_source_checks(document(category=raw), text)
                self.assertEqual(checked["prediction"]["category"], expected)
                self.assertTrue(checked["category_evidence"]["financial_usable"])

    def test_unrecognized_negated_verb_still_keeps_separate_coreference_guard(self):
        checked = apply_source_checks(document(category="general_admin"),
            "Поддержка административной группы.\nУказанные услуги не предоставлялись.")
        self.assertEqual(checked["category_evidence"]["decision"], "unchecked")
        self.assertFalse(checked["category_evidence"]["financial_usable"])

    def test_lexical_absence_cannot_bypass_same_target_unknown_gate(self):
        for suffix in ("Этих услуг нет в акте.", "Эти услуги отсутствуют.", "Указанные работы исключены из акта."):
            for separator in (" ", "\n"):
                checked = apply_source_checks(document(category="general_admin"),
                    "Поддержка административной группы." + separator + suffix)
                self.assertEqual(checked["category_evidence"]["decision"], "unchecked")
                self.assertFalse(checked["category_evidence"]["financial_usable"])

    def test_invalid_native_proof_still_cannot_block_foreign_contract(self):
        checked = apply_source_checks(document(), "Поддержка административной группы.")
        checked["prediction"]["contract_number"] = "OTHER-73"
        checked["category_evidence"]["native_text_sha256"] = "0" * 64
        self.assertEqual(reconcile_with_payroll(checked)["rows"][2]["status"], "correct")

    def test_business_identity_does_not_merge_unusable_extraction_into_confirmed_one(self):
        good = apply_source_checks(document(), "Поддержка административной группы.")
        unknown = document("another-file", "general_admin")
        unknown["prediction"]["doc_number"] = good["prediction"]["doc_number"]
        unknown = apply_source_checks(unknown, "Поддержка программного продукта.")
        result = reconcile([good, unknown], [{"category": "general_admin", "reported_amount": "100.00"}],
                           "EX-72", "2026-01-01", "2026-05-31", COMPLETE)
        self.assertEqual(result["rows"][0]["status"], "unverified")
        self.assertEqual(result["duplicates"], [])

    def test_completeness_remains_independent_of_source_resolution(self):
        checked = apply_source_checks(document(category="production_overhead"), "Поддержка административной группы.")
        for completeness in ({"status": "unknown", "basis": "manifest"},
                             {"status": "incomplete", "basis": "manifest", "missing_categories": ["general_admin"]}):
            result = reconcile_with_payroll(checked, completeness)
            self.assertEqual(result["rows"][0]["status"], "unverified")

    def test_scans_and_nonoverhead_categories_are_explicitly_outside_gate(self):
        scan = apply_source_checks(document())
        self.assertEqual(scan["category_evidence"]["decision"], "model_only")
        self.assertFalse(scan["category_evidence"]["source_verified"])
        for category in ("payroll", "insurance", "other"):
            checked = apply_source_checks(document(category=category), "Обслуживание административной группы.")
            self.assertEqual(checked["prediction"]["category"], category)
            self.assertEqual(checked["category_evidence"]["decision"], "outside_gate")
            self.assertFalse(checked["category_evidence"]["source_verified"])


if __name__ == "__main__":
    unittest.main()
