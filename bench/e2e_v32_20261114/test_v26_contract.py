"""Root follow-up causal cases, written before viewing the new corpus/gold."""
import copy
import unittest

from bench.e2e_v32_20261114.independent_v26_checks import identity, purpose
from bench.e2e_v32_20261114.document_identity import validate_number_evidence


class V26Contract(unittest.TestCase):
    def test_supported_hyphenated_header_does_not_hide_absence(self):
        for header in ('Акт приема-передачи', 'Акт приёма-передачи', 'Счет-фактура'):
            with self.subTest(header=header):
                result = identity('absent', header + ' б/н от 07.02.2026')
                self.assertIsNone(result['prediction']['doc_number'])
                self.assertEqual(result['raw_prediction']['doc_number'], '07.02.2026')
                self.assertTrue(validate_number_evidence(result)['valid'])
                self.assertFalse(validate_number_evidence(result)['identity_usable'])

    def test_literal_punctuation_and_zero_remain_own_identifiers(self):
        for number in ('0', 'А.17', 'А_17', 'А - 17', '07.02.2026', '07 . 02 . 2026'):
            with self.subTest(number=number):
                result = identity('full', 'Номер документа: ' + number, 'wrong')
                self.assertEqual(result['prediction']['doc_number'], number)
                self.assertTrue(validate_number_evidence(result)['identity_usable'])

    def test_separate_sentence_is_not_part_of_identifier(self):
        result = identity('token', 'Документ № А-17\nДоговор № К-913. Этап 3', 'wrong')
        self.assertEqual(result['prediction']['doc_number'], 'А-17')
        self.assertIn('К-913', validate_number_evidence(result)['non_own_candidates'])
        self.assertNotIn('К-913. Этап', validate_number_evidence(result)['non_own_candidates'])

    def test_absence_evidence_is_reparsed_before_authority(self):
        result = identity('empty', 'Акт № ____ от 07.02.2026')
        damaged = copy.deepcopy(result)
        damaged['number_evidence']['absence_evidence'][0]['text'] = 'invented'
        self.assertFalse(validate_number_evidence(damaged)['valid'])

    def test_multiline_foreign_absence_cannot_clear_own_number(self):
        for text in ('Цитата: «Предыдущий документ\nНомер документа: без номера\nКонец цитаты».',
                     'Основание:\nАкт № б/н'):
            with self.subTest(text=text):
                result = identity('foreign', text, 'К-913')
                self.assertEqual(result['prediction']['doc_number'], 'К-913')
                self.assertFalse(validate_number_evidence(result)['identity_usable'])

    def test_multisentence_quotes_do_not_leak_positive_assertions(self):
        for quote in ('«Оцифровка бумаг. Общехозяйственные расходы.»',
                      '«Оцифровка бумаг.\nОбщехозяйственные расходы.»',
                      'В прежнем акте: "Обработка карточек. Общехозяйственные расходы."'):
            with self.subTest(quote=quote):
                evidence = purpose(quote)['category_evidence']
                self.assertFalse(evidence['financial_usable'])
                self.assertEqual(evidence['positive_categories'], [])

    def test_real_named_recipient_does_not_become_foreign_quote(self):
        for text in ('Обслуживание подразделения «Административная дирекция».',
                     'Услуги по поддержке отдела «Бухгалтерия».',
                     'Обслуживание административной системы «Управление».'):
            with self.subTest(text=text):
                self.assertTrue(purpose(text)['category_evidence']['financial_usable'])

    def test_quoted_value_of_own_purpose_label_is_own_assertion(self):
        for text in ('Описание услуг: «Обслуживание административной дирекции».',
                     'Назначение: «Обслуживание административной дирекции. Общехозяйственные расходы.»'):
            with self.subTest(text=text):
                self.assertTrue(purpose(text)['category_evidence']['financial_usable'])

    def test_generic_unknown_operation_denial_remains_guarded(self):
        for text in ('Общехозяйственные расходы.\nПереплёт не выполнялся.',
                     'Общехозяйственные расходы.\nДля примера: переплёт.',
                     'Общехозяйственные расходы.\nОцифровка лишь планировалась.'):
            with self.subTest(text=text):
                self.assertFalse(purpose(text)['category_evidence']['financial_usable'])

    def test_actual_planning_service_and_contract_context_not_plan_only(self):
        for text in ('Планирование бюджета административной дирекции. Общехозяйственные расходы.',
                     'Расходы по договору на обслуживание административного аппарата.'):
            with self.subTest(text=text):
                self.assertTrue(purpose(text)['category_evidence']['financial_usable'])

    def test_neutral_clause_cannot_independently_authorize_category(self):
        self.assertFalse(purpose('Переплёт бумаг административной дирекции.')['category_evidence']['financial_usable'])

    def test_neutral_other_purpose_is_not_ignored(self):
        result = purpose('Общехозяйственные расходы. Оцифровка карт производственного участка.')
        self.assertFalse(result['category_evidence']['financial_usable'])
        self.assertEqual(set(result['category_evidence']['candidates']), {'general_admin', 'production_overhead'})


if __name__ == '__main__':
    unittest.main()
