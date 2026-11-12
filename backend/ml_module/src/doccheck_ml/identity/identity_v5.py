"""Recheck OCR-only recovered prefixes; keep the frozen v4 experiment intact.

The v5 candidate is v4 A2 plus a source-independent prefix confirmation gate.
The development discovery and all changed decisions remain explicit. No gold,
document family, filename pattern, or known prefix dictionary is consulted.
"""
from copy import deepcopy

from . import identity_v3 as v3
from . import identity_v4 as v4

VERSION = 'identity-v5.0-prefix-guard'
ARM = 'v5_A2_guard'


def needs_prefix_confirmation(record: dict) -> bool:
    number = record['number']
    return bool(record.get('acquisition') == 'scan' and
                number.get('usable_value') is not None and
                (number.get('status') == 'prefix_recovered_from_source' or
                 (number.get('verification') == 'existing_source_policy' and
                  'model_omitted_prefix' in number.get('issues', []))))


def resolve_document(
    baseline_v3_record: dict, a2_record: dict, prefix_reader_row: dict | None = None
) -> dict:
    """Apply the fixed A2 policy, revoking single-reader prefix acceptance.

    Callers validate saved reader provenance before invoking this pure module.
    A missing or failed recheck leaves the proposed number visible for review.
    """
    baseline = baseline_v3_record
    for other in (a2_record, prefix_reader_row):
        if other is not None and (other.get('id') != baseline['id'] or
                                  other.get('source_sha256') != baseline['source_sha256']):
            raise ValueError('Observations belong to another document source')
    if a2_record.get('arm') != 'A2':
        raise ValueError('v5 requires the fixed, independently evaluated A2 input')
    required = needs_prefix_confirmation(baseline)
    if prefix_reader_row is not None and not required:
        raise ValueError('Unexpected prefix recheck for an unselected document')
    result = deepcopy(a2_record)
    result.update(version=VERSION, arm=ARM, v3_identity=deepcopy(baseline))
    result['v5'] = {
        'base_arm': 'A2', 'prefix_confirmation_required': required,
        'prior_number': deepcopy(baseline['number']),
        'old_accepted_value_is_not_automatically_trusted': required,
        'new_automatic_merge_authority': False,
    }
    if not required:
        return result
    source = deepcopy(baseline.get('baseline_identity', baseline))
    source['number'].update(usable_value=None, manual_review_required=True,
                            verification='unverified',
                            status='ocr_recovered_prefix_requires_independent_confirmation')
    source['number'].setdefault('issues', []).append('ocr_recovered_prefix_not_independently_confirmed')
    if not prefix_reader_row or not prefix_reader_row.get('selected'):
        result['number'].update(usable_value=None, manual_review_required=True,
                                verification='unverified', status='prefix_recheck_missing')
        result['number'].setdefault('issues', []).append('ocr_recovered_prefix_not_independently_confirmed')
        result['v5']['prefix_recheck_status'] = 'missing'
        return result
    checked = v3.evaluate_arms(source, prefix_reader_row)['combined']
    result['number'] = deepcopy(checked['number'])
    result['reread'] = deepcopy(checked['reread'])
    result['v5'].update(
        prefix_recheck_status='corroborated' if checked['number'].get('usable_value') else 'review_required',
        prefix_reader_policy_sha256=prefix_reader_row.get('policy_sha256'),
        prefix_reader_plan_sha256=prefix_reader_row.get('plan_sha256'),
        full_number_required=True,
        same_confidence_threshold=v3.TESS_CONFIDENCE_MIN,
        reader_agreement_is_not_proof=True,
    )
    return result


def evaluate_arms(
    baseline_v3_record: dict, a2_record: dict, prefix_reader_row: dict | None = None
) -> dict:
    result = {'baseline': deepcopy(baseline_v3_record),
              'A2_diagnostic': deepcopy(a2_record),
              ARM: resolve_document(baseline_v3_record, a2_record, prefix_reader_row)}
    for arm, record in result.items():
        record['arm'] = arm
    return result


# A2 stores the original v3 identity; these functions preserve its merge guard
# and retain candidates/conflicts when a changed number is still unverified.
compare_documents = v4.compare_documents
group_documents = v4.group_documents
review_queue = v4.review_queue
