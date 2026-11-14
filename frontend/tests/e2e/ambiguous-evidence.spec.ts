import { expect, test, type Page } from '@playwright/test';
import example from '../../../contracts/check-result.v1.synthetic.json' with { type: 'json' };

const runId = '51a00000-0000-4000-8000-000000000001';
const pixel = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/6Z8AAAAASUVORK5CYII=',
  'base64',
);

async function stubRun(page: Page, id: string, result: object) {
  await page.route(`**/api/v0/runs/${id}`, (route) => route.fulfill({ json: {
    run_id: id, status: 'completed_with_issues', created_at: '2026-11-14T00:00:00Z',
    error: null, progress: { processed_documents: 4, total_documents: 4 }, synthetic: true,
  } }));
  await page.route(`**/api/v0/runs/${id}/findings`, (route) => route.fulfill({ json: result }));
}

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
    const reportSources = detail.getByRole('list', { name: 'Источники значения КФЗ' });
    const reportButtons = reportSources.getByRole('button');
    await expect(reportButtons).toHaveCount(2);
    await expect(reportButtons.nth(0)).toContainText('Непроверенное чтение 1');
    await expect(reportButtons.nth(0)).toContainText('150,50');
    await expect(reportButtons.nth(1)).toContainText('Непроверенное чтение 2');
    await expect(reportButtons.nth(1)).toContainText('151,50');
    const reason = detail.getByRole('list', { name: 'Источники причины: Неоднозначная сумма отчёта.' });
    await expect(reason.getByRole('button')).toHaveCount(3);
    await expect(reason).toContainText('synthetic-ledger.xlsx');
    await expect(detail.getByRole('list', { name: 'Источники основания полноты' }).getByRole('button')).toHaveCount(1);

    for (const [index, id] of [report.id, alternative.id].entries()) {
      const button = reportButtons.nth(index);
      await button.focus();
      await button.press(index === 0 ? 'Enter' : 'Space');
      const panel = page.getByRole('region', { name: 'Источник документа', exact: true });
      await expect(panel.getByRole('combobox', { name: 'Доказательство' })).toHaveCount(0);
      await expect(panel.locator('.source-workspace-notice').filter({ hasText: `Непроверенное чтение ${index + 1}` }))
        .toContainText(index === 0 ? '150,50' : '151,50');
      await expect(button).toHaveAttribute('aria-pressed', 'true');
      await expect.poll(() => requested.includes(id)).toBe(true);
      await page.getByRole('button', { name: 'Закрыть просмотр источника' }).click();
      await expect(button).toBeFocused();
      await expect(button).toHaveAttribute('aria-pressed', 'false');
    }
    await reason.getByRole('button', { name: /synthetic-ledger\.xlsx/ }).press('Enter');
    await expect(page.getByRole('region', { name: 'Источник документа', exact: true })
      .getByRole('combobox', { name: 'Документы комплекта' })).toHaveValue(context.document_id);
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
  await expect(unknown.getByRole('list', { name: 'Источники основания полноты' })).toHaveCount(0);
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
    await expect(detail.getByText('Источник значения КФЗ не указан.')).toBeVisible();
    await expect(detail.getByRole('list', { name: 'Источники значения КФЗ' })).toHaveCount(0);
    const reasons = detail.getByRole('list', { name: 'Источники причины: Источник не подтверждён.' });
    if (references.length) {
      await expect(reasons).toHaveText('Источник · Адрес источника недоступен.');
      await expect(reasons.getByRole('button')).toHaveCount(0);
    } else {
      await expect(reasons).toHaveCount(0);
    }
  });
}

