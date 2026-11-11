import materialsPdf from './assets/materials.pdf?url';
import materialsPng from './assets/materials.png';
import servicesPdf from './assets/services.pdf?url';
import servicesPng from './assets/services.png';
import locators from './assets/locators.json';
import type { Finding } from '../presentation';

// Hand-authored presentation fixture from the approved mockup, not an OCR result,
// evaluation answer or a reconstruction of the canonical JSON Schema.
export const scope = { contract: 'DEMO-001', periodStart: '2026-11-01', periodEnd: '2026-11-30', row: '3 этап, 2026 г.' };
export const demoFindings: Finding[] = [
  {
    id: 'materials', article: 'Материалы', reported: '125000.00', expected: '123500.00', delta: '1500.00', status: 'discrepancy',
    explanation: 'Сумма в отчёте выше подтверждённой документами.',
    formula: '125 000,00 − 123 500,00 = 1 500,00 ₽',
    sources: [{ id: 'material-act', filename: 'Демо-акт № 01.pdf', previewUrl: materialsPng, originalUrl: materialsPdf, amount: '123500.00', page: 1, bbox: locators.materials.bbox as [number, number, number, number] }],
  },
  {
    id: 'services', article: 'Услуги', reported: '48000.00', expected: '48000.00', delta: '0.00', status: 'verified',
    explanation: 'Сумма в отчёте совпадает с суммой подтверждающего документа.',
    formula: '48 000,00 − 48 000,00 = 0,00 ₽',
    sources: [{ id: 'service-act', filename: 'Демо-акт № 02.pdf', previewUrl: servicesPng, originalUrl: servicesPdf, amount: '48000.00', page: 1, bbox: locators.services.bbox as [number, number, number, number] }],
  },
  {
    id: 'other', article: 'Прочее', reported: '7000.00', expected: null, delta: null, status: 'unverified',
    explanation: 'Подтверждающий документ отсутствует. Ожидаемую сумму и разницу определить нельзя.',
    formula: null, sources: [],
  },
];
