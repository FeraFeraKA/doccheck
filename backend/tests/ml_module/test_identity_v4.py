from copy import deepcopy
import unittest

from doccheck_ml.identity import identity_v3, identity_v4
from test_identity_v3 import baseline, readings


def inputs(number='ЗП-0017'):
    base = baseline()
    old = readings(base, '3П-0017')
    previous = identity_v3.evaluate_arms(base, old)['combined']
    tess = {'id': base['id'], 'source_sha256': base['source_sha256'], 'observations': []}
    for policy in ('tight_row_psm7', 'context_psm6'):
        for variant in ('original', 'gray2x'):
            tess['observations'].append({'policy_id': policy, 'preprocess': variant,
                'status': 'observed', 'crop': {'path': 'unit-only.png'},
                'text': f'№ {number} от 31.03.2026', 'mean_confidence': 95, 'error': None})
    literal = {'id': base['id'], 'source_sha256': base['source_sha256'], 'error': None,
               'prediction': {'doc_number': number, 'verbatim_line': f'№ {number} от 31.03.2026',
                              'readability': 'readable'}}
    return previous, old, tess, literal


class V4SafetyTests(unittest.TestCase):
    def test_proposal_arm_does_not_promote_new_value(self):
        p, old, tess, lit = inputs()
        arms = identity_v4.evaluate_arms(p, old, tess, lit, lit)
        self.assertEqual(arms['B1']['number']['usable_value'], 'ЗП-0017')
        self.assertEqual(arms['B1_proposal']['number']['value'], 'ЗП-0017')
        self.assertIsNone(arms['B1_proposal']['number']['usable_value'])

    def test_explicit_abstention_cannot_retain_a_contract_guess(self):
        p, old, tess, lit = inputs()
        lit['prediction'].update(doc_number=None, readability='unreadable', verbatim_line=None)
        arms = identity_v4.evaluate_arms(p, old, tess, lit, lit)
        for key in ('B1', 'B2', 'C1', 'C2'):
            self.assertIsNone(arms[key]['number']['value'])
            self.assertIsNone(arms[key]['number']['usable_value'])

    def test_existing_v3_accepted_value_survives_new_readers(self):
        p, old, tess, lit = inputs()
        p['number'].update(value='ЛБ-0023', usable_value='ЛБ-0023', manual_review_required=False)
        for r in identity_v4.evaluate_arms(p, old, tess, lit, lit).values():
            self.assertEqual(r['number']['value'], 'ЛБ-0023')
            self.assertEqual(r['number']['usable_value'], 'ЛБ-0023')

    def test_genuine_digit_prefix_is_not_rewritten(self):
        p, old, tess, lit = inputs('3П-0017')
        r = identity_v4.evaluate_arms(p, old, tess, lit, lit)['B1']
        self.assertEqual(r['number']['value'], '3П-0017')
        self.assertIsNone(r['number']['usable_value'])

    def test_source_mismatch_raises_before_any_observation(self):
        p, old, tess, lit = inputs()
        for index in range(4):
            a = [deepcopy(old), deepcopy(tess), deepcopy(lit), deepcopy(lit)]
            a[index]['source_sha256'] = 'another-source'
            with self.assertRaises(ValueError):
                identity_v4.evaluate_arms(p, *a)

    def test_missing_reader_is_not_replaced_with_old_qwen(self):
        p, old, tess, lit = inputs()
        result = identity_v4.evaluate_arms(p, old, tess)['C1']
        self.assertIsNone(result['number']['usable_value'])
        self.assertEqual(result['reread']['roi']['error'], 'requested_reader_missing')

    def test_abstention_does_not_remove_previous_conflict(self):
        a, old, tess, lit = inputs()
        b = deepcopy(a)
        b['id'] = 'b'; b['source_sha256'] = 'other'; b['facts']['amount'] = '101.00'
        self.assertEqual(identity_v3.compare_documents(a, b)['status'], 'conflict')
        lit['prediction'].update(doc_number=None, readability='unreadable', verbatim_line=None)
        new = identity_v4.evaluate_arms(a, old, tess, lit)['B1']
        self.assertEqual(identity_v4.compare_documents(new, b)['status'], 'conflict')
        self.assertFalse(identity_v4.compare_documents(new, b)['auto_merge'])

    def test_cards_cover_all_unverified_documents_without_merging(self):
        a, old, tess, lit = inputs()
        a = identity_v4.evaluate_arms(a, old, tess, lit)['B1_proposal']
        b = deepcopy(a); b['id'] = 'b'; b['source_sha256'] = 'other'
        q = identity_v4.review_queue([a, b])
        self.assertEqual(q['number_review_document_ids'], ['a', 'b'])
        self.assertEqual(len(identity_v4.group_documents([a, b])['groups']), 2)

    def test_preserve_conflict_inherited_by_v3_before_v4(self):
        a, old, tess, lit = inputs()
        b = deepcopy(a)
        b['id'] = 'b'; b['source_sha256'] = 'other'; b['facts']['amount'] = '101.00'
        b['baseline_identity']['facts']['amount'] = '101.00'
        b['baseline_identity'].update(id='b', source_sha256='other')
        a['number']['value'] = 'ЗП-0017'
        self.assertEqual(identity_v3.compare_documents(a, b)['status'], 'conflict')
        new = deepcopy(a); new['v3_identity'] = deepcopy(a)
        self.assertEqual(identity_v4.compare_documents(new, b)['status'], 'conflict')


if __name__ == '__main__':
    unittest.main()
