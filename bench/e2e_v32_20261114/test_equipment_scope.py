import unittest

from .classification import apply_source_checks
from .test_evidence_gate import reconcile_with_payroll
from .test_quality import document


class EquipmentScopeTests(unittest.TestCase):
    def test_source_includes_wrapped_equipment_transfer(self):
        text = ("Предоставление специализированного измерительного оборудования во временное пользование\n"
                "для выполнения работ этапа 3.\nСтоимость услуг: 100,00 руб.")
        item = apply_source_checks(document(category=None), text)
        evidence = item["category_evidence"]
        self.assertEqual(item["prediction"]["category"], "production_overhead")
        self.assertTrue(evidence["financial_usable"])
        statement = next(s for s in evidence["statements"] if s["positive_categories"])
        self.assertEqual(statement["reason"], "temporary_measurement_equipment_for_stage_work")
        self.assertEqual(text[statement["source_char_start"]:statement["source_char_end"]], statement["text"])

    def test_unallocated_use_scopes_review_without_admitting_amount(self):
        for equipment in ("измерительные приборы", "испытательные установки"):
            with self.subTest(equipment=equipment):
                text = f"Переданы {equipment} во временное пользование."
                item = apply_source_checks(document(category="general_admin"), text)
                evidence = item["category_evidence"]
                self.assertFalse(evidence["financial_usable"])
                self.assertEqual(evidence["scope_basis"], "literal_temporary_equipment_use")
                rows = reconcile_with_payroll(item)["rows"]
                self.assertEqual([row["status"] for row in rows], ["unverified", "unverified", "correct"])
                self.assertEqual(rows[0]["partial_amount"], "0.00")
                self.assertIsNone(rows[0]["delta"])

    def test_no_equipment_scope_from_external_or_incompatible_evidence(self):
        purpose = "предоставление измерительных приборов во временное пользование"
        for text in (f"В смете: {purpose} для выполнения работ этапа 3.",
                     f"Цитата: «{purpose} для выполнения работ этапа 3».",
                     f"Если согласовано {purpose} для выполнения работ этапа 3.",
                     f"Предмет: {purpose} для выполнения работ этапа 3?",
                     "Закупка измерительных приборов для испытательного стенда.",
                     f"Предмет: {purpose}. Оплата труда также включена в сумму."):
            with self.subTest(text=text):
                evidence = apply_source_checks(document(category="production_overhead"), text)["category_evidence"]
                self.assertFalse(evidence["financial_usable"])
                self.assertEqual(evidence["candidates"], [])

    def test_current_denial_still_blocks_equipment_transfer(self):
        text = ("Переданы измерительные приборы во временное пользование для выполнения работ этапа 3. "
                "Услуги по настоящему акту не оказывались.")
        evidence = apply_source_checks(document(category="production_overhead"), text)["category_evidence"]
        self.assertFalse(evidence["financial_usable"])
        self.assertEqual(evidence["candidates"], ["production_overhead"])
