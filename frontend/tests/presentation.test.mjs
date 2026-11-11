import test from 'node:test';
import assert from 'node:assert/strict';
import { money, filterFindings } from '../src/presentation.ts';

test('missing values remain distinct from zero and exact large money is not rounded', () => {
  assert.equal(money(null), '—');
  assert.equal(money('0.00', true), '0,00');
  assert.equal(money('9007199254740993.01'), '9\u00a0007\u00a0199\u00a0254\u00a0740\u00a0993,01');
  assert.equal(money('-1500.00', true), '−1\u00a0500,00');
  assert.equal(money('1500.00', true), '+1\u00a0500,00');
  assert.throws(() => money('123.456'));
});

test('status filters retain unverified values and do not mutate the source list', () => {
  const findings = [{ status: 'verified' }, { status: 'unverified', expected: null }, { status: 'discrepancy' }];
  assert.deepEqual(filterFindings(findings, 'unverified'), [findings[1]]);
  assert.equal(filterFindings(findings, 'all').length, 3);
});