test('distinguishes unverified readings at the same XLSX cell', async ({ page }) => {
  const id = 'conflicting-xlsx';
  const base = structuredClone(example.result);
  const report = { ...base.evidence[0], locator: { kind: 'sheet', sheet: 'Синтетика', range: 'C7' } };
  const alternative = { ...report, id: 'alternate-xlsx', raw_value: '151,50', normalized_value: '151.50' };
  const evidence = base.evidence.map((item) => item.document_id !== 'report' ? item : {
    ...item, locator: { kind: 'sheet', sheet: 'Синтетика', range: item.id === 'report-a' ? 'C7' : 'C8' },
  });
  const row = {
    ...base.rows[0], reported_value: null, reported_evidence_refs: [report.id, alternative.id],
    expected_value: null, observed_evidence_sum: null, delta: null, status: 'unverified', root_issue_id: null,
    calculation: { ...base.rows[0].calculation, components: [] },
    completeness: { state: 'unknown', basis: 'none', reason: 'Полнота не установлена.', evidence_refs: [] },
    reasons: [{ code: 'conflicting_readings', message: 'Неоднозначная сумма отчёта.',
      evidence_refs: [report.id, alternative.id] }],
  };
  const result = {
    ...base, run_id: id,
    documents: base.documents.map((document) => document.id === 'report'
      ? { ...document, name: 'synthetic-report.xlsx', format: 'xlsx' } : document),
    evidence: [...evidence, alternative], rows: [row],
    summary: { counts: { verified: 0, discrepancy: 0, unverified: 1 }, primary_issues: [],
      conclusion: 'Одно значение не проверено.' },
  };
  await stubRun(page, id, result);
  const requested: string[] = [];
  await page.route((url) => url.pathname.startsWith(`/api/v0/runs/${id}/documents/report`), (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/fragments')) {
      const evidenceId = url.searchParams.get('evidence_id');
      const source = result.evidence.find((item) => item.id === evidenceId);
      if (source && evidenceId) requested.push(evidenceId);
      return source ? route.fulfill({ json: source }) : route.fulfill({ status: 404 });
    }
    if (url.pathname.endsWith('/fragment-preview')) return route.fulfill({ json: { text: null, highlight: null } });
    if (url.pathname.endsWith('/preview')) return route.fulfill({ json: {
      sheets: ['Синтетика'], sheet: 'Синтетика', row: 1, column: 1, last_row: 7, last_column: 3,
      rows: Array.from({ length: 7 }, (_, index) => ['', '', index === 6 ? '150.50' : '']),
    } });
    return route.fulfill({ body: 'synthetic original', contentType: 'application/octet-stream' });
  });
  await page.goto('/checks/' + id);
  const table = page.getByRole('table', { name: 'Показатели КФЗ' });
  await table.getByRole('button', { name: 'Синтетическая статья A', exact: true }).click();
  const detail = table.getByRole('region', { name: 'Подробности: Синтетическая статья A' });
  const sources = detail.getByRole('list', { name: 'Источники значения КФЗ' }).getByRole('button');
  await expect(sources).toHaveCount(2);
  for (const [index, evidenceId] of ['report-a', 'alternate-xlsx'].entries()) {
    const button = sources.nth(index);
    const value = index === 0 ? '150,50' : '151,50';
    await expect(button).toContainText(`Непроверенное чтение ${index + 1}`);
    await expect(button).toContainText(value);
    await button.click();
    const panel = page.getByRole('region', { name: 'Источник документа', exact: true });
    await expect(panel.getByRole('combobox', { name: 'Доказательство' })).toHaveCount(0);
    await expect(panel.locator('.source-workspace-notice').filter({ hasText: `Непроверенное чтение ${index + 1}` }))
      .toContainText(value);
    await expect.poll(() => requested.includes(evidenceId)).toBe(true);
    await panel.getByRole('button', { name: 'Закрыть просмотр источника' }).click();
    await expect(button).toBeFocused();
  }
  await expect(table.getByTitle('Открыть значение в КФЗ')).toHaveCount(0);
});

test('keeps each reason and completeness source attached to its explanation', async ({ page }) => {
  const id = 'sources-by-reason';
  const base = structuredClone(example.result);
  const row = {
    ...base.rows[0],
    reasons: [
      { code: 'first', message: 'Первое основание.', evidence_refs: ['amount-1', 'amount-1'] },
      { code: 'second', message: 'Второе основание.', evidence_refs: ['amount-1', 'contract'] },
    ],
    completeness: { ...base.rows[0].completeness, reason: 'Основание полноты.',
      evidence_refs: ['amount-1', 'amount-1'] },
  };
  await stubRun(page, id, { ...base, run_id: id, rows: [row, ...base.rows.slice(1)] });
  await page.goto('/checks/' + id);
  const table = page.getByRole('table', { name: 'Показатели КФЗ' });
  await table.getByRole('button', { name: 'Синтетическая статья A', exact: true }).click();
  const detail = table.getByRole('region', { name: 'Подробности: Синтетическая статья A' });
  const first = detail.getByRole('list', { name: 'Источники причины: Первое основание.' });
  const second = detail.getByRole('list', { name: 'Источники причины: Второе основание.' });
  const completeness = detail.getByRole('list', { name: 'Источники основания полноты' });
  await expect(first.getByRole('button')).toHaveCount(1);
  await expect(first).toContainText('C6');
  await expect(second.getByRole('button')).toHaveCount(2);
  await expect(second).toContainText('C6');
  await expect(second).toContainText('A2');
  await expect(completeness.getByRole('button')).toHaveCount(1);
  await expect(completeness).toContainText('C6');
});

test('shows a missing KFZ source even when supporting components exist', async ({ page }) => {
  const id = 'missing-report-with-components';
  const base = structuredClone(example.result);
  const row = {
    ...base.rows[0], reported_value: null, reported_evidence_refs: [], delta: null,
    status: 'unverified', root_issue_id: null,
    reasons: [{ code: 'missing_reported_value', message: 'Нет суммы в КФЗ.', evidence_refs: [] }],
  };
  await stubRun(page, id, { ...base, run_id: id, rows: [row, ...base.rows.slice(1)],
    summary: { ...base.summary, counts: { verified: 0, discrepancy: 0, unverified: 2 },
      primary_issues: base.summary.primary_issues.filter((issue) => issue.id !== 'issue-a') } });
  await page.goto('/checks/' + id);
  const table = page.getByRole('table', { name: 'Показатели КФЗ' });
  const rowElement = table.getByRole('row').filter({ hasText: 'Синтетическая статья A' });
  await expect(rowElement).toContainText('1 док.');
  await rowElement.getByRole('button', { name: 'Синтетическая статья A', exact: true }).click();
  const detail = table.getByRole('region', { name: 'Подробности: Синтетическая статья A' });
  await expect(detail.getByText('Источник значения КФЗ не указан.')).toBeVisible();
  await expect(detail.getByRole('list', { name: 'Слагаемые показателя: Синтетическая статья A' })
    .getByRole('listitem')).toHaveCount(2);
});
