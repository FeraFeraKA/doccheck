import unittest
from copy import deepcopy

from doccheck_ml.identity import identity_v3, identity_v4, identity_v5


def fixture(value='ABCD-101', acquisition='scan', status='prefix_recovered_from_source'):
    source = {'id': 'fixture', 'source_sha256': 'same-source', 'acquisition': acquisition,
        'number': {'value': value, 'usable_value': value, 'model_value': '101',
                   'status': status, 'issues': ['model_omitted_prefix'],
                   'candidates': [{'value': value}], 'manual_review_required': False},
        'issuer': {'value': 'Issuer', 'tax_id': '1234567890', 'tax_id_conflict': False},
        'doc_type': {'value': 'act'}, 'facts': {'contract_number': 'CN-1',
                  'date': '2026-01-01', 'amount': '100.00'}, 'source_facts': {},
        'content_fingerprint': None, 'content_complete': False, 'package_fingerprint': None}
    previous = identity_v3.evaluate_arms(source)['combined']
    a2 = deepcopy(previous)
    a2.update(arm='A2', v3_identity=deepcopy(previous))
    return previous, a2


def readers(value='ABCD-101', confidence=90):
    return {'id': 'fixture', 'source_sha256': 'same-source', 'selected': True,
            'crop': {'mode': 'single_line'},
            'qwen_roi': {'prediction': {'doc_number': value, 'verbatim_line': '№ ' + value}, 'error': None},
            'tesseract': [{'variant': name, 'text': '№ ' + value,
                           'mean_confidence': confidence, 'error': None}
                          for name in ('original', 'gray2x')]}


class PrefixGuardTests(unittest.TestCase):
    def test_missing_recheck_revokes_acceptance_without_guessing_prefix(self):
        base, a2 = fixture('KL-101')
        result = identity_v5.resolve_document(base, a2)
        self.assertEqual(result['number']['value'], 'KL-101')
        self.assertIsNone(result['number']['usable_value'])
        self.assertTrue(result['number']['manual_review_required'])
        self.assertEqual(base['number']['usable_value'], 'KL-101')

    def test_full_number_confirmation_can_restore_acceptance(self):
        base, a2 = fixture()
        result = identity_v5.resolve_document(base, a2, readers())
        self.assertEqual(result['number']['usable_value'], 'ABCD-101')
        self.assertFalse(result['number']['manual_review_required'])

    def test_same_digits_without_full_prefix_confirmation_stay_unverified(self):
        base, a2 = fixture()
        observed = readers()
        observed['qwen_roi']['prediction']['doc_number'] = '101'
        result = identity_v5.resolve_document(base, a2, observed)
        self.assertIsNone(result['number']['usable_value'])

    def test_reader_disagreement_does_not_confirm(self):
        base, a2 = fixture()
        observed = readers()
        observed['tesseract'][1]['text'] = '№ ABCE-101'
        result = identity_v5.resolve_document(base, a2, observed)
        self.assertIsNone(result['number']['usable_value'])

    def test_existing_confidence_threshold_is_not_lowered(self):
        base, a2 = fixture()
        self.assertIsNone(identity_v5.resolve_document(base, a2, readers(confidence=79.99))['number']['usable_value'])

    def test_unresolved_script_ambiguity_is_not_accepted(self):
        base, a2 = fixture('CB-101')
        self.assertIsNone(identity_v5.resolve_document(base, a2, readers('CB-101'))['number']['usable_value'])

    def test_native_prefix_and_other_accepted_values_are_outside_selector(self):
        for args in ({'acquisition': 'native'}, {'status': 'source_model_agreement'}):
            base, a2 = fixture(**args)
            if args.get('status'):
                base['number']['issues'] = []
            self.assertFalse(identity_v5.needs_prefix_confirmation(base))
            self.assertEqual(identity_v5.resolve_document(base, a2)['number'], a2['number'])

    def test_mismatched_source_rejected(self):
        base, a2 = fixture()
        observed = readers(); observed['source_sha256'] = 'other-source'
        with self.assertRaises(ValueError):
            identity_v5.resolve_document(base, a2, observed)

    def test_wrong_base_arm_rejected(self):
        base, a2 = fixture(); a2['arm'] = 'D2'
        with self.assertRaises(ValueError):
            identity_v5.resolve_document(base, a2)

    def test_correcting_prefix_cannot_authorize_a_new_merge(self):
        base_a, a2_a = fixture('WRONG-101')
        base_b, a2_b = fixture('RIGHT-101')
        def second_source(record):
            record['id'] = 'second'; record['source_sha256'] = 'second-source'
            for key in ('baseline_identity', 'v3_identity'):
                if key in record:
                    second_source(record[key])
        for record in (base_b, a2_b):
            second_source(record)
        observed_a = readers('RIGHT-101')
        observed_b = readers('RIGHT-101'); observed_b.update(id='second', source_sha256='second-source')
        a = identity_v5.resolve_document(base_a, a2_a, observed_a)
        b = identity_v5.resolve_document(base_b, a2_b, observed_b)
        self.assertFalse(identity_v5.compare_documents(a, b)['auto_merge'])


if __name__ == '__main__':
    unittest.main()
