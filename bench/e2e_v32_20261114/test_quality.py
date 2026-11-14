import copy
import unittest

from bench.e2e_v32_20261114.classification import apply_source_checks
from bench.e2e_v32_20261114.decision_rules import reconcile


COMPLETE = {"status": "complete", "basis": "user_manifest"}


def document(identifier="a", category="production_overhead", amount="100.00"):
    return {"id": identifier, "source_hash": "sha-" + identifier, "prediction": {
        "contract_number": "EX-72", "doc_number": "ACT-" + identifier,
        "date": "2026-03-31", "period_start": "2026-03-01", "period_end": "2026-03-31",
        "category": category, "amount": amount}}


def check(documents, completeness=COMPLETE, reported="100.00"):
    rows = [{"category": "production_overhead", "reported_amount": reported},
            {"category": "general_admin", "reported_amount": "50.00"}]
    return reconcile(documents, rows, "EX-72", "2026-01-01", "2026-05-31", completeness)


class CompletenessTests(unittest.TestCase):
    def setUp(self):
        self.documents = [document(), document("b", "general_admin", "50.00")]

    def test_partial_different_sum_is_not_a_discrepancy(self):
        result = check(self.documents, {"status": "incomplete", "basis": "user_manifest",
                                      "missing_categories": ["production_overhead"]}, "150.00")
        row, unaffected = result["rows"]
        self.assertEqual(row["status"], "unverified")
        self.assertEqual(row["partial_amount"], "100.00")
        self.assertIsNone(row["expected_amount"])
        self.assertIsNone(row["delta"])
        self.assertEqual(unaffected["status"], "correct")

    def test_partial_accidentally_matching_sum_is_not_verified(self):
        result = check(self.documents, {"status": "incomplete", "basis": "user_manifest",
                                      "missing_categories": ["production_overhead"]})
        self.assertEqual(result["rows"][0]["status"], "unverified")

    def test_unknown_completeness_never_proves_a_total(self):
        for declaration in (None, {}, {"status": "unknown", "basis": "user_manifest"},
                            {"status": "complete"}):
            with self.subTest(declaration=declaration):
                self.assertTrue(all(r["status"] == "unverified" for r in check(self.documents, declaration)["rows"]))

    def test_missing_list_or_invalid_declaration_does_not_invent_scope(self):
        for declaration in (
            {"status": "incomplete", "basis": "user_manifest"},
            {"status": "incomplete", "basis": "user_manifest", "missing_categories": "production_overhead"},
            {"status": "incomplete", "basis": "user_manifest", "missing_categories": ["mistyped"]},
            {"status": "complete", "basis": "user_manifest", "missing_categories": ["production_overhead"]},
        ):
            with self.subTest(declaration=declaration):
                self.assertTrue(all(r["status"] == "unverified" for r in check(self.documents, declaration)["rows"]))

    def test_complete_keeps_existing_correct_and_discrepancy_behaviour(self):
        self.assertEqual(check(self.documents)["rows"][0]["status"], "correct")
        self.assertEqual(check(self.documents, reported="150.00")["rows"][0]["delta"], "50.00")

    def test_absent_source_is_not_zero_even_if_declared_complete(self):
        result = check([self.documents[1]])
        self.assertEqual(result["rows"][0]["status"], "unverified")
        self.assertIsNone(result["rows"][0]["expected_amount"])

    def test_exact_duplicate_does_not_double_count(self):
        duplicate = copy.deepcopy(self.documents[0]); duplicate["id"] = "copy"
        result = check([*self.documents, duplicate])
        self.assertEqual(result["rows"][0]["expected_amount"], "100.00")
        self.assertEqual(len(result["duplicates"]), 1)

    def test_conflicting_versions_still_unverified(self):
        different = document("other")
        different["prediction"]["doc_number"] = "ACT-a"
        different["prediction"]["amount"] = "101.00"
        result = check([*self.documents, different])
        self.assertEqual(result["rows"][0]["status"], "unverified")
        self.assertEqual(result["rows"][1]["status"], "correct")


