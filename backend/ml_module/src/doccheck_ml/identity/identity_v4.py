"""Source-only v4 experiment: corrected OCR inputs and literal line readers.

Reader arms are separate from acceptance. Prior accepted values survive.
No rereading result can create an automatic duplicate edge or silently clear
a previous candidate/conflict using a new unverified number.
"""
from copy import deepcopy
from itertools import combinations

from . import identity_v2 as v2
from . import identity_v3 as v3
from .identity_v4_source import source_corrections, apply_corrections

VERSION = "identity-v4.1-dev"
READER_ARMS = {
    "A1": ("tight_row_psm7", "old_roi"), "A2": ("context_psm6", "old_roi"),
    "B1": ("tight_row_psm7", "literal4b"), "B2": ("context_psm6", "literal4b"),
    "C1": ("tight_row_psm7", "literal9b"), "C2": ("context_psm6", "literal9b"),
    "D1": ("tight_row_psm7", "context9b"), "D2": ("context_psm6", "context9b"),
}


def _verify_envelope(base, row):
    if row and (row.get("id") != base["id"] or row.get("source_sha256") != base["source_sha256"]):
        raise ValueError("Reader observations belong to another source")


def _adapt(base, joined, tess, literal, crop_policy):
    """Adapt saved observations without recomputing or guessing crop evidence."""
    row = deepcopy(joined or {})
    row.update(id=base['id'], source_sha256=base['source_sha256'])
    chosen = [o for o in (tess or {}).get('observations', []) if o['policy_id'] == crop_policy]
    row['tesseract'] = [dict(variant=o['preprocess'], text=o.get('text'),
                              mean_confidence=o.get('mean_confidence'),
                              error=o.get('error') or (o.get('skip_reason') if o.get('status') != 'observed' else None))
                         for o in chosen]
    if literal is not None:
        row['qwen_roi'] = deepcopy(literal)
    # Geometry belongs to this Tesseract crop, not the old contextual image.
    if crop_policy == 'tight_row_psm7':
        observed = [o for o in chosen if o.get('status') == 'observed' and o.get('crop')]
        if observed:
            row['crop'] = {**observed[0]['crop'], 'mode': 'single_line'}
        else:
            row['crop'] = {'mode': 'unavailable'}
    return row


def evaluate_arms(
    baseline_v3_record: dict, v3_joined: dict | None = None,
    tess_v4_row: dict | None = None, literal4b_row: dict | None = None,
    literal9b_row: dict | None = None, context9b_row: dict | None = None,
    *, source_observation: dict | None = None,
) -> dict:
    """Return the unchanged baseline, source-only, and declared reader policies."""
    previous = baseline_v3_record
    for r in (v3_joined, tess_v4_row, literal4b_row, literal9b_row, context9b_row):
        _verify_envelope(previous, r)
    baseline = deepcopy(previous)
    baseline['arm'] = 'baseline'
    result = {'baseline': baseline}
    corrections = source_corrections(previous, v3_joined, source_observation)
    source_only = deepcopy(previous)
    source_only.update(version=VERSION, arm='source_only', v3_identity=deepcopy(previous))
    result['source_only'] = apply_corrections(source_only, corrections)
    old = previous.get('baseline_identity', previous)
    readers = {'old_roi': None, 'literal4b': literal4b_row, 'literal9b': literal9b_row, 'context9b': context9b_row}
    for arm, (crop_policy, reader) in READER_ARMS.items():
        r = readers[reader]
        adapted = _adapt(old, v3_joined, tess_v4_row, r, crop_policy)
        # A requested but absent literal observation cannot secretly reuse ROI4B.
        if reader != 'old_roi' and r is None:
            adapted['qwen_roi'] = {'prediction': None, 'error': 'requested_reader_missing'}
        rec = v3.evaluate_arms(old, adapted)['combined']
        rec.update(version=VERSION, arm=arm, v3_identity=deepcopy(previous))
        apply_corrections(rec, corrections)
        rec['v4'] = {'crop_policy': crop_policy, 'reader': reader,
                     'acceptance': 'corroborated', 'prior_number': deepcopy(previous['number']),
                     'literal_readability': (r or {}).get('prediction', {}).get('readability')
                         if (r or {}).get('prediction') else None}
        # Existing accepted numbers are outside selection even when the old v2
        # selector still includes a value accepted by v3 in the preceding round.
        if previous['number'].get('usable_value') is not None:
            rec['number'] = deepcopy(previous['number'])
            rec['v4']['preserved_v3_accepted'] = True
        elif adapted.get('selected'):
            prediction = (r or {}).get('prediction') or {}
            if r is not None and not r.get('error') and prediction.get('readability') in {'absent', 'unreadable', 'ambiguous'}:
                rec['number'].update(value=None, usable_value=None, manual_review_required=True,
                                     status='literal_reader_abstained', verification='unverified')
                rec['number']['issues'].append('explicit_literal_abstention_no_stale_fallback')
            else:
                # If both number readers fail, retaining the contract number as
                # a suggested document number is unsupported. A correct number
                # coincidentally equal to the contract remains allowed when a
                # new reader explicitly reads the document-number anchor.
                obs = rec['reread']
                no_new_number = not obs['roi']['quote_support'] and not obs['tesseract_stable']
                proposal = rec['number'].get('value')
                if no_new_number and proposal and v2.norm(proposal) == v2.norm(old.get('facts', {}).get('contract_number')):
                    rec['number'].update(value=None, usable_value=None, manual_review_required=True,
                                         status='unsupported_contract_fallback_removed', verification='unverified')
                    rec['number']['issues'].append('no_document_number_reading_for_contract_fallback')
        result[arm] = rec
        proposals = deepcopy(rec)
        proposals['arm'] = arm + '_proposal'
        proposals['v4']['acceptance'] = 'previous_only'
        if previous['number'].get('usable_value') is None:
            proposals['number'].update(usable_value=None, manual_review_required=True,
                                       verification='unverified')
        result[arm + '_proposal'] = proposals
    return result


