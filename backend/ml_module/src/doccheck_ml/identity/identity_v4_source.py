"""Deterministic, source-evidenced fixes for cosmetic issuer and total mapping."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import re

from .parsing import parse_amount

TOTAL_LABEL = re.compile(r'^(?:итого(?:\s+к\s+(?:учету|учёту|оплате))?|итоговая\s+сумма|к\s+оплате(?:\s+по\s+документу)?|сумма\s+по\s+акту)(?![A-Za-zА-Яа-яЁё])\s*(?:,?\s*руб\.?)?\s*[:：]?\s*', re.I)
MONEY = re.compile(r'^\s*([0-9][0-9\s\u00a0]*[.,][0-9]{2})\s*(?:руб\.?|₽)?\s*$', re.I)
QUOTES = str.maketrans('', '', '«»“”„"')


def issuer_key(value: object) -> object:
    return re.sub(r'\s+', ' ', value.translate(QUOTES)).strip() if isinstance(value, str) else value


def _amount(text):
    m = MONEY.fullmatch(text)
    return parse_amount(m.group(1)) if m else None


def total_candidates(lines: list[dict]) -> list[dict]:
    found = []
    for line in lines:
        match = TOTAL_LABEL.match(line['text'].strip())
        if not match:
            continue
        tail = line['text'].strip()[match.end():]
        value = _amount(tail)
        if value is not None:
            found.append({'value': str(value), 'evidence': [line], 'method': 'explicit_total_same_line'})
            continue
        # Labels with unresolved extra text do not authorize joining arbitrary
        # neighboring values. A column heading 'Сумма, руб.' is never a total.
        if tail.strip():
            continue
        a = line.get('bbox')
        if not a or len(a) != 4 or a[3] <= a[1]:
            continue
        matches = []
        for other in lines:
            b = other.get('bbox')
            if other.get('page') != line.get('page') or not b or len(b) != 4 or b[3] <= b[1]:
                continue
            value = _amount(other['text'])
            if value is None or b[0] < a[2]:
                continue
            overlap = max(0, min(a[3], b[3]) - max(a[1], b[1])) / min(a[3]-a[1], b[3]-b[1])
            if overlap >= .5:
                matches.append((value, other))
        # Do not choose one of several numeric columns or totals by magnitude.
        if len(matches) == 1:
            found.append({'value': str(matches[0][0]), 'evidence': [line, matches[0][1]],
                          'method': 'explicit_total_unique_right_hand_same_row'})
    return found


def source_corrections(
    record: dict, joined: dict | None, source_observation: dict | None = None
) -> dict:
    """Use already validated, source-bound OCR lines; never open cache paths.

    ``source_observation`` contains ``id``, ``source_sha256`` and ``lines``.
    The caller is responsible for obtaining these lines from the actual source
    and validating their layout. Its canonical digest identifies the supplied
    observation, not a proof of independently measured OCR correctness.
    Missing observations preserve the proposed amount without a correction.
    """
    if source_observation is not None and (
        source_observation.get('id'), source_observation.get('source_sha256')
    ) != (record['id'], record['source_sha256']):
        raise ValueError('OCR observation belongs to another document source')
    result = {'issuer': {'applied': False}, 'amount': {'applied': False}}
    if record.get('acquisition') != 'scan' or not joined:
        return result
    if (joined.get('id'), joined.get('source_sha256')) != (record['id'], record['source_sha256']):
        raise ValueError('Source metadata belongs to another document')
    issuer = record['issuer']
    before = issuer.get('value')
    after = issuer_key(before)
    if (before and after and after != before and issuer.get('status') == 'explicit_source_role'
            and issuer.get('tax_id') and not issuer.get('tax_id_conflict')):
        result['issuer'] = {'applied': True, 'old': before, 'new': after,
                            'rule': 'remove_typographic_double_quotes_only',
                            'role_evidence': issuer.get('evidence'), 'tax_id': issuer['tax_id'],
                            'tax_id_evidence': issuer.get('tax_id_evidence')}
    # One later crop and a model answer cannot resolve contradictory original
    # totals. Preserve the conflict until the complete source is reviewed.
    if source_observation is None or record.get('fact_conflicts', {}).get('amount'):
        return result
    lines = deepcopy(source_observation['lines'])
    candidates = total_candidates(lines)
    values = {Decimal(c['value']) for c in candidates}
    qwen = parse_amount(joined.get('baseline', {}).get('prediction', {}).get('amount'))
    current = parse_amount(record.get('facts', {}).get('amount'))
    if len(values) == 1 and qwen is not None and qwen in values and qwen != current:
        digest = hashlib.sha256(json.dumps(
            source_observation, ensure_ascii=False, sort_keys=True,
            separators=(',', ':'), allow_nan=False,
        ).encode('utf-8')).hexdigest()
        result['amount'] = {'applied': True, 'old': record.get('facts', {}).get('amount'),
                            'new': str(qwen), 'rule': 'unique_explicit_total_and_fullpage_qwen_agree',
                            'candidates': candidates, 'fullpage_qwen_amount': str(qwen),
                            'source_observation_sha256': digest,
                            'conflict_may_only_be_reclassified_to_candidate': True}
    return result


def apply_corrections(record: dict, corrections: dict) -> dict:
    record['source_corrections'] = deepcopy(corrections)
    if corrections['issuer']['applied']:
        record['issuer']['value'] = corrections['issuer']['new']
    if corrections['amount']['applied']:
        record['facts']['amount'] = corrections['amount']['new']
        record['source_facts']['amount'] = corrections['amount']['new']
        record['fact_evidence']['amount'] = deepcopy(corrections['amount']['candidates'])
    return record
