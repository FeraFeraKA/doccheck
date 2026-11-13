import { expect, it } from 'vitest';
import { formatDecimal } from '../../src/pages/checks/reviewResult';

it.each([
  ['0', '0'],
  ['34', '34'],
  ['1234', '1\u00a0234'],
  ['-12345678901234567.12345678901234567890', '-12\u00a0345\u00a0678\u00a0901\u00a0234\u00a0567,12345678901234567890'],
  ['0.00', '0,00'],
  [null, '—'],
])('форматирует строку %s без потери разрядов', (value, display) => {
  expect(formatDecimal(value)).toBe(display);
});