def compare_documents(a: dict, b: dict) -> dict:
    if 'v3_identity' not in a and 'v3_identity' not in b:
        return v3.compare_documents(a, b)
    decision = v2.compare_documents(a, b)
    previous = v3.compare_documents(a.get('v3_identity', a), b.get('v3_identity', b))
    if decision['auto_merge'] and not previous['auto_merge']:
        decision.update(status='candidate', auto_merge=False)
        decision['reasons'].append('v4_cannot_create_automatic_merge')
    # This also retains reviews v3 itself inherited from v2: the current v3
    # proposal can already differ from the original number before v4 starts.
    unverified_number = any(r['number'].get('usable_value') is None for r in (a, b))
    verified_total_reclassification = (previous['status'] == 'conflict' and decision['status'] == 'candidate'
        and 'same_identity_different_amount' in previous['reasons']
        and any(r.get('source_corrections', {}).get('amount', {}).get('applied') for r in (a, b)))
    if verified_total_reclassification:
        decision['reasons'].append('source_total_correction_preserves_candidate_review')
    if unverified_number and not verified_total_reclassification and ((previous['status'] == 'conflict' and decision['status'] != 'conflict') or
                              (previous['status'] == 'candidate' and decision['status'] not in {'candidate', 'conflict', 'duplicate'})):
        return {**previous, 'reasons': previous['reasons'] + ['unverified_v4_number_cannot_clear_v3_review'],
                'v4_suggested_status': decision['status']}
    return decision


def group_documents(records: list[dict]) -> dict:
    by_id = {r['id']: r for r in records}
    if len(by_id) != len(records):
        raise ValueError('Duplicate document IDs')
    parent = {k: k for k in by_id}
    def root(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    pairs = []
    for a, b in combinations(records, 2):
        d = compare_documents(a, b)
        if d['auto_merge']:
            parent[root(b['id'])] = root(a['id'])
        if d['status'] in {'duplicate', 'candidate', 'conflict'}:
            pairs.append(d)
    groups = {}
    for k in sorted(by_id):
        groups.setdefault(root(k), []).append(k)
    return {'groups': list(groups.values()), 'review_pairs': pairs, 'files_deleted': False,
            'candidate_edges_used_for_clustering': False, 'new_auto_edges_from_rereading': False}


def review_queue(records: list[dict]) -> dict:
    by_id = {r['id']: r for r in records}
    if len(by_id) != len(records):
        raise ValueError('Duplicate document IDs')
    flagged = {r['id'] for r in records if r['number'].get('manual_review_required',
                                                            r['number'].get('usable_value') is None)}
    neighbors = {k: set() for k in by_id}
    compatible, pairs = set(), []
    for a, b in combinations(records, 2):
        d = compare_documents(a, b)
        edge = tuple(sorted((a['id'], b['id'])))
        if d['status'] in {'duplicate', 'candidate'}:
            compatible.add(edge)
            neighbors[a['id']].add(b['id']); neighbors[b['id']].add(a['id'])
        if d['status'] in {'candidate', 'conflict'}:
            pairs.append(d)
    seen, cards = set(), []
    for first in sorted(by_id):
        if first in seen:
            continue
        stack, component = [first], set()
        while stack:
            k = stack.pop()
            if k not in component:
                component.add(k); stack.extend(neighbors[k] - component)
        seen.update(component)
        pending = sorted(component & flagged)
        if not pending:
            continue
        clique = all(tuple(sorted(edge)) in compatible for edge in combinations(component, 2))
        for ids in ([pending] if clique else [[k] for k in pending]):
            cards.append({'document_ids': ids, 'comparison_ids': sorted(component) if clique else ids,
                          'kind': 'number_review', 'correction_propagates': False, 'is_duplicate_group': False})
    fact_flagged = sorted(r['id'] for r in records if r.get('fact_conflicts'))
    fact_cards = [{'document_ids': [ident], 'kind': 'fact_review',
                   'fields': sorted(by_id[ident]['fact_conflicts']),
                   'correction_propagates': False} for ident in fact_flagged]
    return {'number_review_document_ids': sorted(flagged), 'number_cards': cards,
            'fact_review_document_ids': fact_flagged, 'fact_cards': fact_cards,
            'identity_review_pairs': pairs, 'number_review_documents': len(flagged),
            'number_review_cards': len(cards), 'identity_review_pair_count': len(pairs),
            'actual_human_actions_measured': False, 'all_unverified_numbers_are_visible': True}
