import unittest
from doccheck_ml.identity.identity_v4_source import total_candidates, issuer_key


class SourceFactsTests(unittest.TestCase):
    def test_column_heading_does_not_pick_first_item(self):
        lines = [{'text':'Сумма, руб.', 'page':1, 'bbox':[200,10,260,30]},
                 {'text':'150000,00', 'page':1, 'bbox':[200,50,260,70]}]
        self.assertEqual(total_candidates(lines), [])

    def test_reversed_reading_order_uses_total_geometry(self):
        lines = [{'text':'287640,50', 'page':1, 'bbox':[300,90,400,120]},
                 {'text':'Итого к учету', 'page':1, 'bbox':[10,100,150,130]}]
        result = total_candidates(lines)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['value'], '287640.50')

    def test_no_vertical_or_crosspage_guess(self):
        for numeric in [{'text':'200,00','page':1,'bbox':[300,160,400,190]},
                        {'text':'200,00','page':2,'bbox':[300,100,400,130]}]:
            self.assertEqual(total_candidates([{'text':'Итого','page':1,'bbox':[10,100,150,130]}, numeric]), [])

    def test_multiple_numeric_columns_require_review(self):
        lines = [{'text':'Итого','page':1,'bbox':[10,100,150,130]},
                 {'text':'200,00','page':1,'bbox':[200,100,250,130]},
                 {'text':'240,00','page':1,'bbox':[300,100,350,130]}]
        self.assertEqual(total_candidates(lines), [])

    def test_quotes_are_presentation_not_letter_correction(self):
        self.assertEqual(issuer_key('ООО «Вектор»'), issuer_key('ООО «Вектор'))
        self.assertNotEqual(issuer_key('ООО «Вектор»'), issuer_key('ООО «Вектop»'))
        self.assertNotEqual(issuer_key('ООО Альфа-1'), issuer_key('ООО Альфа-2'))

    def test_long_label_is_not_consumed_as_short_prefix(self):
        self.assertEqual(total_candidates([{'text':'Итоговая сумма: 100,00', 'page':1}])[0]['value'], '100.00')
        self.assertEqual(total_candidates([{'text':'Итоговый аванс: 100,00', 'page':1}]), [])


if __name__ == '__main__': unittest.main()
