import { expect, it } from 'vitest';
import { formatDecimal, formatLocation } from '../../src/pages/checks/reviewResult';

it.each([
  ['0', '0'],
  ['34', '34'],
  ['1234', '1\u202f234'],
  ['-12345678901234567.12345678901234567890', '−12\u202f345\u202f678\u202f901\u202f234\u202f567,12345678901234567890'],
  ['0.00', '0,00'],
  [null, '—'],
])('форматирует строку %s без потери разрядов', (value, display) => {
  expect(formatDecimal(value)).toBe(display);
});

it('различает фрагменты на одной строке PDF по их идентификаторам', () => {
  const line = { page: 1, line: 7, table_row: null, table_column: null, bbox: null };

  expect(formatLocation({ ...line, fragment_id: 'fragment-a' })).toBe('Страница 1, строка 7, фрагмент fragment-a');
  expect(formatLocation({ ...line, fragment_id: 'fragment-b' })).toBe('Страница 1, строка 7, фрагмент fragment-b');
  expect(formatLocation(line)).toBe('Страница 1, строка 7');
});
