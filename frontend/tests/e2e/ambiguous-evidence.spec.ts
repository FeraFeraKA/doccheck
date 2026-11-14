import { expect, test } from '@playwright/test';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

const runId = '51a00000-0000-4000-8000-000000000001';
const pixel = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/6Z8AAAAASUVORK5CYII=',
  'base64',
);

for (const sameAddress of [true, false]) {
  test(`opens conflicting report readings at ${sameAddress ? 'the same' : 'different'} addresses by keyboard`, async ({ page }) => {
    const base = structuredClone(example.result);
    const report = base.evidence[0];
    const contract = base.evidence.find(({ id }) => id === 'contract');
    if (!report || !contract) throw new Error('Synthetic evidence is missing');
    const alternative = {
      ...report, id: 'alternate-report', raw_value: '151,50', normalized_value: '151.50',
      locator: sameAddress ? report.locator : { kind: 'page', page: 1, bbox: [0.55, 0.4, 0.8, 0.45] },
    };
    const context = { ...contract, id: 'reason-contract' };
    const row = {
      ...base.rows[0], reported_value: null, reported_evidence_refs: [report.id, alternative.id],
      expected_value: null, observed_evidence_sum: null, delta: null, status: 'unverified',
      completeness: {
        state: 'unknown', basis: 'none', reason: 'Полнота не установлена.',
        evidence_refs: [context.id],
      },
      calculation: { ...base.rows[0].calculation, components: [] },
      reasons: [{
        code: 'conflicting_readings', message: 'Неоднозначная сумма отчёта.',
        evidence_refs: [report.id, alternative.id, context.id, context.id],
      }],
      root_issue_id: null,
    };
    const result = {
      ...base, run_id: runId, evidence: [...base.evidence, alternative, context], rows: [row],
      summary: {
        counts: { verified: 0, discrepancy: 0, unverified: 1 }, primary_issues: [],
        conclusion: 'Одно значение не проверено.',
      },
    };
    const requested: string[] = [];
    await page.route(`**/api/v0/runs/${runId}`, (route) => route.fulfill({ json: {
      run_id: runId, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z',
      error: null, progress: { processed_documents: 4, total_documents: 4 }, synthetic: true,
    } }));
    await page.route(`**/api/v0/runs/${runId}/findings`, (route) => route.fulfill({ json: result }));
    await page.route((url) => url.pathname.startsWith(`/api/v0/runs/${runId}/documents/`), (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith('/fragments')) {
        const id = url.searchParams.get('evidence_id');
        const source = result.evidence.find((item) => item.id === id);
        if (!source || !id) return route.fulfill({ status: 404 });
        requested.push(id);
        return route.fulfill({ json: source });
      }
      if (url.pathname.endsWith('/fragment-preview')) {
        return route.fulfill({ json: { text: null, highlight: null } });
      }
      if (url.pathname.endsWith('/page-preview')) {
        return route.fulfill({ body: pixel, contentType: 'image/png', headers: { 'X-Document-Pages': '1' } });
      }
      if (url.pathname.endsWith('/preview')) {
        return route.fulfill({ json: {
          sheets: ['Синтетика'], sheet: 'Синтетика', row: 1, column: 1,
          last_row: 2, last_column: 1, rows: [[''], ['DEMO-K1']],
        } });
      }
      return route.fulfill({ body: 'synthetic original', contentType: 'application/octet-stream' });
    });

    await page.goto('/checks/' + runId);
    const table = page.getByRole('table', { name: 'Показатели КФЗ' });
    const indicator = table.getByRole('button', { name: 'Синтетическая статья A', exact: true });
    await indicator.focus();
    await indicator.press('Enter');
    const detail = table.getByRole('region', { name: 'Подробности: Синтетическая статья A' });
    await expect(detail).toContainText('Неоднозначная сумма отчёта.');
    await expect(table.getByRole('row').filter({ hasText: 'Синтетическая статья A' })
      .getByRole('cell', { name: '—', exact: true })).toHaveCount(3);
    await expect(detail).not.toContainText('151,50');

    const reportSources = detail.getByRole('list', { name: 'Источники значения КФЗ' });
    const reportButtons = reportSources.getByRole('button');
    await expect(reportButtons).toHaveCount(2);
    await expect(reportButtons.nth(0)).toContainText('КФЗ 1');
    await expect(reportButtons.nth(1)).toContainText('КФЗ 2');
    const reason = detail.getByRole('list', { name: 'Источники оснований показателя' });
    await expect(reason.getByRole('button')).toHaveCount(1);
    await expect(reason).toContainText('synthetic-ledger.xlsx');

    for (const [index, id] of [report.id, alternative.id].entries()) {
      const button = reportButtons.nth(index);
      await button.focus();
      await button.press(index === 0 ? 'Enter' : 'Space');
      await expect(page.getByRole('combobox', { name: 'Доказательство' })).toHaveValue(id);
      await expect.poll(() => requested.includes(id)).toBe(true);
      await page.getByRole('button', { name: 'Закрыть просмотр источника' }).click();
      await expect(button).toBeFocused();
    }
    await reason.getByRole('button').press('Enter');
    await expect(page.getByRole('combobox', { name: 'Доказательство' })).toHaveValue(context.id);
    await expect.poll(() => requested.includes(context.id)).toBe(true);
  });
}