class CategorySourceTests(unittest.TestCase):
    def test_backward_denied_production_and_positive_admin(self):
        result = apply_source_checks(document(),
            "Поддержка управленческих сервисов. К производственным расходам данное обслуживание не относится.")
        self.assertEqual(result["prediction"]["category"], "general_admin")
        self.assertEqual(result["category_evidence"]["negative_categories"], ["production_overhead"])

    def test_backward_denied_admin_and_positive_production(self):
        result = apply_source_checks(document(category="general_admin"),
            "Обеспечение производственной лаборатории. К общехозяйственным затратам указанные работы не относятся.")
        self.assertEqual(result["prediction"]["category"], "production_overhead")

    def test_backward_negative_only_cannot_establish_opposite_role(self):
        result = apply_source_checks(document(),
            "Назначение: к административным расходам данные услуги не относятся.")
        self.assertIsNone(result["prediction"]["category"])
        self.assertEqual(result["category_evidence"]["candidates"], [])

    def test_backward_question_or_unsupported_suffix_is_not_an_assertion(self):
        for text in ("Обслуживание административной группы. К производственным расходам эти услуги не относятся ли?",
                     "Обслуживание административной группы. К производственным расходам эти услуги не относятся при отдельных условиях.",
                     "Обслуживание административной группы. К производственным расходам эти услуги не относятся?",
                     "Обслуживание административной группы. Если к производственным расходам эти услуги не относятся."):
            result = apply_source_checks(document(), text)
            self.assertEqual(result["prediction"]["category"], "production_overhead")
            self.assertEqual(result["category_evidence"]["decision"], "unchecked")
            self.assertFalse(result["category_evidence"]["financial_usable"])

    def test_backward_contrast_retains_independent_positive_allocation(self):
        for text, expected in (
            ("К производственным расходам эти услуги не относятся, а учитываются как общехозяйственное обеспечение.", "general_admin"),
            ("К общехозяйственным затратам эти работы не относятся, но используются для производственного обслуживания.", "production_overhead"),
        ):
            result = apply_source_checks(document(), text)
            self.assertEqual(result["prediction"]["category"], expected)

    def test_separate_line_allocation_denial_is_not_lost(self):
        for text in ("Административное обслуживание.\nК административным затратам данные услуги не относятся.",
                     "К административным расходам данные услуги не относятся."):
            result = apply_source_checks(document(), text)
            self.assertEqual(result["category_evidence"]["status"], "guarded_purpose")
            self.assertIsNone(result["prediction"]["category"])

    def test_explicit_negative_intended_or_used_purpose(self):
        for text, expected in (
            ("Поддержка административной группы не предназначена для производственных нужд.", "general_admin"),
            ("Обслуживание лаборатории. Эти услуги не используются для административных нужд.", "production_overhead"),
            ("Услуги не предназначены для производственных нужд, а используются для административного обслуживания.", "general_admin"),
        ):
            result = apply_source_checks(document(), text)
            self.assertEqual(result["prediction"]["category"], expected)

    def test_direct_purpose_denial_does_not_create_opposite_role(self):
        for text in ("Услуги не предназначены для административных нужд.",
                     "Услуги не используются для производственных нужд.",
                     "Административное обслуживание.\nУслуги не предназначены для административных нужд."):
            result = apply_source_checks(document(), text)
            self.assertEqual(result["category_evidence"]["status"], "guarded_purpose")
            self.assertIsNone(result["prediction"]["category"])

    def test_backward_same_role_contradiction_stays_guarded(self):
        result = apply_source_checks(document(),
            "Административное обслуживание. К административным затратам данные услуги не относятся.")
        self.assertEqual(result["category_evidence"]["status"], "guarded_purpose")

    def test_mixed_roles_keep_scope_when_numeric_split_is_missing(self):
        for note in ("Распределение стоимости между подразделениями не представлено.",
                     "Стоимость услуг по статьям не выделена.",
                     "Раздельная сумма по категориям не указана."):
            text = "Поддержка аппарата управления и производственной лаборатории. " + note
            result = apply_source_checks(document(), text)
            self.assertEqual(result["category_evidence"]["status"], "mixed_purpose")
            self.assertEqual(set(result["category_evidence"]["candidates"]), {"general_admin", "production_overhead"})

    def test_no_numeric_split_cannot_create_missing_positive_role(self):
        result = apply_source_checks(document(),
            "Поддержка административных систем. Раздельная стоимость по направлениям не определена.")
        self.assertEqual(result["prediction"]["category"], "general_admin")
        self.assertEqual(result["category_evidence"]["candidates"], ["general_admin"])

    def test_no_split_note_does_not_cancel_independent_service_denial(self):
        for separator in (" ", "\n"):
            result = apply_source_checks(document(),
                "Поддержка административных и производственных систем." + separator +
                "Раздельная стоимость не указана." + separator + "Услуги не выполнялись.")
            self.assertEqual(result["category_evidence"]["status"], "guarded_purpose")
            self.assertEqual(set(result["category_evidence"]["candidates"]), {"general_admin", "production_overhead"})

    def test_mixed_unsplit_source_keeps_payroll_independent(self):
        mixed = apply_source_checks(document(category=None),
            "Поддержка административного аппарата и производственной лаборатории. Стоимость по направлениям не разделена.")
        result = reconcile([mixed, document("salary", "payroll", "60.00")],
            [{"category": "payroll", "reported_amount": "60.00"},
             {"category": "general_admin", "reported_amount": "100.00"}],
            "EX-72", "2026-01-01", "2026-05-31", COMPLETE)
        self.assertEqual(result["rows"][0]["status"], "correct")
        self.assertEqual(result["rows"][1]["status"], "unverified")

    def test_explicit_admin_with_denied_production_is_admin(self):
        text = ("Обеспечение сервисов для административной группы.\n"
                "Расходы не относятся непосредственно к отдельной производственной операции "
                "и учитываются в составе общехозяйственного обеспечения.")
        result = apply_source_checks(document(category="general_admin"), text)
        self.assertEqual(result["prediction"]["category"], "general_admin")
        self.assertEqual(result["category_evidence"]["negative_categories"], ["production_overhead"])
        self.assertEqual(result["category_evidence"]["positive_categories"], ["general_admin"])

    def test_explicit_production_with_denied_admin_is_production(self):
        result = apply_source_checks(document(category="general_admin"),
            "Обслуживание не относится к административной деятельности "
            "и учитывается как общепроизводственное обеспечение.")
        self.assertEqual(result["prediction"]["category"], "production_overhead")

    def test_explicit_contrast_does_not_infer_from_denial_alone(self):
        for text, expected in (
            ("Поддержка не для административной группы, а для производственной лаборатории.", "production_overhead"),
            ("Поддержка не для производственной лаборатории, а для административной группы.", "general_admin"),
        ):
            self.assertEqual(apply_source_checks(document(), text)["prediction"]["category"], expected)

    def test_negative_only_roles_do_not_imply_opposite_category(self):
        for text in ("Назначение: не для производственных нужд.",
                     "Назначение: не для административных нужд.",
                     "Обслуживание не для административной и производственной групп."):
            result = apply_source_checks(document(), text)
            self.assertIsNone(result["prediction"]["category"])
            self.assertEqual(result["category_evidence"]["candidates"], [])

    def test_same_role_affirmed_and_denied_is_guarded(self):
        result = apply_source_checks(document(),
            "Обслуживание административной группы; не для административных нужд.")
        self.assertIsNone(result["prediction"]["category"])
        self.assertEqual(result["category_evidence"]["status"], "guarded_purpose")

    def test_not_only_construction_remains_guarded(self):
        result = apply_source_checks(document(),
            "Обслуживание не только административной группы, но и производственной лаборатории.")
        self.assertIsNone(result["prediction"]["category"])
        self.assertEqual(result["category_evidence"]["status"], "guarded_purpose")

    def test_unsupported_negation_syntax_remains_guarded(self):
        result = apply_source_checks(document(),
            "Обслуживание не исключает административное назначение.")
        self.assertEqual(result["prediction"]["category"], "production_overhead")
        self.assertEqual(result["category_evidence"]["decision"], "unchecked")
        self.assertFalse(result["category_evidence"]["financial_usable"])

    def test_benign_quality_qualifier_keeps_positive_purpose(self):
        for text in ("Обслуживание административного аппарата без замечаний по качеству.",
                     "Поддержка лабораторной установки без претензий."):
            result = apply_source_checks(document(), text)
            self.assertEqual(result["category_evidence"]["status"], "explicit_purpose")

    def test_denial_of_work_performance_is_not_a_benign_qualifier(self):
        result = apply_source_checks(document(), "Обслуживание административных систем не выполнялось.")
        self.assertIsNone(result["prediction"]["category"])
        self.assertEqual(result["category_evidence"]["status"], "guarded_purpose")

    def test_purchase_still_blocks_overhead_override(self):
        result = apply_source_checks(document(),
            "Обеспечение административной группы и закупка материалов.")
        self.assertIsNone(result["prediction"]["category"])

    def test_source_check_preserves_all_other_facts_and_raw_output(self):
        original = document()
        original["prediction"].update(description="Исходное назначение", evidence_quote="Дословный фрагмент")
        before = copy.deepcopy(original)
        text = "Обеспечение административной группы, а не производственной лаборатории."
        checked = apply_source_checks(original, text)
        self.assertEqual(original, before)
        self.assertEqual(checked["raw_prediction"], before["prediction"])
        self.assertEqual({k: v for k, v in checked["prediction"].items() if k != "category"},
                         {k: v for k, v in before["prediction"].items() if k != "category"})
        self.assertEqual(checked["category_evidence"]["excerpts"][0]["text"], text)
        self.assertEqual(checked["category_evidence"]["excerpts"][0]["line_start"], 1)

    def test_admin_is_corrected_from_literal_purpose_without_phrase_special_case(self):
        original = document()
        changed = apply_source_checks(original,
            "Акт услуг № ACT-a\nДоговор № EX-72\nОбслуживание рабочих мест аппарата управления.\nИтого 100,00")
        self.assertEqual(changed["prediction"]["category"], "general_admin")
        self.assertEqual(changed["raw_prediction"]["category"], "production_overhead")
        self.assertEqual(original["prediction"]["category"], "production_overhead")
        self.assertTrue(any("Обслуживание рабочих мест аппарата управления." in item["text"]
                            for item in changed["category_evidence"]["excerpts"]))

    def test_same_service_for_laboratory_remains_production(self):
        result = apply_source_checks(document(category="general_admin"),
            "Поддержка программной системы производственной лаборатории.")
        self.assertEqual(result["prediction"]["category"], "production_overhead")

    def test_line_wrapped_purpose_is_supported(self):
        result = apply_source_checks(document(),
            "Сопровождение средств связи\nадминистративной группы.\nИтого 100,00")
        self.assertEqual(result["prediction"]["category"], "general_admin")

    def test_sender_and_signatory_are_not_allocation_evidence(self):
        result = apply_source_checks(document(),
            "Исполнитель: ООО Административное обслуживание\nПоддержка программного продукта.\nГлавный бухгалтер: Петров")
        self.assertEqual(result["prediction"]["category"], "production_overhead")
        self.assertEqual(result["category_evidence"]["decision"], "unchecked")
        self.assertFalse(result["category_evidence"]["financial_usable"])

    def test_unlabelled_company_header_is_not_allocation_evidence(self):
        result = apply_source_checks(document(category=None),
            'ООО «Административное обслуживание»\nПоддержка программного продукта.')
        self.assertIsNone(result["prediction"]["category"])
        self.assertEqual(result["category_evidence"]["decision"], "unchecked")
        self.assertFalse(result["category_evidence"]["financial_usable"])

    def test_company_header_cannot_contaminate_preceding_purpose(self):
        result = apply_source_checks(document(category="general_admin"),
            'Поддержка программной системы лаборатории\nООО «Административное обслуживание»')
        self.assertEqual(result["prediction"]["category"], "production_overhead")

    def test_negated_purpose_does_not_create_positive_allocation(self):
        result = apply_source_checks(document(),
            "Обслуживание не административной группы проекта.")
        self.assertIsNone(result["prediction"]["category"])
        self.assertEqual(result["category_evidence"]["candidates"], [])

    def test_service_qualifier_does_not_negate_administrative_purpose(self):
        for phrase in ("Обслуживание административной группы без НДС.",
                       "Поддержка административных сервисов без перерывов."):
            result = apply_source_checks(document(), phrase)
            self.assertEqual(result["prediction"]["category"], "general_admin")

    def test_allocation_negation_keeps_uncertainty(self):
        for phrase in ("Обслуживание не для административных нужд.",
                       "Обслуживание подразделений кроме лаборатории."):
            result = apply_source_checks(document(), phrase)
            self.assertIsNone(result["prediction"]["category"])

    def test_mixed_purpose_is_not_forced_into_one_article(self):
        result = apply_source_checks(document(),
            "Обслуживание административной группы и производственной лаборатории.")
        self.assertIsNone(result["prediction"]["category"])
        self.assertEqual(set(result["category_evidence"]["candidates"]), {"production_overhead", "general_admin"})

    def test_missing_amount_does_not_destroy_known_purpose(self):
        unknown = document(category=None, amount=None)
        result = apply_source_checks(unknown, "Поверка приборов производственной лаборатории.")
        result = check([result, document("b", "general_admin", "50.00")])
        self.assertEqual(result["rows"][0]["status"], "unverified")
        self.assertEqual(result["rows"][1]["status"], "correct")

    def test_unknown_purpose_still_affects_all_articles(self):
        result = apply_source_checks(document(category=None, amount=None), "Назначение: неразборчиво")
        result = check([result, document("b", "general_admin", "50.00")])
        self.assertTrue(all(r["status"] == "unverified" for r in result["rows"]))

    def test_scan_model_quote_cannot_authorize_override(self):
        scan = document()
        scan["prediction"]["evidence_quote"] = "Обслуживание административной группы."
        result = apply_source_checks(scan)
        self.assertEqual(result["prediction"]["category"], "production_overhead")
        self.assertFalse(result["category_evidence"]["source_verified"])

    def test_payroll_and_insurance_are_outside_overhead_override(self):
        for category in ("payroll", "insurance", "other"):
            result = apply_source_checks(document(category=category),
                "Обслуживание административной группы проекта.")
            self.assertEqual(result["prediction"]["category"], category)

    def test_scoped_uncertainty_keeps_independent_payroll_verifiable(self):
        mixed = apply_source_checks(document(category=None),
            "Обслуживание административной группы и производственной лаборатории.")
        result = reconcile([mixed, document("w", "payroll", "60.00")],
            [{"category": "payroll", "reported_amount": "60.00"},
             {"category": "production_overhead", "reported_amount": "100.00"}],
            "EX-72", "2026-01-01", "2026-05-31", COMPLETE)
        self.assertEqual(result["rows"][0]["status"], "correct")
        self.assertEqual(result["rows"][1]["status"], "unverified")

    def test_unverified_model_candidate_list_cannot_narrow_uncertainty(self):
        unknown = document(category=None)
        unknown["category_evidence"] = {"candidates": ["production_overhead"], "source_verified": False}
        result = check([unknown, document("b", "general_admin", "50.00")])
        self.assertEqual(result["rows"][1]["status"], "unverified")


if __name__ == "__main__":
    unittest.main()