test('keeps the ordinary reported-value action and does not invent missing sources', async ({ page }) => {
  await page.goto('/checks/synthetic-example');
  const table = page.getByRole('table', { name: 'Показатели КФЗ' });
  await expect(table.getByTitle('Открыть значение в КФЗ')).toHaveCount(2);
  await expect(table.getByRole('row').filter({ hasText: 'Синтетическая статья B' })
    .getByTitle('Открыть значение в КФЗ')).toContainText('0,00');
  await table.getByRole('button', { name: 'Синтетическая статья A', exact: true }).click();
  const detail = table.getByRole('region', { name: 'Подробности: Синтетическая статья A' });
  await expect(table.getByTitle('Открыть значение в КФЗ').first()).toBeVisible();
  await expect(detail.getByRole('list', { name: 'Источники значения КФЗ' }).getByRole('button')).toHaveCount(1);
  await table.getByRole('button', { name: 'Синтетическая статья B', exact: true }).click();
  const unknown = table.getByRole('region', { name: 'Подробности: Синтетическая статья B' });
  await expect(unknown.getByText('Нет подтверждённых слагаемых.')).toBeVisible();
  await expect(unknown.getByRole('list', { name: 'Источники оснований показателя' })).toHaveCount(0);
});

for (const references of [[], ['unavailable-evidence']]) {
  test(`shows no fabricated source when an address is ${references.length ? 'unavailable' : 'absent'}`, async ({ page }) => {
    const id = references.length ? 'unavailable-address' : 'absent-address';
    const row = {
      ...example.result.rows[1], reported_value: null, reported_evidence_refs: [], root_issue_id: null,
      completeness: { state: 'unknown', basis: 'none', reason: 'Нет данных.', evidence_refs: [] },
      reasons: [{ code: 'missing_evidence', message: 'Источник не подтверждён.', evidence_refs: references }],
    };
    const result = {
      ...example.result, run_id: id, rows: [row],
      summary: {
        counts: { verified: 0, discrepancy: 0, unverified: 1 }, primary_issues: [],
        conclusion: 'Значение не проверено.',
      },
    };
    await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
      run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z',
      error: null, progress: { processed_documents: 4, total_documents: 4 },
    } }));
    await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({ json: result }));
    await page.goto('/checks/' + id);
    const table = page.getByRole('table', { name: 'Показатели КФЗ' });
    await table.getByRole('button', { name: 'Синтетическая статья B', exact: true }).click();
    const detail = table.getByRole('region', { name: 'Подробности: Синтетическая статья B' });
    await expect(detail.getByRole('list', { name: 'Источники значения КФЗ' })).toHaveCount(0);
    const reasons = detail.getByRole('list', { name: 'Источники оснований показателя' });
    if (references.length) {
      await expect(reasons).toHaveText('Основание · Адрес источника недоступен.');
      await expect(reasons.getByRole('button')).toHaveCount(0);
    } else {
      await expect(reasons).toHaveCount(0);
    }
  });
}
